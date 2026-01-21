# 🤖 Scheduled Repeat Bot (Render Deploy Ready)

A Telegram bot that can **capture any message by replying** with `/add` and then repeat-send it at intervals.

✅ Supports:
- Text message
- Photo + caption + inline buttons
- Video + caption + inline buttons
- Document + caption + inline buttons
- Sticker (Sticker cannot have buttons; bot sends sticker then buttons separately if needed)

✅ Commands:
- `/start` – shows UI menu + sends **multiple welcome pics (album)**
- `/add` – reply to any message and select interval
- `/stop` – stop all schedules in that chat
- `/getid` – reply to a photo/video/document/sticker to get file_id

✅ Render Free deploy ready:
- Flask web server opens port for Render
- UptimeRobot can ping `/` to prevent sleep

---

## 📁 Project Structure
```
scheduled_repeat_bot/
 ├─ bot.py
 ├─ db.py
 ├─ scheduler.py
 ├─ requirements.txt
 ├─ Procfile
 ├─ .env.example
 └─ README.md
```

---

## 🧪 Local Run
```bash
pip install -r requirements.txt
cp .env.example .env
python bot.py
```

---

## 🌍 Render Deploy
1) Push to GitHub
2) Render → New → Web Service → select repo
3) Build Command: `pip install -r requirements.txt`
4) Start Command auto uses Procfile: `python bot.py`
5) Add Environment variables:
   - `BOT_TOKEN`
   - `MONGO_URI`
   - `DB_NAME` (optional)
   - `PORT` (optional)

---

## ⏱ UptimeRobot
Create HTTP monitor:
- URL: `https://<your-service>.onrender.com/`
- Interval: 5 minutes
