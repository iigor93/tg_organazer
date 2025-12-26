import logging

from sqlalchemy import select, update

from database.models.event_models import DbEvent
from database.models.user_model import User as DB_User
from database.session import AsyncSessionLocal
from entities import Event, Recurrent, TgUser

logger = logging.getLogger(__name__)


class DBController:
    async def save_update_user(self, tg_user: TgUser) -> None:
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

    async def save_event(self, event: Event) -> None:
        logger.info(f"db_controller save event: {event}")

        new_event = DbEvent(
            description=event.description,
            start_time=event.start_time,
            event_date_pickup=event.event_date,
            daily=True if event.recurrent == Recurrent.daily else False,
            weekly=event.event_date.weekday() if event.recurrent == Recurrent.weekly else None,
            monthly=event.event_date.month if event.recurrent == Recurrent.monthly else None,
            annual_day=event.event_date.day if event.recurrent == Recurrent.annual else None,
            annual_month=event.event_date.month if event.recurrent == Recurrent.annual else None,
            stop_time=event.stop_time,
            tg_id=event.tg_id,
        )
        async with AsyncSessionLocal() as session:
            session.add(new_event)
            await session.commit()


db_controller = DBController()
