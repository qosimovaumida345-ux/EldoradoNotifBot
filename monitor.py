"""
Eldorado.gg Order Monitor -> Telegram Bot
-------------------------------------------
Gmail'dagi Eldorado.gg dan kelgan barcha yangi xabarlarni:
- Yangi buyurtmalar (New Orders)
- Xaridor chat xabarlari (Buyer messages via TalkJS)
- Dispute / Shikoyatlar (Order disputes)
- Boshqa muhim hisob bildirishnomalarini
IMAP orqali doimiy tekshirib, darhol Telegram bot orqali batafsil va qulay tugmalar bilan yuboradi.
"""

import email
import html
import imaplib
import json
import logging
import os
import re
import sys

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import time
from datetime import datetime
from email.header import decode_header
from pathlib import Path
from typing import Dict, Any, Optional, Set, Tuple

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
SEEN_UIDS_FILE = BASE_DIR / "seen_uids.json"
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

logger = logging.getLogger("EldoradoMonitor")


def decode_mime_words(value: Any) -> str:
    """Decode MIME encoded email headers safely."""
    if not value:
        return ""
    try:
        parts = []
        for part, encoding in decode_header(str(value)):
            if isinstance(part, bytes):
                parts.append(part.decode(encoding or "utf-8", errors="ignore"))
            else:
                parts.append(str(part))
        return "".join(parts)
    except Exception as e:
        logger.debug(f"Header decoding fallback: {e}")
        return str(value)


def clean_text(text: str) -> str:
    """Clean and normalize HTML/plain text."""
    if not text:
        return ""
    text = html.unescape(text)
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Remove excessive blank lines and whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


class EmailParser:
    """Extracts Eldorado.gg details and links from emails."""

    @staticmethod
    def get_email_content(msg: email.message.Message) -> Tuple[str, str, list]:
        """Extract plain text, html text, and embedded URLs."""
        plain_body = ""
        html_body = ""
        extracted_links = []

        try:
            if msg.is_multipart():
                for part in msg.walk():
                    ctype = part.get_content_type()
                    disposition = str(part.get("Content-Disposition", ""))
                    if "attachment" in disposition:
                        continue

                    payload = part.get_payload(decode=True)
                    if not payload:
                        continue

                    charset = part.get_content_charset() or "utf-8"
                    decoded_part = payload.decode(charset, errors="ignore")

                    if ctype == "text/plain":
                        plain_body += decoded_part + "\n"
                    elif ctype == "text/html":
                        html_body += decoded_part + "\n"
            else:
                payload = msg.get_payload(decode=True)
                if payload:
                    charset = msg.get_content_charset() or "utf-8"
                    decoded_part = payload.decode(charset, errors="ignore")
                    if msg.get_content_type() == "text/html":
                        html_body = decoded_part
                    else:
                        plain_body = decoded_part
        except Exception as e:
            logger.warning(f"Error reading email body parts: {e}")

        # Extract links from HTML and text
        full_raw = plain_body + " " + html_body
        found_urls = re.findall(r'https?://[^\s<>"\')]+', full_raw)
        for url in found_urls:
            cleaned_url = url.rstrip('.,;)]}"')
            if ("eldorado.gg" in cleaned_url or "url6310.eldorado.gg" in cleaned_url) and cleaned_url not in extracted_links:
                extracted_links.append(cleaned_url)

        final_body = clean_text(plain_body) if plain_body else clean_text(html_body)
        return final_body, html_body, extracted_links

    @staticmethod
    def is_eldorado_email(sender: str, subject: str, body: str) -> bool:
        """Accurately check if the email is from Eldorado or buyer chat."""
        sender_lower = (sender or "").lower()
        subject_lower = (subject or "").lower()
        body_lower = (body or "").lower()

        # Eldorado senders & talkjs chat notifications
        if any(marker in sender_lower for marker in [
            "eldorado.gg", "noreply@eldorado", "no-reply@eldorado",
            "@r.talkjs.com", "talkjs.com"
        ]):
            return True

        if "eldorado" in sender_lower or "eldorado" in subject_lower:
            return True

        # Body markers
        if "eldorado.gg" in body_lower or "eldorado" in body_lower:
            if any(term in body_lower for term in [
                "order id", "order:", "game:", "category:", "order price",
                "dispute", "buyer has opened", "view order", "read full conversation"
            ]):
                return True

        return False

    @staticmethod
    def parse_eldorado_data(subject: str, sender: str, body: str, links: list) -> Dict[str, Any]:
        """Parse structured order info, chat details, or dispute notifications."""
        data = {
            "type": "GENERAL",
            "order_id": None,
            "category": None,
            "game": None,
            "price": None,
            "dispute_reason": None,
            "buyer_name": None,
            "chat_message": None,
            "action_url": None,
            "summary": ""
        }

        subj_lower = subject.lower()
        body_clean = clean_text(body)

        # 1. NEW ORDER
        if "new order" in subj_lower or "you have a new order" in body_clean.lower():
            data["type"] = "NEW_ORDER"

        # 2. CHAT MESSAGE (via TalkJS or Eldorado)
        elif "message received from" in subj_lower or "you received a message from" in body_clean.lower():
            data["type"] = "CHAT_MESSAGE"
            # Extract buyer username
            buyer_match = re.search(r"message received from\s+([A-Za-z0-9_\-]+)", subject, re.IGNORECASE)
            if not buyer_match:
                buyer_match = re.search(r"received a message from\s+([A-Za-z0-9_\-]+)", body_clean, re.IGNORECASE)
            if buyer_match:
                data["buyer_name"] = buyer_match.group(1).strip()

            # Extract chat text
            msg_match = re.search(
                r"received a message from\s+[A-Za-z0-9_\-]+:\s*(.*?)(?=\s*Read full conversation|\s*Best wishes|\s*Unsubscribe|$)",
                body_clean, re.DOTALL | re.IGNORECASE
            )
            if msg_match:
                data["chat_message"] = msg_match.group(1).strip()
            data["action_url"] = "https://www.eldorado.gg/dashboard/messages"

        # 3. DISPUTE
        elif "order disputed" in subj_lower or "dispute" in subj_lower or "dispute" in body_clean.lower():
            data["type"] = "DISPUTE"
            reason_match = re.search(r"Dispute reason:\s*([^\n\r]+)", body_clean, re.IGNORECASE)
            if reason_match:
                data["dispute_reason"] = reason_match.group(1).strip()

        # 4. DISPUTE RESOLUTION
        elif "dispute lost" in subj_lower or "dispute won" in subj_lower:
            data["type"] = "DISPUTE_RESOLUTION"

        # 5. VERIFICATION
        elif "verification" in subj_lower:
            data["type"] = "VERIFICATION"

        # Extract Order ID (handles UUID or 'Order: <id>' / 'Order ID: <id>')
        uuid_match = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", body_clean, re.IGNORECASE)
        if uuid_match:
            data["order_id"] = uuid_match.group(0)
        else:
            order_match = re.search(r"Order\s*(?:ID)?\s*:\s*([A-Za-z0-9\-]+)", body_clean, re.IGNORECASE)
            if order_match and order_match.group(1).lower() not in ["page", "price", "disputed", "received", "details"]:
                data["order_id"] = order_match.group(1).strip()

        # Extract Category
        cat_match = re.search(r"Category\s*[:#-]?\s*([A-Za-z0-9 _&/.-]+?)(?=(?:Game|Order|Price|\n|$))", body_clean, re.IGNORECASE)
        if cat_match:
            data["category"] = cat_match.group(1).strip()

        # Extract Game
        game_match = re.search(r"Game\s*[:#-]?\s*([A-Za-z0-9 _&/.-]+?)(?=(?:Order|Price|Category|\n|$))", body_clean, re.IGNORECASE)
        if game_match:
            data["game"] = game_match.group(1).strip()

        # Extract Order Price
        price_match = re.search(r"Order\s*price\s*[:#-]?\s*([\d\.,]+\s*(?:USD|EUR|RUB|USDT|GBP|KZT)?)", body_clean, re.IGNORECASE)
        if price_match:
            data["price"] = price_match.group(1).strip()

        # Find best action URL if not set
        if not data["action_url"]:
            # Prefer 'View order' or order links
            for link in links:
                if "click" in link or "order" in link.lower() or "dashboard" in link.lower():
                    data["action_url"] = link
                    break
            if not data["action_url"] and links:
                data["action_url"] = links[0]

        data["summary"] = body_clean[:500]
        return data


class TelegramNotifier:
    """Sends rich HTML formatted alerts with inline action buttons."""

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

    def send_notification(self, subject: str, sender: str, parsed_data: Dict[str, Any], date_str: str = "") -> bool:
        if not self.bot_token or not self.chat_id:
            logger.error("Telegram bot token or chat ID is missing.")
            return False

        msg_type = parsed_data.get("type", "GENERAL")
        now_str = date_str or datetime.now().strftime("%d.%m.%Y %H:%M:%S")

        # Construct message based on type
        if msg_type == "NEW_ORDER":
            header = "🎉 <b>YANGI BUYURTMA TUSHDI! (NEW ORDER)</b> 🛒"
            lines = [header, ""]
            if parsed_data.get("game"):
                lines.append(f"🎮 <b>O'yin:</b> <code>{html.escape(parsed_data['game'])}</code>")
            if parsed_data.get("category"):
                lines.append(f"📂 <b>Kategoriya:</b> <code>{html.escape(parsed_data['category'])}</code>")
            if parsed_data.get("price"):
                lines.append(f"💰 <b>Narxi:</b> <b>{html.escape(parsed_data['price'])}</b>")
            if parsed_data.get("order_id"):
                lines.append(f"🆔 <b>Order ID:</b> <code>{html.escape(parsed_data['order_id'])}</code>")
            
            lines.append("")
            lines.append("⚡ <i>Xaridorga hisob ma'lumotlarini yetkazib bering yoki Eldorado sahifasida tasdiqlang!</i>")

        elif msg_type == "CHAT_MESSAGE":
            buyer = parsed_data.get("buyer_name", "Xaridor")
            header = "💬 <b>ELDORADO'DAN YANGI XABAR KELDI!</b>"
            lines = [header, ""]
            lines.append(f"👤 <b>Xaridor:</b> <b>{html.escape(buyer)}</b>")
            if parsed_data.get("chat_message"):
                lines.append(f"📝 <b>Xabar matni:</b>\n<blockquote>{html.escape(parsed_data['chat_message'][:300])}</blockquote>")
            else:
                lines.append("📝 <i>Yangi xabar yuborildi. O'qish uchun chatga kiring.</i>")

        elif msg_type == "DISPUTE":
            header = "⚠️ <b>DIQQAT: BUYURTMA BO'YICHA DISPUTE OCHILDI!</b>"
            lines = [header, ""]
            if parsed_data.get("order_id"):
                lines.append(f"🆔 <b>Order ID:</b> <code>{html.escape(parsed_data['order_id'])}</code>")
            if parsed_data.get("game"):
                lines.append(f"🎮 <b>O'yin:</b> {html.escape(parsed_data['game'])}")
            if parsed_data.get("price"):
                lines.append(f"💰 <b>Summa:</b> {html.escape(parsed_data['price'])}")
            if parsed_data.get("dispute_reason"):
                lines.append(f"❗ <b>Sababi:</b> <code>{html.escape(parsed_data['dispute_reason'])}</code>")
            lines.append("")
            lines.append("🚨 <i>Xaridor bilan zudlik bilan bog'lanib, masalani hal qiling!</i>")

        elif msg_type == "DISPUTE_RESOLUTION":
            header = f"⚖️ <b>DISPUTE YAKUNI: {html.escape(subject)}</b>"
            lines = [header, ""]
            if parsed_data.get("order_id"):
                lines.append(f"🆔 <b>Order ID:</b> <code>{html.escape(parsed_data['order_id'])}</code>")
            if parsed_data.get("summary"):
                lines.append(f"ℹ️ {html.escape(parsed_data['summary'][:300])}")

        elif msg_type == "VERIFICATION":
            header = "🔐 <b>ELDORADO: AKKAUNT TASDIQLASH (VERIFICATION)</b>"
            lines = [header, ""]
            lines.append(f"📌 <b>Mavzu:</b> {html.escape(subject)}")
            lines.append(f"ℹ️ {html.escape(parsed_data['summary'][:300])}")

        else:
            header = "🔔 <b>Eldorado.gg Bildirishnomasi</b>"
            lines = [header, ""]
            lines.append(f"📌 <b>Mavzu:</b> {html.escape(subject)}")
            lines.append(f"📧 <b>Jo'natuvchi:</b> {html.escape(sender)}")
            if parsed_data.get("order_id"):
                lines.append(f"🆔 <b>Order ID:</b> <code>{html.escape(parsed_data['order_id'])}</code>")
            if parsed_data.get("summary"):
                lines.append("")
                lines.append(f"📝 <b>Tafsilot:</b> {html.escape(parsed_data['summary'][:300])}")

        lines.append("")
        lines.append(f"🕐 <code>{now_str}</code>")
        text = "\n".join(lines)

        # Build inline button markup
        reply_markup = None
        action_url = parsed_data.get("action_url")
        if action_url:
            button_title = "👉 Buyurtmaga o'tish (View Order)" if msg_type == "NEW_ORDER" else \
                           "💬 Chatni ochish (Open Chat)" if msg_type == "CHAT_MESSAGE" else \
                           "🔗 Sahifani ochish (Open Link)"
            reply_markup = {
                "inline_keyboard": [
                    [{"text": button_title, "url": action_url}]
                ]
            }

        return self._send_raw(text, reply_markup)

    def send_system_message(self, text: str) -> bool:
        """Send simple system notification."""
        return self._send_raw(text)

    def _send_raw(self, text: str, reply_markup: Optional[Dict] = None) -> bool:
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False
        }
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup)

        try:
            res = requests.post(self.api_url, data=payload, timeout=15)
            if res.status_code == 200:
                return True
            else:
                logger.error(f"Telegram API error {res.status_code}: {res.text}")
                # Retry once without reply markup and HTML if formatting failed
                payload["parse_mode"] = ""
                payload.pop("reply_markup", None)
                payload["text"] = re.sub(r"<[^>]+>", "", text)
                fallback_res = requests.post(self.api_url, data=payload, timeout=10)
                return fallback_res.status_code == 200
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False


class EldoradoMonitor:
    """Core monitor engine: Connects via IMAP, inspects emails, triggers alerts."""

    def __init__(self, state: Optional[Dict[str, Any]] = None):
        self.state = state or {}
        self.gmail_user = os.getenv("GMAIL_USER", "").strip()
        self.gmail_pass = os.getenv("GMAIL_APP_PASSWORD", "").strip()
        self.sender_filter = os.getenv("SENDER_FILTER", "eldorado.gg").strip()
        self.check_interval = int(os.getenv("CHECK_INTERVAL_SECONDS", "20"))
        self.max_emails = int(os.getenv("MAX_EMAILS_TO_CHECK", "50"))
        self.seen_limit = int(os.getenv("SEEN_UIDS_LIMIT", "500"))

        self.telegram = TelegramNotifier(
            bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
            chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip()
        )

        self.seen_identifiers: Set[str] = self._load_seen_identifiers()

    def _load_seen_identifiers(self) -> Set[str]:
        """Load seen UIDs / Message IDs from local storage."""
        if SEEN_UIDS_FILE.exists():
            try:
                with open(SEEN_UIDS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return set(data)
            except Exception as e:
                logger.warning(f"Could not load seen_uids.json: {e}")
        return set()

    def _save_seen_identifiers(self):
        """Save seen IDs to file to prevent duplicate alerts."""
        try:
            with open(SEEN_UIDS_FILE, "w", encoding="utf-8") as f:
                # Keep latest seen_limit items
                json.dump(list(self.seen_identifiers)[-self.seen_limit:], f)
        except Exception as e:
            logger.error(f"Error saving seen_uids.json: {e}")

    def _connect_imap(self) -> Optional[imaplib.IMAP4_SSL]:
        """Create an authenticated IMAP SSL connection to Gmail."""
        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=30)
            mail.login(self.gmail_user, self.gmail_pass)
            mail.select("inbox")
            return mail
        except Exception as e:
            logger.error(f"IMAP connection failed ({self.gmail_user}): {e}")
            return None

    def initialize(self):
        """Initial startup: snapshot existing emails or notify startup."""
        logger.info("=" * 60)
        logger.info("🚀 Eldorado.gg Order Monitor -> Telegram Bot ishga tushdi")
        logger.info(f"📧 Gmail: {self.gmail_user}")
        logger.info(f"⏱️ Tekshirish oralig'i: {self.check_interval} soniya")
        logger.info(f"📂 Oldin saqlangan ID lar soni: {len(self.seen_identifiers)}")
        logger.info("=" * 60)

        # If seen_identifiers is empty (first launch or clean container), index existing emails
        if not self.seen_identifiers:
            logger.info("Boshlang'ich sozlash: mavjud eski xatlarni belgilab olyapmiz...")
            mail = self._connect_imap()
            if mail:
                try:
                    status, msgs = mail.uid("search", None, "ALL")
                    if status == "OK" and msgs[0]:
                        uids = msgs[0].split()
                        # Mark existing emails as seen
                        for u in uids[-self.max_emails:]:
                            self.seen_identifiers.add(u.decode("utf-8", errors="ignore"))
                        self._save_seen_identifiers()
                        logger.info(f"{len(self.seen_identifiers)} ta mavjud xat UID belgilandi.")
                    mail.logout()
                except Exception as e:
                    logger.error(f"Boshlang'ich xatlarni o'qishda xatolik: {e}")

        # Send Telegram Bot online startup message
        welcome_text = (
            "✅ <b>Eldorado Monitor Bot ishga tushdi va faol!</b>\n\n"
            f"📧 <b>Kuzatilayotgan Gmail:</b> <code>{html.escape(self.gmail_user)}</code>\n"
            f"⏱️ <b>Tekshirish tezligi:</b> Har {self.check_interval} soniyada\n"
            f"🟢 <b>Status:</b> 100% Live & Tayyor\n\n"
            "Endi Eldorado.gg dagi har bir yangi buyurtma, xaridor xabari yoki dispute haqida darhol shu yerga xabar keladi!"
        )
        self.telegram.send_system_message(welcome_text)

    def process_email_uid(self, mail: imaplib.IMAP4_SSL, uid_bytes: bytes) -> bool:
        """Fetch, parse and send alert for a single email UID."""
        uid_str = uid_bytes.decode("utf-8", errors="ignore")
        
        status, data = mail.uid("fetch", uid_bytes, "(RFC822)")
        if status != "OK" or not data or not data[0]:
            return False

        raw_email = None
        for item in data:
            if isinstance(item, tuple) and len(item) >= 2:
                raw_email = item[1]
                break

        if not raw_email:
            return False

        try:
            msg = email.message_from_bytes(raw_email)
            subject = decode_mime_words(msg.get("Subject", "(Mavzusiz)"))
            sender = decode_mime_words(msg.get("From", "(Noma'lum)"))
            date_header = decode_mime_words(msg.get("Date", ""))
            message_id = decode_mime_words(msg.get("Message-ID", "")).strip()

            # Unique key for tracking
            unique_key = message_id if message_id else f"uid_{uid_str}"

            if unique_key in self.seen_identifiers:
                return False

            body_text, html_text, extracted_links = EmailParser.get_email_content(msg)

            # Check if this email belongs to Eldorado or related buyer chats
            if not EmailParser.is_eldorado_email(sender, subject, body_text):
                # Mark as seen so we don't re-check next time
                self.seen_identifiers.add(unique_key)
                self.seen_identifiers.add(uid_str)
                return False

            logger.info(f"🔔 Yangi Eldorado xati topildi! Mavzu: '{subject}', Jo'natuvchi: '{sender}'")

            # Parse structured data
            parsed_data = EmailParser.parse_eldorado_data(subject, sender, body_text, extracted_links)

            # Send Telegram alert
            sent = self.telegram.send_notification(subject, sender, parsed_data, date_header)
            if sent:
                logger.info(f"✅ Telegramga muvaffaqiyatli yuborildi: {subject}")
                if self.state:
                    self.state["alerts_sent"] = self.state.get("alerts_sent", 0) + 1
            else:
                logger.error(f"❌ Telegramga yuborishda xatolik: {subject}")

            self.seen_identifiers.add(unique_key)
            self.seen_identifiers.add(uid_str)
            return True

        except Exception as e:
            logger.error(f"Xatni qayta ishlashda xatolik (UID {uid_str}): {e}", exc_info=True)
            self.seen_identifiers.add(uid_str)
            return False

    def check_once(self):
        """Execute one polling cycle over Gmail inbox."""
        mail = self._connect_imap()
        if not mail:
            if self.state:
                self.state["last_error"] = "IMAP connection failed"
            return

        try:
            # Search for latest emails
            status, msgs = mail.uid("search", None, "ALL")
            if status == "OK" and msgs[0]:
                all_uids = msgs[0].split()
                # Check recent batch
                recent_uids = all_uids[-self.max_emails:]

                for uid_bytes in recent_uids:
                    uid_str = uid_bytes.decode("utf-8", errors="ignore")
                    if uid_str in self.seen_identifiers:
                        continue

                    self.process_email_uid(mail, uid_bytes)

                self._save_seen_identifiers()

            mail.logout()

            # Update runtime state
            if self.state:
                self.state["last_check"] = datetime.now().isoformat()
                self.state["checks_count"] = self.state.get("checks_count", 0) + 1
                self.state["last_error"] = None

        except Exception as e:
            logger.error(f"Tekshirish jarayonida xatolik: {e}")
            if self.state:
                self.state["last_error"] = str(e)
            try:
                mail.logout()
            except Exception:
                pass

    def start(self):
        """Main loop that continuously monitors inbox."""
        self.initialize()

        while True:
            try:
                self.check_once()
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.critical(f"Asosiy tekshirish siklida xato: {e}", exc_info=True)

            time.sleep(self.check_interval)


def main():
    monitor = EldoradoMonitor()
    monitor.start()


if __name__ == "__main__":
    main()
