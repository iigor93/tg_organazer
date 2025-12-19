from dataclasses import dataclass, field


@dataclass
class Event:
    title: str
    event_datetime: str
    recurrent: str


@dataclass
class User:
    telegram_id: str | int
    geo_location: str | None = None
    events: list[Event | None] = field(default_factory=lambda: [])

    def get_events(self) -> str:
        if self.events:
            _events = "\n".join([f"{event.event_datetime}: {event.title}" for event in self.events])
        else:
            _events = "Событий не найдено. Давай заведем событие"

        return _events
