import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME", "schedule_bot")

client = MongoClient(MONGO_URI)
db = client[DB_NAME]

schedules_col = db["schedules"]
messages_col = db["messages"]
