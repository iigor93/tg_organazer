import logging
from calendar import monthrange
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import and_, delete, extract, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

import config
from config import NEAREST_EVENTS_DAYS
from database.models.event_models import CanceledEvent, DbEvent
from database.models.user_model import User as DB_User
from database.models.user_model import UserRelation
from database.session import AsyncSessionLocal
from entities import Event, Recurrent, TgUser

logger = logging.getLogger(__name__)


class DBController:
    @staticmethod
    def get_effective_month_day(year: int, month: int, day: int) -> int:
        _, num_days = monthrange(year, month)
        return day if day <= num_days else num_days

    @staticmethod
    async def save_update_user(tg_user: TgUser, from_contact: bool = False, current_user: int | None = None) -> None | TgUser:
        logger.info(f"db_controller save: {tg_user}")
        async with AsyncSessionLocal() as session:
            query = select(DB_User).where(DB_User.tg_id == tg_user.tg_id)
            result = (await session.execute(query)).scalar_one_or_none()

            if not result:
                user = DB_User(**tg_user.model_dump())
                user.is_active = False if from_contact else True
                session.add(user)
            else:
                tg_user_dict = tg_user.model_dump()
                if from_contact:
                    tg_user_dict.pop("is_active")
                update_query = update(DB_User).where(DB_User.tg_id == tg_user.tg_id).values(**tg_user_dict).returning(DB_User)
                user = (await session.execute(update_query)).scalar_one_or_none()

            await session.commit()
            await session.refresh(user)

            if from_contact and current_user:
                current_user_query = select(DB_User).where(DB_User.tg_id == current_user)
                current_user = (await session.execute(current_user_query)).scalar_one_or_none()

                new_user_relation = UserRelation(
                    user_id=current_user.id,
                    related_user_id=user.id,
                )
                session.add(new_user_relation)

                try:
                    await session.commit()
                except IntegrityError:
                    return None

        user.id = user.tg_id
        return TgUser.model_validate(user)

    @staticmethod
    async def get_user(tg_id: int) -> dict | None: ...

    @staticmethod
    async def get_participants(tg_id: int) -> dict[int, str] | None:
        async with AsyncSessionLocal() as session:
            db_user_alias = aliased(DB_User)
            query = (
                select(DB_User)
                .join(UserRelation, DB_User.id == UserRelation.related_user_id)
                .join(db_user_alias, UserRelation.user_id == db_user_alias.id)
                .where(db_user_alias.tg_id == tg_id, DB_User.is_active.is_(True))
            )

            participants = (await session.execute(query)).scalars().all()

            return {item.tg_id: item.first_name for item in participants}

    @staticmethod
    async def save_event(event: Event) -> int | None:
        logger.info(f"db_controller save event: {event}")

        start_datetime_tz = (
            datetime.combine(event.event_date, event.start_time)
            .replace(tzinfo=timezone(timedelta(hours=config.DEFAULT_TIMEZONE, minutes=0)))
            .astimezone(timezone.utc)
        )

        stop_datetime_tz = None
        if event.stop_time:
            stop_datetime_tz = (
                datetime.combine(event.event_date, event.stop_time)
                .replace(tzinfo=timezone(timedelta(hours=config.DEFAULT_TIMEZONE, minutes=0)))
                .astimezone(timezone.utc)
            )

        new_event = DbEvent(
            description=event.description,
            start_time=start_datetime_tz.time(),
            event_date_pickup=start_datetime_tz.date(),
            single_event=True if event.recurrent == Recurrent.never else False,
            daily=True if event.recurrent == Recurrent.daily else False,
            weekly=start_datetime_tz.weekday() if event.recurrent == Recurrent.weekly else None,
            monthly=start_datetime_tz.day if event.recurrent == Recurrent.monthly else None,
            annual_day=start_datetime_tz.day if event.recurrent == Recurrent.annual else None,
            annual_month=start_datetime_tz.month if event.recurrent == Recurrent.annual else None,
            stop_time=stop_datetime_tz.time() if stop_datetime_tz else event.stop_time,
            tg_id=event.tg_id,
        )
        async with AsyncSessionLocal() as session:
            session.add(new_event)
            await session.commit()
            await session.refresh(new_event)

            return new_event.id

    @staticmethod
    def get_weekday_days_in_month(year: int, month: int, weekday: int) -> list[int]:
        _, num_days = monthrange(year, month)
        return [day for day in range(1, num_days + 1) if date(year, month, day).weekday() == weekday]

    async def get_current_month_events_by_user(self, user_id: int, month: int, year: int) -> dict[int, int]:
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

            event_dict: dict[int, int | list] = {day: 0 for day in range(1, num_days + 1)}
            event_dict[0] = []  # daily events

            for event in result:
                if event.single_event is True:
                    event_dict[event.event_date_pickup.day] += 1
                elif event.daily is True:
                    event_dict[0].append(event)
                elif event.monthly is not None:
                    effective_day = self.get_effective_month_day(year, month, event.monthly)
                    _calculated_date = date.fromisoformat(f"{year}-{month:02d}-{effective_day:02d}")
                    if _calculated_date in [_ev.cancel_date for _ev in event.canceled_events]:
                        continue

                    event_dict[effective_day] += 1
                elif event.annual_day is not None:
                    _calculated_date = date.fromisoformat(f"{year}-{month:02d}-{event.annual_day:02d}")
                    if _calculated_date in [_ev.cancel_date for _ev in event.canceled_events]:
                        continue
                    event_dict[event.annual_day] += 1
                elif event.weekly is not None:
                    _weekdays = self.get_weekday_days_in_month(year=year, month=month, weekday=event.weekly)
                    for _weekday in _weekdays:
                        _calculated_date = date.fromisoformat(f"{year}-{month:02d}-{_weekday:02d}")
                        if _calculated_date in [_ev.cancel_date for _ev in event.canceled_events]:
                            continue

                        if (
                            _weekday >= event.event_date_pickup.day
                            or date.fromisoformat(f"{year}-{month:02d}-01") > event.event_date_pickup
                        ):
                            try:
                                event_dict[_weekday] += 1
                            except KeyError:
                                event_dict[num_days] += 1

            if event_dict[0]:
                for daily_event in event_dict[0]:
                    if (
                        daily_event.event_date_pickup.month == month and daily_event.event_date_pickup.year == year
                    ):  # daily for current month
                        for key, val in event_dict.items():
                            if key >= daily_event.event_date_pickup.day:
                                _calculated_date = date.fromisoformat(f"{year}-{month:02d}-{key:02d}")
                                if _calculated_date in [_ev.cancel_date for _ev in daily_event.canceled_events]:
                                    continue
                                event_dict[key] += 1
                    else:
                        for key, val in event_dict.items():
                            if key != 0:
                                _calculated_date = date.fromisoformat(f"{year}-{month:02d}-{key:02d}")
                                if _calculated_date in [_ev.cancel_date for _ev in daily_event.canceled_events]:
                                    continue

                                event_dict[key] += 1

            return event_dict

    @staticmethod
    async def get_current_day_events_by_user(user_id: int, month: int, year: int, day: int, deleted: bool = False) -> str | list:
        last_day = monthrange(year, month)[1]
        monthly_clause = DbEvent.monthly == day
        if day == last_day:
            monthly_clause = or_(monthly_clause, DbEvent.monthly > last_day)

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
                        monthly_clause,  # Все ежемесячные события, если совпал день
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

            if deleted:  # тут выборка для удаления по дню
                for event in result:
                    if pickup_date in [_ev.cancel_date for _ev in event.canceled_events]:
                        continue
                    event_list.append(
                        (
                            f"{event.start_time.strftime('%H:%M')}-"
                            f"{event.stop_time.strftime('%H:%M') if event.stop_time else ''}\n"
                            f"{event.description[:20]}",
                            event.id,
                            event.single_event,
                        )
                    )
                return event_list
            else:
                for event in result:
                    if pickup_date in [_ev.cancel_date for _ev in event.canceled_events]:
                        continue

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

    @staticmethod
    async def delete_all_events_by_user(user_id: int) -> None:
        query = delete(DbEvent).where(DbEvent.tg_id == user_id)
        async with AsyncSessionLocal() as session:
            await session.execute(query)
            await session.commit()

    @staticmethod
    async def delete_event_by_id(event_id: int | str) -> tuple:
        query = delete(DbEvent).where(DbEvent.id == int(event_id)).returning(DbEvent)
        async with AsyncSessionLocal() as session:
            result = (await session.execute(query)).scalar_one_or_none()
            await session.commit()

            return result.single_event, f"{result.start_time.strftime('%H:%M')} {result.description}"

    @staticmethod
    async def get_nearest_events(self, user_id: int) -> list:
        start_nearest_date = datetime.now().date()
        stop_nearest_date = start_nearest_date + timedelta(days=NEAREST_EVENTS_DAYS)
        days = []
        months = []
        years = []

        for _date in range(0, NEAREST_EVENTS_DAYS):
            _calculated_date = start_nearest_date + timedelta(days=_date)
            days.append(_calculated_date.day)
            months.append(_calculated_date.month)
            years.append(_calculated_date.year)

        async with AsyncSessionLocal() as session:
            query = (
                select(DbEvent)
                .where(
                    DbEvent.tg_id == user_id,
                    DbEvent.event_date_pickup <= stop_nearest_date,
                    or_(
                        and_(DbEvent.single_event.is_(True), DbEvent.event_date_pickup.between(start_nearest_date, stop_nearest_date)),
                        DbEvent.daily.is_(True),  # Все ежедневные события
                        DbEvent.weekly.is_not(None),  # Все еженедельные события ТК у нас 10 дней, то любое недельное событие попадает
                        DbEvent.monthly.is_not(None),  # Все ежемесячные события, если совпал день
                        and_(
                            DbEvent.annual_day.in_(days),  # Все ежегодные, если совпал месяц и день
                            DbEvent.annual_month.in_(months),
                        ),
                    ),
                )
                .order_by(DbEvent.start_time)
            )

            result = (await session.execute(query)).scalars().all()

            event_list = []

            for event in result:
                if event.single_event is True:
                    event_list.append({datetime.combine(event.event_date_pickup, event.start_time): event.description})

                elif event.daily is True:
                    for _date in range(0, NEAREST_EVENTS_DAYS):
                        _calculated_date = start_nearest_date + timedelta(days=_date)
                        if _calculated_date in [_ev.cancel_date for _ev in event.canceled_events]:
                            continue
                        event_list.append({datetime.combine(_calculated_date, event.start_time): event.description})

                elif event.monthly is not None:
                    for _date in range(0, NEAREST_EVENTS_DAYS):
                        _calculated_date = start_nearest_date + timedelta(days=_date)
                        if _calculated_date in [_ev.cancel_date for _ev in event.canceled_events]:
                            continue
                        effective_day = self.get_effective_month_day(_calculated_date.year, _calculated_date.month, event.monthly)
                        if _calculated_date.day == effective_day:
                            event_list.append({datetime.combine(_calculated_date, event.start_time): event.description})
                            break
                elif event.annual_day is not None:
                    for _date in range(0, NEAREST_EVENTS_DAYS):
                        _calculated_date = start_nearest_date + timedelta(days=_date)
                        if _calculated_date in [_ev.cancel_date for _ev in event.canceled_events]:
                            continue
                        if event.annual_day == _calculated_date.day and event.annual_month == _calculated_date.month:
                            event_list.append({datetime.combine(_calculated_date, event.start_time): event.description})
                            break

                elif event.weekly is not None:
                    for _date in range(0, NEAREST_EVENTS_DAYS):
                        _calculated_date = start_nearest_date + timedelta(days=_date)
                        if _calculated_date in [_ev.cancel_date for _ev in event.canceled_events]:
                            continue
                        if event.weekly == _calculated_date.weekday():
                            event_list.append({datetime.combine(_calculated_date, event.start_time): event.description})

            if event_list:
                event_list = sorted(event_list, key=lambda d: list(d.keys())[0])
            return event_list

    @staticmethod
    async def create_cancel_event(event_id: int, cancel_date: date) -> None:
        new_cancel_event = CanceledEvent(cancel_date=cancel_date, event_id=int(event_id))
        async with AsyncSessionLocal() as session:
            session.add(new_cancel_event)
            await session.commit()

    @staticmethod
    async def get_current_day_events_all_users(event_date: date, event_time: time, session: AsyncSession) -> list:
        last_day = monthrange(event_date.year, event_date.month)[1]
        monthly_clause = DbEvent.monthly == event_date.day
        if event_date.day == last_day:
            monthly_clause = or_(monthly_clause, DbEvent.monthly > last_day)

        logger.info(f"events for day from db: {event_date}, week: {event_date.weekday()}")
        logger.info(f"INCOME DATETIME: {event_date}, {event_time}")

        query = (
            select(DbEvent)
            .where(
                DbEvent.event_date_pickup <= event_date,
                DbEvent.start_time == event_time,
                or_(
                    and_(DbEvent.single_event.is_(True), DbEvent.event_date_pickup == event_date),
                    DbEvent.daily.is_(True),  # Все ежедневные события
                    DbEvent.weekly == event_date.weekday(),  # Все еженедельные события
                    monthly_clause,  # Все ежемесячные события, если совпал день
                    and_(
                        DbEvent.annual_day == event_date.day,  # Все ежегодные, если совпал месяц и день
                        DbEvent.annual_month == event_date.month,
                    ),
                ),
            )
            .order_by(DbEvent.start_time)
        )

        event_list = []
        # {"tg_id": "", "start_time": "", "description": ""}

        result = (await session.execute(query)).scalars().all()

        for event in result:
            if event_date in [_ev.cancel_date for _ev in event.canceled_events]:
                continue

            event_list.append({"tg_id": event.tg_id, "start_time": event.start_time, "description": event.description})

        return event_list

    @staticmethod
    async def resave_event_to_participant(event_id: int, user_id: int) -> int | None:
        async with AsyncSessionLocal() as session:
            query = select(DbEvent).where(DbEvent.id == event_id)
            event = (await session.execute(query)).scalar_one_or_none()

            if not event:
                return None

            new_event = DbEvent(
                description=event.description,
                start_time=event.start_time,
                event_date_pickup=event.event_date_pickup,
                single_event=event.single_event,
                daily=event.daily,
                weekly=event.weekly,
                monthly=event.monthly,
                annual_day=event.annual_day,
                annual_month=event.annual_month,
                stop_time=event.stop_time,
                tg_id=user_id,
            )

            session.add(new_event)
            await session.commit()
            await session.refresh(new_event)
            #
            # text = (
            #     f"Событие добавлено в календарь:"
            #     f"\n{event.event_date_pickup.day}.{event.event_date_pickup.month:02d}.{event.event_date_pickup.year} "
            #     f"время {event.start_time.strftime('%H:%M')}-{event.stop_time.strftime('%H:%M') if event.stop_time else ''}"
            #     f"\n{event.description}"
            # )

            return new_event.id


db_controller = DBController()
