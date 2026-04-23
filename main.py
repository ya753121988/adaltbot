import os
import asyncio
import datetime
from fastapi import FastAPI, Body
from fastapi.responses import HTMLResponse
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from motor.motor_asyncio import AsyncIOMotorClient
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import uvicorn
from bson import ObjectId

# --- কনফিগারেশন ---
TOKEN = os.getenv("BOT_TOKEN")
MONGO_URL = os.getenv("MONGO_URI")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
APP_URL = os.getenv("APP_URL")

bot = Bot(token=TOKEN)
dp = Dispatcher()
app = FastAPI()
scheduler = AsyncIOScheduler()

# অ্যাডমিন স্টেট সেভ করার জন্য (ফাইল আইডি সাময়িক রাখার জন্য)
admin_temp_files = {}

# --- ডেটাবেস কানেকশন ---
try:
    client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    db = client['movie_database']
    print("✅ MongoDB Connected Successfully")
except Exception as e:
    print(f"❌ MongoDB Connection Error: {e}")

# --- ১. বটের কাজ (সহজ অ্যাডমিন ফ্লো) ---

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    uid = message.from_user.id
    kb = [[types.InlineKeyboardButton(text="🎬 ওপেন মুভি অ্যাপ", web_app=types.WebAppInfo(url=APP_URL))]]
    markup = types.InlineKeyboardMarkup(inline_keyboard=kb)

    if uid == ADMIN_ID:
        text = (
            "👋 **হ্যালো অ্যাডমিন!**\n\n"
            "নতুন মুভি অ্যাড করার জন্য নিচের ধাপগুলো অনুসরণ করুন:\n"
            "১. প্রথমে মুভি ফাইলটি (Document/Video) এখানে পাঠান।\n"
            "২. ফাইলটি পাঠানো হলে আমি আপনাকে নাম এবং পোস্টার দিতে বলবো।"
        )
    else:
        text = (
            f"👋 হ্যালো **{message.from_user.first_name}**!\n\n"
            "🎬 আমাদের মুভি অ্যাপে আপনাকে স্বাগতম।\n"
            "মুভি পেতে নিচে দেওয়া 'ওপেন মুভি অ্যাপ' বাটনে ক্লিক করুন।"
        )
    await message.answer(text, reply_markup=markup, parse_mode="Markdown")

# ধাপ ১: অ্যাডমিন ফাইল পাঠালে তা সেভ করা
@dp.message(F.document | F.video)
async def catch_file(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    
    file_id = message.document.file_id if message.document else message.video.file_id
    admin_temp_files[message.from_user.id] = file_id
    
    await message.answer("✅ ফাইলটি পেয়েছি! এখন এই ফরম্যাটে মুভির নাম এবং পোস্টার লিঙ্ক পাঠান:\n\n`মুভির নাম | পোস্টার লিঙ্ক`", parse_mode="Markdown")

# ধাপ ২: অ্যাডমিন টেক্সট পাঠালে ডেটাবেসে মুভি সেভ করা
@dp.message(F.text)
async def save_movie_details(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    if message.text.startswith("/"): return # কমান্ড হলে ইগনোর করবে
    
    uid = message.from_user.id
    if uid not in admin_temp_files:
        await message.answer("⚠️ আগে একটি মুভি ফাইল পাঠান, তারপর নাম এবং পোস্টার দিন।")
        return

    try:
        if "|" not in message.text:
            await message.answer("❌ ফরম্যাট ভুল! দয়া করে এভাবে লিখুন: `মুভির নাম | পোস্টার লিঙ্ক`")
            return

        title, thumb = message.text.split("|")
        file_id = admin_temp_files[uid]

        await db.movies.insert_one({
            "title": title.strip(),
            "thumbnail": thumb.strip(),
            "file_id": file_id,
            "created_at": datetime.datetime.utcnow()
        })
        
        del admin_temp_files[uid] # কাজ শেষ হলে মেমোরি খালি করা
        await message.answer("🎉 অভিনন্দন! মুভিটি সফলভাবে অ্যাপে যুক্ত হয়েছে।")
    except Exception as e:
        await message.answer(f"⚠️ এরর: {str(e)}")

# --- ২. অটো ডিলিট টাস্ক (২৪ ঘণ্টা পর) ---
async def delete_expired():
    now = datetime.datetime.utcnow()
    expired = db.auto_delete.find({"delete_at": {"$lte": now}})
    async for item in expired:
        try:
            await bot.delete_message(item['chat_id'], item['message_id'])
        except: pass
        await db.auto_delete.delete_one({"_id": item['_id']})

# --- ৩. ওয়েব অ্যাপ (উন্নত ইন্টারফেস) ---

@app.get("/", response_class=HTMLResponse)
async def web_ui():
    return f"""
    <!DOCTYPE html>
    <html lang="bn">
    <head>
        <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Moviee BD</title><script src="https://telegram.org/js/telegram-web-app.js"></script>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ background: #080a12; color: #fff; font-family: sans-serif; }}
            header {{ display: flex; justify-content: space-between; align-items: center; padding: 15px 20px; background: #111827; position: sticky; top: 0; z-index: 100; border-bottom: 1px solid #1f2937; }}
            .logo {{ font-size: 20px; font-weight: bold; }}
            .logo span {{ background: #e11d48; padding: 2px 6px; border-radius: 4px; font-size: 14px; }}
            .search-box {{ padding: 20px; }}
            .search-input {{ width: 100%; padding: 14px; border-radius: 10px; border: 1px solid #1f2937; background: #111827; color: #fff; outline: none; }}
            .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 15px; padding: 0 20px 20px; }}
            .card {{ background: #111827; border-radius: 12px; overflow: hidden; aspect-ratio: 2/3; position: relative; border: 1px solid #1f2937; }}
            .card img {{ width: 100%; height: 100%; object-fit: cover; }}
            .card-title {{ position: absolute; bottom: 0; width: 100%; background: rgba(0,0,0,0.8); padding: 10px 5px; text-align: center; font-size: 13px; }}
            .ad-screen {{ position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: #000; display: none; flex-direction: column; align-items: center; justify-content: center; z-index: 9999; }}
            .timer {{ font-size: 50px; color: #e11d48; border: 5px solid #e11d48; width: 110px; height: 110px; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin-bottom: 20px; }}
        </style>
    </head>
    <body>
        <header><div class="logo">Moviee <span>BD</span></div></header>
        <div class="search-box"><input type="text" class="search-input" placeholder="মুভি সার্চ করুন..." onkeyup="search()"></div>
        <div class="grid" id="movieGrid"></div>
        <div id="adBox" class="ad-screen"><div class="timer" id="timer">10</div><p>সার্ভারের সাথে কানেক্ট হচ্ছে...</p></div>
        <script>
            let tg = window.Telegram.WebApp; tg.expand();
            let allMovies = [];
            async function load() {{
                try {{
                    const r = await fetch('/api/list');
                    allMovies = await r.json();
                    render(allMovies);
                }} catch(e) {{ alert("ডেটাবেস কানেক্ট হতে পারেনি!"); }}
            }}
            function render(data) {{
                document.getElementById('movieGrid').innerHTML = data.map(m => `
                    <div class="card" onclick="startAd('\${m._id}')">
                        <img src="\${m.thumbnail}">
                        <div class="card-title">\${m.title}</div>
                    </div>
                `).join('');
            }}
            function search() {{
                let q = document.querySelector('.search-input').value.toLowerCase();
                render(allMovies.filter(m => m.title.toLowerCase().includes(q)));
            }}
            function startAd(id) {{
                document.getElementById('adBox').style.display = 'flex';
                let t = 10;
                let iv = setInterval(() => {{
                    t--; document.getElementById('timer').innerText = t;
                    if(t <= 0) {{ clearInterval(iv); send(id); }}
                }}, 1000);
            }}
            async function send(id) {{
                await fetch('/api/send', {{
                    method: 'POST', headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{ userId: tg.initDataUnsafe.user.id, movieId: id }})
                }});
                document.getElementById('adBox').style.display = 'none'; tg.close();
            }}
            load();
        </script>
    </body>
    </html>
    """

# --- ৪. API রুটস ---

@app.get("/api/list")
async def api_list():
    movies = []
    try:
        async for m in db.movies.find().sort("created_at", -1):
            m["_id"] = str(m["_id"])
            movies.append(m)
    except: pass
    return movies

@app.post("/api/send")
async def api_send(data: dict = Body(...)):
    movie = await db.movies.find_one({"_id": ObjectId(data['movieId'])})
    if movie:
        msg = await bot.send_document(data['userId'], movie['file_id'], caption=f"🎬 {movie['title']}\n⚠️ ২৪ ঘণ্টা পর ডিলিট হবে।")
        del_at = datetime.datetime.utcnow() + datetime.timedelta(hours=24)
        await db.auto_delete.insert_one({"chat_id": data['userId'], "message_id": msg.message_id, "delete_at": del_at})
    return {"ok": True}

# --- ৫. রানার ---

async def start_app():
    scheduler.add_job(delete_expired, 'interval', minutes=1)
    scheduler.start()
    port = int(os.getenv("PORT", 8000))
    config = uvicorn.Config(app, host="0.0.0.0", port=port, loop="asyncio")
    server = uvicorn.Server(config)
    await asyncio.gather(server.serve(), dp.start_polling(bot))

if __name__ == "__main__":
    asyncio.run(start_app())
