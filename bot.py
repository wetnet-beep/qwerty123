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

# Хранилище
user_warns = {}
muted_users = {}
warn_threshold = {}
mute_timers = {}

def parse_mute_time(time_str):
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

def mute_user(user_id, duration):
    muted_users[user_id] = (datetime.now() + duration)
    timer = threading.Timer(duration.total_seconds(), unmute_user, args=[user_id])
    timer.daemon = True
    timer.start()
    mute_timers[user_id] = timer

def unmute_user(user_id):
    if user_id in muted_users:
        del muted_users[user_id]

@bot.business_message_handler(func=lambda message: True)
def handle_message(message):
    user_id = message.chat.id
    text = message.text or ""
    
    # Проверка мута
    if user_id in muted_users:
        mute_end = muted_users[user_id]
        if datetime.now() < mute_end:
            try:
                bot.delete_business_messages(
                    business_connection_id=message.business_connection_id,
                    message_ids=[message.message_id]
                )
            except:
                pass
            
            time_left = (mute_end - datetime.now()).total_seconds()
            if time_left > 3600:
                time_str = f"{int(time_left/3600)} часов"
            elif time_left > 60:
                time_str = f"{int(time_left/60)} минут"
            else:
                time_str = f"{int(time_left)} секунд"
            
            try:
                bot.send_message(
                    chat_id=user_id,
                    business_connection_id=message.business_connection_id,
                    text=f"🔇 Помолчи, а то устал писать)\n⏳ Время до конца мута: {time_str}"
                )
            except:
                pass
            return
    
    # .mute команда
    if text.startswith('.mute'):
        parts = text.split()
        if len(parts) >= 2:
            duration = parse_mute_time(parts[1])
            if duration:
                mute_user(user_id, duration)
                bot.send_message(
                    chat_id=user_id,
                    business_connection_id=message.business_connection_id,
                    text=f"🔇 Вы замьючены на {parts[1]}"
                )
            else:
                bot.send_message(
                    chat_id=user_id,
                    business_connection_id=message.business_connection_id,
                    text="❌ Используй: .mute 1m / 1h / 1d"
                )
        return
    
    # .warn команда
    if text.startswith('.warn'):
        parts = text.split()
        if len(parts) >= 2:
            try:
                threshold = int(parts[1])
                warn_threshold[user_id] = threshold
                user_warns[user_id] = 0
                bot.send_message(
                    chat_id=user_id,
                    business_connection_id=message.business_connection_id,
                    text=f"⚠️ Порог предупреждений: {threshold}"
                )
            except:
                bot.send_message(
                    chat_id=user_id,
                    business_connection_id=message.business_connection_id,
                    text="❌ Введите число: .warn 3"
                )
        return
    
    # .check команда
    if text.startswith('.check'):
        if user_id in muted_users:
            mute_end = muted_users[user_id]
            time_left = (mute_end - datetime.now()).total_seconds()
            if time_left > 3600:
                time_str = f"{int(time_left/3600)} часов"
            elif time_left > 60:
                time_str = f"{int(time_left/60)} минут"
            else:
                time_str = f"{int(time_left)} секунд"
            bot.send_message(
                chat_id=user_id,
                business_connection_id=message.business_connection_id,
                text=f"🔇 Замьючен\n⏳ Осталось: {time_str}"
            )
        else:
            bot.send_message(
                chat_id=user_id,
                business_connection_id=message.business_connection_id,
                text="✅ Не замьючен"
            )
        return
    
    # Логика предупреждений
    if user_id in warn_threshold:
        threshold = warn_threshold[user_id]
        user_warns[user_id] = user_warns.get(user_id, 0) + 1
        
        if user_warns[user_id] >= threshold:
            mute_user(user_id, timedelta(hours=1))
            user_warns[user_id] = 0
            bot.send_message(
                chat_id=user_id,
                business_connection_id=message.business_connection_id,
                text="🔇 Автоматический мут на 1 час (превышен порог)"
            )
            return
        
        left = threshold - user_warns[user_id]
        word = "сообщений" if left > 1 else "сообщение"
        bot.send_message(
            chat_id=user_id,
            business_connection_id=message.business_connection_id,
            text=f"⚠️ До мута {left} {word}"
        )
    
    # Обычный ответ
    bot.send_message(
        chat_id=user_id,
        business_connection_id=message.business_connection_id,
        text="Привет! Как дела?"
    )

print("✅ SWILL Модератор запущен!")
while True:
    try:
        bot.infinity_polling(timeout=60)
    except:
        time.sleep(5)
