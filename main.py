import os
import json
import base64
import requests
import threading
from flask import Flask
import firebase_admin
from firebase_admin import credentials, firestore
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes, ConversationHandler
)

# ================= API KEYS =================
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OWNER_ID = int(os.environ.get("OWNER_ID", 0))

# ================= FIREBASE SETUP =================
try:
    firebase_json = os.environ.get("FIREBASE_JSON")
    cred_dict = json.loads(firebase_json) if firebase_json.startswith("{") else json.loads(base64.b64decode(firebase_json).decode('utf-8'))
    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred)
    db = firestore.client()
except Exception as e:
    print(f"Firebase Error: {e}")

# ================= STATES =================
WAITING_WEB_APP_URL, WAITING_ADMIN_ID, WAITING_REMOVE_ADMIN, WAITING_TEST_EMAIL = range(4)

# ================= HELPER FUNCTIONS =================
def is_admin(user_id):
    if user_id == OWNER_ID: return True
    doc = db.collection('settings').document('admins').get()
    if doc.exists:
        admin_list = doc.to_dict().get('admin_ids',[])
        return user_id in admin_list
    return False

def get_api_url():
    doc = db.collection('settings').document('config').get()
    return doc.to_dict().get('web_app_url', '') if doc.exists else ''

def get_main_menu():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🚀 ইমেইল পাঠানো শুরু করুন", callback_data='start_sending')],[InlineKeyboardButton("🧪 স্প্যাম চেক (Test Email)", callback_data='test_email_start')],[InlineKeyboardButton("📊 ক্যাম্পেইন স্ট্যাটাস", callback_data='check_stats')],[InlineKeyboardButton("ℹ️ বর্তমান ইমেইল ও API স্ট্যাটাস", callback_data='check_info')],
        [InlineKeyboardButton("🔗 API লিংক পরিবর্তন করুন", callback_data='set_api')],[InlineKeyboardButton("👮 অ্যাডমিন প্যানেল", callback_data='admin_mng')]
    ])

def get_back_btn():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ফিরে যান", callback_data='back_home')]])

# ================= BOT COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ এই বটটি শুধুমাত্র অ্যাডমিনদের জন্য।")
        return

    await update.message.reply_text(
        "📧 **বাল্ক ইমেইল সেন্ডার বটে স্বাগতম!**\n\nনিচের মেনু থেকে আপনার কাজ সিলেক্ট করুন:",
        reply_markup=get_main_menu(), parse_mode='Markdown'
    )

async def btn_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    if not is_admin(user_id): return

    data = query.data
    api_url = get_api_url()

    if data == 'back_home':
        await query.edit_message_text("📧 **মেইন মেনু:**", reply_markup=get_main_menu(), parse_mode='Markdown')
        return ConversationHandler.END

    elif data == 'test_email_start':
        if not api_url:
            await query.edit_message_text("⚠️ আগে API লিংক সেট করুন।", reply_markup=get_back_btn())
            return
        await query.edit_message_text("🧪 **স্প্যাম চেক (Test Email):**\n\nআপনি যেই ইমেইলে টেস্ট মেসেজটি পাঠাতে চান, সেটি লিখে পাঠান:\n*(উদাহরণ: test@mailchecker.com)*", reply_markup=get_back_btn(), parse_mode='Markdown')
        return WAITING_TEST_EMAIL

    elif data == 'check_info':
        if not api_url:
            await query.edit_message_text("⚠️ ডাটাবেজে কোনো API লিংক সেট করা নেই।", reply_markup=get_back_btn())
            return
        await query.edit_message_text("⏳ গুগলের সাথে যোগাযোগ করা হচ্ছে, অপেক্ষা করুন...")
        try:
            res = requests.post(api_url, json={"action": "info"}, timeout=15).json()
            email_used = res.get('email', 'অজানা')
            msg = (f"ℹ️ **বর্তমান সিস্টেম স্ট্যাটাস:**\n\n📧 **অ্যাক্টিভ ইমেইল:** `{email_used}`\n🔗 **API URL:** `{api_url[:30]}.......`")
            await query.edit_message_text(msg, reply_markup=get_back_btn(), parse_mode='Markdown')
        except Exception as e:
            await query.edit_message_text(f"❌ গুগল স্ক্রিপ্টের সাথে কানেক্ট করা যাচ্ছে না।", reply_markup=get_back_btn())

    elif data == 'check_stats':
        if not api_url:
            await query.edit_message_text("⚠️ আগে API লিংক সেট করুন।", reply_markup=get_back_btn())
            return
        await query.edit_message_text("⏳ শিট চেক করা হচ্ছে...")
        try:
            res = requests.post(api_url, json={"action": "stats"}, timeout=20).json()
            msg = (f"📊 **ক্যাম্পেইন স্ট্যাটাস:**\n\n👥 মোট লিডস: {res.get('total')}\n✅ পাঠানো হয়েছে: {res.get('sent')}\n⏳ বাকি আছে: {res.get('pending')}")
            await query.edit_message_text(msg, reply_markup=get_back_btn(), parse_mode='Markdown')
        except:
            await query.edit_message_text("❌ শিটের সাথে কানেক্ট করা যাচ্ছে না।", reply_markup=get_back_btn())

    elif data == 'start_sending':
        if not api_url:
            await query.edit_message_text("⚠️ আগে API লিংক সেট করুন।", reply_markup=get_back_btn())
            return
        await query.edit_message_text("🚀 ইমেইল পাঠানো হচ্ছে... দয়া করে অপেক্ষা করুন (একবারে ১০টি করে)।")
        try:
            res = requests.post(api_url, json={"action": "send", "limit": 10}, timeout=30).json()
            if res.get('status') == 'success':
                sent = res.get('sent')
                if sent == 0:
                    await query.edit_message_text("✅ সব লিডসে ইমেইল পাঠানো শেষ!", reply_markup=get_back_btn())
                else:
                    await query.edit_message_text(f"✅ সফলভাবে **{sent}টি** ইমেইল পাঠানো হয়েছে!\n\nআরও পাঠাতে আবার ক্লিক করুন।", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚀 আরও ১০টি পাঠান", callback_data='start_sending')],[InlineKeyboardButton("🔙 ফিরে যান", callback_data='back_home')]]), parse_mode='Markdown')
            else:
                await query.edit_message_text("✅ কাজ শেষ বা কোনো লিডস পাওয়া যায়নি।", reply_markup=get_back_btn())
        except Exception as e:
            await query.edit_message_text(f"❌ এরর: টাইমআউট বা গুগলের রেসপন্সে সমস্যা। আবার চেষ্টা করুন।", reply_markup=get_back_btn())

    elif data == 'set_api':
        await query.edit_message_text("🔗 অনুগ্রহ করে আপনার Google Apps Script এর **Web App URL** টি পেস্ট করুন:\n\n(বাতিল করতে /cancel লিখুন)")
        return WAITING_WEB_APP_URL

    elif data == 'admin_mng':
        if user_id != OWNER_ID:
            await query.edit_message_text("⛔ শুধুমাত্র মেইন ওনার (Owner) অ্যাডমিন যুক্ত বা বাতিল করতে পারবেন।", reply_markup=get_back_btn())
            return
        kb = [[InlineKeyboardButton("➕ অ্যাডমিন যুক্ত করুন", callback_data='add_admin'), InlineKeyboardButton("➖ অ্যাডমিন বাদ দিন", callback_data='rmv_admin')],[InlineKeyboardButton("🔙 ফিরে যান", callback_data='back_home')]]
        await query.edit_message_text("👮 **অ্যাডমিন ম্যানেজমেন্ট:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    elif data == 'add_admin':
        await query.edit_message_text("নতুন অ্যাডমিনের Telegram ID (নম্বর) দিন:", reply_markup=get_back_btn())
        return WAITING_ADMIN_ID

    elif data == 'rmv_admin':
        await query.edit_message_text("যাকে বাদ দিতে চান তার Telegram ID দিন:", reply_markup=get_back_btn())
        return WAITING_REMOVE_ADMIN

# ================= CONVERSATION HANDLERS =================
async def send_test_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target_email = update.message.text.strip()
    api_url = get_api_url()
    
    loading_msg = await update.message.reply_text("⏳ টেস্ট ইমেইল পাঠানো হচ্ছে...")
    try:
        res = requests.post(api_url, json={"action": "test_email", "email": target_email}, timeout=20).json()
        if res.get('status') == 'success':
            await loading_msg.edit_text(f"✅ সফলভাবে `{target_email}` ঠিকানায় টেস্ট ইমেইল পাঠানো হয়েছে! ইনবক্স বা স্প্যাম ফোল্ডার চেক করুন।", reply_markup=get_back_btn(), parse_mode='Markdown')
        else:
            await loading_msg.edit_text(f"❌ ইমেইল পাঠাতে সমস্যা হয়েছে: {res.get('error', 'Unknown error')}", reply_markup=get_back_btn())
    except Exception as e:
        await loading_msg.edit_text(f"❌ কানেকশনে সমস্যা হয়েছে।", reply_markup=get_back_btn())
        
    return ConversationHandler.END

async def save_api_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    db.collection('settings').document('config').set({'web_app_url': url}, merge=True)
    await update.message.reply_text("✅ API লিংক সফলভাবে আপডেট করা হয়েছে!", reply_markup=get_back_btn())
    return ConversationHandler.END

async def save_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        new_admin = int(update.message.text.strip())
        doc_ref = db.collection('settings').document('admins')
        doc = doc_ref.get()
        admin_list = doc.to_dict().get('admin_ids', []) if doc.exists else[]
        if new_admin not in admin_list:
            admin_list.append(new_admin)
            doc_ref.set({'admin_ids': admin_list}, merge=True)
        await update.message.reply_text("✅ অ্যাডমিন সফলভাবে যুক্ত করা হয়েছে!", reply_markup=get_back_btn())
    except:
        await update.message.reply_text("❌ ভুল আইডি।", reply_markup=get_back_btn())
    return ConversationHandler.END

async def remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        rmv_admin = int(update.message.text.strip())
        doc_ref = db.collection('settings').document('admins')
        doc = doc_ref.get()
        admin_list = doc.to_dict().get('admin_ids',[]) if doc.exists else[]
        if rmv_admin in admin_list:
            admin_list.remove(rmv_admin)
            doc_ref.set({'admin_ids': admin_list}, merge=True)
        await update.message.reply_text("🗑️ অ্যাডমিন রিমুভ করা হয়েছে!", reply_markup=get_back_btn())
    except:
        await update.message.reply_text("❌ আইডি পাওয়া যায়নি।", reply_markup=get_back_btn())
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ কাজ বাতিল করা হয়েছে।", reply_markup=get_back_btn())
    return ConversationHandler.END

# ================= FLASK FALLBACK =================
app = Flask(__name__)
@app.route('/')
def home(): return "Email Bot Webhook is Active!"
def run_flask(): app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

# ================= MAIN (WEBHOOK SYSTEM) =================
def main():
    app_bot = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(btn_handler)],
        states={
            WAITING_WEB_APP_URL:[MessageHandler(filters.TEXT & ~filters.COMMAND, save_api_url)],
            WAITING_ADMIN_ID:[MessageHandler(filters.TEXT & ~filters.COMMAND, save_admin)],
            WAITING_REMOVE_ADMIN:[MessageHandler(filters.TEXT & ~filters.COMMAND, remove_admin)],
            WAITING_TEST_EMAIL:[MessageHandler(filters.TEXT & ~filters.COMMAND, send_test_email)],
        },
        fallbacks=[CommandHandler('cancel', cancel), CallbackQueryHandler(btn_handler, pattern='^back_home$')]
    )

    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(conv_handler)
    
    # 🔴 Webhook Setup 🔴
    RENDER_URL = os.environ.get("RENDER_URL", "").strip()
    PORT = int(os.environ.get('PORT', 8080))
    
    if RENDER_URL:
        if not RENDER_URL.endswith('/'):
            RENDER_URL += '/'
            
        print(f"🚀 Starting Webhook Server on {RENDER_URL}...")
        app_bot.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=f"{RENDER_URL}{BOT_TOKEN}",
            url_path=BOT_TOKEN,
            drop_pending_updates=True
        )
    else:
        print("⚠️ RENDER_URL পাওয়া যায়নি! Polling সিস্টেমে চলছে...")
        threading.Thread(target=run_flask, daemon=True).start()
        app_bot.run_polling()

if __name__ == '__main__':
    main()
