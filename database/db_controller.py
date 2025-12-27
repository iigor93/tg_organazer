import logging
from calendar import monthrange
from datetime import date

from sqlalchemy import and_, extract, or_, select, update

from database.models.event_models import DbEvent
from database.models.user_model import User as DB_User
from database.session import AsyncSessionLocal
from entities import Event, Recurrent, TgUser

logger = logging.getLogger(__name__)


class DBController:
    @staticmethod
    async def save_update_user(tg_user: TgUser) -> None:
        logger.info(f"db_controller save: {tg_user}")
        async with AsyncSessionLocal() as session:
            query = select(DB_User).where(DB_User.tg_id == tg_user.tg_id)
            result = (await session.execute(query)).scalar_one_or_none()

            if not result:
                new_user = DB_User(**tg_user.model_dump())
                session.add(new_user)
            else:
                update_query = update(DB_User).where(DB_User.tg_id == tg_user.tg_id).values(**tg_user.model_dump())
                await session.execute(update_query)

            await session.commit()

    @staticmethod
    async def save_event(event: Event) -> None:
        logger.info(f"db_controller save event: {event}")

        new_event = DbEvent(
            description=event.description,
            start_time=event.start_time,
            event_date_pickup=event.event_date,
            single_event=True if event.recurrent == Recurrent.never else False,
            daily=True if event.recurrent == Recurrent.daily else False,
            weekly=event.event_date.weekday() if event.recurrent == Recurrent.weekly else None,
            monthly=event.event_date.day if event.recurrent == Recurrent.monthly else None,
            annual_day=event.event_date.day if event.recurrent == Recurrent.annual else None,
            annual_month=event.event_date.month if event.recurrent == Recurrent.annual else None,
            stop_time=event.stop_time,
            tg_id=event.tg_id,
        )
        async with AsyncSessionLocal() as session:
            session.add(new_event)
            await session.commit()

    @staticmethod
    def get_weekday_days_in_month(year: int, month: int, weekday: int) -> list[int]:
        _, num_days = monthrange(year, month)
        return [day for day in range(1, num_days + 1) if date(year, month, day).weekday() == weekday]

    async def get_current_month_events_by_user(self, user_id, month: int, year: int) -> dict[int, int]:
        _, num_days = monthrange(year, month)

        last_day_of_month = date.fromisoformat(f"{year}-{month:02d}-{num_days:02d}")

        async with AsyncSessionLocal() as session:
            query = select(DbEvent).where(
                DbEvent.tg_id == user_id,
                DbEvent.event_date_pickup <= last_day_of_month,
                or_(
                    and_(
                        DbEvent.single_event.is_(True),
                        extract("year", DbEvent.event_date_pickup) == year,
                        extract("month", DbEvent.event_date_pickup) == month,
                    ),
                    DbEvent.daily.is_(True),  # Все ежедневные события
                    DbEvent.weekly.is_not(None),  # Все еженедельные события
                    DbEvent.monthly.is_not(None),  # Все ежемесячные события
                    DbEvent.annual_month == month,  # Все ежегодные, если совпал месяц
                ),
            )

            result = (await session.execute(query)).scalars().all()
            for i in result:
                logger.info(f"event id: {i.id}")

            event_dict = {day: 0 for day in range(1, num_days + 1)}
            event_dict[0] = 0  # daily events
            for event in result:
                if event.single_event is True:
                    event_dict[event.event_date_pickup.day] += 1
                elif event.daily is True:
                    event_dict[0] += 1
                elif event.monthly is not None:
                    try:
                        event_dict[event.monthly] += 1
                    except KeyError:
                        event_dict[num_days] += 1
                elif event.annual_day is not None:
                    event_dict[event.annual_day] += 1
                elif event.weekly is not None:
                    _weekdays = self.get_weekday_days_in_month(year=year, month=month, weekday=event.weekly)
                    for _weekday in _weekdays:
                        if (
                            _weekday >= event.event_date_pickup.day
                            or date.fromisoformat(f"{year}-{month:02d}-01") > event.event_date_pickup
                        ):
                            try:
                                event_dict[_weekday] += 1
                            except KeyError:
                                event_dict[num_days] += 1

            if event_dict[0]:
                add_events = event_dict[0]
                for key, val in event_dict.items():
                    if key != 0:
                        event_dict[key] += add_events

            return event_dict

    async def get_current_day_events_by_user(self, user_id, month: int, year: int, day: int) -> str:
        pickup_date = date.fromisoformat(f"{year}-{month:02d}-{day:02d}")
        logger.info(f"events for day from db: {pickup_date}, week: {pickup_date.weekday()}")

        async with AsyncSessionLocal() as session:
            query = (
                select(DbEvent)
                .where(
                    DbEvent.tg_id == user_id,
                    DbEvent.event_date_pickup <= pickup_date,
                    or_(
                        and_(DbEvent.single_event.is_(True), DbEvent.event_date_pickup == pickup_date),
                        DbEvent.daily.is_(True),  # Все ежедневные события
                        DbEvent.weekly == pickup_date.weekday(),  # Все еженедельные события
                        DbEvent.monthly == day,  # Все ежемесячные события, если совпал день
                        and_(
                            DbEvent.annual_day == day,  # Все ежегодные, если совпал месяц и день
                            DbEvent.annual_month == month,
                        ),
                    ),
                )
                .order_by(DbEvent.start_time)
            )

            event_list = []

            result = (await session.execute(query)).scalars().all()
            for event in result:
                recurrent = ""
                if event.single_event:
                    recurrent = "(одиночное)"
                elif event.daily:
                    recurrent = f"({Recurrent.daily.get_name().lower()})"
                elif event.weekly:
                    recurrent = f"({Recurrent.weekly.get_name().lower()})"
                elif event.monthly:
                    recurrent = f"({Recurrent.monthly.get_name().lower()})"
                elif event.annual_day:
                    recurrent = f"({Recurrent.annual.get_name().lower()})"

                event_list.append(
                    f"{event.start_time.strftime('%H:%M')}-{event.stop_time.strftime('%H:%M') if event.stop_time else ''}"
                    f" {recurrent} — {event.description}"
                )

            return "\n".join(event_list)


db_controller = DBController()
