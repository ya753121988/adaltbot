import os, asyncio, datetime, uvicorn
from fastapi import FastAPI, Body, Request
from fastapi.responses import HTMLResponse
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from motor.motor_asyncio import AsyncIOMotorClient
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bson import ObjectId

# --- Environment Variables ---
TOKEN = os.getenv("BOT_TOKEN")
MONGO_URL = os.getenv("MONGO_URI")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
APP_URL = os.getenv("APP_URL")

bot = Bot(token=TOKEN)
dp = Dispatcher()
app = FastAPI()
scheduler = AsyncIOScheduler()

# MongoDB কানেকশন এরর হ্যান্ডেল করার জন্য
try:
    client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    db = client['movie_database']
except Exception as e:
    print(f"❌ MongoDB Connection Error: {e}")

# এডমিন স্টেট সেভ করার জন্য
admin_temp = {}

# --- ১. বটের কাজ (Admin vs User) ---

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    kb = [[types.InlineKeyboardButton(text="🎬 ওপেন মুভি অ্যাপ", web_app=types.WebAppInfo(url=APP_URL))]]
    markup = types.InlineKeyboardMarkup(inline_keyboard=kb)
    
    if message.from_user.id == ADMIN_ID:
        text = "👋 **হ্যালো অ্যাডমিন!**\n\nমুভি অ্যাড করতে প্রথমে ভিডিও বা ফাইল পাঠান।"
    else:
        text = f"👋 হ্যালো **{message.from_user.first_name}**!\n\nমুভি অ্যাপে ঢুকতে নিচের বাটনে ক্লিক করুন।"
    
    await message.answer(text, reply_markup=markup, parse_mode="Markdown")

@dp.message(F.document | F.video)
async def catch_file(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    fid = message.document.file_id if message.document else message.video.file_id
    admin_temp[message.from_user.id] = fid
    await message.answer("✅ ফাইল পেয়েছি! এখন মুভির নাম এবং পোস্টার লিঙ্ক দিন।\n\n**ফরম্যাট:** `মুভির নাম | পোস্টার লিঙ্ক`", parse_mode="Markdown")

@dp.message(F.text)
async def save_data(message: types.Message):
    if message.from_user.id != ADMIN_ID or "|" not in message.text: return
    uid = message.from_user.id
    if uid not in admin_temp: return
    
    try:
        title, thumb = message.text.split("|")
        await db.movies.insert_one({
            "title": title.strip(),
            "thumbnail": thumb.strip(),
            "file_id": admin_temp[uid],
            "created_at": datetime.datetime.utcnow()
        })
        del admin_temp[uid]
        await message.answer("🎉 মুভিটি অ্যাপে যুক্ত করা হয়েছে!")
    except Exception as e:
        await message.answer(f"⚠️ এরর হয়েছে: {e}")

# --- ২. অটো ডিলিট লজিক ---

async def delete_expired():
    now = datetime.datetime.utcnow()
    expired = db.auto_delete.find({"delete_at": {"$lte": now}})
    async for item in expired:
        try:
            await bot.delete_message(item['chat_id'], item['message_id'])
        except: pass
        await db.auto_delete.delete_one({"_id": item['_id']})

# --- ৩. ওয়েব অ্যাপ UI (প্রিমিয়াম ডিজাইন) ---

@app.get("/", response_class=HTMLResponse)
async def web_ui():
    # JavaScript এর $ সিম্বল ঠিক রাখতে এখানে Python f-string এর বাইরে রাখা হয়েছে
    html_content = r"""
    <!DOCTYPE html>
    <html lang="bn">
    <head>
        <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Moviee BD</title><script src="https://telegram.org/js/telegram-web-app.js"></script>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { background: #080a12; color: #fff; font-family: sans-serif; }
            header { display: flex; justify-content: space-between; align-items: center; padding: 15px 20px; background: #111827; border-bottom: 2px solid #e11d48; position: sticky; top: 0; z-index: 100; }
            .logo { font-size: 22px; font-weight: bold; }
            .logo span { background: #e11d48; padding: 2px 6px; border-radius: 4px; font-size: 14px; margin-left: 5px; }
            .search-box { padding: 20px; }
            .search-input { width: 100%; padding: 14px; border-radius: 10px; border: 1px solid #1f2937; background: #111827; color: #fff; outline: none; }
            .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; padding: 0 20px 20px; }
            .card { background: #111827; border-radius: 12px; overflow: hidden; aspect-ratio: 2/3; position: relative; border: 1px solid #1f2937; cursor: pointer; transition: 0.3s; }
            .card:hover { transform: scale(1.02); }
            .card img { width: 100%; height: 100%; object-fit: cover; }
            .card-title { position: absolute; bottom: 0; width: 100%; background: linear-gradient(transparent, rgba(0,0,0,0.9)); padding: 15px 5px 8px; text-align: center; font-size: 13px; font-weight: 500; }
            .ad-screen { position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: #000; display: none; flex-direction: column; align-items: center; justify-content: center; z-index: 9999; }
            .timer { font-size: 50px; color: #e11d48; border: 5px solid #e11d48; width: 110px; height: 110px; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin-bottom: 20px; font-weight: bold; }
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

            async function loadData() {
                try {
                    const r = await fetch('/api/list');
                    allMovies = await r.json();
                    render(allMovies);
                } catch(e) { console.error("Load Error"); }
            }

            function render(data) {
                const grid = document.getElementById('movieGrid');
                grid.innerHTML = data.map(m => `
                    <div class="card" onclick="startAd('${m._id}')">
                        <img src="${m.thumbnail}">
                        <div class="card-title">${m.title}</div>
                    </div>
                `).join('');
            }

            function search() {
                let q = document.querySelector('.search-input').value.toLowerCase();
                render(allMovies.filter(m => m.title.toLowerCase().includes(q)));
            }

            function startAd(id) {
                document.getElementById('adBox').style.display = 'flex';
                let t = 10;
                let iv = setInterval(() => {
                    t--; document.getElementById('timer').innerText = t;
                    if(t <= 0) { clearInterval(iv); sendFile(id); }
                }, 1000);
            }

            async function sendFile(id) {
                await fetch('/api/send', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ userId: tg.initDataUnsafe.user.id, movieId: id })
                });
                document.getElementById('adBox').style.display = 'none'; tg.close();
            }
            loadData();
        </script>
    </body>
    </html>
    """
    return html_content

# --- ৪. API এবং রানার ---

@app.get("/api/list")
async def api_list():
    try:
        movies = []
        async for m in db.movies.find().sort("created_at", -1):
            m["_id"] = str(m["_id"])
            movies.append(m)
        return movies
    except: return []

@app.post("/api/send")
async def api_send(data: dict = Body(...)):
    movie = await db.movies.find_one({"_id": ObjectId(data['movieId'])})
    if movie:
        msg = await bot.send_document(data['userId'], movie['file_id'], caption=f"🎬 {movie['title']}\n⚠️ ২৪ ঘণ্টা পর ডিলিট হবে।")
        del_at = datetime.datetime.utcnow() + datetime.timedelta(hours=24)
        await db.auto_delete.insert_one({"chat_id": data['userId'], "message_id": msg.message_id, "delete_at": del_at})
    return {"ok": True}

async def run():
    scheduler.add_job(delete_expired, 'interval', minutes=1)
    scheduler.start()
    port = int(os.getenv("PORT", 8000))
    config = uvicorn.Config(app, host="0.0.0.0", port=port, loop="asyncio")
    server = uvicorn.Server(config)
    # Conflict এড়ানোর জন্য bot.delete_webhook() ব্যবহার করা হয়েছে
    await bot.delete_webhook(drop_pending_updates=True)
    await asyncio.gather(server.serve(), dp.start_polling(bot))

if __name__ == "__main__":
    asyncio.run(run())
