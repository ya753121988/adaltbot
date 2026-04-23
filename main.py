import os
import asyncio
import datetime
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from motor.motor_asyncio import AsyncIOMotorClient
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pydantic import BaseModel

# --- কনফিগারেশন (Environment Variables থেকে আসবে) ---
TOKEN = os.getenv("BOT_TOKEN")
MONGO_URL = os.getenv("MONGO_URI")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
APP_URL = os.getenv("APP_URL") # যেমন: https://your-app.koyeb.app

bot = Bot(token=TOKEN)
dp = Dispatcher()
app = FastAPI()
client = AsyncIOMotorClient(MONGO_URL)
db = client['movie_database']
scheduler = AsyncIOScheduler()

# --- ডেটাবেস মডেল ---
class SendFileRequest(BaseModel):
    userId: int
    movieId: str

# --- ১. বটের কাজ (Admin Section) ---
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    kb = [
        [types.InlineKeyboardButton(text="🎬 ওপেন মুভি অ্যাপ", web_app=types.WebAppInfo(url=APP_URL))]
    ]
    markup = types.InlineKeyboardMarkup(inline_keyboard=kb)
    await message.answer("আমাদের মুভি অ্যাপে স্বাগতম!", reply_markup=markup)

@dp.message(F.document)
async def handle_admin_upload(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    
    caption = message.caption
    if not caption or "|" not in caption:
        await message.answer("⚠️ ফরম্যাট: Title | ThumbnailURL")
        return

    title, thumb = caption.split("|")
    movie_data = {
        "title": title.strip(),
        "thumbnail": thumb.strip(),
        "file_id": message.document.file_id,
        "created_at": datetime.datetime.utcnow()
    }
    await db.movies.insert_one(movie_data)
    await message.answer("✅ ডেটাবেসে লম্বা পোস্টারসহ সেভ হয়েছে!")

# --- ২. অটো ডিলিট ফাংশন (২৪ ঘণ্টা পর) ---
async def delete_expired_messages():
    now = datetime.datetime.utcnow()
    expired = db.auto_delete.find({"delete_at": {"$lte": now}})
    async for item in expired:
        try:
            await bot.delete_message(item['chat_id'], item['message_id'])
        except: pass
        await db.auto_delete.delete_one({"_id": item['_id']})

# --- ৩. ওয়েব অ্যাপ API এবং ডিজাইন ---
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Moviee BD</title>
        <script src="https://telegram.org/js/telegram-web-app.js"></script>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ background: #080a12; color: white; font-family: 'Poppins', sans-serif; }}
            
            /* Header & Profile Section */
            .header {{ display: flex; justify-content: space-between; align-items: center; padding: 20px; }}
            .logo {{ font-size: 22px; font-weight: bold; }}
            .logo span {{ background: #ff0000; padding: 2px 8px; border-radius: 5px; margin-left: 5px; }}
            .admin-profile {{ display: flex; align-items: center; background: rgba(255,255,255,0.1); padding: 5px 15px; border-radius: 30px; border: 1px solid rgba(255,255,255,0.2); }}
            .admin-profile img {{ width: 30px; height: 30px; border-radius: 50%; margin-right: 10px; border: 2px solid #38bdf8; }}

            /* Search Bar */
            .search-container {{ padding: 0 20px; }}
            .search-bar {{ width: 100%; padding: 15px; border-radius: 15px; border: none; background: #1a1f2e; color: white; outline: none; border: 1px solid #2d3748; }}

            /* Long Poster Grid */
            .grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 15px; padding: 20px; }}
            .card {{ position: relative; border-radius: 15px; overflow: hidden; box-shadow: 0 10px 20px rgba(0,0,0,0.5); transition: 0.3s; aspect-ratio: 2/3; }}
            .card img {{ width: 100%; height: 100%; object-fit: cover; }}
            .card-overlay {{ position: absolute; bottom: 0; width: 100%; background: linear-gradient(transparent, rgba(0,0,0,0.9)); padding: 10px; text-align: center; font-size: 13px; }}

            /* Ad Overlay */
            .ad-overlay {{ position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: #000; display: none; flex-direction: column; align-items: center; justify-content: center; z-index: 10000; }}
            .timer {{ font-size: 50px; border: 4px solid #38bdf8; width: 100px; height: 100px; display: flex; align-items: center; justify-content: center; border-radius: 50%; margin-bottom: 20px; color: #38bdf8; }}
        </style>
    </head>
    <body>
        <div class="header">
            <div class="logo">Moviee <span>BD</span></div>
            <div class="admin-profile" id="userProfile">
                <img id="userPic" src="https://via.placeholder.com/150">
                <span id="userName">Admin</span>
            </div>
        </div>

        <div class="search-container">
            <input type="text" class="search-bar" placeholder="এপিসোড নাম্বার বা নাম দিয়ে সার্চ করুন..." onkeyup="search()">
        </div>

        <div class="grid" id="movieGrid"></div>

        <div id="adScreen" class="ad-overlay">
            <div class="timer" id="timer">10</div>
            <p>সার্ভারের সাথে কানেক্ট হচ্ছে...</p>
        </div>

        <script>
            let tg = window.Telegram.WebApp;
            tg.expand();

            // ইউজার প্রোফাইল সেট করা
            if(tg.initDataUnsafe.user) {{
                document.getElementById('userName').innerText = tg.initDataUnsafe.user.first_name;
                if(tg.initDataUnsafe.user.photo_url) {{
                    document.getElementById('userPic').src = tg.initDataUnsafe.user.photo_url;
                }}
            }}

            let movies = [];
            async function load() {{
                const r = await fetch('/api/movies');
                movies = await r.json();
                render(movies);
            }}

            function render(data) {{
                const grid = document.getElementById('movieGrid');
                grid.innerHTML = data.map(m => `
                    <div class="card" onclick="startAd('${{m._id}}')">
                        <img src="${{m.thumbnail}}">
                        <div class="card-overlay">${{m.title}}</div>
                    </div>
                `).join('');
            }}

            function search() {{
                const q = document.querySelector('.search-bar').value.toLowerCase();
                render(movies.filter(m => m.title.toLowerCase().includes(q)));
            }}

            function startAd(id) {{
                document.getElementById('adScreen').style.display = 'flex';
                let timeLeft = 10;
                let timer = setInterval(() => {{
                    timeLeft--;
                    document.getElementById('timer').innerText = timeLeft;
                    if(timeLeft <= 0) {{
                        clearInterval(timer);
                        send(id);
                    }}
                }}, 1000);
            }}

            async function send(id) {{
                await fetch('/api/send-file', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{ userId: tg.initDataUnsafe.user.id, movieId: id }})
                }});
                document.getElementById('adScreen').style.display = 'none';
                tg.close();
            }}
            load();
        </script>
    </body>
    </html>
    """

@app.get("/api/movies")
async def get_movies():
    movies = []
    async for m in db.movies.find().sort("created_at", -1):
        m["_id"] = str(m["_id"])
        movies.append(m)
    return movies

@app.post("/api/send-file")
async def send_file(data: SendFileRequest):
    from bson import ObjectId
    movie = await db.movies.find_one({"_id": ObjectId(data.movieId)})
    if movie:
        msg = await bot.send_document(data.userId, movie['file_id'], caption=f"🎬 {movie['title']}\\n⏰ এটি ২৪ ঘণ্টা পর ডিলিট হবে।")
        delete_time = datetime.datetime.utcnow() + datetime.timedelta(hours=24)
        await db.auto_delete.insert_one({"chat_id": data.userId, "message_id": msg.message_id, "delete_at": delete_time})
    return {"status": "success"}

# --- ৪. অ্যাপ রানার ---
async def main():
    scheduler.add_job(delete_expired_messages, 'interval', minutes=1)
    scheduler.start()
    # একসাথ বত এবং এপিআই চালানো
    loop = asyncio.get_event_loop()
    config = uvicorn.Config(app=app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)), loop="asyncio")
    server = uvicorn.Server(config)
    await asyncio.gather(server.serve(), dp.start_polling(bot))

if __name__ == "__main__":
    asyncio.run(main())
