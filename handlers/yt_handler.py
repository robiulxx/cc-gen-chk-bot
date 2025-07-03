import os
import re
import requests
import subprocess
from telebot import TeleBot
from telebot.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery
)

# === APIs ===
SEARCH_API = "https://smartytdl.vercel.app/search?q="
DOWNLOAD_API = "https://smartytdl.vercel.app/dl?url="

# === Store user-specific data ===
user_search_results = {}
user_sent_messages = {}

def download_file(url, filename, bot=None, chat_id=None):
    try:
        with requests.get(url, stream=True, timeout=15) as r:
            r.raise_for_status()
            os.makedirs(os.path.dirname(filename), exist_ok=True)
            with open(filename, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        if bot and chat_id:
                            bot.send_chat_action(chat_id, 'upload_document')
        return True
    except Exception as e:
        print(f"[!] Direct download failed: {e}")
        return False

def fallback_ytdlp(link, filename, audio=False):
    try:
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        format_str = 'bestaudio[ext=m4a]' if audio else '18'
        cmd = [
            "yt-dlp",
            "-f", format_str,
            "-o", filename,
            link
        ]
        subprocess.run(cmd, check=True)
        return True
    except Exception as e:
        print(f"[!] yt-dlp fallback failed: {e}")
        return False

# === Bot Command Register ===
def register(bot: TeleBot):

    @bot.message_handler(commands=["yt"])
    def yt_command(message: Message):
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            bot.reply_to(message, "দয়া করে ইউটিউব সার্চ করার জন্য কিছু লিখুন।\nUsage: /yt <search>")
            return

        query = args[1].strip()

        # ===== Direct YouTube link handling =====
        if "youtu" in query:
            try:
                res = requests.get(DOWNLOAD_API + query)
                data = res.json()

                if not data.get("success") or not data.get("title"):
                    bot.reply_to(message, "❌ ভিডিও ডেটা আনতে সমস্যা হয়েছে।")
                    return

                title = re.sub(r'[\\/:*?"<>|]', '', data["title"])
                thumb = data.get("thumbnail")
                duration = data.get("duration", "Unknown")
                caption = f"🕒 {duration}\n{title}"

                # Store as search result so callback works
                user_search_results[message.chat.id] = [{
                    "title": title,
                    "imageUrl": thumb,
                    "duration": duration,
                    "link": query
                }]

                markup = InlineKeyboardMarkup()
                markup.add(
                    InlineKeyboardButton("🎵 অডিও", callback_data=f"download_0_audio"),
                    InlineKeyboardButton("🎬 ভিডিও", callback_data=f"download_0_video")
                )

                sent_msg = bot.send_photo(message.chat.id, photo=thumb, caption=caption, reply_markup=markup)
                user_sent_messages[message.chat.id] = [sent_msg.message_id]

            except Exception as e:
                print(f"[YT LINK ERROR] {e}")
                bot.reply_to(message, "❌ ভিডিও প্রসেস করতে সমস্যা হয়েছে।")
            return

        # ======= Search mode (normal) =======
        try:
            resp = requests.get(SEARCH_API + query)
            data = resp.json()

            if "result" not in data or not data["result"]:
                bot.reply_to(message, "❌ কোনো রেজাল্ট পাওয়া যায়নি।")
                return

            results = data["result"][:10]
            user_search_results[message.chat.id] = results

            msg_text = "🔍 সার্চ রেজাল্ট:\n\n"
            for i, video in enumerate(results):
                title = re.sub(r'[\\/:*?"<>|]', '', video["title"])
                duration = video.get("duration", "Unknown")
                msg_text += f"[{i+1}] 🕒 {duration} | 🎵 {title}\n"

            markup = InlineKeyboardMarkup(row_width=5)
            buttons = [InlineKeyboardButton(str(i+1), callback_data=f"select_{i}") for i in range(len(results))]
            markup.add(*buttons)
            bot.send_message(message.chat.id, msg_text, reply_markup=markup)

        except Exception as e:
            print(f"[SEARCH ERROR] {e}")
            bot.reply_to(message, "❌ সার্চ করতে সমস্যা হয়েছে।")


    @bot.callback_query_handler(func=lambda call: call.data.startswith("select_"))
    def handle_select(call: CallbackQuery):
        idx = int(call.data.split("_")[1])
        chat_id = call.message.chat.id

        if chat_id not in user_search_results:
            bot.answer_callback_query(call.id, "Session expired. Please search again.")
            return

        video = user_search_results[chat_id][idx]
        title = re.sub(r'[\\/:*?"<>|]', '', video["title"])
        duration = video.get("duration", "Unknown")
        thumb_url = video.get("imageUrl")

        caption = f"🕒 {duration}\n{title}"
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("🎵 অডিও", callback_data=f"download_{idx}_audio"),
            InlineKeyboardButton("🎬 ভিডিও", callback_data=f"download_{idx}_video")
        )

        sent_msg = bot.send_photo(chat_id, photo=thumb_url, caption=caption, reply_markup=markup)

        if chat_id not in user_sent_messages:
            user_sent_messages[chat_id] = []
        user_sent_messages[chat_id].append(sent_msg.message_id)

        bot.answer_callback_query(call.id)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("download_"))
    def handle_download(call: CallbackQuery):
        parts = call.data.split("_")
        idx = int(parts[1])
        choice = parts[2]
        chat_id = call.message.chat.id

        if chat_id not in user_search_results:
            bot.answer_callback_query(call.id, "Session expired. Please search again.")
            return

        for msg_id in user_sent_messages.get(chat_id, []):
            try:
                bot.delete_message(chat_id, msg_id)
            except:
                pass
        user_sent_messages[chat_id] = []

        video = user_search_results[chat_id][idx]
        title = re.sub(r'[\\/:*?"<>|]', '', video["title"])
        link = video["link"]
        ext = "mp4" if choice == "video" else "m4a"
        filename = f"downloads/{title}.{ext}"

        wait_msg = bot.send_message(chat_id, f"📥 '{title}' ডাউনলোড হচ্ছে... অপেক্ষা করুন")

        try:
            res = requests.get(DOWNLOAD_API + link)
            ddata = res.json()

            if ddata.get("success"):
                medias = ddata.get("medias", [])
                media_url = None

                if choice == "audio":
                    for media in medias:
                        if media.get("type") == "audio":
                            media_url = media.get("url")
                            break
                else:
                    # Primary: video with audio and mp4
                    for media in medias:
                        if (
                            media.get("type") == "video"
                            and media.get("has_audio") == True
                            and media.get("extension") == "mp4"
                        ):
                            media_url = media.get("url")
                            break
                    # Fallback: any video with audio
                    if not media_url:
                        for media in medias:
                            if media.get("type") == "video" and media.get("has_audio") == True:
                                media_url = media.get("url")
                                break

                if media_url:
                    success = download_file(media_url, filename, bot, chat_id)
                    if not success:
                        raise Exception("Direct download failed")
                else:
                    raise Exception("No valid media URL found")
            else:
                raise Exception("API failed")

        except Exception as e:
            print(f"[x] Direct method failed: {e}")
            fallback_ytdlp(link, filename, audio=(choice == "audio"))

        try:
            with open(filename, "rb") as f:
                if choice == "audio":
                    bot.send_audio(chat_id, f, caption=f"\n{title}")
                else:
                    bot.send_video(chat_id, f, caption=f"\n{title}")
            bot.delete_message(chat_id, wait_msg.message_id)
        except Exception as e:
            bot.send_message(chat_id, f"❌ ফাইল পাঠাতে সমস্যা হয়েছে:\n{str(e)}")
        finally:
            if os.path.exists(filename):
                os.remove(filename)
