import os, asyncio, datetime, uvicorn
import aiohttp
from fastapi import FastAPI, Body, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from motor.motor_asyncio import AsyncIOMotorClient
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bson import ObjectId
from pydantic import BaseModel

# --- কনফিগারেশন ---
TOKEN = os.getenv("BOT_TOKEN")
MONGO_URL = os.getenv("MONGO_URI")
OWNER_ID = int(os.getenv("ADMIN_ID", "0"))
APP_URL = os.getenv("APP_URL")

bot = Bot(token=TOKEN)
dp = Dispatcher()
app = FastAPI()

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

client = AsyncIOMotorClient(MONGO_URL)
db = client['movie_database']

admin_temp = {}
admin_cache = set([OWNER_ID]) 

async def load_admins():
    admin_cache.clear()
    admin_cache.add(OWNER_ID)
    async for admin in db.admins.find():
        admin_cache.add(admin["user_id"])

# --- ব্যাকগ্রাউন্ড অটো-ডিলিট ওয়ার্কার ---
async def auto_delete_worker():
    while True:
        try:
            now = datetime.datetime.utcnow()
            expired_msgs = db.auto_delete.find({"delete_at": {"$lte": now}})
            async for msg in expired_msgs:
                try:
                    await bot.delete_message(chat_id=msg["chat_id"], message_id=msg["message_id"])
                except Exception: pass
                await db.auto_delete.delete_one({"_id": msg["_id"]})
        except Exception: pass
        await asyncio.sleep(60)

# ==========================================
# ১. মেইন ওনার (Owner) স্পেশাল কমান্ড
# ==========================================

@dp.message(Command("addadmin"))
async def add_admin_cmd(m: types.Message):
    if m.from_user.id != OWNER_ID: return
    try:
        new_admin = int(m.text.split()[1])
        if new_admin in admin_cache:
            return await m.answer("⚠️ এই ইউজারটি আগে থেকেই অ্যাডমিন!")
        await db.admins.insert_one({"user_id": new_admin})
        admin_cache.add(new_admin)
        await m.answer(f"✅ নতুন অ্যাডমিন যুক্ত করা হয়েছে: <code>{new_admin}</code>", parse_mode="HTML")
        try: await bot.send_message(new_admin, "🎉 <b>অভিনন্দন!</b> আপনাকে এই বটের অ্যাডমিন বানানো হয়েছে। আপনি এখন মুভি আপলোড করতে পারবেন।", parse_mode="HTML")
        except: pass
    except: await m.answer("⚠️ সঠিক নিয়ম: <code>/addadmin ইউজার_আইডি</code>", parse_mode="HTML")

@dp.message(Command("deladmin"))
async def del_admin_cmd(m: types.Message):
    if m.from_user.id != OWNER_ID: return
    try:
        del_admin = int(m.text.split()[1])
        if del_admin == OWNER_ID: return await m.answer("⚠️ আপনি নিজেকে (Owner) ডিলিট করতে পারবেন না!")
        await db.admins.delete_one({"user_id": del_admin})
        admin_cache.discard(del_admin)
        await m.answer(f"✅ অ্যাডমিন রিমুভ করা হয়েছে: <code>{del_admin}</code>", parse_mode="HTML")
    except: await m.answer("⚠️ সঠিক নিয়ম: <code>/deladmin ইউজার_আইডি</code>", parse_mode="HTML")

@dp.message(Command("adminlist"))
async def list_admins_cmd(m: types.Message):
    if m.from_user.id != OWNER_ID: return
    text = "👥 <b>বর্তমান অ্যাডমিন লিস্ট:</b>\n"
    text += f"👑 Owner: <code>{OWNER_ID}</code>\n"
    for ad in admin_cache:
        if ad != OWNER_ID: text += f"👮 Admin: <code>{ad}</code>\n"
    await m.answer(text, parse_mode="HTML")

# ==========================================
# ২. বটের সাধারণ অ্যাডমিন কমান্ড
# ==========================================

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    await db.users.update_one({"user_id": message.from_user.id}, {"$set": {"first_name": message.from_user.first_name}}, upsert=True)
    kb = [[types.InlineKeyboardButton(text="🎬 BD Viral Link", web_app=types.WebAppInfo(url=APP_URL))]]
    markup = types.InlineKeyboardMarkup(inline_keyboard=kb)
    
    uid = message.from_user.id
    if uid in admin_cache:
        text = (
            "👋 <b>হ্যালো অ্যাডমিন!</b>\n\n"
            "⚙️ <b>কমান্ড:</b>\n"
            "🔸 অ্যাড জোন: <code>/setad ID</code> | অ্যাড সংখ্যা: <code>/setadcount সংখ্যা</code>\n"
            "🔸 টেলিগ্রাম: <code>/settg লিংক</code> | 18+: <code>/set18 লিংক</code>\n"
            "🔸 প্রোটেকশন: <code>/protect on</code> বা <code>/protect off</code>\n"
            "🔸 অটো-ডিলিট টাইম: <code>/settime [মিনিট]</code>\n"
            "🔸 ডিলিট: <code>/del</code> | স্ট্যাটাস: <code>/stats</code> | ব্রডকাস্ট: <code>/cast</code>\n"
        )
        if uid == OWNER_ID:
            text += "\n👑 <b>ওনার কমান্ড:</b>\n🔸 অ্যাড অ্যাডমিন: <code>/addadmin ID</code>\n🔸 ডিলিট অ্যাডমিন: <code>/deladmin ID</code>\n🔸 অ্যাডমিন লিস্ট: <code>/adminlist</code>\n"
            
        text += "\n📥 <b>মুভি আপলোড করতে প্রথমে ভিডিও বা ডকুমেন্ট ফাইল পাঠান। একাধিক ফাইল পাঠাতে পারবেন।</b>"
    else:
        text = f"👋 <b>স্বাগতম {message.from_user.first_name}!</b>\n\n[আপনার টেলিগ্রাম আইডি: <code>{uid}</code>]\n\nমুভি দেখতে নিচের বাটনে ক্লিক করুন।"
    await message.answer(text, reply_markup=markup, parse_mode="HTML")

@dp.message(Command("setadcount", "protect", "stats", "del", "settime", "setad", "settg", "set18", "cast"))
async def admin_commands(m: types.Message):
    # আপনার আগের কোড ঠিক রাখার জন্য কমান্ডগুলো এখানে একসাথে রাখা হলো
    cmd = m.text.split()[0].lower()
    if m.from_user.id not in admin_cache: return
    
    if cmd == "/setadcount":
        try:
            count = max(1, int(m.text.split(" ")[1]))
            await db.settings.update_one({"id": "ad_count"}, {"$set": {"count": count}}, upsert=True)
            await m.answer(f"✅ প্রতি মুভিতে অ্যাড দেখার সংখ্যা সেট করা হয়েছে: <b>{count} টি</b>।", parse_mode="HTML")
        except: await m.answer("⚠️ সঠিক নিয়ম: <code>/setadcount 3</code>")
    
    elif cmd == "/protect":
        try:
            state = m.text.split(" ")[1].lower()
            await db.settings.update_one({"id": "protect_content"}, {"$set": {"status": state == "on"}}, upsert=True)
            await m.answer(f"✅ প্রোটেকশন <b>{state.upper()}</b> করা হয়েছে।", parse_mode="HTML")
        except: await m.answer("⚠️ সঠিক নিয়ম: <code>/protect on</code> অথবা <code>/protect off</code>")
        
    elif cmd == "/stats":
        uc = await db.users.count_documents({})
        mc = await db.movies.count_documents({})
        time_cfg = await db.settings.find_one({"id": "del_time"})
        del_m = time_cfg['minutes'] if time_cfg else 60
        protect_cfg = await db.settings.find_one({"id": "protect_content"})
        prot_status = "ON 🔒" if protect_cfg and protect_cfg.get('status', True) else "OFF 🔓"
        await m.answer(f"📊 <b>স্ট্যাটাস:</b>\n👥 মোট ইউজার: <code>{uc}</code>\n🎬 মোট মুভি: <code>{mc}</code>\n⏳ অটো-ডিলিট: <code>{del_m} মিনিট</code>\n🛡️ প্রোটেকশন: <b>{prot_status}</b>", parse_mode="HTML")
        
    elif cmd == "/del":
        movies = await db.movies.find().sort("created_at", -1).limit(20).to_list(length=20)
        if not movies: return await m.answer("কোনো মুভি নেই।")
        builder = InlineKeyboardBuilder()
        for mv in movies: builder.button(text=f"❌ {mv['title'][:30]}", callback_data=f"del_{str(mv['_id'])}")
        builder.adjust(1)
        await m.answer("⚠️ ডিলিট করতে ক্লিক করুন:", reply_markup=builder.as_markup())
        
    elif cmd == "/settime":
        try:
            await db.settings.update_one({"id": "del_time"}, {"$set": {"minutes": int(m.text.split(" ")[1])}}, upsert=True)
            await m.answer(f"✅ অটো-ডিলিট টাইম সেট করা হয়েছে।")
        except: await m.answer("⚠️ সঠিক নিয়ম: <code>/settime 60</code>")
        
    elif cmd == "/setad":
        try:
            await db.settings.update_one({"id": "ad_config"}, {"$set": {"zone_id": m.text.split(" ")[1]}}, upsert=True)
            await m.answer("✅ জোন আপডেট হয়েছে।")
        except: await m.answer("⚠️ সঠিক নিয়ম: <code>/setad 1234567</code>")
        
    elif cmd == "/settg":
        try:
            await db.settings.update_one({"id": "link_tg"}, {"$set": {"url": m.text.split(" ")[1]}}, upsert=True)
            await m.answer("✅ টেলিগ্রাম লিংক আপডেট হয়েছে।")
        except: pass
        
    elif cmd == "/set18":
        try:
            await db.settings.update_one({"id": "link_18"}, {"$set": {"url": m.text.split(" ")[1]}}, upsert=True)
            await m.answer("✅ 18+ লিংক আপডেট হয়েছে।")
        except: pass
        
    elif cmd == "/cast":
        admin_temp[m.from_user.id] = {"step": "bcast_wait"}
        await m.answer("📢 <b>অ্যাডভান্সড ব্রডকাস্ট:</b>\nযে মেসেজটি ব্রডকাস্ট করতে চান সেটি পাঠান।", parse_mode="HTML")

@dp.callback_query(F.data.startswith("del_"))
async def del_movie_callback(c: types.CallbackQuery):
    if c.from_user.id not in admin_cache: return
    try:
        await db.movies.delete_one({"_id": ObjectId(c.data.split("_")[1])})
        await c.answer("✅ ডিলিট হয়েছে!", show_alert=True)
        await c.message.edit_text("✅ মুভিটি ডাটাবেস থেকে মুছে ফেলা হয়েছে।", reply_markup=None)
    except: pass

# ==========================================
# ৩. ইনপুট প্রসেসিং (মাল্টিপল কোয়ালিটি আপলোড)
# ==========================================

@dp.callback_query(F.data.startswith("reply_"))
async def process_reply_cb(c: types.CallbackQuery):
    if c.from_user.id not in admin_cache: return
    user_id = int(c.data.split("_")[1])
    admin_temp[c.from_user.id] = {"step": "reply_user", "target_uid": user_id}
    await c.message.reply("✍️ <b>ইউজারকে কী রিপ্লাই দিতে চান তা লিখে পাঠান:</b>")
    await c.answer()

@dp.message(F.content_type.in_({'text', 'photo', 'video', 'document', 'voice'}))
async def catch_all_inputs(m: types.Message):
    uid = m.from_user.id
    if uid not in admin_cache: return

    # রিপ্লাই এবং ব্রডকাস্ট লজিক
    step = admin_temp.get(uid, {}).get("step")
    if step == "reply_user":
        target_uid = admin_temp[uid]["target_uid"]
        del admin_temp[uid]
        try:
            if m.text: await bot.send_message(target_uid, f"📩 <b>অ্যাডমিন রিপ্লাই:</b>\n\n{m.text}", parse_mode="HTML")
            else: await m.copy_to(target_uid, caption=f"📩 <b>অ্যাডমিন রিপ্লাই:</b>\n\n{m.caption or ''}", parse_mode="HTML")
            await m.answer("✅ ইউজারকে সফলভাবে রিপ্লাই পাঠানো হয়েছে!")
        except: await m.answer("⚠️ রিপ্লাই পাঠানো যায়নি!")
        return

    if step == "bcast_wait":
        del admin_temp[uid]
        await m.answer("⏳ ব্রডকাস্ট শুরু হয়েছে...")
        kb = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="🎬 ওপেন মুভি অ্যাপ", web_app=types.WebAppInfo(url=APP_URL))]])
        success = 0
        async for u in db.users.find():
            try:
                await m.copy_to(chat_id=u['user_id'], reply_markup=kb)
                success += 1
                await asyncio.sleep(0.05)
            except: pass
        await m.answer(f"✅ সম্পন্ন! সর্বমোট <b>{success}</b> জনকে মেসেজ পাঠানো হয়েছে।", parse_mode="HTML")
        return

    # === মাল্টিপল কোয়ালিটি আপলোড লজিক ===
    
    # 1. ফাইল রিসিভ করা
    if (m.document or m.video) and step not in ["quality", "title"]:
        fid = m.video.file_id if m.video else m.document.file_id
        ftype = "video" if m.video else "document"
        
        if uid not in admin_temp or "files" not in admin_temp[uid]:
            admin_temp[uid] = {"files": [], "step": "quality", "current_file": {"id": fid, "type": ftype}}
        else:
            admin_temp[uid]["step"] = "quality"
            admin_temp[uid]["current_file"] = {"id": fid, "type": ftype}
            
        await m.answer("✅ ফাইল পেয়েছি! এই ফাইলের <b>কোয়ালিটি</b> কত? (যেমন: 480p, 720p বা 1080p লিখে পাঠান)", parse_mode="HTML")
        return

    # 2. কোয়ালিটি রিসিভ করা
    if m.text and step == "quality":
        quality = m.text.strip()
        admin_temp[uid]["current_file"]["quality"] = quality
        admin_temp[uid]["files"].append(admin_temp[uid]["current_file"])
        del admin_temp[uid]["current_file"]
        
        admin_temp[uid]["step"] = "wait_more"
        await m.answer(f"✅ <b>{quality}</b> অ্যাড করা হয়েছে।\n\n📥 <b>আপনি চাইলে আরও কোয়ালিটির ফাইল পাঠাতে পারেন।</b>\n\n🖼 অথবা, আপলোড শেষ করতে মুভির <b>পোস্টার (Photo)</b> সেন্ড করুন।", parse_mode="HTML")
        return

    # 3. পোস্টার রিসিভ করা
    if m.photo and step == "wait_more":
        admin_temp[uid]["photo_id"] = m.photo[-1].file_id
        admin_temp[uid]["step"] = "title"
        await m.answer("✅ পোস্টার পেয়েছি! এবার মুভির <b>নাম</b> লিখে পাঠান।", parse_mode="HTML")
        return

    # 4. মুভির নাম রিসিভ করা ও সেভ করা
    if m.text and not str(m.text).startswith("/") and step == "title":
        title = m.text.strip()
        files = admin_temp[uid]["files"]
        await db.movies.insert_one({
            "title": title, 
            "photo_id": admin_temp[uid]["photo_id"], 
            "files": files, 
            "clicks": 0, 
            "created_at": datetime.datetime.utcnow()
        })
        del admin_temp[uid]
        await m.answer(f"🎉 <b>{title}</b> অ্যাপে সফলভাবে যুক্ত করা হয়েছে! (মোট কোয়ালিটি: {len(files)}টি)", parse_mode="HTML")


# ==========================================
# ৪. ওয়েব অ্যাপ UI এবং APIs
# ==========================================

@app.get("/", response_class=HTMLResponse)
async def web_ui():
    ad_cfg = await db.settings.find_one({"id": "ad_config"})
    tg_cfg = await db.settings.find_one({"id": "link_tg"})
    b18_cfg = await db.settings.find_one({"id": "link_18"})
    ad_count_cfg = await db.settings.find_one({"id": "ad_count"})
    
    zone_id = ad_cfg['zone_id'] if ad_cfg else "10916755"
    tg_url = tg_cfg['url'] if tg_cfg else "https://t.me/MovieeBD"
    link_18 = b18_cfg['url'] if b18_cfg else "https://t.me/MovieeBD"
    required_ads = ad_count_cfg['count'] if ad_count_cfg else 1

    html_code = r"""
    <!DOCTYPE html>
    <html lang="bn">
    <head>
        <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Moviee BD</title>
        <script src="https://telegram.org/js/telegram-web-app.js"></script>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
        <style>
            * { margin:0; padding:0; box-sizing:border-box; }
            body { background:#0f172a; font-family: sans-serif; color:#fff; } 
            header { display:flex; justify-content:space-between; align-items:center; padding:15px; border-bottom:1px solid #1e293b; position:sticky; top:0; background:#0f172a; z-index:1000; }
            .logo { font-size:24px; font-weight:bold; }
            .logo span { background:red; color:#fff; padding:2px 5px; border-radius:5px; margin-left:5px; font-size:16px; }
            .user-info { display:flex; align-items:center; gap:8px; background:#1e293b; padding:5px 12px; border-radius:20px; font-weight:bold; font-size:14px; }
            .user-info img { width:26px; height:26px; border-radius:50%; object-fit:cover; }
            
            .search-box { padding:15px; }
            .search-input { width:100%; padding:14px; border-radius:25px; border:none; outline:none; text-align:center; background:#1e293b; color:#fff; font-size:16px; transition: 0.3s; }
            .search-input:focus { box-shadow: 0 0 10px rgba(248,113,113,0.5); }
            
            .section-title { padding: 5px 15px 10px; font-size: 18px; font-weight: bold; color: #f87171; display:flex; align-items:center; gap:8px;}
            
            .trending-container { display: flex; overflow-x: auto; gap: 12px; padding: 0 15px 20px; scroll-behavior: smooth; }
            .trending-container::-webkit-scrollbar { display: none; }
            .trending-card { min-width: 130px; max-width: 130px; background: #1e293b; border-radius: 12px; overflow: hidden; cursor: pointer; flex-shrink: 0; position:relative;}
            .trending-card img { height: 170px; object-fit:cover; width:100%; border-radius:10px; display:block; }
            
            .grid { padding:0 15px 20px; display: grid; grid-template-columns: repeat(2, 1fr); gap: 15px; }
            .card { background:#1e293b; border-radius:12px; overflow:hidden; cursor:pointer; transition: transform 0.2s; }
            .card:active { transform: scale(0.95); }
            
            .post-content { 
                position:relative; padding: 3px; border-radius: 12px;
                background: linear-gradient(45deg, #ff0000, #ff7300, #fffb00, #48ff00, #00ffd5, #002bff, #7a00ff, #ff00c8, #ff0000);
                background-size: 400%; animation: glowing 8s linear infinite;
            }
            @keyframes glowing { 0% { background-position: 0 0; } 50% { background-position: 400% 0; } 100% { background-position: 0 0; } }

            .post-content img { width:100%; height:180px; object-fit:cover; display:block; border-radius: 10px; }
            
            .tag { position:absolute; top:8px; right:8px; padding:4px 6px; border-radius:6px; font-weight:bold; font-size:10px; display:flex; align-items:center; gap:4px; box-shadow: 0 2px 5px rgba(0,0,0,0.5); }
            .tag-locked { background:rgba(0,0,0,0.85); color:#f87171; border: 1px solid #f87171; }
            .tag-unlocked { background:rgba(0,0,0,0.85); color:#10b981; border: 1px solid #10b981; }
            
            .top-badge { position:absolute; top:8px; left:8px; background:red; color:white; padding:3px 6px; border-radius:6px; font-size:10px; font-weight:bold; box-shadow: 0 2px 5px rgba(0,0,0,0.5); z-index:10;}
            .view-badge { position:absolute; bottom:8px; left:8px; background:rgba(0,0,0,0.7); color:#fff; padding:3px 6px; border-radius:6px; font-size:11px; font-weight:bold; display:flex; align-items:center; gap:4px; box-shadow: 0 2px 5px rgba(0,0,0,0.5); }

            .card-footer { padding:10px; font-size:13px; font-weight:bold; text-align:center; word-wrap: break-word; color:#e2e8f0; line-height:1.4; }
            
            .skeleton { background: #1e293b; border-radius: 12px; height: 215px; overflow: hidden; position: relative; }
            .skeleton::after { content: ""; position: absolute; top: 0; left: 0; width: 100%; height: 100%; background: linear-gradient(90deg, transparent, rgba(255,255,255,0.05), transparent); animation: shimmer 1.5s infinite; }
            @keyframes shimmer { 0% { transform: translateX(-100%); } 100% { transform: translateX(100%); } }

            .pagination { display: flex; justify-content: center; align-items: center; gap: 8px; padding: 10px 15px 120px; flex-wrap: wrap; }
            .page-btn { background: #1e293b; color: #fff; border: 1px solid #334155; padding: 10px 15px; border-radius: 8px; cursor: pointer; font-weight: bold; transition: 0.2s; outline: none; }
            .page-btn.active { background: #f87171; border-color: #f87171; color: white; }

            .floating-btn { position:fixed; right:20px; color:white; width:50px; height:50px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:20px; font-weight:bold; z-index:500; cursor:pointer; box-shadow: 0 4px 10px rgba(0,0,0,0.5); }
            .btn-18 { bottom:155px; background:red; border:2px solid #fff; }
            .btn-tg { bottom:95px; background:#24A1DE; }
            .btn-req { bottom:35px; background:#10b981; }

            .ad-screen { position:fixed; top:0; left:0; width:100%; height:100%; background:#0f172a; display:none; flex-direction:column; align-items:center; justify-content:center; z-index:2000; }
            .timer-ui { display:flex; flex-direction:column; align-items:center; }
            .timer { width:100px; height:100px; border-radius:50%; border:5px solid red; display:flex; align-items:center; justify-content:center; font-size:40px; margin-bottom:15px; color:red; font-weight:bold; }
            .ad-step-text { font-size:18px; font-weight:bold; color:#fff; margin-bottom: 20px; background:#1e293b; padding:8px 15px; border-radius:20px;}
            .btn-next-ad { display:none; background:#f87171; color:white; border:none; padding:15px 30px; border-radius:30px; font-size:18px; font-weight:bold; cursor:pointer;}
            
            .modal { position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.8); display:none; align-items:center; justify-content:center; z-index:3000; }
            .modal-content { background:#1e293b; width:90%; padding:30px; border-radius:15px; text-align:center; }
            .req-input { width: 100%; padding: 12px; margin: 15px 0; border-radius: 8px; border: none; background: #0f172a; color: white; outline:none; }
            .btn-submit { background: #10b981; color: white; border: none; padding: 12px 20px; border-radius: 8px; font-weight: bold; width:100%; font-size:16px; margin-bottom:10px; cursor:pointer; display:flex; justify-content:center; align-items:center; gap:8px;}
            
        </style>
    </head>
    <body>
        <header>
            <div class="logo">BD Viral <span>Link</span></div>
            <div class="user-info"><span id="uName">Guest</span><img id="uPic" src="https://cdn-icons-png.flaticon.com/512/3135/3135715.png"></div>
        </header>

        <div class="search-box">
            <input type="text" id="searchInput" class="search-input" placeholder="মুভি বা ওয়েব সিরিজ খুঁজুন...">
        </div>

        <div id="trendingWrapper">
            <div class="section-title"><i class="fa-solid fa-fire"></i> ট্রেন্ডিং মুভি</div>
            <div class="trending-container" id="trendingGrid">
                <div class="skeleton" style="min-width:130px; height:180px;"></div>
                <div class="skeleton" style="min-width:130px; height:180px;"></div>
            </div>
        </div>

        <div class="section-title"><i class="fa-solid fa-film"></i> নতুন সব মুভি</div>
        <div class="grid" id="movieGrid"></div>
        <div class="pagination" id="paginationBox"></div>

        <div class="floating-btn btn-18" onclick="window.open('{{LINK_18}}')">18+</div>
        <div class="floating-btn btn-tg" onclick="window.open('{{TG_LINK}}')"><i class="fa-brands fa-telegram"></i></div>
        <div class="floating-btn btn-req" onclick="openReqModal()"><i class="fa-solid fa-code-pull-request"></i></div>

        <!-- Quality Selection Modal (NEW) -->
        <div id="qualityModal" class="modal">
            <div class="modal-content">
                <h2 style="margin-bottom: 20px; color:#f87171;">কোয়ালিটি নির্বাচন করুন</h2>
                <div id="qualityButtons"></div>
                <p style="margin-top:15px; color:gray; cursor:pointer;" onclick="document.getElementById('qualityModal').style.display='none'">বাতিল করুন</p>
            </div>
        </div>

        <!-- Ad Screen -->
        <div id="adScreen" class="ad-screen">
            <div class="ad-step-text" id="adStepText">অ্যাড: 1/1</div>
            <div class="timer-ui" id="timerUI">
                <div class="timer" id="timer">15</div>
                <p>সার্ভারের সাথে কানেক্ট হচ্ছে...</p>
            </div>
            <button class="btn-next-ad" id="nextAdBtn" onclick="nextAdStep()">পরবর্তী অ্যাড দেখুন <i class="fa-solid fa-arrow-right"></i></button>
        </div>

        <!-- Success Modal -->
        <div id="successModal" class="modal">
            <div class="modal-content">
                <i class="fa-solid fa-circle-check" style="font-size:60px; color:#10b981;"></i>
                <h2 style="margin:15px 0;">সম্পন্ন হয়েছে!</h2>
                <p style="margin-bottom: 20px; color:gray; font-size:14px;">বটের ইনবক্স চেক করুন। <br><span style="color:#f87171;">সতর্কতা: মুভিটি কিছুক্ষণ পর অটোমেটিক ডিলিট হয়ে যাবে।</span></p>
                <button class="btn-submit" onclick="tg.close()" style="background:#10b981;">বটে ফিরে যান</button>
            </div>
        </div>

        <!-- Request Modal -->
        <div id="reqModal" class="modal">
            <div class="modal-content">
                <h2>মুভি রিকোয়েস্ট করুন</h2>
                <input type="text" id="reqText" class="req-input" placeholder="মুভির নাম ও রিলিজ সাল লিখুন...">
                <button class="btn-submit" onclick="sendReq()" style="background:#10b981;">সাবমিট করুন</button>
                <p style="margin-top:15px; color:gray; cursor:pointer;" onclick="document.getElementById('reqModal').style.display='none'">বাতিল করুন</p>
            </div>
        </div>

        <script>
            let tg = window.Telegram.WebApp; tg.expand();
            const ZONE_ID = "{{ZONE_ID}}";
            const REQUIRED_ADS = parseInt("{{AD_COUNT}}");
            
            let currentPage = 1; let isLoading = false; let searchQuery = "";
            let uid = tg.initDataUnsafe.user?.id || 0;
            
            let currentAdStep = 1;
            let activeMovieId = null;
            let activeQualityIndex = 0;
            
            // Global storage for movies to access qualities easily
            let globalMovies = {}; 

            if(tg.initDataUnsafe && tg.initDataUnsafe.user) {
                document.getElementById('uName').innerText = tg.initDataUnsafe.user.first_name;
                if(tg.initDataUnsafe.user.photo_url) document.getElementById('uPic').src = tg.initDataUnsafe.user.photo_url;
            }

            const s = document.createElement('script');
            s.src = '//libtl.com/sdk.js'; s.setAttribute('data-zone', ZONE_ID); s.setAttribute('data-sdk', 'show_' + ZONE_ID);
            document.head.appendChild(s);

            function drawSkeletons(count) {
                let html = ""; for(let i=0; i<count; i++) html += `<div class="skeleton"></div>`; return html;
            }

            async function loadTrending() {
                try {
                    const r = await fetch(`/api/trending?uid=${uid}`);
                    const data = await r.json();
                    const grid = document.getElementById('trendingGrid');
                    if(data.length === 0) return document.getElementById('trendingWrapper').style.display = 'none';
                    
                    data.forEach(m => globalMovies[m._id] = m); // Store globally
                    
                    grid.innerHTML = data.map(m => {
                        let tagHtml = m.is_unlocked ? `<div class="tag tag-unlocked"><i class="fa-solid fa-unlock"></i></div>` : `<div class="tag tag-locked"><i class="fa-solid fa-lock"></i></div>`;
                        return `
                        <div class="trending-card" onclick="openQualityModal('${m._id}', ${m.is_unlocked})">
                            <div class="post-content">
                                <div class="top-badge">🔥 TOP</div>
                                <img src="/api/image/${m.photo_id}" onerror="this.src='https://via.placeholder.com/400x200?text=No+Image'">
                                ${tagHtml}
                                <div class="view-badge"><i class="fa-solid fa-eye"></i> ${m.clicks}</div>
                            </div>
                            <div class="card-footer" style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${m.title}</div>
                        </div>`;
                    }).join('');
                } catch(e) {}
            }

            async function loadMovies(page = 1) {
                if(isLoading) return; isLoading = true; currentPage = page;
                const grid = document.getElementById('movieGrid');
                grid.innerHTML = drawSkeletons(16); document.getElementById('paginationBox').innerHTML = "";

                try {
                    const r = await fetch(`/api/list?page=${currentPage}&q=${searchQuery}&uid=${uid}`);
                    const data = await r.json();
                    
                    if(data.movies.length === 0) grid.innerHTML = "<p style='grid-column: span 2; text-align:center; color:gray; padding:20px;'>কোনো মুভি পাওয়া যায়নি!</p>";
                    else {
                        data.movies.forEach(m => globalMovies[m._id] = m); // Store globally
                        grid.innerHTML = data.movies.map(m => {
                            let tagHtml = m.is_unlocked ? `<div class="tag tag-unlocked"><i class="fa-solid fa-unlock"></i></div>` : `<div class="tag tag-locked"><i class="fa-solid fa-lock"></i></div>`;
                            return `
                            <div class="card" onclick="openQualityModal('${m._id}', ${m.is_unlocked})">
                                <div class="post-content">
                                    <img src="/api/image/${m.photo_id}" onerror="this.src='https://via.placeholder.com/400x200?text=No+Image'">
                                    ${tagHtml}
                                    <div class="view-badge"><i class="fa-solid fa-eye"></i> ${m.clicks}</div>
                                </div>
                                <div class="card-footer">${m.title}</div>
                            </div>`;
                        }).join('');
                        renderPagination(data.total_pages);
                    }
                } catch(e) {}
                isLoading = false;
            }

            function renderPagination(totalPages) {
                if (totalPages <= 1) return;
                let html = "";
                for (let i = 1; i <= totalPages; i++) { html += `<button class="page-btn ${i === currentPage ? 'active' : ''}" onclick="goToPage(${i})">${i}</button>`; }
                document.getElementById('paginationBox').innerHTML = html;
            }
            function goToPage(p) { loadMovies(p); window.scrollTo({ top: document.getElementById('movieGrid').offsetTop - 100, behavior: 'smooth' }); }

            let timeout = null;
            document.getElementById('searchInput').addEventListener('input', function(e) {
                clearTimeout(timeout); searchQuery = e.target.value.trim();
                if(searchQuery !== "") document.getElementById('trendingWrapper').style.display = 'none';
                else { document.getElementById('trendingWrapper').style.display = 'block'; loadTrending(); }
                timeout = setTimeout(() => { loadMovies(1); }, 500); 
            });

            // Quality Selection Logic
            function openQualityModal(id, isUnlocked) {
                let movie = globalMovies[id];
                if(!movie) return;
                
                let qHtml = "";
                movie.files.forEach((file, index) => {
                    qHtml += `<button class="btn-submit" style="background:#f87171;" onclick="selectQuality('${id}', ${isUnlocked}, ${index})"><i class="fa-solid fa-play"></i> ${file.quality}</button>`;
                });
                
                document.getElementById('qualityButtons').innerHTML = qHtml;
                document.getElementById('qualityModal').style.display = 'flex';
            }

            function selectQuality(id, isUnlocked, index) {
                document.getElementById('qualityModal').style.display = 'none';
                activeMovieId = id;
                activeQualityIndex = index;
                
                if(isUnlocked) sendFile(id);
                else {
                    currentAdStep = 1;
                    startAdTimer();
                }
            }

            function startAdTimer() {
                if (typeof window['show_' + ZONE_ID] === 'function') window['show_' + ZONE_ID]();
                document.getElementById('adScreen').style.display = 'flex';
                document.getElementById('timerUI').style.display = 'flex';
                document.getElementById('nextAdBtn').style.display = 'none';
                document.getElementById('adStepText').innerText = `অ্যাড: ${currentAdStep}/${REQUIRED_ADS}`;
                
                let t = 15; document.getElementById('timer').innerText = t;
                let iv = setInterval(() => {
                    t--; document.getElementById('timer').innerText = t;
                    if(t <= 0) { 
                        clearInterval(iv); 
                        if(currentAdStep < REQUIRED_ADS) {
                            document.getElementById('timerUI').style.display = 'none';
                            document.getElementById('nextAdBtn').style.display = 'block';
                            document.getElementById('nextAdBtn').innerHTML = `পরবর্তী অ্যাড দেখুন (${currentAdStep + 1}/${REQUIRED_ADS}) <i class="fa-solid fa-arrow-right"></i>`;
                        } else { sendFile(activeMovieId); }
                    }
                }, 1000);
            }

            function nextAdStep() { currentAdStep++; startAdTimer(); }

            async function sendFile(id) {
                await fetch('/api/send', { 
                    method:'POST', headers:{'Content-Type':'application/json'}, 
                    body:JSON.stringify({userId: uid, movieId: id, qIndex: activeQualityIndex})
                });
                document.getElementById('adScreen').style.display = 'none';
                document.getElementById('successModal').style.display = 'flex';
                setTimeout(() => { loadTrending(); loadMovies(currentPage); }, 1000); 
            }

            function openReqModal() { document.getElementById('reqModal').style.display = 'flex'; }
            async function sendReq() {
                const text = document.getElementById('reqText').value;
                if(!text) return alert('মুভির নাম লিখুন!');
                await fetch('/api/request', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({uid: uid, uname: tg.initDataUnsafe.user?.first_name || 'Guest', movie: text})});
                document.getElementById('reqModal').style.display = 'none'; document.getElementById('reqText').value = '';
                alert('রিকোয়েস্ট সফলভাবে পাঠানো হয়েছে!');
            }

            loadTrending(); loadMovies(1); 
        </script>
    </body>
    </html>
    """
    html_code = html_code.replace("{{ZONE_ID}}", zone_id).replace("{{TG_LINK}}", tg_url).replace("{{LINK_18}}", link_18).replace("{{AD_COUNT}}", str(required_ads))
    return html_code

@app.get("/api/trending")
async def trending_movies(uid: int = 0):
    unlocked_movie_ids = []
    if uid != 0:
        time_limit = datetime.datetime.utcnow() - datetime.timedelta(hours=24)
        async for u in db.user_unlocks.find({"user_id": uid, "unlocked_at": {"$gt": time_limit}}):
            unlocked_movie_ids.append(u["movie_id"])

    movies = []
    async for m in db.movies.find().sort("clicks", -1).limit(10):
        m_id = str(m["_id"])
        m["_id"] = m_id
        m["clicks"] = m.get("clicks", 0)
        m["is_unlocked"] = m_id in unlocked_movie_ids 
        
        # Backwards compatibility for old movies
        if "files" not in m:
            m["files"] = [{"id": m.get("file_id"), "type": m.get("file_type", "video"), "quality": "Default"}]
            
        movies.append(m)
    return movies

@app.get("/api/list")
async def list_movies(page: int = 1, q: str = "", uid: int = 0):
    limit = 16
    skip = (page - 1) * limit
    query = {"title": {"$regex": q, "$options": "i"}} if q else {}
    total_movies = await db.movies.count_documents(query)
    total_pages = (total_movies + limit - 1) // limit

    unlocked_movie_ids = []
    if uid != 0:
        time_limit = datetime.datetime.utcnow() - datetime.timedelta(hours=24)
        async for u in db.user_unlocks.find({"user_id": uid, "unlocked_at": {"$gt": time_limit}}):
            unlocked_movie_ids.append(u["movie_id"])

    movies = []
    async for m in db.movies.find(query).sort("created_at", -1).skip(skip).limit(limit):
        m_id = str(m["_id"])
        m["_id"] = m_id
        m["clicks"] = m.get("clicks", 0)
        m["created_at"] = str(m.get("created_at", ""))
        m["is_unlocked"] = m_id in unlocked_movie_ids 
        
        # Backwards compatibility for old movies
        if "files" not in m:
            m["files"] = [{"id": m.get("file_id"), "type": m.get("file_type", "video"), "quality": "Default Quality"}]
            
        movies.append(m)
        
    return {"movies": movies, "total_pages": total_pages}

@app.get("/api/image/{photo_id}")
async def get_image(photo_id: str):
    try:
        file_info = await bot.get_file(photo_id)
        file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_info.file_path}"
        async def stream_image():
            async with aiohttp.ClientSession() as session:
                async with session.get(file_url) as resp:
                    async for chunk in resp.content.iter_chunked(1024): yield chunk
        return StreamingResponse(stream_image(), media_type="image/jpeg")
    except: return {"error": "not found"}

@app.post("/api/send")
async def send_file(d: dict = Body(...)):
    uid = d['userId']
    mid = d['movieId']
    q_idx = d.get('qIndex', 0)
    
    if uid == 0: return {"ok": False}
    try:
        m = await db.movies.find_one({"_id": ObjectId(mid)})
        if m:
            # Backwards compatibility
            if "files" not in m:
                m["files"] = [{"id": m.get("file_id"), "type": m.get("file_type", "video"), "quality": "Default"}]
                
            selected_file = m['files'][q_idx] if len(m['files']) > q_idx else m['files'][0]
            
            time_cfg = await db.settings.find_one({"id": "del_time"})
            del_minutes = time_cfg['minutes'] if time_cfg else 60
            
            protect_cfg = await db.settings.find_one({"id": "protect_content"})
            is_protected = protect_cfg['status'] if protect_cfg else True
            
            caption = f"🎥 <b>{m['title']}</b>\n🎞 <b>কোয়ালিটি:</b> {selected_file.get('quality', 'Video')}\n\n⏳ <b>সতর্কতা:</b> কপিরাইট এড়াতে মুভিটি <b>{del_minutes} মিনিট</b> পর অটো-ডিলিট হয়ে যাবে। দয়া করে এখনই ফরওয়ার্ড বা সেভ করে নিন!\n\n📥 Join: @TGLinkBase"
            
            sent_msg = None
            if selected_file.get("type") == "video": 
                sent_msg = await bot.send_video(uid, selected_file['id'], caption=caption, parse_mode="HTML", protect_content=is_protected)
            else: 
                sent_msg = await bot.send_document(uid, selected_file['id'], caption=caption, parse_mode="HTML", protect_content=is_protected)
            
            await db.movies.update_one({"_id": ObjectId(mid)}, {"$inc": {"clicks": 1}})
            await db.user_unlocks.update_one({"user_id": uid, "movie_id": mid}, {"$set": {"unlocked_at": datetime.datetime.utcnow()}}, upsert=True)
            
            if sent_msg:
                delete_at = datetime.datetime.utcnow() + datetime.timedelta(minutes=del_minutes)
                await db.auto_delete.insert_one({"chat_id": uid, "message_id": sent_msg.message_id, "delete_at": delete_at})
    except Exception as e: print(e)
    return {"ok": True}

class ReqModel(BaseModel):
    uid: int; uname: str; movie: str

@app.post("/api/request")
async def handle_request(data: ReqModel):
    try: 
        builder = InlineKeyboardBuilder()
        builder.button(text="✍️ রিপ্লাই দিন", callback_data=f"reply_{data.uid}")
        await bot.send_message(OWNER_ID, f"🔔 <b>নতুন মুভি রিকোয়েস্ট!</b>\n\n👤 ইউজার: {data.uname} (<code>{data.uid}</code>)\n🎬 মুভির নাম: <b>{data.movie}</b>", parse_mode="HTML", reply_markup=builder.as_markup())
    except: pass
    return {"ok": True}

async def start():
    await load_admins()
    port = int(os.getenv("PORT", 8000))
    config = uvicorn.Config(app, host="0.0.0.0", port=port, loop="asyncio")
    server = uvicorn.Server(config)
    
    asyncio.create_task(auto_delete_worker())
    
    await bot.delete_webhook(drop_pending_updates=True)
    await asyncio.gather(server.serve(), dp.start_polling(bot))

if __name__ == "__main__": asyncio.run(start())
