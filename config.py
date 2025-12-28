import logging
import os

from dotenv import load_dotenv

load_dotenv(".env")


logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S%z", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

MONTH_NAMES = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
NEAREST_EVENTS_DAYS = 10


TOKEN = os.getenv("TG_BOT_TOKEN")
