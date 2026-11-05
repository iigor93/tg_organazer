# Small-server deployment and migration

Production is on `77.91.75.194`, Ubuntu 24.04 with 2 vCPU / 2 GB RAM. FamPlanner
shares native PostgreSQL 16 and nginx with the separate comments application.
No Supabase containers are needed for the organizer bots.

## Runtime

- Checkout: `/home/tg_bot`, owned by system user/group `famplanner`.
- Python 3.12 dependencies: `uv sync --frozen --no-dev --python /usr/bin/python3.12`.
- Private configuration: `/home/tg_bot/.env`, mode 600, owner `famplanner`.
- Non-secret runtime overrides: `.env.low-memory`, copied from `deploy/app.env.example`.
- Database and role: `famplanner`, using loopback PostgreSQL and a dedicated password.
- Service units: `tg_bot`, `tg_max_bot`, `famplanner-reminders.service` and `.timer`.
- Runtime webhook listeners bind only to `127.0.0.1:8001` and `127.0.0.1:8003`.
- Bot database pools allow 2 connections with no overflow. The reminder job uses 1.
- Keep `LOCAL` unset in production: any non-empty value selects SQLite.
- Preserve existing bot tokens, webhook secrets, service-account IDs and `TG_PROXY`.
  Export `SSL_CERT_FILE` through the systemd override file; the trusted CA bundle
  for MAX is installed at `/etc/ssl/certs/famplanner-ca-bundle.pem`.

The reminder wrapper attempts both modes sequentially, so failure in the one-hour
mode does not suppress the current-time mode. systemd prevents concurrent copies.
Do not also install the two old root cron jobs. The timer uses current UTC minutes,
matching the original sender; it does not replay missed minutes after a long outage.

## Data migration

The old Supabase cluster stored the organizer's seven application tables in
`postgres.public`. Copy only that schema, including enums, sequences, data and
`alembic_version`, with `pg_dump --format=custom --schema=public --no-owner --no-acl`.
Do not copy Supabase's Auth, Storage, Realtime or analytics schemas.

1. Rehearse restoration into the new dedicated `famplanner` database. Use a target
   PostgreSQL version at least as new as the source (old: 15.8, new: 16).
2. Back up the source checkout/config, unit files and root crontab privately.
3. Remove only the organizer reminder cron entries and wait for active reminder
   processes to finish. Pause both old webhook entrypoints, then stop both bots
   gracefully; MAX must finish its already queued updates.
4. Take a fresh final dump with source writers stopped. Restore only into the
   dedicated target database; `pg_restore --clean --if-exists --no-owner --no-acl
   --exit-on-error --role=famplanner -d famplanner` drops target objects.
5. Compare row counts for all seven tables. Run `alembic upgrade heads` once:
   the source intentionally has two heads, `e4f5a6b7c8d9` and `f6a7b8c9d0e1`.
6. Start the new bots and replace the old MAX subscription with the new URL. Check
   subscription listing for duplicates; keep Telegram pending updates.
7. Start the one-minute timer, reopen ingress, and mask the old bot units to stop
   accidental restarts by a legacy deploy. Observe scheduled runs and errors.
8. Move A records `tgwebhook.ckobah.ru` and `maxhook.ckobah.ru` to `77.91.75.194`.
   The old host temporarily forwards ports 8001/8003 over verified HTTPS.

The final migration preserved 351 events, 102 users, 424 event-participant rows,
3 notes and 26 user relationships; canceled-events was empty. No schema change
was required. Old backups are under `/root/famplanner-migration-20261105`.

After the new database accepts writes, reverting DNS to old writers loses new
changes. Rollback then requires stopping writers and migrating current data back.

## HTTPS and deployments

nginx configuration is in `deploy/nginx.conf.example`. Existing certificates were
copied privately for staging. Production now uses the managed `famplanner`
certificate under `/etc/letsencrypt/live/famplanner`, with the system Certbot timer
and a root-owned nginx reload hook. During propagation the old proxy forwards
ACME challenge paths for these two names to the new host.

Main deployments use GitHub repository secrets `SSH_HOST`, `SSH_USERNAME`,
`SSH_PORT`, `SSH_KEY` and `SSH_FINGERPRINT`. The dedicated public key has
`restrict,command="/usr/local/sbin/famplanner-deploy"` in authorized_keys. Install
`deploy/deploy.sh` root-owned at that path, mode 755. It updates the checkout,
installs locked dependencies, migrates once and restarts both bots. It refuses
dirty tracked files. The Go SSH action negotiates the host's ECDSA key, so derive
its fingerprint with `ssh-keygen -lf /etc/ssh/ssh_host_ecdsa_key.pub -E sha256`.
Do not reuse a personal SSH private key for Actions. TEST/Vitaly secrets are separate.

## Verification

```bash
systemctl is-active tg_bot tg_max_bot famplanner-reminders.timer
systemctl show famplanner-reminders.service -p Result -p ExecMainStatus
systemctl list-timers famplanner-reminders.timer
cd /home/tg_bot
sudo -u famplanner .venv/bin/python cron_handler.py --dry-run
sudo -u famplanner .venv/bin/python cron_handler.py --now=true --dry-run
sudo -u famplanner env LOCAL=1 TG_BOT_TOKEN=test-token MAX_BOT_TOKEN=test-token .venv/bin/python -m pytest -q
```

The MAX webhook responds `200 OK` to GET. Telegram's webhook-only root responds
`405` to GET; confirm the service and Bot API webhook metadata as well. Do not
send real test reminders to users. Check bot `/start`, calendar, notes, event
creation and participant flows manually in the real clients.
