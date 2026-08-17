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
5. Tayyor dars matni Telegram kanaliga joylanadi.
6. Muvaffaqiyatli joylansa, index birga oshiriladi va lesson_progress.json'ga
   yoziladi (keyingi safar navbatdagi mavzu olinadi).
7. Barcha 160 ta mavzu tugagach, LOOP_LESSONS=true qilib qo'yilsa, kurs
   boshidan qaytadan boshlanadi; aks holda bot to'xtaydi va shu haqda
   log yozadi (default: to'xtaydi).

Bu skript kuniga 2 marta GitHub Actions orqali avtomatik ishga tushadi
(.github/workflows/lessons.yml faylida sozlangan) — har safar 1 ta mavzu,
demak kuniga 2 ta mavzu dars joylanadi, doim 1-mavzudan boshlab tartib bilan.
"""

import json
import os
import time
from pathlib import Path

import requests

# ---------- SOZLAMALAR ----------

# Kurs mavzulari ro'yxati (tepadan pastga qarab, tartib bilan o'tiladi)
TOPICS_FILE = Path(__file__).parent / "topics.json"

# "Hozir nechinchi mavzudamiz" ko'rsatkichi shu faylda saqlanadi
PROGRESS_FILE = Path(__file__).parent / "lesson_progress.json"

# Barcha mavzular tugagach kursni boshidan qaytadan boshlash kerakmi?
# ("true"/"false" — GitHub Actions'da workflow env orqali ham berish mumkin)
LOOP_LESSONS = os.environ.get("LOOP_LESSONS", "false").lower() == "true"

# Har bir postning eng pastida ko'rinadigan kanal linki
CHANNEL_LINK = "https://t.me/aiyangiliklaruz"

# Gemini modeli (kerak bo'lsa GitHub Secrets/Variables orqali o'zgartirish mumkin).
# "gemini-flash-latest" — bu doimiy nom (alias), u doim Google'ning eng so'nggi
# Flash modeliga ishora qiladi. Aniq versiya nomlarini (masalan
# "gemini-2.5-flash") qattiq yozib qo'yish tavsiya etilmaydi — Google vaqti-vaqti
# bilan eski versiyalarni o'chirib, 404 xatosini beradigan qilib qo'yadi.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")

# Telegramning bitta xabar uchun belgilar limiti (xavfsizlik uchun ozroq marja bilan)
TELEGRAM_MAX_CHARS = 3900

# Gemini va Telegram sozlamalari — GitHub Secrets orqali beriladi
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

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
- Sodda, tushunarli o'zbek tilida yoz, mavzuni hech narsa bilmaydigan
  boshlang'ich darajadagi o'quvchiga tushuntirgandek yoz
- Quyidagi tuzilishda yoz:
  1) Qisqa kirish — bu mavzu nima haqida va nega muhim (2-3 gap)
  2) Asosiy tushuntirish — tushunchani aniq, misollar bilan ochib ber
  3) Kamida 1-2 ta real hayotiy yoki amaliy misol
  4) "Esda tuting" — mavzu bo'yicha 2-3 ta muhim xulosa
  5) Mustaqil mashq — o'quvchi shu darsdan keyin sinab ko'rishi mumkin
     bo'lgan 1 ta kichik topshiriq
- Telegram xabari sifatida chiqadi, shuning uchun faqat quyidagi oddiy
  HTML teglaridan foydalan: <b>qalin</b>, <i>qiyshiq</i>. Boshqa teg ishlatma
  (h1, ul, li, img va h.k. ishlatma)
- Matn juda uzun bo'lmasin — taxminan 350-500 so'z atrofida bo'lsin
- Emoji'lardan o'rinli va kam miqdorda foydalanish mumkin
- Javobingda faqat tayyor dars matnini yoz, boshqa hech qanday izoh yoki
  sarlavha qo'shma (sarlavhani men o'zim alohida qo'shaman)"""


def list_available_models() -> str:
    """Diagnostika uchun: shu API kalit bilan qaysi modellar mavjudligini
    so'raydi. generateContent 404 xato bersa, sababni aniqlashda yordam beradi
    (masalan: kalit noto'g'ri/yoqilmagan bo'lsa, bu so'rov ham xato beradi;
    kalit to'g'ri bo'lsa-yu model nomi noto'g'ri bo'lsa, shu yerda mavjud
    model nomlari ko'rinadi)."""
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


def call_gemini(prompt: str) -> str:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
    }
    resp = requests.post(url, json=body, timeout=120)
    if not resp.ok:
        diag = list_available_models()
        raise RuntimeError(
            f"Gemini so'rovi xato qaytardi ({resp.status_code}): {resp.text[:500]}\n"
            f"DIAGNOSTIKA: {diag}"
        )
    data = resp.json()
    candidates = data.get("candidates", [])
    if not candidates:
        raise RuntimeError(f"Gemini javob qaytarmadi: {data}")
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts).strip()
    if not text:
        raise RuntimeError(f"Gemini bo'sh matn qaytardi: {data}")
    return text


def split_into_chunks(text: str, max_len: int = TELEGRAM_MAX_CHARS) -> list[str]:
    """Uzun matnni Telegram limitidan oshib ketmaydigan bo'laklarga bo'ladi,
    imkon boricha paragraf chegaralaridan bo'lib beradi."""
    if len(text) <= max_len:
        return [text]

    chunks = []
    remaining = text
    while len(remaining) > max_len:
        split_at = remaining.rfind("\n\n", 0, max_len)
        if split_at == -1:
            split_at = remaining.rfind("\n", 0, max_len)
        if split_at == -1:
            split_at = remaining.rfind(" ", 0, max_len)
        if split_at == -1:
            split_at = max_len
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def send_message_to_telegram(text: str) -> bool:
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
        print(f"Telegramga yuborishda xato: {resp.status_code} {resp.text}")
    return resp.ok


def send_lesson_to_telegram(module: str, topic: str, lesson_no: int, total: int, body: str) -> bool:
    header = f"<b>📚 Dars {lesson_no}/{total}</b>\n<b>{module}</b>\n<b>{topic}</b>\n\n"
    footer = f"\n\n{CHANNEL_LINK}"

    chunks = split_into_chunks(body, TELEGRAM_MAX_CHARS - len(header))
    for i, chunk in enumerate(chunks):
        is_last = i == len(chunks) - 1
        text = (header if i == 0 else "") + chunk + (footer if is_last else "")
        if not send_message_to_telegram(text):
            return False
        if not is_last:
            time.sleep(2)
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

    ok = send_lesson_to_telegram(module, topic, lesson_no, total, body)
    if ok:
        save_progress(index + 1)
        print(f"Dars joylandi: {lesson_no}/{total} — {topic}")
    else:
        print("Dars joylanmadi, Telegramga yuborishda xato yuz berdi.")


if __name__ == "__main__":
    main()
