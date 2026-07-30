# AI News Bot — o'zbek tilida avtomatik AI yangiliklar kanali

Bu loyiha RSS manbalaridan AI yangiliklarini o'qib, o'zbek tiliga tarjima
qilib, Telegram kanalingizga avtomatik joylab boradi. To'liq bepul —
server kerak emas, hammasi GitHub Actions orqali ishlaydi.

## 1-qadam: Telegram bot yaratish

1. Telegram'da **@BotFather** ga yozing
2. `/newbot` buyrug'ini yuboring, botga nom va username bering
3. Sizga beriladigan **token**ni saqlab qo'ying (masalan `123456:ABC-DEF...`)

## 2-qadam: Telegram kanal yaratish

1. Telegram'da yangi kanal yarating (ochiq yoki yopiq — farqi yo'q)
2. Yaratgan botingizni kanalga **administrator** qilib qo'shing
   (kamida "Post messages" ruxsati bo'lishi kerak)
3. Kanal ID'sini aniqlash:
   - Agar kanal public bo'lsa: `@kanal_username` shaklida ishlatavering
   - Agar private bo'lsa: kanalga bir marta biror xabar joylab,
     `https://api.telegram.org/bot<TOKEN>/getUpdates` sahifasini ochib,
     u yerdan `"chat":{"id": -100...}` raqamini toping

## 3-qadam: GitHub repo yaratish

1. GitHub'da yangi **repository** yarating (public yoki private, farqi yo'q)
2. Ushbu papkadagi barcha fayllarni (`bot.py`, `requirements.txt`,
   `seen.json`, `.github/workflows/post.yml`, `README.md`) shu repo'ga
   yuklang

## 4-qadam: Maxfiy kalitlarni (Secrets) qo'shish

Repo sahifasida: **Settings → Secrets and variables → Actions → New repository secret**

Ikkita secret qo'shing:

| Nomi | Qiymati |
|---|---|
| `TELEGRAM_BOT_TOKEN` | BotFather bergan token |
| `TELEGRAM_CHAT_ID` | Kanal username (`@kanal_username`) yoki ID (`-100...`) |

## 5-qadam: Ishga tushirish

- Workflow avtomatik ravishda **har 30 daqiqada** ishga tushadi
- Qo'lda sinab ko'rish uchun: repo'da **Actions** bo'limiga o'ting →
  "AI News Bot" → **Run workflow**

## Sozlash

`bot.py` faylining boshida quyidagilarni o'zgartirishingiz mumkin:

- **`RSS_FEEDS`** — kuzatiladigan sayt manbalari ro'yxati
- **`KEYWORDS`** — qaysi kalit so'zlar bo'yicha maqola tanlansin
- **`MAX_POSTS_PER_RUN`** — bir ishga tushishda nechta post joylansin
  (spam bo'lmasligi uchun kam sonda qoldiring, masalan 2-3)

## Muhim eslatmalar

- Tarjima **deep-translator** (Google Translate) orqali bepul amalga
  oshadi, lekin ba'zan aniqlik cheklangan bo'lishi mumkin — vaqti-vaqti
  bilan tekshirib turing
- Har bir post faqat qisqa xulosa + manba havolasini o'z ichiga oladi,
  to'liq maqola matni ko'chirilmaydi (mualliflik huquqini hurmat qilish
  uchun)
- Agar biror RSS manba ishlamay qolsa (sayt formatini o'zgartirsa),
  konsol logida xato ko'rinadi — o'sha manbani ro'yxatdan olib tashlashingiz
  yoki yangilashingiz kerak bo'ladi
