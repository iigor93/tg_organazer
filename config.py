import logging
import os

from dotenv import load_dotenv

load_dotenv(".env")


logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S%z", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

MONTH_NAMES = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
NEAREST_EVENTS_DAYS = 10


TOKEN = os.getenv("TG_BOT_TOKEN")


LOCAL = os.getenv("LOCAL")

if LOCAL:
    database_url = "sqlite+aiosqlite:///bot.db"
else:
    DB_USERNAME = os.getenv("DB_USERNAME")
    DB_PASSWORD = os.getenv("DB_PASSWORD")
    DB_HOST = os.getenv("DB_HOST")
    DB_PORT = os.getenv("DB_PORT")
    DB_NAME = os.getenv("DB_NAME")
    database_url = f"postgresql+asyncpg://{DB_USERNAME}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
