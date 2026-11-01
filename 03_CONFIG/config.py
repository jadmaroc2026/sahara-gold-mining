import os
from dotenv import load_dotenv
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)
DB_PATH = os.getenv("DB_PATH", "sahara_gold.sqlite3")

DAILY_REWARDS = [10, 20, 30, 40, 50, 60, 100]
MINING_INTERVAL_HOURS = 2
MINING_REWARDS = [
    10, 15, 20, 25, 30, 40, 50, 60, 65, 70,
    75, 80, 90, 95, 100, 110, 115, 120, 130, 135,
    145, 150, 160, 165, 170, 180, 185, 190, 195, 200
]
TOKEN_SYMBOL = "DRJ"
PLANNED_TOTAL_SUPPLY = 1_000_000_000
