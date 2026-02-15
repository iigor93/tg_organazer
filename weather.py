import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_GEOCODING_SEARCH_URL = "https://geocoding-api.open-meteo.com/v1/search"
_GEOCODING_REVERSE_URL = "https://geocoding-api.open-meteo.com/v1/reverse"


def _emoji_for_weather_code(code: int | None) -> str:
    if code is None:
        return "❔"
    if code == 0:
        return "☀️"
    if code in {1, 2, 3}:
        return "☁️"
    if code in {45, 48}:
        return "🌫️"
    if code in {51, 53, 55, 56, 57}:
        return "🌦️"
    if code in {61, 63, 65, 66, 67, 80, 81, 82}:
        return "🌧️"
    if code in {71, 73, 75, 77, 85, 86}:
        return "❄️"
    if code in {95, 96, 99}:
        return "⛈️"
    return "🌤️"


def _format_temperature(temp_c: float | None) -> str:
    if temp_c is None:
        return "--°C"
    rounded = int(round(temp_c))
    return f"{rounded:+d}°C"


@dataclass
class WeatherInfo:
    city: str
    temperature_text: str
    emoji: str
    fetched_at: datetime


@dataclass
class _WeatherCacheItem:
    city_key: str
    data: WeatherInfo
    saved_at: datetime


class WeatherService:
    def __init__(self) -> None:
        self._weather_cache: dict[tuple[str, int], _WeatherCacheItem] = {}
        self._geocode_cache: dict[str, tuple[float, float, datetime]] = {}
        self._lock = asyncio.Lock()
        self._weather_ttl = timedelta(hours=1)
        self._geocode_ttl = timedelta(hours=24)

    @staticmethod
    def _city_key(city: str) -> str:
        return city.strip().lower()

    async def resolve_city_from_coords(self, latitude: float, longitude: float, locale: str | None = None) -> str | None:
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "count": 1,
            "language": (locale or "ru")[:2],
        }
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.get(_GEOCODING_REVERSE_URL, params=params)
                response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            logger.exception("Failed to resolve city by coordinates: lat=%s lon=%s", latitude, longitude)
            return None

        results = payload.get("results") if isinstance(payload, dict) else None
        if not results:
            return None
        first = results[0]
        city = first.get("city") or first.get("name")
        if not city:
            return None
        return str(city).strip() or None

    async def get_weather_for_city(self, user_id: int, city: str | None, platform: str = "tg") -> WeatherInfo | None:
        if not city or not city.strip():
            return None

        city_key = self._city_key(city)
        now = datetime.now(timezone.utc)
        cache_key = (platform, int(user_id))

        async with self._lock:
            cached = self._weather_cache.get(cache_key)
            if cached and cached.city_key == city_key and now - cached.saved_at < self._weather_ttl:
                return cached.data

        coords = await self._resolve_city_coords(city=city)
        if not coords:
            return None

        temperature_text, weather_emoji = await self._fetch_forecast(latitude=coords[0], longitude=coords[1])
        if temperature_text is None:
            return None

        weather_data = WeatherInfo(city=city.strip(), temperature_text=temperature_text, emoji=weather_emoji, fetched_at=now)

        async with self._lock:
            self._weather_cache[cache_key] = _WeatherCacheItem(city_key=city_key, data=weather_data, saved_at=now)

        return weather_data

    async def _resolve_city_coords(self, city: str) -> tuple[float, float] | None:
        city_key = self._city_key(city)
        now = datetime.now(timezone.utc)
        cached = self._geocode_cache.get(city_key)
        if cached and now - cached[2] < self._geocode_ttl:
            return cached[0], cached[1]

        params = {
            "name": city,
            "count": 1,
            "language": "ru",
            "format": "json",
        }
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.get(_GEOCODING_SEARCH_URL, params=params)
                response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            logger.exception("Failed to resolve city coordinates: city=%s", city)
            return None

        results = payload.get("results") if isinstance(payload, dict) else None
        if not results:
            return None

        first = results[0]
        latitude = first.get("latitude")
        longitude = first.get("longitude")
        if latitude is None or longitude is None:
            return None

        lat = float(latitude)
        lon = float(longitude)
        self._geocode_cache[city_key] = (lat, lon, now)
        return lat, lon

    async def _fetch_forecast(self, latitude: float, longitude: float) -> tuple[str | None, str]:
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,weather_code",
            "timezone": "auto",
        }
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.get(_FORECAST_URL, params=params)
                response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            logger.exception("Failed to fetch weather forecast for lat=%s lon=%s", latitude, longitude)
            return None, "❔"

        current = payload.get("current") if isinstance(payload, dict) else None
        if not isinstance(current, dict):
            return None, "❔"

        temperature = current.get("temperature_2m")
        weather_code = current.get("weather_code")

        temp_value = float(temperature) if temperature is not None else None
        temp_text = _format_temperature(temp_value)

        try:
            code_value = int(weather_code) if weather_code is not None else None
        except (TypeError, ValueError):
            code_value = None
        return temp_text, _emoji_for_weather_code(code_value)


weather_service = WeatherService()
