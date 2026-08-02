import telebot
import time
import ssl
import requests
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager
import re
import threading
from datetime import datetime, timedelta
import os
import logging
import random

logging.basicConfig(level=logging.INFO)

TOKEN = os.environ.get("TELEGRAM_TOKEN", "8321389005:AAFLGNmxcnLB5GlZ2vXIc5DzNQNX1DOg_7M")

class SSLAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        kwargs['cert_reqs'] = ssl.CERT_NONE
        super().init_poolmanager(*args, **kwargs)

session = requests.Session()
session.mount('https://', SSLAdapter())
session.verify = False

bot = telebot.TeleBot(TOKEN)
bot.session = session

# ============ ХРАНИЛИЩА ============
user_warns = {}           # {user_id: count}
warn_threshold = {}       # {user_id: threshold}
muted_users = {}          # {user_id: (mute_end, warn_msg_id, mute_msg_id)}
warn_messages = {}        # {user_id: message_id}  # ID сообщения с варнами
mute_timers = {}          # {user_id: timer}
spam_timers = {}          # {user_id: timer}
echo_status = {}          # {user_id: True/False}
last_command_time = {}    # {user_id: timestamp} для защиты от спама
animation_messages = {}   # {user_id: message_id} для анимации

# ============ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ============
def parse_time(time_str):
    time_str = time_str.lower()
    if 'm' in time_str:
        minutes = int(re.search(r'(\d+)', time_str).group(1))
        return timedelta(minutes=minutes)
    elif 'h' in time_str:
        hours = int(re.search(r'(\d+)', time_str).group(1))
        return timedelta(hours=hours)
    elif 'd' in time_str:
        days = int(re.search(r'(\d+)', time_str).group(1))
        return timedelta(days=days)
    return None

def format_time(seconds):
    if seconds > 3600:
        return f"{int(seconds/3600)} часов"
    elif seconds > 60:
        return f"{int(seconds/60)} минут"
    else:
        return f"{int(seconds)} секунд"

def mute_user(user_id, duration, chat_id, business_conn_id):
    """Замутить пользователя и создать сообщение с таймером"""
    mute_end = datetime.now() + duration
    
    # Удаляем старое сообщение о муте если было
    if user_id in muted_users:
        old_mute_msg_id = muted_users[user_id][2]
        try:
            bot.delete_business_messages(
                business_connection_id=business_conn_id,
                message_ids=[old_mute_msg_id]
            )
        except:
            pass
    
    # Отправляем сообщение о муте
    time_str = format_time(duration.total_seconds())
    msg = bot.send_message(
        chat_id=chat_id,
        business_connection_id=business_conn_id,
        text=f"🔇 Помолчи, а то устал писать)\n⏳ Время до конца мута: {time_str}"
    )
    
    # Сохраняем данные
    muted_users[user_id] = (mute_end, None, msg.message_id, business_conn_id)
    
    # Запускаем таймер на размут
    timer = threading.Timer(duration.total_seconds(), unmute_user, args=[user_id, chat_id, business_conn_id])
    timer.daemon = True
    timer.start()
    mute_timers[user_id] = timer
    
    # Запускаем обновление таймера каждую минуту
    update_mute_timer(user_id, chat_id, business_conn_id)

def update_mute_timer(user_id, chat_id, business_conn_id):
    """Обновляет таймер в сообщении о муте каждую минуту"""
    if user_id not in muted_users:
        return
    
    mute_end, _, msg_id, conn_id = muted_users[user_id]
    time_left = (mute_end - datetime.now()).total_seconds()
    
    if time_left <= 0:
        return
    
    time_str = format_time(time_left)
    
    try:
        bot.edit_message_text(
            text=f"🔇 Помолчи, а то устал писать)\n⏳ Время до конца мута: {time_str}",
            chat_id=chat_id,
            message_id=msg_id,
            business_connection_id=conn_id
        )
    except:
        pass
    
    # Запускаем следующее обновление через 10 секунд
    timer = threading.Timer(10, update_mute_timer, args=[user_id, chat_id, business_conn_id])
    timer.daemon = True
    timer.start()

def unmute_user(user_id, chat_id, business_conn_id):
    """Снять мут"""
    if user_id in muted_users:
        _, _, msg_id, conn_id = muted_users[user_id]
        try:
            bot.delete_business_messages(
                business_connection_id=conn_id,
                message_ids=[msg_id]
            )
        except:
            pass
        del muted_users[user_id]
        
        try:
            bot.send_message(
                chat_id=chat_id,
                business_connection_id=business_conn_id,
                text="✅ Вы размучены"
            )
        except:
            pass

def delete_after_delay(chat_id, business_conn_id, message_id, delay):
    """Удалить сообщение через N секунд"""
    def delete():
        time.sleep(delay)
        try:
            bot.delete_business_messages(
                business_connection_id=business_conn_id,
                message_ids=[message_id]
            )
        except:
            pass
    timer = threading.Timer(delay, delete)
    timer.daemon = True
    timer.start()

# ============ ОСНОВНОЙ ОБРАБОТЧИК ============
@bot.business_message_handler(func=lambda message: True)
def handle_message(message):
    user_id = message.chat.id
    text = message.text or ""
    chat_id = message.chat.id
    conn_id = message.business_connection_id
    
    # Защита от спама команд (1 секунда между командами)
    if user_id in last_command_time:
        if time.time() - last_command_time[user_id] < 1:
            return
    last_command_time[user_id] = time.time()
    
    # ===== ПРОВЕРКА МУТА =====
    if user_id in muted_users:
        mute_end, _, _, _ = muted_users[user_id]
        if datetime.now() < mute_end:
            # Удаляем сообщение замученного
            try:
                bot.delete_business_messages(
                    business_connection_id=conn_id,
                    message_ids=[message.message_id]
                )
            except:
                pass
            return
    
    # ===== .mute N =====
    if text.startswith('.mute'):
        parts = text.split()
        if len(parts) >= 2:
            duration = parse_time(parts[1])
            if duration:
                mute_user(user_id, duration, chat_id, conn_id)
            else:
                bot.send_message(chat_id=chat_id, business_connection_id=conn_id, text="❌ Используй: .mute 5m / 1h")
        return
    
    # ===== .unmute =====
    if text.startswith('.unmute'):
        unmute_user(user_id, chat_id, conn_id)
        return
    
    # ===== .spam текст N =====
    if text.startswith('.spam'):
        parts = text.split(maxsplit=2)
        if len(parts) >= 3:
            try:
                count = int(parts[1])
                if count > 30:
                    count = 30
                spam_text = parts[2]
                for i in range(count):
                    bot.send_message(chat_id=chat_id, business_connection_id=conn_id, text=spam_text)
                    time.sleep(0.1)
            except:
                bot.send_message(chat_id=chat_id, business_connection_id=conn_id, text="❌ .spam текст N")
        return
    
    # ===== .txt текст (анимация по буквам) =====
    if text.startswith('.txt'):
        parts = text.split(maxsplit=1)
        if len(parts) >= 2:
            txt = parts[1]
            # Создаём сообщение с первой буквой
            msg = bot.send_message(chat_id=chat_id, business_connection_id=conn_id, text=txt[0])
            animation_messages[user_id] = msg.message_id
            # Анимируем по буквам
            for i in range(1, len(txt)):
                time.sleep(0.1)
                try:
                    bot.edit_message_text(
                        text=txt[:i+1],
                        chat_id=chat_id,
                        message_id=msg.message_id,
                        business_connection_id=conn_id
                    )
                except:
                    pass
        return
    
    # ===== .echo on/off =====
    if text.startswith('.echo'):
        parts = text.split()
        if len(parts) >= 2:
            if parts[1].lower() == 'on':
                echo_status[user_id] = True
                bot.send_message(chat_id=chat_id, business_connection_id=conn_id, text="🔄 Эхо включено")
            elif parts[1].lower() == 'off':
                echo_status[user_id] = False
                bot.send_message(chat_id=chat_id, business_connection_id=conn_id, text="🔄 Эхо выключено")
        return
    
    # ===== ЭХО (автоповтор) =====
    if user_id in echo_status and echo_status[user_id]:
        if not text.startswith('.'):
            bot.send_message(chat_id=chat_id, business_connection_id=conn_id, text=text)
        return
    
    # ===== .st текст (каждое слово отдельно) =====
    if text.startswith('.st'):
        parts = text.split(maxsplit=1)
        if len(parts) >= 2:
            words = parts[1].split()
            for word in words:
                bot.send_message(chat_id=chat_id, business_connection_id=conn_id, text=word)
                time.sleep(0.1)
        return
    
    # ===== .dl N текст =====
    if text.startswith('.dl'):
        parts = text.split(maxsplit=2)
        if len(parts) >= 3:
            try:
                delay = int(parts[1])
                if delay > 300:
                    delay = 300
                dl_text = parts[2]
                msg = bot.send_message(chat_id=chat_id, business_connection_id=conn_id, text=dl_text)
                delete_after_delay(chat_id, conn_id, msg.message_id, delay)
            except:
                bot.send_message(chat_id=chat_id, business_connection_id=conn_id, text="❌ .dl N текст")
        return
    
    # ===== .ball вопрос =====
    if text.startswith('.ball'):
        answers = ["✅ Да", "❌ Нет", "🔄 Возможно", "🤔 Спроси позже", "⭐ Определённо да", "🚫 Абсолютно нет"]
        bot.send_message(chat_id=chat_id, business_connection_id=conn_id, text=random.choice(answers))
        return
    
    # ===== .warn N =====
    if text.startswith('.warn'):
        parts = text.split()
        if len(parts) >= 2:
            try:
                threshold = int(parts[1])
                if threshold <= 0:
                    threshold = 1
                warn_threshold[user_id] = threshold
                user_warns[user_id] = 0
                
                # Удаляем команду
                try:
                    bot.delete_business_messages(
                        business_connection_id=conn_id,
                        message_ids=[message.message_id]
                    )
                except:
                    pass
                
                # Создаём сообщение с счётчиком
                msg = bot.send_message(
                    chat_id=chat_id,
                    business_connection_id=conn_id,
                    text=f"⚠️ До твоего молчания {threshold} сообщений)"
                )
                warn_messages[user_id] = msg.message_id
                
            except:
                bot.send_message(chat_id=chat_id, business_connection_id=conn_id, text="❌ .warn N")
        return
    
    # ===== .unwarn =====
    if text.startswith('.unwarn'):
        if user_id in warn_threshold:
            del warn_threshold[user_id]
        if user_id in user_warns:
            del user_warns[user_id]
        if user_id in warn_messages:
            try:
                bot.delete_business_messages(
                    business_connection_id=conn_id,
                    message_ids=[warn_messages[user_id]]
                )
            except:
                pass
            del warn_messages[user_id]
        bot.send_message(chat_id=chat_id, business_connection_id=conn_id, text="✅ Варны сброшены")
        return
    
    # ===== ЛОГИКА ВАРНОВ (счётчик) =====
    if user_id in warn_threshold:
        threshold = warn_threshold[user_id]
        user_warns[user_id] = user_warns.get(user_id, 0) + 1
        
        # Обновляем сообщение с варнами
        if user_id in warn_messages:
            left = threshold - user_warns[user_id]
            try:
                if left > 0:
                    bot.edit_message_text(
                        text=f"⚠️ До твоего молчания {left} сообщений)",
                        chat_id=chat_id,
                        message_id=warn_messages[user_id],
                        business_connection_id=conn_id
                    )
                else:
                    # Удаляем сообщение с варнами
                    bot.delete_business_messages(
                        business_connection_id=conn_id,
                        message_ids=[warn_messages[user_id]]
                    )
                    del warn_messages[user_id]
            except:
                pass
        
        # Если достигнут порог - мут
        if user_warns[user_id] >= threshold:
            user_warns[user_id] = 0
            mute_user(user_id, timedelta(hours=1), chat_id, conn_id)
            return
    
    # ===== ОБЫЧНЫЙ ОТВЕТ (если ничего не сработало) =====
    bot.send_message(
        chat_id=chat_id,
        business_connection_id=conn_id,
        text="Привет! Как дела?"
    )

# ============ FLASK ДЛЯ RENDER ============
from flask import Flask, jsonify
app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({
        "status": "Бот работает!",
        "muted": len(muted_users),
        "warns": len(warn_threshold),
        "echo": len(echo_status)
    })

@app.route('/ping')
def ping():
    return jsonify({"status": "pong", "time": datetime.now().isoformat()})

if __name__ == "__main__":
    print("✅ SWILL Модератор запущен!")
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
