import datetime
import enum

from pydantic import BaseModel, ConfigDict, Field

from config import MONTH_NAMES


class Recurrent(enum.StrEnum):
    never = "never"
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"
    annual = "annual"

    def get_name(self) -> str:
        if self.value == "never":
            return "Никогда"
        elif self.value == "daily":
            return "Ежедневно"
        elif self.value == "weekly":
            return "Еженедельно"
        elif self.value == "monthly":
            return "Ежемесячно"
        else:
            return "Каждый год"

    @staticmethod
    def get_all_names() -> list[tuple]:
        return [(item.get_name(), item.value) for item in Recurrent]


class Event(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_date: datetime.date
    description: str | None = None
    start_time: datetime.time | None = None
    stop_time: datetime.time | None = None
    recurrent: Recurrent = Recurrent.never
    participants: list[int | None] = Field(default_factory=list)
    tg_id: int

    def get_date(self) -> tuple[int, int, int]:
        return self.event_date.year, self.event_date.month, self.event_date.day

    def get_format_date(self) -> str:
        return f"{self.event_date.day} {(MONTH_NAMES[int(self.event_date.month) - 1]).title()} {self.event_date.year} года"


class TgUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tg_id: int = Field(int, alias="id")
    is_active: bool = True
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    language_code: str | None = None
