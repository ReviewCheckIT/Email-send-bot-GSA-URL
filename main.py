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
OWNER_ID = int(os.environ.get("OWNER_ID", 0)) # সুপার অ্যাডমিন

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
def is_super_admin(user_id):
    return user_id == OWNER_ID

def is_client_admin(user_id):
    if user_id == OWNER_ID: return True
    doc = db.collection('settings').document('admins').get()
    if doc.exists:
        admin_list = doc.to_dict().get('admin_ids',[])
        return user_id in admin_list
    return False

def get_user_api_url(user_id):
    # প্রতিটি ইউজারের আলাদা API URL থাকবে
    doc = db.collection('client_data').document(str(user_id)).get()
    return doc.to_dict().get('api_url', '') if doc.exists else ''

def get_main_menu(user_id):
    buttons = [[InlineKeyboardButton("🚀 ইমেইল পাঠানো শুরু করুন", callback_data='start_sending')],[InlineKeyboardButton("🧪 স্প্যাম চেক (Test Email)", callback_data='test_email_start')],[InlineKeyboardButton("📊 আমার ক্যাম্পেইন স্ট্যাটাস", callback_data='check_stats')],[InlineKeyboardButton("ℹ️ বর্তমান ইমেইল ও API স্ট্যাটাস", callback_data='check_info')],
        [InlineKeyboardButton("🔗 আমার API লিংক সেট করুন", callback_data='set_api')]
    ]
    
    # সুপার অ্যাডমিনের জন্য এক্সট্রা বাটন
    if is_super_admin(user_id):
        buttons.append([InlineKeyboardButton("🌍 গ্লোবাল স্ট্যাটিস্টিকস (SaaS)", callback_data='global_stats')])
        buttons.append([InlineKeyboardButton("👑 সুপার অ্যাডমিন প্যানেল", callback_data='admin_mng')])
        
    return InlineKeyboardMarkup(buttons)

def get_back_btn():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ফিরে যান", callback_data='back_home')]])

# ================= BOT COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_client_admin(user_id):
        await update.message.reply_text("⛔ আপনার এই বটটি ব্যবহার করার অনুমতি নেই। অ্যাক্সেস পেতে অ্যাডমিনের সাথে যোগাযোগ করুন।")
        return

    msg = "📧 **অ্যাডভান্সড ইমেইল সেন্ডার বটে স্বাগতম!**\n\nনিচের মেনু থেকে আপনার কাজ সিলেক্ট করুন:"
    if is_super_admin(user_id):
        msg = "👑 **স্বাগতম সুপার অ্যাডমিন!**\n\nনিচের মেনু থেকে আপনার কাজ সিলেক্ট করুন:"

    await update.message.reply_text(msg, reply_markup=get_main_menu(user_id), parse_mode='Markdown')

async def btn_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    if not is_client_admin(user_id): return

    data = query.data
    api_url = get_user_api_url(user_id)

    if data == 'back_home':
        await query.edit_message_text("📧 **মেইন মেনু:**", reply_markup=get_main_menu(user_id), parse_mode='Markdown')
        return ConversationHandler.END

    elif data == 'test_email_start':
        if not api_url:
            await query.edit_message_text("⚠️ আগে আপনার API লিংক সেট করুন।", reply_markup=get_back_btn())
            return
        await query.edit_message_text("🧪 **স্প্যাম চেক (Test Email):**\n\nআপনি যেই ইমেইলে টেস্ট মেসেজটি পাঠাতে চান, সেটি লিখে পাঠান:\n*(উদাহরণ: test@mailchecker.com)*", reply_markup=get_back_btn(), parse_mode='Markdown')
        return WAITING_TEST_EMAIL

    elif data == 'check_info':
        if not api_url:
            await query.edit_message_text("⚠️ আপনার অ্যাকাউন্টে কোনো API লিংক সেট করা নেই।", reply_markup=get_back_btn())
            return
        await query.edit_message_text("⏳ গুগলের সাথে যোগাযোগ করা হচ্ছে, অপেক্ষা করুন...")
        try:
            res = requests.post(api_url, json={"action": "info"}, timeout=15).json()
            email_used = res.get('email', 'অজানা')
            msg = (f"ℹ️ **আপনার সিস্টেম স্ট্যাটাস:**\n\n📧 **অ্যাক্টিভ ইমেইল:** `{email_used}`\n🔗 **API URL:** `{api_url[:30]}.......`")
            await query.edit_message_text(msg, reply_markup=get_back_btn(), parse_mode='Markdown')
        except:
            await query.edit_message_text(f"❌ গুগল স্ক্রিপ্টের সাথে কানেক্ট করা যাচ্ছে না।", reply_markup=get_back_btn())

    elif data == 'check_stats':
        if not api_url:
            await query.edit_message_text("⚠️ আগে আপনার API লিংক সেট করুন।", reply_markup=get_back_btn())
            return
        await query.edit_message_text("⏳ আপনার শিট চেক করা হচ্ছে...")
        try:
            res = requests.post(api_url, json={"action": "stats"}, timeout=20).json()
            
            # ফায়ারবেস থেকে টোটাল সেন্ট কাউন্ট আনা
            client_doc = db.collection('client_data').document(str(user_id)).get()
            total_lifetime_sent = client_doc.to_dict().get('total_sent', 0) if client_doc.exists else 0
            
            msg = (
                f"📊 **আপনার ক্যাম্পেইন স্ট্যাটাস:**\n\n"
                f"👥 বর্তমান শিটে মোট লিডস: {res.get('total')}\n"
                f"✅ বর্তমান শিট থেকে পাঠানো হয়েছে: {res.get('sent')}\n"
                f"⏳ বাকি আছে: {res.get('pending')}\n\n"
                f"🔥 **আপনার লাইফটাইম ইমেইল সেন্ড:** {total_lifetime_sent} টি"
            )
            await query.edit_message_text(msg, reply_markup=get_back_btn(), parse_mode='Markdown')
        except:
            await query.edit_message_text("❌ শিটের সাথে কানেক্ট করা যাচ্ছে না।", reply_markup=get_back_btn())

    elif data == 'start_sending':
        if not api_url:
            await query.edit_message_text("⚠️ আগে আপনার API লিংক সেট করুন।", reply_markup=get_back_btn())
            return
        await query.edit_message_text("🚀 আপনার ইমেইল পাঠানো হচ্ছে... দয়া করে অপেক্ষা করুন (একবারে ১০টি করে)।")
        try:
            res = requests.post(api_url, json={"action": "send", "limit": 10}, timeout=30).json()
            if res.get('status') == 'success':
                sent = res.get('sent')
                if sent == 0:
                    await query.edit_message_text("✅ আপনার শিটের সব লিডসে ইমেইল পাঠানো শেষ!", reply_markup=get_back_btn())
                else:
                    # ইউজারের ডাটাবেজে কাউন্ট যোগ করা
                    db.collection('client_data').document(str(user_id)).set({
                        'total_sent': firestore.Increment(sent)
                    }, merge=True)
                    
                    await query.edit_message_text(
                        f"✅ সফলভাবে **{sent}টি** ইমেইল পাঠানো হয়েছে!\n\nআরও পাঠাতে আবার ক্লিক করুন।", 
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚀 আরও ১০টি পাঠান", callback_data='start_sending')],[InlineKeyboardButton("🔙 ফিরে যান", callback_data='back_home')]]), 
                        parse_mode='Markdown'
                    )
            else:
                await query.edit_message_text("✅ কাজ শেষ বা কোনো লিডস পাওয়া যায়নি।", reply_markup=get_back_btn())
        except Exception as e:
            await query.edit_message_text(f"❌ এরর: টাইমআউট বা গুগলের রেসপন্সে সমস্যা। আবার চেষ্টা করুন।", reply_markup=get_back_btn())

    elif data == 'set_api':
        await query.edit_message_text("🔗 অনুগ্রহ করে আপনার Google Apps Script এর **Web App URL** টি পেস্ট করুন:\n\n(বাতিল করতে /cancel লিখুন)")
        return WAITING_WEB_APP_URL

    # ================= SUPER ADMIN ONLY =================
    elif data == 'admin_mng':
        if not is_super_admin(user_id): return
        kb = [[InlineKeyboardButton("➕ ক্লায়েন্ট যুক্ত করুন", callback_data='add_admin'), InlineKeyboardButton("➖ ক্লায়েন্ট রিমুভ করুন", callback_data='rmv_admin')],[InlineKeyboardButton("🔙 ফিরে যান", callback_data='back_home')]]
        await query.edit_message_text("👑 **সুপার অ্যাডমিন ম্যানেজমেন্ট:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    elif data == 'add_admin':
        if not is_super_admin(user_id): return
        await query.edit_message_text("যাকে বট ভাড়া দিতে চান, তার Telegram ID দিন:", reply_markup=get_back_btn())
        return WAITING_ADMIN_ID

    elif data == 'rmv_admin':
        if not is_super_admin(user_id): return
        await query.edit_message_text("যাকে বাদ দিতে চান তার Telegram ID দিন:", reply_markup=get_back_btn())
        return WAITING_REMOVE_ADMIN
        
    elif data == 'global_stats':
        if not is_super_admin(user_id): return
        await query.edit_message_text("⏳ ডাটা লোড হচ্ছে...")
        
        clients = db.collection('client_data').stream()
        msg = "🌍 **গ্লোবাল স্ট্যাটিস্টিকস (SaaS):**\n\n"
        total_global_sent = 0
        
        for c in clients:
            c_data = c.to_dict()
            sent = c_data.get('total_sent', 0)
            total_global_sent += sent
            name = c_data.get('name', f"ID: {c.id}")
            msg += f"👤 {name} : **{sent}** টি মেইল\n"
            
        msg += f"\n🔥 **বট থেকে মোট পাঠানো হয়েছে: {total_global_sent} টি মেইল!**"
        
        await query.edit_message_text(msg, reply_markup=get_back_btn(), parse_mode='Markdown')

# ================= CONVERSATION HANDLERS =================
async def send_test_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target_email = update.message.text.strip()
    user_id = update.effective_user.id
    api_url = get_user_api_url(user_id)
    
    loading_msg = await update.message.reply_text("⏳ টেস্ট ইমেইল পাঠানো হচ্ছে...")
    try:
        res = requests.post(api_url, json={"action": "test_email", "email": target_email}, timeout=20).json()
        if res.get('status') == 'success':
            await loading_msg.edit_text(f"✅ সফলভাবে `{target_email}` ঠিকানায় টেস্ট ইমেইল পাঠানো হয়েছে!", reply_markup=get_back_btn(), parse_mode='Markdown')
        else:
            await loading_msg.edit_text(f"❌ ইমেইল পাঠাতে সমস্যা হয়েছে।", reply_markup=get_back_btn())
    except:
        await loading_msg.edit_text(f"❌ কানেকশনে সমস্যা হয়েছে।", reply_markup=get_back_btn())
        
    return ConversationHandler.END

async def save_api_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    
    # ইউজারের নিজের ডাটাবেজে লিংক সেভ হবে
    db.collection('client_data').document(str(user_id)).set({
        'api_url': url,
        'name': user_name
    }, merge=True)
    
    await update.message.reply_text("✅ আপনার API লিংক সফলভাবে সেভ হয়েছে!", reply_markup=get_back_btn())
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
        await update.message.reply_text("✅ ক্লায়েন্ট সফলভাবে যুক্ত করা হয়েছে!", reply_markup=get_back_btn())
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
        await update.message.reply_text("🗑️ ক্লায়েন্ট রিমুভ করা হয়েছে!", reply_markup=get_back_btn())
    except:
        await update.message.reply_text("❌ আইডি পাওয়া যায়নি।", reply_markup=get_back_btn())
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ কাজ বাতিল করা হয়েছে।", reply_markup=get_back_btn())
    return ConversationHandler.END

# ================= FLASK FALLBACK =================
app = Flask(__name__)
@app.route('/')
def home(): return "SaaS Email Bot Webhook is Active!"
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
