import logging
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import and_, delete, or_, select, update
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
                tg_user_dict = tg_user.model_dump(exclude={"title"}, exclude_defaults=True, exclude_unset=True)
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
        user.time_zone = config.DEFAULT_TIMEZONE_NAME if not user.time_zone else user.time_zone
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
    async def save_event(event: Event, tz_name: str = config.DEFAULT_TIMEZONE_NAME) -> int | None:
        logger.info(f"db_controller save event: {event}")

        user_tz = ZoneInfo(tz_name)

        start_datetime_tz = datetime.combine(event.event_date, event.start_time).replace(tzinfo=user_tz).astimezone(timezone.utc)

        stop_datetime_tz = None
        if event.stop_time:
            stop_datetime_tz = datetime.combine(event.event_date, event.stop_time).replace(tzinfo=user_tz).astimezone(timezone.utc)

        new_event = DbEvent(
            description=event.description,
            start_time=start_datetime_tz.time(),
            single_event=True if event.recurrent == Recurrent.never else False,
            daily=True if event.recurrent == Recurrent.daily else False,
            weekly=start_datetime_tz.weekday() if event.recurrent == Recurrent.weekly else None,
            monthly=start_datetime_tz.day if event.recurrent == Recurrent.monthly else None,
            annual_day=start_datetime_tz.day if event.recurrent == Recurrent.annual else None,
            annual_month=start_datetime_tz.month if event.recurrent == Recurrent.annual else None,
            tg_id=event.tg_id,
            start_at=start_datetime_tz,
            stop_at=stop_datetime_tz,
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

    async def get_current_month_events_by_user(
        self, user_id: int, month: int, year: int, tz_name: str = config.DEFAULT_TIMEZONE_NAME
    ) -> dict[int, int]:
        _, num_days = monthrange(year, month)

        user_tz = ZoneInfo(tz_name)

        month_start_local = datetime(year, month, 1, 0, 0, 0, tzinfo=user_tz)
        month_end_local = datetime(year, month, num_days, 23, 59, 59, tzinfo=user_tz)

        # Переводим границы в UTC
        month_start_utc = month_start_local.astimezone(timezone.utc)
        month_end_utc = month_end_local.astimezone(timezone.utc)

        async with AsyncSessionLocal() as session:
            query = select(DbEvent).where(
                DbEvent.tg_id == user_id,
                DbEvent.start_at <= month_end_utc,
                or_(
                    and_(
                        DbEvent.single_event.is_(True),
                        DbEvent.start_at >= month_start_utc,
                    ),
                    and_(
                        or_(
                            DbEvent.daily.is_(True),
                            DbEvent.weekly.is_not(None),
                            DbEvent.monthly.is_not(None),
                            and_(DbEvent.annual_month.is_not(None), DbEvent.annual_month.in_([month_start_utc.month, month_end_utc.month])),
                        ),
                    ),
                ),
            )

            events = (await session.execute(query)).scalars().all()

        event_dict: dict[int, int | list] = {day: 0 for day in range(1, num_days + 1)}
        event_dict[0] = []  # для daily

        def is_canceled(ev: DbEvent, d: date) -> bool:
            return d in {_ev.cancel_date for _ev in ev.canceled_events}

        for event in events:
            # Локальное время начала события
            start_local_dt = event.start_at.astimezone(user_tz)
            end_local_time = event.stop_at.astimezone(user_tz).time() if event.stop_at else None  # noqa

            # SINGLE EVENT
            if event.single_event:
                event_dict[start_local_dt.day] += 1

            # DAILY EVENTS
            elif event.daily:
                event_dict[0].append(event)

            # MONTHLY EVENTS
            elif event.monthly is not None:
                day_in_month = self.get_effective_month_day(year, month, start_local_dt.day)
                calculated_date = date(year, month, day_in_month)
                if calculated_date >= start_local_dt.date() and not is_canceled(event, calculated_date):
                    event_dict[day_in_month] += 1

            # ANNUAL EVENTS
            elif event.annual_day is not None:
                start_local = event.start_at.astimezone(user_tz)

                event_month = start_local.month
                event_day = start_local.day

                if event_month != month:
                    continue

                calculated_date = date(year, month, event_day)

                if calculated_date >= start_local.date() and not is_canceled(event, calculated_date):
                    event_dict[event_day] += 1

            # WEEKLY EVENTS
            elif event.weekly is not None:
                weekday_user_tz = event.start_at.astimezone(user_tz).weekday()
                weekdays = self.get_weekday_days_in_month(year=year, month=month, weekday=weekday_user_tz)
                for day in weekdays:
                    calculated_date_user_tz = date(year, month, day)
                    if calculated_date_user_tz >= start_local_dt.date() and not is_canceled(event, calculated_date_user_tz):
                        event_dict[day] += 1

        for daily_event in event_dict[0]:
            start_day = daily_event.start_at.astimezone(user_tz).date()
            for day in range(1, num_days + 1):
                calculated_date = date(year, month, day)
                if start_day <= calculated_date and not is_canceled(daily_event, calculated_date):
                    event_dict[day] += 1

        return event_dict

    @staticmethod
    async def get_current_day_events_by_user(
        user_id: int, month: int, year: int, day: int, tz_name: str = config.DEFAULT_TIMEZONE_NAME, deleted: bool = False
    ) -> str | list:
        user_tz = ZoneInfo(tz_name)
        pickup_date_local = date(year, month, day)
        _, num_days = monthrange(year, month)
        add_days = 4 if day == num_days else 0

        day_start_local = datetime(year, month, day, 0, 0, 0, tzinfo=user_tz)
        day_end_local = datetime(year, month, day, 23, 59, 59, tzinfo=user_tz)

        day_start_utc = day_start_local.astimezone(timezone.utc)
        day_end_utc = day_end_local.astimezone(timezone.utc)

        day_start_for_monthly = 1 if day_start_utc.day > day_end_utc.day else day_start_utc.day

        async with AsyncSessionLocal() as session:
            query = select(DbEvent).where(
                DbEvent.tg_id == user_id,
                DbEvent.start_at <= day_end_utc,
                or_(
                    and_(
                        DbEvent.single_event.is_(True),
                        DbEvent.start_at >= day_start_utc,
                    ),
                    DbEvent.daily.is_(True),
                    and_(DbEvent.weekly.is_not(None), DbEvent.weekly.in_([day_start_utc.weekday(), day_end_utc.weekday()])),
                    and_(
                        DbEvent.monthly.is_not(None),
                        or_(
                            DbEvent.monthly.in_(range(day_start_for_monthly, day_end_utc.day + 1 + add_days)),
                            DbEvent.monthly == day_start_utc.day,
                        ),
                    ),
                    and_(
                        DbEvent.annual_day.is_not(None),
                        DbEvent.annual_day.in_([day_start_utc.day, day_end_utc.day]),
                        DbEvent.annual_month.in_([day_start_utc.month, day_end_utc.month]),
                    ),
                ),
            )

            events = (await session.execute(query)).scalars().all()

        event_list = []

        def is_canceled(event: DbEvent) -> bool:
            return pickup_date_local in {_ev.cancel_date for _ev in event.canceled_events}

        for event in events:
            if is_canceled(event):
                continue

            event_start_local_dt = event.start_at.astimezone(user_tz)

            event_stop_local_time = None
            if event.stop_at:
                event_stop_local_time = event.stop_at.astimezone(user_tz).time()

            if event.daily:
                recurrent = f"({Recurrent.daily.get_name().lower()})"
            elif event.weekly is not None:
                if event_start_local_dt.weekday() != day_start_local.weekday():
                    continue
                recurrent = f"({Recurrent.weekly.get_name().lower()})"
            elif event.monthly is not None:
                if event_start_local_dt.day not in range(day_start_local.day, day_start_local.day + 1 + add_days):
                    continue
                recurrent = f"({Recurrent.monthly.get_name().lower()})"
            elif event.annual_day is not None:
                if event_start_local_dt.day != day_start_local.day or event_start_local_dt.month != day_start_local.month:
                    continue
                recurrent = f"({Recurrent.annual.get_name().lower()})"
            else:
                recurrent = ""

            if deleted:
                event_list.append(
                    (
                        f"{event_start_local_dt.time().strftime('%H:%M')}-"
                        f"{event_stop_local_time.strftime('%H:%M') if event_stop_local_time else ''}\n"
                        f"{event.description[:20]}",
                        event.id,
                        event.single_event,
                    )
                )
            else:
                event_list.append(
                    f"{event_start_local_dt.time().strftime('%H:%M')}-"
                    f"{event_stop_local_time.strftime('%H:%M') if event_stop_local_time else ''} "
                    f"{recurrent} — {event.description}"
                )

        event_list.sort(key=lambda x: x[0] if isinstance(x, tuple) else x)

        return event_list if deleted else "\n".join(event_list)

    @staticmethod
    async def delete_all_events_by_user(user_id: int) -> None:
        query = delete(DbEvent).where(DbEvent.tg_id == user_id)
        async with AsyncSessionLocal() as session:
            await session.execute(query)
            await session.commit()

    @staticmethod
    async def delete_event_by_id(
        event_id: int | str,
        tz_name: str = config.DEFAULT_TIMEZONE_NAME,
    ) -> tuple:
        user_tz = ZoneInfo(tz_name)
        query = delete(DbEvent).where(DbEvent.id == int(event_id)).returning(DbEvent)
        async with AsyncSessionLocal() as session:
            result = (await session.execute(query)).scalar_one_or_none()
            await session.commit()

            return result.single_event, f"{result.start_at.astimezone(user_tz).time().strftime('%H:%M')} {result.description}"

    async def get_nearest_events(
        self,
        user_id: int,
        tz_name: str = config.DEFAULT_TIMEZONE_NAME,
    ) -> list:
        user_tz = ZoneInfo(tz_name)

        start_local = datetime.now(user_tz)
        stop_local = start_local + timedelta(days=NEAREST_EVENTS_DAYS)

        start_dt_utc = start_local.astimezone(timezone.utc)
        stop_dt_utc = stop_local.astimezone(timezone.utc)

        async with AsyncSessionLocal() as session:
            query = (
                select(DbEvent)
                .where(
                    DbEvent.tg_id == user_id,
                    DbEvent.start_at <= stop_dt_utc,
                    or_(
                        and_(DbEvent.single_event.is_(True), DbEvent.start_at.between(start_dt_utc, stop_dt_utc)),
                        DbEvent.daily.is_(True),  # Все ежедневные события
                        DbEvent.weekly.is_not(None),  # Все еженедельные события ТК у нас 10 дней, то любое недельное событие попадает
                        and_(
                            DbEvent.monthly.is_not(None),  # Все ежемесячные события, если совпал день
                            DbEvent.monthly.between(start_dt_utc.day, stop_dt_utc.day),
                        ),
                        and_(
                            DbEvent.annual_day.between(start_dt_utc.day, stop_dt_utc.day),
                            DbEvent.annual_month.in_([start_dt_utc.month, stop_dt_utc.month]),
                        ),
                    ),
                )
                .order_by(DbEvent.start_time)
            )

            result = (await session.execute(query)).scalars().all()

            event_list = []

            for event in result:
                _event_start_at_user_tz = event.start_at.astimezone(user_tz)

                if event.single_event is True:
                    event_list.append({_event_start_at_user_tz: event.description})

                elif event.daily is True:
                    for _date in range(0, NEAREST_EVENTS_DAYS):
                        _calculated_date = start_local + timedelta(days=_date)
                        if _calculated_date.date() in [_ev.cancel_date for _ev in event.canceled_events]:
                            continue
                        _combined = datetime.combine(_calculated_date.date(), _event_start_at_user_tz.time()).astimezone(user_tz)
                        event_list.append({_combined: event.description})

                elif event.monthly is not None:
                    for _date in range(0, NEAREST_EVENTS_DAYS):
                        _calculated_date = start_local + timedelta(days=_date)
                        if _calculated_date.date() in [_ev.cancel_date for _ev in event.canceled_events]:
                            continue

                        effective_day = self.get_effective_month_day(
                            _calculated_date.year, _calculated_date.month, _event_start_at_user_tz.day
                        )
                        if _calculated_date.day == effective_day:
                            _combined = datetime.combine(_calculated_date.date(), _event_start_at_user_tz.time()).astimezone(user_tz)
                            event_list.append({_combined: event.description})

                elif event.annual_day is not None:
                    for _date in range(0, NEAREST_EVENTS_DAYS):
                        _calculated_date = start_local + timedelta(days=_date)
                        if _calculated_date.date() in [_ev.cancel_date for _ev in event.canceled_events]:
                            continue
                        if _event_start_at_user_tz.day == _calculated_date.day and _event_start_at_user_tz.month == _calculated_date.month:
                            _combined = datetime.combine(_calculated_date.date(), _event_start_at_user_tz.time()).astimezone(user_tz)
                            event_list.append({_combined: event.description})
                            break

                elif event.weekly is not None:
                    for _date in range(0, NEAREST_EVENTS_DAYS):
                        _calculated_date = start_local + timedelta(days=_date)
                        if _calculated_date.date() in [_ev.cancel_date for _ev in event.canceled_events]:
                            continue
                        if _event_start_at_user_tz.weekday() == _calculated_date.weekday() and _event_start_at_user_tz < _calculated_date:
                            _combined = datetime.combine(_calculated_date.date(), _event_start_at_user_tz.time()).astimezone(user_tz)
                            event_list.append({_combined: event.description})

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
    async def get_current_day_events_all_users(event_dt: datetime, session: AsyncSession) -> list:
        last_day = monthrange(event_dt.year, event_dt.month)[1]
        monthly_clause = DbEvent.monthly == event_dt.day
        if event_dt.day == last_day:
            monthly_clause = or_(monthly_clause, DbEvent.monthly > last_day)

        logger.info(f"events for day from db: {event_dt}, week: {event_dt.weekday()}")
        logger.info(f"INCOME DATETIME: {event_dt}")

        query = (
            select(DbEvent)
            .where(
                DbEvent.start_at <= event_dt,
                DbEvent.start_time == event_dt.time(),
                or_(
                    and_(DbEvent.single_event.is_(True), DbEvent.start_at == event_dt),
                    DbEvent.daily.is_(True),  # Все ежедневные события
                    DbEvent.weekly == event_dt.weekday(),  # Все еженедельные события
                    monthly_clause,  # Все ежемесячные события, если совпал день
                    and_(
                        DbEvent.annual_day == event_dt.day,  # Все ежегодные, если совпал месяц и день
                        DbEvent.annual_month == event_dt.month,
                    ),
                ),
            )
            .order_by(DbEvent.start_time)
        )

        event_list = []
        # {"tg_id": "", "start_time": "", "description": ""}

        result = (await session.execute(query)).scalars().all()

        users_query = select(DB_User).where(DB_User.tg_id.in_([event.tg_id for event in result]))
        users = (await session.execute(users_query)).scalars().all()

        users_dict = {}

        dt_aware_default = datetime.now(ZoneInfo(config.DEFAULT_TIMEZONE_NAME)).utcoffset()

        for _user in users:
            tz = ZoneInfo(_user.time_zone) if _user.time_zone else ZoneInfo(config.DEFAULT_TIMEZONE_NAME)
            dt_aware = datetime.now(tz)

            users_dict[_user.tg_id] = dt_aware.utcoffset()

        for event in result:
            if event_dt.date() in [_ev.cancel_date for _ev in event.canceled_events]:
                continue

            event_list.append(
                {
                    "tg_id": event.tg_id,
                    "start_time": (event.start_at + users_dict.get(event.tg_id, dt_aware_default)).time(),
                    "description": event.description,
                }
            )

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
                start_at=event.start_at,
                stop_at=event.stop_at,
                single_event=event.single_event,
                daily=event.daily,
                weekly=event.weekly,
                monthly=event.monthly,
                annual_day=event.annual_day,
                annual_month=event.annual_month,
                tg_id=user_id,
            )

            session.add(new_event)
            await session.commit()
            await session.refresh(new_event)

            return new_event.id


db_controller = DBController()
