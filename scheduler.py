from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import datetime

scheduler = AsyncIOScheduler(timezone="UTC")

def interval_trigger(seconds: int):
    return IntervalTrigger(
        seconds=seconds,
        start_date=datetime.datetime.utcnow() + datetime.timedelta(seconds=seconds)
    )
