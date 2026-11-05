import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import cron_handler


@pytest.mark.parametrize("send_now", [False, True])
async def test_dry_run_checks_both_platforms_without_sending(monkeypatch, send_now):
    bot = SimpleNamespace(
        request=SimpleNamespace(shutdown=AsyncMock()),
        send_message=AsyncMock(side_effect=AssertionError("Unexpected send")),
    )
    max_api = SimpleNamespace(close=AsyncMock(), send_message=AsyncMock(side_effect=AssertionError("Unexpected send")))
    monkeypatch.setattr(cron_handler.telegram, "Bot", lambda **kwargs: bot)
    monkeypatch.setattr(cron_handler, "HTTPXRequest", lambda **kwargs: None)
    monkeypatch.setattr(cron_handler, "build_max_api", AsyncMock(return_value=max_api))
    monkeypatch.setattr(cron_handler, "engine", SimpleNamespace(dispose=AsyncMock()))
    queries = []

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    async def query(**kwargs):
        queries.append(kwargs)
        return [{"tg_id": 42, "event_id": 7}] if kwargs["offset"] == 0 else []

    monkeypatch.setattr(cron_handler, "AsyncSessionLocal", Session)
    monkeypatch.setattr(cron_handler.db_controller, "get_current_day_events_all_users", query)
    before = datetime.datetime(2026, 11, 5, 12, 0, tzinfo=datetime.timezone.utc)

    class FrozenDatetime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return before

    monkeypatch.setattr(cron_handler.datetime, "datetime", FrozenDatetime)
    await cron_handler.send_messages(send_now=send_now, dry_run=True)
    assert len(queries) == 4
    assert queries[0].get("platform", "tg") == "tg"
    assert queries[1]["platform"] == "max"
    expected = before if send_now else before + datetime.timedelta(hours=1)
    assert queries[0]["event_dt"] == expected
    bot.send_message.assert_not_awaited()
    max_api.send_message.assert_not_awaited()
    bot.request.shutdown.assert_awaited_once()
    max_api.close.assert_awaited_once()
