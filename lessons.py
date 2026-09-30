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
5. Tayyor dars matni (rasmsiz, faqat matn) Telegram kanaliga joylanadi.
6. Muvaffaqiyatli joylansa, index birga oshiriladi va lesson_progress.json'ga
   yoziladi (keyingi safar navbatdagi mavzu olinadi).
7. Barcha mavzular tugagach, LOOP_LESSONS=true qilib qo'yilsa, kurs
   boshidan qaytadan boshlanadi; aks holda bot to'xtaydi.

Kuniga 4 marta GitHub Actions orqali avtomatik ishga tushadi:
08:00, 12:00, 16:00, 20:00 (Toshkent vaqti, UTC+5).
"""

import json
import os
import re
import sys
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
- O'quvchi — AI bilan tanish bo'lmagan oddiy kattalar (25-35 yosh).
  Sodda va tushunarli yoz, lekin bolalarcha emas. Na'ra urma, na mushuk-dinozavr misol keltirma.
  Gapirish ohangi: yaxshi do'sting suhbatdoshingga tushuntirayotgandek — samimiy, aniq, qiziqarli
- Quyidagi tuzilishda yoz:
  1) Kirish — hayotdan olingan real holat yoki savol bilan boshlang
     (ish, pul, vaqt, muloqot — kundalik hayot bilan bog'liq)
  2) Asosiy tushuntirish — tushunchani oddiy so'zlar bilan batafsil ochib ber,
     o'rinli qiyoslar va aniq misollar ishlat
  3) 2-3 ta real, amaliy misol keltir — ChatGPT, ish, ijtimoiy tarmoq, biznes kabi
  4) "Esda tuting" — 3-4 ta asosiy xulosani aniq yoz
  5) Mustaqil mashq — o'quvchi hoziroq o'z hayotida sinab ko'rishi mumkin bo'lgan topshiriq
- Faqat quyidagi oddiy HTML teglaridan foydalan: <b>qalin</b>, <i>qiyshiq</i>.
  Boshqa teg ishlatma (h1, ul, li, img va h.k. ishlatma)
- Matn to'liq va batafsil bo'lsin — 400-600 so'z atrofida
- Hech qanday emoji ishlatma — na matn ichida, na sarlavhada
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


def _strip_tags(text: str) -> str:
    """HTML teglarni olib tashlaydi (HTML xato bersa, oddiy matn sifatida yuborish uchun)."""
    text = re.sub(r"<[^>]+>", "", text)
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def send_message_to_telegram(text: str) -> bool:
    """Matn yuboradi. HTML xato bersa, teglarsiz qayta urinib ko'radi."""
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
    if resp.ok:
        return True

    print(f"Telegramga matn yuborishda xato: {resp.status_code} {resp.text}")
    if resp.status_code == 400 and "parse" in resp.text.lower():
        print("HTML formatida xato, teglarsiz qayta yuborilmoqda...")
        resp = requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": _strip_tags(text),
                "disable_web_page_preview": True,
            },
            timeout=30,
        )
        if not resp.ok:
            print(f"Teglarsiz ham yuborilmadi: {resp.status_code} {resp.text}")
        return resp.ok
    return False


def send_lesson_to_telegram(
    module: str, topic: str, lesson_no: int, total: int, body: str
) -> bool:
    """Darsni faqat matn ko'rinishida yuboradi (rasmsiz).

    Sarlavha + dars matni + pastki qism bitta xabar bo'lib ketadi;
    matn 4096 belgidan uzun bo'lsa, bir necha xabarga bo'linadi.
    """
    header = f"<b>Dars {lesson_no}/{total}</b>\n<b>{module}</b>\n<b>{topic}</b>"
    footer = f"\n\n#dars{lesson_no}\n{CHANNEL_LINK}"
    full_text = header + "\n\n" + body + footer

    # 4096 belgidan uzun bo'lsa, bo'lib yuboriladi
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
        if not send_message_to_telegram(chunk):
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
        sys.exit(1)  # Actions qizil ✗ bo'lsin, xato darrov ko'rinsin

    ok = send_lesson_to_telegram(module, topic, lesson_no, total, body)
    if ok:
        save_progress(index + 1)
        print(f"Dars joylandi: {lesson_no}/{total} — {topic}")
    else:
        print("Dars joylanmadi, Telegramga yuborishda xato yuz berdi.")
        sys.exit(1)


if __name__ == "__main__":
    main()
