# Project memory

- Production runs on `77.91.75.194` (Ubuntu 24.04, 2 vCPU / 2 GB) at `/home/tg_bot`.
  `tg_bot` and `tg_max_bot` run as the unprivileged `famplanner` user using the
  locked Python 3.12 environment. Native PostgreSQL database/role: `famplanner`.
  Supabase is not used by these bots.
- The migration preserved all seven public tables, including both Alembic heads
  `e4f5a6b7c8d9` and `f6a7b8c9d0e1`. Use `alembic upgrade heads`, not `head`.
  Do not stamp away the two-head history or mix this database with `max_comments`.
- Webhooks: `https://tgwebhook.ckobah.ru` and `https://maxhook.ckobah.ru`.
  The old MAX subscription at `maxhook.famplanner.ru` was replaced, not duplicated.
  Telegram pending updates are retained. Both webhook secrets remain required.
- `famplanner-reminders.timer` runs one non-overlapping job every minute, executing
  the one-hour and current-time modes sequentially. Both modes are attempted even
  if one fails. Old reminder cron entries are disabled. `--dry-run` reads schedules
  without sending. This preserves the existing minute-based behavior, without
  persistent delivery retries or catch-up after prolonged outages.
- DB pools are bounded: two connections per bot, one for the reminder process.
  All reminder DB work shares the module engine. Telegram reminder/link requests
  honor `TG_PROXY`; preserve the existing proxy and trusted CA settings.
- Old `ru-vmv2-nano` bot units are masked. Its database is stale after cutover;
  never restart its writers as a simple rollback. Original files/DB/cron/units are
  backed up under `/root/famplanner-migration-20261105`. A temporary forwarder
  handles old ports 8001/8003 during DNS propagation.
- Main deployments use a dedicated restricted Actions SSH key and the root-owned
  `/usr/local/sbin/famplanner-deploy` script. `SSH_FINGERPRINT` pins the host ECDSA
  key selected by the Go SSH client. The Vitaly/test deployment remains separate.
- Operational templates and the cutover/rollback procedure are in `deploy/`
  and `docs/server_migration.md`. Secrets belong only in the private `.env` or
  GitHub secrets; do not commit keys, tokens, copied dotenv files or database dumps.
