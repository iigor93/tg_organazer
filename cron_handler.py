import argparse
import asyncio
import datetime
import logging

import telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import TOKEN, database_url
from database.db_controller import db_controller

engine = create_async_engine(database_url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


logger = logging.getLogger(__name__)


async def send_messages(send_now: bool = False):
    bot = telegram.Bot(token=TOKEN)
    now = datetime.datetime.now(datetime.timezone.utc)
    now = now.replace(second=0, microsecond=0)
    if not send_now:
        now += datetime.timedelta(hours=1)
    limit = 400
    offset = 0
    while True:
        async with AsyncSessionLocal() as session:
            events = await db_controller.get_current_day_events_all_users(event_dt=now, session=session, limit=limit, offset=offset)

        logger.info(f"** len events: {len(events)}")
        if not events:
            await engine.dispose()
            break

        for event in events:
            text = "🔔 Напоминание о начале события"
            if not send_now:
                text += "\nЧерез 1 час:"
            text += f"\n⏰ {event.get('start_time').strftime('%H:%M')}\n📝 {event.get('description')}"

            event_id = event.get("event_id")
            reply_markup = None
            if event_id:
                buttons = [
                    [InlineKeyboardButton("Перенести на 1 час", callback_data=f"reschedule_event_{event_id}_hour")],
                    [InlineKeyboardButton("Перенести на завтра", callback_data=f"reschedule_event_{event_id}_day")],
                ]
                reply_markup = InlineKeyboardMarkup(buttons)

            await bot.send_message(chat_id=event.get("tg_id"), text=text, reply_markup=reply_markup)
            await asyncio.sleep(0.001)

        await engine.dispose()

        offset += limit


if __name__ == "__main__":
    logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S%z", level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    parser = argparse.ArgumentParser(description="Choose datetime")
    parser.add_argument("--now", type=bool, help="send events NOW", default=False)

    args = parser.parse_args()

    logger.info(f"Args: {args.now}")

    asyncio.run(send_messages(send_now=args.now))
