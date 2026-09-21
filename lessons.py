"""
AI darsliklarini avtomatik joylovchi Telegram bot.

Ishlash mantig'i:
1. `topics.json` faylida "SUN'IY INTELLEKT: 0 DAN BOSHLAB" kursining barcha
   mavzulari tepadan pastga qarab tartib bilan turadi (1-modul -> 15-modul).
2. `lesson_progress.json` faylida "hozir nechinchi mavzuda turibmiz" degan
   raqam (index) saqlanadi.
3. Har ishga tushganda faqat BITTA keyingi mavzu olinadi (index bo'yicha),
   avval o'tilgan mavzular qayta tashlanmaydi.
4. Gemini API'ga o'sha mavzu bo'yicha to'liq, tushunarli dars matni
   (o'zbek tilida) yozib berish so'raladi.
5. Tayyor dars matni + mavzuga mos rasm Telegram kanaliga joylanadi.
6. Muvaffaqiyatli joylansa, index birga oshiriladi va lesson_progress.json'ga
   yoziladi (keyingi safar navbatdagi mavzu olinadi).
7. Barcha mavzular tugagach, LOOP_LESSONS=true qilib qo'yilsa, kurs
   boshidan qaytadan boshlanadi; aks holda bot to'xtaydi.

Kuniga 4 marta GitHub Actions orqali avtomatik ishga tushadi:
08:00, 12:00, 16:00, 20:00 (Toshkent vaqti, UTC+5).
"""

import json
import os
import time
from pathlib import Path

import requests

# ---------- SOZLAMALAR ----------

TOPICS_FILE = Path(__file__).parent / "topics.json"
PROGRESS_FILE = Path(__file__).parent / "lesson_progress.json"
LOOP_LESSONS = os.environ.get("LOOP_LESSONS", "false").lower() == "true"
CHANNEL_LINK = "https://t.me/aiyangiliklaruz"

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")
GEMINI_FALLBACK_MODELS = [
    m for m in ["gemini-3.1-flash-lite", "gemini-flash-latest", "gemini-pro-latest"]
    if m != GEMINI_MODEL
]
GEMINI_MAX_RETRIES = 3
GEMINI_RETRY_DELAY_SEC = 20
TELEGRAM_MAX_CHARS = 1000  # sendPhoto caption uchun limit

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# ---------- MAVZUGA MOS RASM URL'LARI ----------
# Har bir kalit so'z bo'yicha Unsplash'dan bepul rasmlar (Creative Commons)
# Rasm URL'lari ochiq va litsenziyasiz (Unsplash free license)
MODULE_IMAGES = {
    "default": "https://images.unsplash.com/photo-1677442135703-1787eea5ce01?w=800&q=80",
    "neyron": "https://images.unsplash.com/photo-1620712943543-bcc4688e7485?w=800&q=80",
    "machine learning": "https://images.unsplash.com/photo-1555949963-ff9fe0c870eb?w=800&q=80",
    "deep learning": "https://images.unsplash.com/photo-1488229297570-58520851e868?w=800&q=80",
    "chatgpt": "https://images.unsplash.com/photo-1676272747765-9d06697e41b0?w=800&q=80",
    "robototexnika": "https://images.unsplash.com/photo-1485827404703-89b55fcc595e?w=800&q=80",
    "robot": "https://images.unsplash.com/photo-1485827404703-89b55fcc595e?w=800&q=80",
    "kompyuter": "https://images.unsplash.com/photo-1518770660439-4636190af475?w=800&q=80",
    "tarix": "https://images.unsplash.com/photo-1461360370896-922624d12aa1?w=800&q=80",
    "algoritm": "https://images.unsplash.com/photo-1509228468518-180dd4864904?w=800&q=80",
    "ma'lumot": "https://images.unsplash.com/photo-1551288049-bebda4e38f71?w=800&q=80",
    "dasturlash": "https://images.unsplash.com/photo-1461749280684-dccba630e2f6?w=800&q=80",
    "til": "https://images.unsplash.com/photo-1546410531-bb4caa6b424d?w=800&q=80",
    "rasm": "https://images.unsplash.com/photo-1574861573-2e0ecc6eb3a7?w=800&q=80",
    "ovoz": "https://images.unsplash.com/photo-1508700115892-45ecd05ae2ad?w=800&q=80",
    "etika": "https://images.unsplash.com/photo-1589829545856-d10d557cf95f?w=800&q=80",
    "kelajak": "https://images.unsplash.com/photo-1485827404703-89b55fcc595e?w=800&q=80",
    "sun'iy intellekt": "https://images.unsplash.com/photo-1677442135703-1787eea5ce01?w=800&q=80",
    "ai": "https://images.unsplash.com/photo-1677442135703-1787eea5ce01?w=800&q=80",
}


def get_image_url(module: str, topic: str) -> str:
    """Modul va mavzu nomiga qarab mos rasm URL'ini qaytaradi."""
    combined = f"{module} {topic}".lower()
    for keyword, url in MODULE_IMAGES.items():
        if keyword in combined:
            return url
    return MODULE_IMAGES["default"]


# ---------- YORDAMCHI FUNKSIYALAR ----------


def load_topics() -> list[dict]:
    return json.loads(TOPICS_FILE.read_text(encoding="utf-8"))


def load_progress() -> int:
    if PROGRESS_FILE.exists():
        data = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        return int(data.get("index", 0))
    return 0


def save_progress(index: int) -> None:
    PROGRESS_FILE.write_text(
        json.dumps({"index": index}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_gemini_prompt(module: str, topic: str, lesson_no: int, total: int) -> str:
    return f"""Sen tajribali sun'iy intellekt (AI) o'qituvchisisan. O'zbek tilida,
"SUN'IY INTELLEKT: 0 DAN BOSHLAB" kursi uchun bitta to'liq dars matni yoz.

Kurs bo'limi: {module}
Bugungi mavzu: {topic}
(Bu kursning {lesson_no}-darsi, jami {total} ta dars bor)

Talablar:
- Mavzuni hech narsa bilmaydigan 10 yoshli bolaga tushuntirgandek yoz —
  juda sodda, jonli, qiziqarli tarzda. O'quvchi o'qib bo'lgach "voy, shunday
  ekan-da!" deb hayratlanishi kerak
- Quyidagi tuzilishda yoz:
  1) Kirish — o'quvchini qiziqtiradigan savol yoki hayotiy holat bilan boshlang
     (2-3 gap, mavzuni nima uchun o'rganish kerakligini his ettirsin)
  2) Asosiy tushuntirish — tushunchani oddiy so'zlar va ko'plab jonli
     misollar orqali batafsil ochib ber. Qiyoslar, metaforalar ishlatavering
  3) Kamida 2-3 ta real hayotiy yoki kulgili amaliy misol keltir
  4) "Esda tuting" — 3-4 ta muhim xulosani aniq va qisqa qilib yoz
  5) Mustaqil mashq — o'quvchi hoziroq sinab ko'rishi mumkin bo'lgan
     1 ta kichik, qiziqarli topshiriq
- Faqat quyidagi oddiy HTML teglaridan foydalan: <b>qalin</b>, <i>qiyshiq</i>.
  Boshqa teg ishlatma (h1, ul, li, img va h.k. ishlatma)
- Matn to'liq va batafsil bo'lsin — 400-600 so'z atrofida
- Emoji'lardan o'rinli va quvnoq tarzda foydalanish mumkin
- Javobingda faqat tayyor dars matnini yoz, boshqa hech qanday izoh yoki
  sarlavha qo'shma (sarlavhani men o'zim alohida qo'shaman)"""


def list_available_models() -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
    try:
        resp = requests.get(url, timeout=30)
        if not resp.ok:
            return f"Modellar ro'yxatini olishda ham xato ({resp.status_code}): {resp.text[:300]}"
        names = [m.get("name", "") for m in resp.json().get("models", [])]
        if not names:
            return "API kalit ishladi, lekin hech qanday model qaytmadi."
        return "Shu API kalit bilan mavjud modellar: " + ", ".join(names[:20])
    except Exception as e:
        return f"Modellar ro'yxatini olishda xato: {e}"


def _call_gemini_once(prompt: str, model: str) -> str:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={GEMINI_API_KEY}"
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
    }
    resp = requests.post(url, json=body, timeout=120)
    if not resp.ok:
        raise RuntimeError(f"({resp.status_code}) {resp.text[:400]}")
    data = resp.json()
    candidates = data.get("candidates", [])
    if not candidates:
        raise RuntimeError(f"Gemini javob qaytarmadi: {data}")
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts).strip()
    if not text:
        raise RuntimeError(f"Gemini bo'sh matn qaytardi: {data}")
    return text


def call_gemini(prompt: str) -> str:
    models_to_try = [GEMINI_MODEL] + GEMINI_FALLBACK_MODELS
    last_error = None

    for model in models_to_try:
        for attempt in range(1, GEMINI_MAX_RETRIES + 1):
            try:
                print(f"Gemini so'ralmoqda: model={model}, urinish={attempt}/{GEMINI_MAX_RETRIES}")
                return _call_gemini_once(prompt, model)
            except Exception as e:
                last_error = e
                is_last_attempt_for_model = attempt == GEMINI_MAX_RETRIES
                print(f"  -> xato: {e}")
                if not is_last_attempt_for_model:
                    time.sleep(GEMINI_RETRY_DELAY_SEC)
        print(f"Model '{model}' bilan {GEMINI_MAX_RETRIES} marta urinildi, navbatdagi modelga o'tilmoqda...")

    diag = list_available_models()
    raise RuntimeError(
        f"Barcha modellar ({', '.join(models_to_try)}) band yoki ishlamadi. "
        f"Oxirgi xato: {last_error}\nDIAGNOSTIKA: {diag}"
    )


def send_photo_to_telegram(photo_url: str, caption: str) -> bool:
    """Rasm + caption (HTML) yuboradi. Rasm URL orqali beriladi."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    resp = requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "photo": photo_url,
            "caption": caption,
            "parse_mode": "HTML",
        },
        timeout=60,
    )
    if not resp.ok:
        print(f"Telegramga rasm yuborishda xato: {resp.status_code} {resp.text}")
    return resp.ok


def send_message_to_telegram(text: str) -> bool:
    """Faqat matn yuboradi (caption juda uzun bo'lganda zaxira usul)."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    resp = requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    if not resp.ok:
        print(f"Telegramga matn yuborishda xato: {resp.status_code} {resp.text}")
    return resp.ok


def send_lesson_to_telegram(
    module: str, topic: str, lesson_no: int, total: int, body: str, image_url: str
) -> bool:
    """Darsni yuboradi: avval rasm (sarlavha bilan), keyin to'liq matn alohida.

    Matn uzun bo'lgani uchun (400-600 so'z) caption ishlatilmaydi —
    rasm sarlavha bilan, matn esa alohida sendMessage orqali yuboriladi.
    Shu tarzda Telegram 4096 belgilik matn limitidan to'liq foydalaniladi.
    """
    header = f"<b>📚 Dars {lesson_no}/{total}</b>\n<b>{module}</b>\n<b>{topic}</b>"
    footer = f"\n\n#dars{lesson_no}\n{CHANNEL_LINK}"

    # 1) Avval rasm + qisqa sarlavha
    ok1 = send_photo_to_telegram(image_url, header)
    if not ok1:
        return False

    time.sleep(1)

    # 2) Keyin to'liq dars matni alohida xabar sifatida
    full_text = body + footer

    # Agar matn 4096 belgidan uzun bo'lsa, bo'lib yuboriladi
    chunks = []
    remaining = full_text
    while len(remaining) > 3900:
        split_at = remaining.rfind("\n\n", 0, 3900)
        if split_at == -1:
            split_at = remaining.rfind("\n", 0, 3900)
        if split_at == -1:
            split_at = 3900
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)

    for i, chunk in enumerate(chunks):
        ok = send_message_to_telegram(chunk)
        if not ok:
            return False
        if i < len(chunks) - 1:
            time.sleep(1)

    return True


# ---------- ASOSIY MANTIQ ----------


def main() -> None:
    topics = load_topics()
    total = len(topics)
    index = load_progress()

    if index >= total:
        if LOOP_LESSONS:
            print("Barcha darslar tugagan edi, kurs boshidan qaytadan boshlanmoqda.")
            index = 0
        else:
            print(
                f"Kursdagi barcha {total} ta dars allaqachon joylangan. "
                "Yangi mavzu qo'shish yoki LOOP_LESSONS=true qilish mumkin."
            )
            return

    item = topics[index]
    module, topic = item["module"], item["topic"]
    lesson_no = index + 1

    print(f"Tayyorlanmoqda: {lesson_no}/{total} — {module} — {topic}")

    prompt = build_gemini_prompt(module, topic, lesson_no, total)
    try:
        body = call_gemini(prompt)
    except Exception as e:
        print(f"Gemini xatosi, dars joylanmadi: {e}")
        return

    image_url = get_image_url(module, topic)
    print(f"Rasm URL: {image_url}")

    ok = send_lesson_to_telegram(module, topic, lesson_no, total, body, image_url)
    if ok:
        save_progress(index + 1)
        print(f"Dars joylandi: {lesson_no}/{total} — {topic}")
    else:
        print("Dars joylanmadi, Telegramga yuborishda xato yuz berdi.")


if __name__ == "__main__":
    main()
