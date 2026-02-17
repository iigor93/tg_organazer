from __future__ import annotations

from datetime import timedelta

import pytest

from weather import WeatherService


def test_weather_cache_ttl_is_two_hours():
    service = WeatherService()
    assert service._weather_ttl == timedelta(hours=2)


@pytest.mark.asyncio
async def test_get_weather_for_city_uses_cache_within_ttl(monkeypatch):
    service = WeatherService()
    resolve_calls = 0
    fetch_calls = 0

    async def fake_resolve_city_coords(city: str):
        nonlocal resolve_calls
        resolve_calls += 1
        return 55.7558, 37.6176

    async def fake_fetch_forecast(latitude: float, longitude: float):
        nonlocal fetch_calls
        fetch_calls += 1
        return "+5°C", "☀️"

    monkeypatch.setattr(service, "_resolve_city_coords", fake_resolve_city_coords)
    monkeypatch.setattr(service, "_fetch_forecast", fake_fetch_forecast)

    first = await service.get_weather_for_city(user_id=1, city="Moscow", platform="tg")
    second = await service.get_weather_for_city(user_id=1, city="Moscow", platform="tg")

    assert first is not None
    assert second is not None
    assert first == second
    assert resolve_calls == 1
    assert fetch_calls == 1


@pytest.mark.asyncio
async def test_localize_city_name_respects_locale_and_cache(monkeypatch):
    service = WeatherService()
    calls: list[tuple[str, str]] = []

    async def fake_search_city_name(city: str, language: str):
        calls.append((city, language))
        if language == "ru":
            return "Москва"
        if language == "en":
            return "Moscow"
        return city

    monkeypatch.setattr(service, "_search_city_name", fake_search_city_name)

    ru_first = await service.localize_city_name("Moscow", "ru")
    ru_second = await service.localize_city_name("Moscow", "ru")
    en_value = await service.localize_city_name("Moscow", "en")

    assert ru_first == "Москва"
    assert ru_second == "Москва"
    assert en_value == "Moscow"
    assert calls == [("Moscow", "ru"), ("Moscow", "en")]


@pytest.mark.asyncio
async def test_localize_city_name_skips_placeholder(monkeypatch):
    service = WeatherService()
    called = False

    async def fake_search_city_name(city: str, language: str):
        nonlocal called
        called = True
        return city

    monkeypatch.setattr(service, "_search_city_name", fake_search_city_name)

    value = await service.localize_city_name("-", "ru")
    assert value == "-"
    assert called is False
