"""
Eldorado.gg Order Monitor -> Telegram Bot
-------------------------------------------
Gmail'dagi Eldorado.gg dan kelgan yangi xabarlarni (yangi buyurtma, xabar va h.k.)
IMAP orqali tekshirib, Telegram botga darhol yuboradi.

Ishlash mantig'i:
1. Har N sekundda (default: 20 soniya) Gmail'ga IMAP orqali ulanadi
2. "UNSEEN" (o'qilmagan) va jo'natuvchisi eldorado.gg bo'lgan xatlarni qidiradi
3. Har bir yangi xatni Telegram'ga yuboradi
4. Xatni "o'qilgan" deb belgilamaydi (Gmail'da ham ko'rinib turishi uchun),
   lekin allaqachon yuborilganlarni takror yubormaslik uchun UID'larni saqlaydi

Xavfsizlik:
- Barcha maxfiy ma'lumotlar .env faylidan o'qiladi
- GitHub'ga .env fayli yuklanmaydi (.gitignore da belgilan'gan)
"""

import imaplib
import email
from email.header import decode_header
import time
import re
import json
import os
import logging
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ============== SOZLAMALAR ==============
GMAIL_USER = os.getenv('GMAIL_USER', '')
GMAIL_APP_PASSWORD = os.getenv('GMAIL_APP_PASSWORD', '')
SENDER_FILTER = os.getenv('SENDER_FILTER', 'eldorado.gg')

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')

CHECK_INTERVAL_SECONDS = int(os.getenv('CHECK_INTERVAL_SECONDS', '20'))
MAX_EMAILS_TO_CHECK = int(os.getenv('MAX_EMAILS_TO_CHECK', '50'))
SEEN_UIDS_LIMIT = int(os.getenv('SEEN_UIDS_LIMIT', '500'))

# File paths
BASE_DIR = Path(__file__).parent
SEEN_UIDS_FILE = BASE_DIR / "seen_uids.json"
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOGS_DIR / 'bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ============== YORDAMCHI FUNKSIYALAR ==============

def load_seen_uids():
    """Oldin yuborilgan xatlar UID ro'yxatini fayldan o'qiydi."""
    if SEEN_UIDS_FILE.exists():
        try:
            with open(SEEN_UIDS_FILE, "r") as f:
                return set(json.load(f))
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"UID faylini o'qishda xatolik: {e}")
            return set()
    return set()


def save_seen_uids(uids):
    """Yuborilgan xatlar UID ro'yxatini faylga yozadi (oxirgi N tasini saqlaydi)."""
    try:
        with open(SEEN_UIDS_FILE, "w") as f:
            json.dump(list(uids)[-SEEN_UIDS_LIMIT:], f)
    except IOError as e:
        logger.error(f"UID fayliga yozishda xatolik: {e}")


def decode_mime_words(s):
    """Email sarlavhasidagi kodlangan matnni (masalan =?utf-8?...) o'qiladigan holga o'tkazadi."""
    if not s:
        return ""
    try:
        decoded_parts = decode_header(s)
        result = ""
        for part, encoding in decoded_parts:
            if isinstance(part, bytes):
                result += part.decode(encoding or "utf-8", errors="ignore")
            else:
                result += part
        return result
    except Exception as e:
        logger.warning(f"Sarlavha dekodlashda xatolik: {e}")
        return str(s)


def get_email_body(msg):
    """Email xabarining matn qismini (plain text) ajratib oladi."""
    body = ""
    try:
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))
                if content_type == "text/plain" and "attachment" not in content_disposition:
                    try:
                        charset = part.get_content_charset() or "utf-8"
                        body = part.get_payload(decode=True).decode(charset, errors="ignore")
                        break
                    except Exception:
                        continue
            # Agar plain text topilmasa, HTML'dan tozalab olishga harakat qilamiz
            if not body:
                for part in msg.walk():
                    if part.get_content_type() == "text/html":
                        try:
                            charset = part.get_content_charset() or "utf-8"
                            html = part.get_payload(decode=True).decode(charset, errors="ignore")
                            body = re.sub("<[^<]+?>", " ", html)
                            break
                        except Exception:
                            continue
        else:
            try:
                charset = msg.get_content_charset() or "utf-8"
                body = msg.get_payload(decode=True).decode(charset, errors="ignore")
            except Exception:
                body = str(msg.get_payload())
    except Exception as e:
        logger.warning(f"Email tanasini olishda xatolik: {e}")
        body = "[Xabar matnini olishda xatolik yuzberdi]"

    body = re.sub(r"\s+", " ", body).strip()
    return body[:800]  # juda uzun bo'lmasin


def extract_order_info(subject, body):
    """
    Eldorado xatidan asosiy ma'lumotlarni (Order ID, Category, Game, Price)
    ajratib olishga harakat qiladi. Topilmasa, oddiy xulosa qaytaradi.
    """
    info = {}
    patterns = {
        "Order ID": r"Order ID:?\s*([a-zA-Z0-9\-]+)",
        "Category": r"Category:?\s*([A-Za-z ]+?)(?:Game|Order|$)",
        "Game": r"Game:?\s*([A-Za-z0-9 ]+?)(?:Order price|Order|$)",
        "Order price": r"Order price:?\s*([\d\.,]+\s*[A-Z]{3})",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, body, re.IGNORECASE)
        if match:
            info[key] = match.group(1).strip()

    return info


def send_telegram_message(text):
    """Telegram botga xabar yuboradi."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        response = requests.post(url, data=payload, timeout=15)
        if response.status_code != 200:
            logger.error(f"Telegram javobi: {response.status_code} - {response.text}")
        return response.status_code == 200
    except requests.RequestException as e:
        logger.error(f"Telegram'ga yuborishda xatolik: {e}")
        return False


def format_telegram_notification(subject, sender, body, order_info):
    """Telegram uchun chiroyli formatlangan xabar tayyorlaydi."""
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")

    lines = [
        "🔔 <b>Yangi xabar - Eldorado.gg</b>",
        "",
        f"📌 <b>Mavzu:</b> {subject}",
    ]

    if order_info:
        lines.append("")
        for key, value in order_info.items():
            emoji = {
                "Order ID": "🆔",
                "Category": "📂",
                "Game": "🎮",
                "Order price": "💰",
            }.get(key, "•")
            lines.append(f"{emoji} <b>{key}:</b> {value}")

    lines.append("")
    lines.append(f"📝 <b>Matn:</b> {body[:400]}{'...' if len(body) > 400 else ''}")
    lines.append("")
    lines.append(f"🕐 {now}")

    return "\n".join(lines)


# ============== ASOSIY MANTIQ ==============

def check_inbox_once(seen_uids):
    """Bitta marta Gmail'ni tekshiradi va yangi Eldorado xatlarini Telegram'ga yuboradi."""
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        mail.select("inbox")
    except imaplib.IMAP4.error as e:
        logger.error(f"Gmail'ga ulanib bo'lmadi: {e}")
        return seen_uids
    except Exception as e:
        logger.error(f"Kutilmagan ulanish xatosi: {e}")
        return seen_uids

    try:
        # Eldorado'dan kelgan barcha xatlarni qidiramiz (oxirgi N tasini tekshiramiz)
        status, messages = mail.search(None, f'(FROM "{SENDER_FILTER}")')
        if status != "OK":
            logger.warning("Qidiruv muvaffaqiyatsiz tugadi.")
            mail.logout()
            return seen_uids

        mail_ids = messages[0].split()
        # Faqat oxirgi N tasini tekshiramiz (tezlik uchun)
        mail_ids = mail_ids[-MAX_EMAILS_TO_CHECK:]

        new_uids = set(seen_uids)

        for mail_id in mail_ids:
            uid_str = mail_id.decode()
            if uid_str in seen_uids:
                continue  # allaqachon ko'rilgan va yuborilgan

            status, msg_data = mail.fetch(mail_id, "(RFC822)")
            if status != "OK":
                continue

            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    try:
                        msg = email.message_from_bytes(response_part[1])
                        subject = decode_mime_words(msg.get("Subject", "(mavzusiz)"))
                        sender = decode_mime_words(msg.get("From", "(nomalum)"))
                        body = get_email_body(msg)
                        order_info = extract_order_info(subject, body)

                        text = format_telegram_notification(subject, sender, body, order_info)
                        sent = send_telegram_message(text)

                        if sent:
                            logger.info(f"Yuborildi: {subject}")
                        else:
                            logger.error(f"Yuborilmadi: {subject}")
                    except Exception as e:
                        logger.error(f"Xatni qayta ishlashda xatolik: {e}")

            new_uids.add(uid_str)

        mail.logout()
        return new_uids

    except Exception as e:
        logger.error(f"Tekshirish jarayonida xatolik: {e}")
        try:
            mail.logout()
        except Exception:
            pass
        return seen_uids


def main():
    if not all([GMAIL_USER, GMAIL_APP_PASSWORD, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID]):
        logger.error("Kerakli sozlamalar topilmadi! .env faylini tekshiring.")
        logger.error("Kerakli: GMAIL_USER, GMAIL_APP_PASSWORD, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID")
        return

    logger.info("=" * 50)
    logger.info("Eldorado.gg -> Telegram Monitor ishga tushdi")
    logger.info(f"Gmail: {GMAIL_USER}")
    logger.info(f"Tekshirish oralig'i: {CHECK_INTERVAL_SECONDS} soniya")
    logger.info("=" * 50)

    seen_uids = load_seen_uids()
    logger.info(f"Oldin ko'rilgan xatlar soni: {len(seen_uids)}")

    # Ishga tushganda birinchi tekshiruv - eski xatlarni "ko'rilgan" deb belgilash uchun
    # (bot ishga tushganda eski xatlarni qayta yubormasligi uchun)
    if not seen_uids:
        logger.info("Birinchi ishga tushish: mavjud xatlarni belgilab olyapmiz (xabar yubormay)...")
        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            mail.select("inbox")
            status, messages = mail.search(None, f'(FROM "{SENDER_FILTER}")')
            if status == "OK":
                mail_ids = messages[0].split()
                seen_uids = set(m.decode() for m in mail_ids)
                save_seen_uids(seen_uids)
                logger.info(f"{len(seen_uids)} ta eski xat belgilandi.")
            mail.logout()
        except Exception as e:
            logger.error(f"Boshlang'ich belgilashda xatolik: {e}")

        send_telegram_message(
            "✅ <b>Bot ishga tushdi!</b>\n\nEndi Eldorado.gg dan kelgan har bir yangi xabar/buyurtma haqida darhol shu yerga xabar beraman."
        )

    while True:
        try:
            seen_uids = check_inbox_once(seen_uids)
            save_seen_uids(seen_uids)
        except KeyboardInterrupt:
            logger.info("Bot to'xtatildi.")
            break
        except Exception as e:
            logger.error(f"Asosiy siklda kutilmagan xato: {e}")

        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()