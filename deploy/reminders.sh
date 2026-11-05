#!/bin/sh
# Attempt both modes even if one fails. systemd prevents overlapping runs.
status=0
cd /home/tg_bot || exit 1
.venv/bin/python cron_handler.py || status=1
.venv/bin/python cron_handler.py --now=true || status=1
exit "$status"
