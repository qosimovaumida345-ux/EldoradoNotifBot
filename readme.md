# ⚡ Eldorado.gg -> Telegram Order & Message Monitor Bot

Gmail pochtangizga Eldorado.gg dan kelgan barcha:
- 🛒 **Yangi buyurtmalar (New Orders)**
- 💬 **Xaridor chat xabarlari (Buyer Messages - TalkJS)**
- ⚠️ **Buyurtma bo'yicha dispute/shikoyatlar (Disputes)**
- ⚖️ **Dispute yakunlari (Dispute Won / Lost)**
- 🔐 **Akkaunt tasdiqlash bildirishnomalari**

kabilarni IMAP orqali har 20 soniyada tekshirib, darhol Telegram botingizga chiroyli va qulay tugmalar bilan yuboradi.

---

## 🚀 Xususiyatlari

1. **Render.com Web Service bilan 100% mos:**
   - O'rnatilgan HTTP Health Check serveri (`/health`, `/`) orqali Render portini darhol ulaydi (`Build successful` -> `Live`).
   - Hech qanday "Port scan timeout" yoki deploy error bermaydi.
2. **Kengaytirilgan xat tahlili:**
   - O'yin nomi (Game), Kategoriya (Category), Buyurtma narxi (Price), Order ID (UUID) va to'g'ridan-to'g'ri buyurtma havolasini avtomatik ajratib oladi.
   - Xaridor yuborgan chat xabarlarini aniqlaydi va ko'rsatadi.
3. **Telegram Inline Tugmalar:**
   - Xabar tagida to'g'ridan-to'g'ri `[👉 Buyurtmaga o'tish]` yoki `[💬 Chatni ochish]` tugmasi bo'ladi.
4. **Takrorlanishdan himoya (Deduplication):**
   - Ko'rilgan xatlar ID lari xotirada saqlanadi, bitta xabar ikki marta yuborilmaydi.
5. **Avtomatik qayta ulanish:**
   - Internet uzilishi yoki Gmail IMAP uzilishida bot o'chib qolmaydi, avtomatik qayta ulanadi.

---

## ⚙️ Sozlash (Environment Variables)

Render.com da `Environment` bo'limiga yoki mahalliy `.env` faylga quyidagi o'zgaruvchilarni kiriting:

| O'zgaruvchi | Tavsif | Misol |
|---|---|---|
| `GMAIL_USER` | Gmail pochtangiz manzili | `misol@gmail.com` |
| `GMAIL_APP_PASSWORD` | Google Hisobingizdagi 16 xonali Ilova Paroli (App Password) | `xxxx xxxx xxxx xxxx` |
| `TELEGRAM_BOT_TOKEN` | @BotFather dan olingan bot tokeni | `123456789:ABCdef...` |
| `TELEGRAM_CHAT_ID` | Botingiz sizga yozishi uchun Telegram Chat ID | `123456789` |
| `CHECK_INTERVAL_SECONDS` | Har necha soniyada tekshirish | `20` |
| `MAX_EMAILS_TO_CHECK` | Har safar tekshiriladigan oxirgi xatlar soni | `50` |
| `PORT` | Render.com porti (Render avtomatik beradi) | `10000` |

---

## 🌐 Render.com ga Deploy qilish

1. GitHub dagi ushbu omborni Render.com bilan ulang:
   - **Type:** `Web Service`
   - **Name:** `EldoradoNotifBot`
   - **Runtime:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python app.py`
2. **Environment Variables** bo'limida `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` qiymatlarini kiriting.
3. **Save & Deploy** tugmasini bosing.
4. Bot darhol ishga tushadi va Telegramingizga `✅ Eldorado Monitor Bot ishga tushdi va faol!` deb xabar jo'natadi.

---

## 💻 Mahalliy (Kompyuterda) ishga tushirish

```bash
# 1. Kutubxonalarni o'rnating
pip install -r requirements.txt

# 2. .env faylini to'ldiring
cp .env.example .env

# 3. Ishga tushiring
python app.py
```