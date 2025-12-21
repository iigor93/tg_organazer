import datetime
import enum
from dataclasses import dataclass, field

from config import MONTH_NAMES


class Recurrent(enum.StrEnum):
    never = "never"
    daily = "daily"
    weekly = "weekly"
    annual = "annual"

    def get_name(self) -> str:
        if self.value == "never":
            return "Никогда"
        elif self.value == "daily":
            return "Ежедневно"
        elif self.value == "weekly":
            return "Еженедельно"
        else:
            return "Каждый год"

    @staticmethod
    def get_all_names() -> list[tuple]:
        return [(item.get_name(), item.value) for item in Recurrent]


@dataclass
class Event:
    event_date: datetime.date
    title: str | None = None
    start_time: str | None = None
    stop_time: str | None = None
    recurrent: Recurrent = Recurrent.never
    participants: list | None = None

    def get_date(self) -> tuple[int, int, int]:
        return self.event_date.year, self.event_date.month, self.event_date.day

    def get_format_date(self) -> str:
        return f"{self.event_date.day} {(MONTH_NAMES[int(self.event_date.month) - 1]).title()} {self.event_date.year} года"


@dataclass
class User:
    telegram_id: str | int
    geo_location: str | None = None
    events: list[Event | None] = field(default_factory=lambda: [])

    def get_events(self) -> str:
        if self.events:
            _events = "\n".join([f"{event.start_time}: {event.title}" for event in self.events])
        else:
            _events = "Событий не найдено. Давай заведем событие"

        return _events
