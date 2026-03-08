import os
import json
import base64
import requests
import threading
import asyncio
import traceback
import random
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

# গ্লোবাল ডিকশনারি (অটো-সেন্ডিং কন্ট্রোল করার জন্য)
auto_sending_status = {}

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
    doc = db.collection('client_data').document(str(user_id)).get()
    return doc.to_dict().get('api_url', '') if doc.exists else ''

def get_main_menu(user_id):
    buttons = [[InlineKeyboardButton("🚀 স্বয়ংক্রিয় ইমেইল পাঠানো শুরু", callback_data='start_auto')],[InlineKeyboardButton("🛑 পাঠানো বন্ধ করুন", callback_data='stop_auto'), InlineKeyboardButton("🔄 রিফ্রেশ", callback_data='refresh_bot')],[InlineKeyboardButton("🧪 স্প্যাম চেক (Test Email)", callback_data='test_email_start')],
        [InlineKeyboardButton("📊 আমার ক্যাম্পেইন স্ট্যাটাস", callback_data='check_stats')],[InlineKeyboardButton("ℹ️ বর্তমান ইমেইল ও API স্ট্যাটাস", callback_data='check_info')],
        [InlineKeyboardButton("🔗 আমার API লিংক সেট করুন", callback_data='set_api')]
    ]
    if is_super_admin(user_id):
        buttons.append([InlineKeyboardButton("🌍 গ্লোবাল স্ট্যাটিস্টিকস (SaaS)", callback_data='global_stats')])
        buttons.append([InlineKeyboardButton("👑 সুপার অ্যাডমিন প্যানেল", callback_data='admin_mng')])
        
    return InlineKeyboardMarkup(buttons)

def get_back_btn():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ফিরে যান", callback_data='back_home')]])

# ================= BACKGROUND AUTO SENDER TASK =================
async def auto_sender_task(user_id, chat_id, api_url, context: ContextTypes.DEFAULT_TYPE):
    """ব্যাকগ্রাউন্ডে রেন্ডম টাইমে ইমেইল পাঠানোর ইঞ্জিন"""
    await context.bot.send_message(chat_id=chat_id, text="🚀 **অটো-সেন্ডিং শুরু হয়েছে!**\nবট এখন নিজে থেকে রেন্ডম সময়ে (১-৩ মিনিট পর পর) ইমেইল পাঠাতে থাকবে। আপনি এখন নিশ্চিন্তে ঘুমিয়ে পড়তে পারেন! 😴\n\n(বন্ধ করতে মেনু থেকে '🛑 বন্ধ করুন' চাপুন)", parse_mode='Markdown')
    
    while auto_sending_status.get(user_id, False):
        try:
            # একসাথে ২-৩টি মেইল পাঠাবে (মানুষের মতো আচরণ করার জন্য)
            batch_limit = random.randint(2, 4)
            
            # Requests call কে async করা হয়েছে যেন বট হ্যাং না হয়
            res = await asyncio.to_thread(requests.post, api_url, json={"action": "send", "limit": batch_limit}, timeout=30)
            res_data = res.json()
            
            if res_data.get('status') == 'success':
                sent = res_data.get('sent', 0)
                if sent == 0:
                    auto_sending_status[user_id] = False
                    await context.bot.send_message(chat_id=chat_id, text="✅ **আপনার শিটের সব লিডসে ইমেইল পাঠানো শেষ!**\nঅটো-সেন্ডিং স্বয়ংক্রিয়ভাবে বন্ধ করা হয়েছে।", parse_mode='Markdown')
                    break
                else:
                    # ডাটাবেজে কাউন্ট আপডেট
                    db.collection('client_data').document(str(user_id)).set({'total_sent': firestore.Increment(sent)}, merge=True)
                    
                    # রেন্ডম ডিলে (৬০ থেকে ১৮০ সেকেন্ড বা ১-৩ মিনিট)
                    delay = random.randint(60, 180)
                    next_time = delay // 60
                    await context.bot.send_message(chat_id=chat_id, text=f"✅ সফলভাবে **{sent}টি** ইমেইল পাঠানো হয়েছে!\n⏳ গুগলকে ফাঁকি দিতে বট এখন **{next_time} মিনিট** অপেক্ষা করবে, এরপর আবার পাঠাবে...", parse_mode='Markdown')
                    
                    # Sleep (প্রতি ৫ সেকেন্ড পর পর চেক করবে ইউজার স্টপ করেছে কিনা)
                    for _ in range(delay // 5):
                        if not auto_sending_status.get(user_id, False):
                            break
                        await asyncio.sleep(5)
            else:
                auto_sending_status[user_id] = False
                await context.bot.send_message(chat_id=chat_id, text="✅ কাজ শেষ বা কোনো লিডস পাওয়া যায়নি। অটো-সেন্ডিং বন্ধ করা হয়েছে।")
                break
        except Exception as e:
            await context.bot.send_message(chat_id=chat_id, text=f"⚠️ কানেকশনে সমস্যা হয়েছে। ১৫ সেকেন্ড পর আবার চেষ্টা করা হচ্ছে...")
            await asyncio.sleep(15)

# ================= BOT COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_client_admin(user_id):
        await update.message.reply_text("⛔ আপনার এই বটটি ব্যবহার করার অনুমতি নেই।")
        return

    msg = "📧 **অ্যাডভান্সড ইমেইল সেন্ডার বটে স্বাগতম!**\n\nনিচের মেনু থেকে আপনার কাজ সিলেক্ট করুন:"
    if is_super_admin(user_id):
        msg = "👑 **স্বাগতম সুপার অ্যাডমিন!**\n\nনিচের মেনু থেকে আপনার কাজ সিলেক্ট করুন:"

    await update.message.reply_text(msg, reply_markup=get_main_menu(user_id), parse_mode='Markdown')

async def btn_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    await query.answer()

    if not is_client_admin(user_id): return

    data = query.data
    api_url = get_user_api_url(user_id)

    if data == 'back_home':
        await query.edit_message_text("📧 **মেইন মেনু:**", reply_markup=get_main_menu(user_id), parse_mode='Markdown')
        return ConversationHandler.END

    elif data == 'refresh_bot':
        context.user_data.clear()
        auto_sending_status[user_id] = False
        await query.edit_message_text("🔄 **বট সফলভাবে রিফ্রেশ করা হয়েছে!**\n\nআপনার অ্যাকাউন্ট এখন সম্পূর্ণ ফ্রেশ।", reply_markup=get_main_menu(user_id), parse_mode='Markdown')
        return ConversationHandler.END

    elif data == 'start_auto':
        if not api_url:
            await query.edit_message_text("⚠️ আগে আপনার API লিংক সেট করুন।", reply_markup=get_back_btn())
            return
        
        if auto_sending_status.get(user_id, False):
            await query.edit_message_text("⚠️ আপনার অটো-সেন্ডিং আগে থেকেই চলছে! নিশ্চিন্তে থাকুন।", reply_markup=get_back_btn())
            return
            
        # অটো সেন্ডিং স্টার্ট
        auto_sending_status[user_id] = True
        asyncio.create_task(auto_sender_task(user_id, chat_id, api_url, context))
        await query.edit_message_text("⚙️ অটো-সেন্ডিং ইঞ্জিন চালু করা হচ্ছে...", reply_markup=get_back_btn())

    elif data == 'stop_auto':
        if auto_sending_status.get(user_id, False):
            auto_sending_status[user_id] = False
            await query.edit_message_text("🛑 **অটো-সেন্ডিং সফলভাবে বন্ধ করা হয়েছে!**\nবট আর কোনো ইমেইল পাঠাবে না।", reply_markup=get_back_btn(), parse_mode='Markdown')
        else:
            await query.edit_message_text("⚠️ আপনার কোনো অটো-সেন্ডিং চালু নেই।", reply_markup=get_back_btn())

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
        await query.edit_message_text("⏳ গুগলের সাথে যোগাযোগ করা হচ্ছে...")
        try:
            res = requests.post(api_url, json={"action": "info"}, timeout=15).json()
            email_used = res.get('email', 'অজানা')
            msg = (f"ℹ️ **আপনার সিস্টেম স্ট্যাটাস:**\n\n📧 **অ্যাক্টিভ ইমেইল:** `{email_used}`\n🔗 **API URL:** `{api_url[:30]}.......`")
            await query.edit_message_text(msg, reply_markup=get_back_btn(), parse_mode='Markdown')
        except:
            await query.edit_message_text("❌ গুগল স্ক্রিপ্টের সাথে কানেক্ট করা যাচ্ছে না।", reply_markup=get_back_btn())

    elif data == 'check_stats':
        if not api_url:
            await query.edit_message_text("⚠️ আগে আপনার API লিংক সেট করুন।", reply_markup=get_back_btn())
            return
        await query.edit_message_text("⏳ আপনার শিট চেক করা হচ্ছে...")
        try:
            res = requests.post(api_url, json={"action": "stats"}, timeout=20).json()
            client_doc = db.collection('client_data').document(str(user_id)).get()
            total_lifetime_sent = client_doc.to_dict().get('total_sent', 0) if client_doc.exists else 0
            
            msg = (f"📊 **আপনার ক্যাম্পেইন স্ট্যাটাস:**\n\n👥 বর্তমান শিটে মোট লিডস: {res.get('total')}\n✅ পাঠানো হয়েছে: {res.get('sent')}\n⏳ বাকি আছে: {res.get('pending')}\n\n🔥 **আপনার লাইফটাইম ইমেইল সেন্ড:** {total_lifetime_sent} টি")
            await query.edit_message_text(msg, reply_markup=get_back_btn(), parse_mode='Markdown')
        except:
            await query.edit_message_text("❌ শিটের সাথে কানেক্ট করা যাচ্ছে না।", reply_markup=get_back_btn())

    elif data == 'set_api':
        await query.edit_message_text("🔗 অনুগ্রহ করে আপনার Google Apps Script এর **Web App URL** টি পেস্ট করুন:\n\n(বাতিল করতে /cancel লিখুন)")
        return WAITING_WEB_APP_URL

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
async def force_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    context.user_data.clear()
    auto_sending_status[user_id] = False
    await update.message.reply_text("🔄 **বট সফলভাবে রিফ্রেশ করা হয়েছে!**\n\nআপনার অ্যাকাউন্ট এখন সম্পূর্ণ ফ্রেশ।", reply_markup=get_main_menu(user_id), parse_mode='Markdown')
    return ConversationHandler.END

async def send_test_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target_email = update.message.text.strip()
    user_id = update.effective_user.id
    api_url = get_user_api_url(user_id)
    
    loading_msg = await update.message.reply_text("⏳ টেস্ট ইমেইল পাঠানো হচ্ছে...")
    try:
        res = await asyncio.to_thread(requests.post, api_url, json={"action": "test_email", "email": target_email}, timeout=20)
        res_data = res.json()
        if res_data.get('status') == 'success':
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
    db.collection('client_data').document(str(user_id)).set({'api_url': url, 'name': user_name}, merge=True)
    await update.message.reply_text("✅ আপনার API লিংক সফলভাবে সেভ হয়েছে!", reply_markup=get_back_btn())
    return ConversationHandler.END

async def save_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        new_admin = int(update.message.text.strip())
        doc_ref = db.collection('settings').document('admins')
        doc = doc_ref.get()
        admin_list = doc.to_dict().get('admin_ids',[]) if doc.exists else[]
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
def home(): return "SaaS Email Auto-Sender Bot is Active!"
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
        fallbacks=[
            CommandHandler('cancel', cancel), 
            CommandHandler('refresh', force_refresh),
            CallbackQueryHandler(btn_handler, pattern='^back_home$')
        ]
    )

    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("refresh", force_refresh))
    app_bot.add_handler(conv_handler)
    
    RENDER_URL = os.environ.get("RENDER_URL", "").strip()
    PORT = int(os.environ.get('PORT', 8080))
    
    if RENDER_URL:
        if not RENDER_URL.endswith('/'): RENDER_URL += '/'
        print(f"🚀 Starting Webhook Server on {RENDER_URL}...")
        app_bot.run_webhook(listen="0.0.0.0", port=PORT, webhook_url=f"{RENDER_URL}{BOT_TOKEN}", url_path=BOT_TOKEN, drop_pending_updates=True)
    else:
        print("⚠️ RENDER_URL পাওয়া যায়নি! Polling সিস্টেমে চলছে...")
        threading.Thread(target=run_flask, daemon=True).start()
        app_bot.run_polling()

if __name__ == '__main__':
    main()
