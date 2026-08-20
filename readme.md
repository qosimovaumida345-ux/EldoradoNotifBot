# Eldorado.gg → Telegram Monitor Bot

Gmail'ga kelgan Eldorado.gg xabarlarini (yangi buyurtma, xabar va h.k.) darhol Telegram'ga yuboradi.

## 1. O'rnatish

Kompyuteringizda Python 3.8+ o'rnatilgan bo'lishi kerak.

```bash
# 1. Papkaga kiring
cd eldorado_bot

# 2. Kerakli kutubxonani o'rnating
pip install -r requirements.txt
```

## 2. Ishga tushirish

```bash
python monitor.py
```

Bot ishga tushganda:
- Birinchi marta ishga tushganda, mavjud eski xatlarni "ko'rilgan" deb belgilaydi (ularni qayta yubormaslik uchun) va Telegram'ga "Bot ishga tushdi" degan xabar yuboradi.
- Shundan keyin har 20 soniyada Gmail'ni tekshiradi va Eldorado'dan kelgan **yangi** xatni darhol Telegram'ga yuboradi.
- Xat Gmail'da "o'qilmagan" holida qoladi — dasturingiz uni o'qilgan deb belgilamaydi.

To'xtatish uchun: `Ctrl + C`

## 3. 24/7 ishlashi uchun (kompyuter yopilganda ham)

Oddiy `python monitor.py` faqat siz kompyuteringizni ochiq qo'yganingizda ishlaydi. 24/7 tinimsiz ishlashi uchun quyidagi variantlardan birini tanlang:

### Variant A — Bepul VPS (tavsiya etiladi)
Oracle Cloud Free Tier, yoki shunga o'xshash bepul serverga joylashtiring:
1. Serverga ulaning (SSH)
2. Python va kerakli kutubxonalarni o'rnating
3. `screen` yoki `tmux` yordamida fonda ishga tushiring:
   ```bash
   screen -S eldorado_bot
   python3 monitor.py
   # Ctrl+A keyin D bosib screen'dan chiqing (bot ishlashda davom etadi)
   ```
4. Qaytib kirish: `screen -r eldorado_bot`

### Variant B — systemd service (Linux serverida doimiy ishlashi uchun)
`/etc/systemd/system/eldorado-bot.service` fayl yarating:
```ini
[Unit]
Description=Eldorado Telegram Monitor
After=network.target

[Service]
Type=simple
WorkingDirectory=/TO'LIQ/YOL/eldorado_bot
ExecStart=/usr/bin/python3 /TO'LIQ/YOL/eldorado_bot/monitor.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```
Keyin:
```bash
sudo systemctl enable eldorado-bot
sudo systemctl start eldorado-bot
```

## 4. Sozlamalarni o'zgartirish

`monitor.py` faylining boshida quyidagilarni o'zgartirish mumkin:
- `CHECK_INTERVAL_SECONDS` — necha soniyada bir tekshirish (default: 20)
- `SENDER_FILTER` — qaysi jo'natuvchidan kelgan xatlarni kuzatish (default: "eldorado.gg")

## 5. Muhim xavfsizlik eslatmasi

`monitor.py` faylida Gmail App Password va Telegram Bot Token ochiq holda saqlangan.
- Bu faylni **hech kimga yubormang** va GitHub kabi ochiq joyga yuklamang.
- Agar token yoki parol "sizib ketgan" deb o'ylasangiz — Google App Password'ni bekor qilib, yangisini yarating, va Telegram'da @BotFather orqali `/revoke` bilan tokenni yangilang.