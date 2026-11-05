#!/usr/bin/env bash
set -euo pipefail
exec 9>/run/lock/famplanner-deploy.lock
flock 9
cd /home/tg_bot
if [[ -n "$(runuser -u famplanner -- git status --porcelain --untracked-files=no)" ]]; then
    echo "Refusing to overwrite uncommitted deployment changes." >&2
    exit 1
fi
runuser -u famplanner -- git pull --ff-only origin main
runuser -u famplanner -- /usr/local/bin/uv sync --frozen --no-dev --python /usr/bin/python3.12
runuser -u famplanner -- .venv/bin/python -m alembic upgrade heads
systemctl restart tg_bot tg_max_bot
systemctl enable --now famplanner-reminders.timer
for attempt in {1..30}; do
    tg_status=$(curl --silent --max-time 2 --output /dev/null --write-out '%{http_code}' http://127.0.0.1:8001/ || true)
    if [[ "$tg_status" == 405 ]] && curl --fail --silent --max-time 2 http://127.0.0.1:8003/; then
        echo "FamPlanner webhooks are ready."
        exit 0
    fi
    sleep 1
done
echo "FamPlanner webhook readiness check failed." >&2
exit 1
