"""
Eldorado.gg Order Monitor -> Telegram Bot
-------------------------------------------
Gmail'dagi Eldorado.gg dan kelgan yangi xabarlarni (yangi buyurtma, xabar va h.k.)
IMAP orqali tekshirib, Telegram botga darhol yuboradi.

Xavfsizlik:
- Barcha maxfiy ma'lumotlar .env faylidan o'qiladi
- GitHub'ga .env fayli yuklanmaydi (.gitignore da belgilan'gan)
"""

import email
import html
import imaplib
import json
import logging
import os
import re
import time
from datetime import datetime
from email.header import decode_header
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

GMAIL_USER = os.getenv("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
SENDER_FILTER = os.getenv("SENDER_FILTER", "eldorado.gg")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "20"))
MAX_EMAILS_TO_CHECK = int(os.getenv("MAX_EMAILS_TO_CHECK", "200"))
SEEN_UIDS_LIMIT = int(os.getenv("SEEN_UIDS_LIMIT", "500"))

BASE_DIR = Path(__file__).parent
SEEN_UIDS_FILE = BASE_DIR / "seen_uids.json"
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(LOGS_DIR / "bot.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


def load_seen_uids():
    if SEEN_UIDS_FILE.exists():
        try:
            with open(SEEN_UIDS_FILE, "r") as f:
                data = json.load(f)
                return set(data)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"UID faylini o'qishda xatolik: {e}")
            return set()
    return set()


def save_seen_uids(uids):
    try:
        with open(SEEN_UIDS_FILE, "w") as f:
            json.dump(list(uids)[-SEEN_UIDS_LIMIT:], f)
    except IOError as e:
        logger.error(f"UID fayliga yozishda xatolik: {e}")


def decode_mime_words(value):
    if not value:
        return ""
    try:
        parts = []
        for part, encoding in decode_header(value):
            if isinstance(part, bytes):
                parts.append(part.decode(encoding or "utf-8", errors="ignore"))
            else:
                parts.append(part)
        return "".join(parts)
    except Exception as e:
        logger.warning(f"Header dekodlashda xatolik: {e}")
        return str(value)


def clean_text(text):
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def get_email_body(msg):
    body = ""
    try:
        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                disposition = str(part.get("Content-Disposition", ""))
                if ctype == "text/plain" and "attachment" not in disposition:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        body = payload.decode(charset, errors="ignore")
                        break
            if not body:
                for part in msg.walk():
                    if part.get_content_type() == "text/html":
                        payload = part.get_payload(decode=True)
                        if payload:
                            charset = part.get_content_charset() or "utf-8"
                            html_text = payload.decode(charset, errors="ignore")
                            body = clean_text(html_text)
                            break
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                body = payload.decode(charset, errors="ignore")
            else:
                body = str(msg.get_payload())
    except Exception as e:
        logger.warning(f"Email tanasini olishda xatolik: {e}")
        body = "[Xabar matnini olishda xatolik yuz berdi]"

    return clean_text(body)[:1500]


def is_eldorado_email(sender, subject, body):
    text = f"{sender} {subject} {body}".lower()
    sender_text = (sender or "").lower()
    eldorado_markers = ["eldorado.gg", "eldorado", "@eldorado", "noreply@eldorado", "no-reply@eldorado"]
    order_markers = [
        "you have a new order",
        "new order",
        "order id",
        "order price",
        "game:",
        "category:",
        "purchase",
        "payment",
    ]

    if any(marker in sender_text for marker in eldorado_markers):
        return True
    if "eldorado" in text and any(marker in text for marker in order_markers):
        return True
    if text.count("order") >= 2 and "eldorado" in text:
        return True
    return False


def extract_order_info(subject, body):
    text = clean_text(body)
    info = {}
    patterns = {
        "Order ID": r"order\s*id\s*[:#-]?\s*([A-Za-z0-9\-]+)",
        "Category": r"category\s*[:#-]?\s*([A-Za-z0-9 _&/.-]+?)(?=(?:game|order|price|$))",
        "Game": r"game\s*[:#-]?\s*([A-Za-z0-9 _&/.-]+?)(?=(?:order|price|category|$))",
        "Order price": r"order\s*price\s*[:#-]?\s*([\d\.,]+\s*(?:USD|EUR|RUB|USDT|GBP|KZT)?)",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            info[key] = match.group(1).strip()
    if not info and subject:
        subject_text = clean_text(subject)
        if re.search(r"order", subject_text, re.IGNORECASE):
            info["Order ID"] = "Not detected"
    return info


def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("Telegram token yoki chat id bo'sh. .env faylini tekshiring.")
        return False

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
            return False
        return True
    except requests.RequestException as e:
        logger.error(f"Telegram'ga yuborishda xatolik: {e}")
        return False


def format_telegram_notification(subject, sender, body, order_info):
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    lines = [
        "🔔 <b>Yangi xabar - Eldorado.gg</b>",
        "",
        f"📌 <b>Mavzu:</b> {subject or 'No subject'}",
        f"📧 <b>Jo'natuvchi:</b> {sender or 'Noma\'lum'}",
    ]

    if order_info:
        lines.append("")
        for key, value in order_info.items():
            emoji = {"Order ID": "🆔", "Category": "📂", "Game": "🎮", "Order price": "💰"}.get(key, "•")
            lines.append(f"{emoji} <b>{key}:</b> {value}")

    lines.append("")
    lines.append(f"📝 <b>Matn:</b> {body[:400]}{'...' if len(body) > 400 else ''}")
    lines.append("")
    lines.append(f"🕐 {now}")
    return "\n".join(lines)


def process_message(mail, mail_id):
    status, msg_data = mail.fetch(mail_id, "(RFC822)")
    if status != "OK":
        return False

    for response_part in msg_data:
        if not isinstance(response_part, tuple):
            continue
        try:
            msg = email.message_from_bytes(response_part[1])
            subject = decode_mime_words(msg.get("Subject", "(mavzusiz)"))
            sender = decode_mime_words(msg.get("From", "(nomalum)"))
            body = get_email_body(msg)

            logger.info(f"Yangi xat: sender={sender}, subject={subject}, body_preview={body[:120]}")

            if not is_eldorado_email(sender, subject, body):
                logger.info(f"Skip: bu Eldorado xati emas. sender={sender}")
                return False

            order_info = extract_order_info(subject, body)
            telegram_text = format_telegram_notification(subject, sender, body, order_info)
            sent = send_telegram_message(telegram_text)
            if sent:
                logger.info(f"Yuborildi: {subject}")
                return True
            logger.error(f"Yuborilmadi: {subject}")
            return False
        except Exception as e:
            logger.error(f"Xatni qayta ishlashda xatolik: {e}")
    return False


def check_inbox_once(seen_uids):
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        mail.select("inbox")
    except Exception as e:
        logger.error(f"Gmail'ga ulanib bo'lmadi: {e}")
        return seen_uids

    try:
        status, messages = mail.search(None, "ALL")
        if status != "OK":
            logger.warning("Qidiruv muvaffaqiyatsiz tugadi.")
            mail.logout()
            return seen_uids

        all_ids = messages[0].split()
        mail_ids = all_ids[-MAX_EMAILS_TO_CHECK:]
        new_uids = set(seen_uids)

        for mail_id in reversed(mail_ids):
            uid_str = mail_id.decode()
            if uid_str in seen_uids:
                continue

            if process_message(mail, mail_id):
                new_uids.add(uid_str)
            else:
                # Bu Eldorado xati bo'lmasa ham kaytadan tekshirishga ruxsat beramiz.
                # Shuning uchun ko'rilgan ro'yxatga qo'shmaymiz.
                pass

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

    if not seen_uids:
        logger.info("Birinchi ishga tushish: mavjud xatlarni belgilab olyapmiz (xabar yubormay)...")
        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            mail.select("inbox")
            status, messages = mail.search(None, "ALL")
            if status == "OK":
                ids = messages[0].split()
                seen_uids = set(m.decode() for m in ids[-MAX_EMAILS_TO_CHECK:])
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
