import asyncio
import datetime
import logging

import telegram
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import TOKEN, database_url
from database.db_controller import db_controller

engine = create_async_engine(database_url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


logger = logging.getLogger(__name__)


async def send_messages():
    bot = telegram.Bot(token=TOKEN)
    now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
    now = now.replace(minute=0, second=0, microsecond=0)

    async with AsyncSessionLocal() as session:
        events = await db_controller.get_current_day_events_all_users(event_dt=now, session=session)

    logger.info(f"*** {events}")

    for event in events:
        text = f"⏰ Напоминание\nЧерез 1 час:\n⏱️ {event.get('start_time').strftime('%H:%M')}\n📝 {event.get('description')}"
        await bot.send_message(chat_id=event.get("tg_id"), text=text)
        await asyncio.sleep(0.001)

    await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S%z", level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(send_messages())
