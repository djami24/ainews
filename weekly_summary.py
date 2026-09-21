"""
Haftalik AI darslar xulosasi — PDF shaklida Telegram kanaliga yuboradi.

Ishlash mantig'i:
1. lesson_progress.json dan hozirgi index o'qiladi
2. O'tgan 7 kun ichida joylangan darslar aniqlanadi
   (index - 28 dan index gacha, chunki kuniga 4 ta dars = 7 kun * 4 = 28 ta)
3. Har bir mavzu uchun Gemini'dan qisqa xulosa so'raladi
4. Barcha xulosalar chiroyli PDF ga yig'iladi
5. PDF Telegram kanaliga yuboriladi

Har yakshanba ishga tushadi (lessons.yml dan alohida workflow).
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path

import requests
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ---------- SOZLAMALAR ----------

TOPICS_FILE = Path(__file__).parent / "topics.json"
PROGRESS_FILE = Path(__file__).parent / "lesson_progress.json"
CHANNEL_LINK = "https://t.me/aiyangiliklaruz"

# Kuniga 4 ta dars joylangani uchun 7 kun = 28 ta dars
LESSONS_PER_DAY = 4
DAYS_IN_WEEK = 7
LESSONS_PER_WEEK = LESSONS_PER_DAY * DAYS_IN_WEEK  # 28

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")
GEMINI_FALLBACK_MODELS = [
    m for m in ["gemini-3.1-flash-lite", "gemini-flash-latest", "gemini-pro-latest"]
    if m != GEMINI_MODEL
]
GEMINI_MAX_RETRIES = 3
GEMINI_RETRY_DELAY_SEC = 15

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

PDF_PATH = Path(__file__).parent / "haftalik_darslar.pdf"


# ---------- GEMINI ----------

def _call_gemini_once(prompt: str, model: str) -> str:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={GEMINI_API_KEY}"
    )
    resp = requests.post(
        url,
        json={"contents": [{"parts": [{"text": prompt}]}]},
        timeout=120,
    )
    if not resp.ok:
        raise RuntimeError(f"({resp.status_code}) {resp.text[:400]}")
    data = resp.json()
    candidates = data.get("candidates", [])
    if not candidates:
        raise RuntimeError(f"Gemini javob qaytarmadi: {data}")
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts).strip()
    if not text:
        raise RuntimeError("Gemini bo'sh matn qaytardi")
    return text


def call_gemini(prompt: str) -> str:
    models_to_try = [GEMINI_MODEL] + GEMINI_FALLBACK_MODELS
    last_error = None
    for model in models_to_try:
        for attempt in range(1, GEMINI_MAX_RETRIES + 1):
            try:
                print(f"Gemini: model={model}, urinish={attempt}")
                return _call_gemini_once(prompt, model)
            except Exception as e:
                last_error = e
                print(f"  -> xato: {e}")
                if attempt < GEMINI_MAX_RETRIES:
                    time.sleep(GEMINI_RETRY_DELAY_SEC)
        print(f"'{model}' ishlamadi, keyingisiga o'tilmoqda...")
    raise RuntimeError(f"Barcha modellar ishlamadi. Oxirgi xato: {last_error}")


def get_lesson_summary(module: str, topic: str, lesson_no: int) -> str:
    """Bitta mavzu uchun qisqa xulosa oladi."""
    prompt = f"""O'zbek tilida, quyidagi AI kursi mavzusi uchun 3-4 jumladan iborat 
qisqa va aniq xulosa yoz. Oddiy kattalar (25-35 yosh) uchun, do'stona ohangda.
Faqat sof matn yoz — hech qanday HTML teg, markdown, yulduzcha, tire, emoji ishlatma.

Mavzu: {topic}
Kurs bo'limi: {module}

Xulosada: mavzu nima haqida, asosiy g'oya nima, amalda qanday qo'llanadi."""
    return call_gemini(prompt)


# ---------- PDF YARATISH ----------

def register_fonts():
    """O'zbek harflari uchun unicode shrift o'rnatish."""
    # DejaVu — barcha unicode harflarni qo'llab-quvvatlaydi, GitHub Actions da mavjud
    try:
        pdfmetrics.registerFont(TTFont("DejaVu", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
        pdfmetrics.registerFont(TTFont("DejaVu-Bold", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"))
        return "DejaVu", "DejaVu-Bold"
    except Exception:
        pass
    # Fallback: Helvetica (ba'zi harflar ko'rinmasligi mumkin)
    return "Helvetica", "Helvetica-Bold"


def build_pdf(week_lessons: list[dict], week_num: int, date_range: str) -> Path:
    """Haftalik darslar PDF faylini yaratadi."""
    font_normal, font_bold = register_fonts()

    doc = SimpleDocTemplate(
        str(PDF_PATH),
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2.5 * cm,
        bottomMargin=2.5 * cm,
    )

    # Ranglar
    DARK_BLUE = colors.HexColor("#1a237e")
    ACCENT = colors.HexColor("#1565c0")
    LIGHT_BG = colors.HexColor("#e8eaf6")
    CARD_BG = colors.HexColor("#f5f5f5")
    TEXT = colors.HexColor("#212121")
    MUTED = colors.HexColor("#757575")

    # Stillar
    styles = {
        "cover_title": ParagraphStyle(
            "cover_title",
            fontName=font_bold,
            fontSize=26,
            textColor=DARK_BLUE,
            alignment=TA_CENTER,
            spaceAfter=8,
        ),
        "cover_sub": ParagraphStyle(
            "cover_sub",
            fontName=font_normal,
            fontSize=14,
            textColor=ACCENT,
            alignment=TA_CENTER,
            spaceAfter=6,
        ),
        "cover_date": ParagraphStyle(
            "cover_date",
            fontName=font_normal,
            fontSize=11,
            textColor=MUTED,
            alignment=TA_CENTER,
            spaceAfter=4,
        ),
        "section_header": ParagraphStyle(
            "section_header",
            fontName=font_bold,
            fontSize=11,
            textColor=colors.white,
            alignment=TA_LEFT,
            leftIndent=8,
            spaceAfter=0,
        ),
        "lesson_title": ParagraphStyle(
            "lesson_title",
            fontName=font_bold,
            fontSize=12,
            textColor=DARK_BLUE,
            spaceAfter=4,
        ),
        "lesson_body": ParagraphStyle(
            "lesson_body",
            fontName=font_normal,
            fontSize=10,
            textColor=TEXT,
            leading=16,
            spaceAfter=4,
        ),
        "lesson_num": ParagraphStyle(
            "lesson_num",
            fontName=font_bold,
            fontSize=9,
            textColor=MUTED,
            spaceAfter=2,
        ),
        "footer": ParagraphStyle(
            "footer",
            fontName=font_normal,
            fontSize=9,
            textColor=MUTED,
            alignment=TA_CENTER,
        ),
        "toc_item": ParagraphStyle(
            "toc_item",
            fontName=font_normal,
            fontSize=10,
            textColor=TEXT,
            leading=16,
            leftIndent=10,
        ),
        "toc_num": ParagraphStyle(
            "toc_num",
            fontName=font_bold,
            fontSize=10,
            textColor=ACCENT,
        ),
    }

    story = []

    # ── MUQOVA ──────────────────────────────────────────────
    story.append(Spacer(1, 3 * cm))
    story.append(Paragraph("SUN'IY INTELLEKT", styles["cover_title"]))
    story.append(Paragraph("0 DAN BOSHLAB", styles["cover_title"]))
    story.append(Spacer(1, 0.5 * cm))
    story.append(HRFlowable(width="60%", thickness=2, color=ACCENT, hAlign="CENTER"))
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph(f"HAFTALIK DARSLAR — {week_num}-HAFTA", styles["cover_sub"]))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(date_range, styles["cover_date"]))
    story.append(Paragraph(f"Jami {len(week_lessons)} ta dars", styles["cover_date"]))
    story.append(Spacer(1, 3 * cm))

    # Muqova — jadval (mavzular ro'yxati)
    toc_data = [[
        Paragraph("№", styles["toc_num"]),
        Paragraph("Mavzu", styles["toc_num"]),
    ]]
    for item in week_lessons:
        toc_data.append([
            Paragraph(str(item["lesson_no"]), styles["toc_num"]),
            Paragraph(item["topic"], styles["toc_item"]),
        ])

    toc_table = Table(toc_data, colWidths=[1.2 * cm, 14 * cm])
    toc_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), font_bold),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, CARD_BG]),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e0e0e0")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(toc_table)
    story.append(Spacer(1, 1 * cm))
    story.append(Paragraph(CHANNEL_LINK, styles["footer"]))
    story.append(PageBreak())

    # ── HAR BIR DARS ────────────────────────────────────────
    current_module = None
    for item in week_lessons:
        # Modul sarlavhasi (yangi modul boshlananda)
        if item["module"] != current_module:
            current_module = item["module"]
            module_table = Table(
                [[Paragraph(current_module, styles["section_header"])]],
                colWidths=[16.6 * cm],
            )
            module_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), ACCENT),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [ACCENT]),
            ]))
            story.append(module_table)
            story.append(Spacer(1, 0.3 * cm))

        # Dars kartasi
        story.append(Paragraph(f"Dars {item['lesson_no']}/160", styles["lesson_num"]))
        story.append(Paragraph(item["topic"], styles["lesson_title"]))
        story.append(Paragraph(item["summary"], styles["lesson_body"]))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e0e0e0")))
        story.append(Spacer(1, 0.4 * cm))

    # Oxirgi sahifa
    story.append(Spacer(1, 1 * cm))
    story.append(HRFlowable(width="100%", thickness=1, color=ACCENT))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(
        f"AI darslar kanali: {CHANNEL_LINK}",
        styles["footer"],
    ))
    story.append(Paragraph(
        f"Keyingi hafta yana {LESSONS_PER_WEEK} ta yangi dars.",
        styles["footer"],
    ))

    doc.build(story)
    return PDF_PATH


# ---------- TELEGRAM ----------

def send_pdf_to_telegram(pdf_path: Path, caption: str) -> bool:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    with open(pdf_path, "rb") as f:
        resp = requests.post(
            url,
            data={"chat_id": CHAT_ID, "caption": caption, "parse_mode": "HTML"},
            files={"document": (pdf_path.name, f, "application/pdf")},
            timeout=120,
        )
    if not resp.ok:
        print(f"PDF yuborishda xato: {resp.status_code} {resp.text}")
    return resp.ok


# ---------- ASOSIY MANTIQ ----------

def main() -> None:
    topics = json.loads(TOPICS_FILE.read_text(encoding="utf-8"))
    total = len(topics)

    current_index = 0
    if PROGRESS_FILE.exists():
        current_index = int(json.loads(
            PROGRESS_FILE.read_text(encoding="utf-8")
        ).get("index", 0))

    # O'tgan hafta joylangan darslar oralig'i
    end_index = current_index  # hozirgi pozitsiya (bu dars hali joylangan emas)
    start_index = max(0, end_index - LESSONS_PER_WEEK)

    if end_index <= start_index:
        print("Hali yetarlicha dars joylangan emas (kamida 1 ta bo'lishi kerak).")
        return

    week_lessons_raw = topics[start_index:end_index]
    print(f"O'tgan haftadagi darslar: {start_index + 1}–{end_index} ({len(week_lessons_raw)} ta)")

    # Hafta raqami va sana
    today = datetime.now()
    week_num = (end_index // LESSONS_PER_WEEK) + 1
    date_str = today.strftime("%d.%m.%Y")

    # Har bir dars uchun Gemini'dan xulosa olish
    week_lessons = []
    for i, item in enumerate(week_lessons_raw):
        lesson_no = start_index + i + 1
        print(f"  Xulosa tayyorlanmoqda: {lesson_no}/{total} — {item['topic']}")
        try:
            summary = get_lesson_summary(item["module"], item["topic"], lesson_no)
        except Exception as e:
            print(f"  Xulosa olishda xato: {e}")
            summary = f"{item['topic']} mavzusi bo'yicha dars o'tildi."
        week_lessons.append({
            "lesson_no": lesson_no,
            "module": item["module"],
            "topic": item["topic"],
            "summary": summary,
        })
        time.sleep(2)  # API limitiga tushib qolmaslik uchun

    # PDF yaratish
    print("PDF yaratilmoqda...")
    date_range = f"{date_str} haftalik xulosasi"
    pdf_path = build_pdf(week_lessons, week_num, date_range)
    print(f"PDF tayyor: {pdf_path} ({pdf_path.stat().st_size // 1024} KB)")

    # Telegram ga yuborish
    first_lesson = week_lessons[0]["lesson_no"]
    last_lesson = week_lessons[-1]["lesson_no"]
    caption = (
        f"<b>Haftalik darslar xulosasi — {week_num}-hafta</b>\n\n"
        f"O'tgan hafta {len(week_lessons)} ta dars o'tildi:\n"
        f"<i>Dars {first_lesson}–{last_lesson}</i>\n\n"
        f"PDF ni yuklab oling va takrorlang.\n\n"
        f"{CHANNEL_LINK}"
    )
    ok = send_pdf_to_telegram(pdf_path, caption)
    if ok:
        print(f"Haftalik PDF muvaffaqiyatli yuborildi!")
    else:
        print("PDF yuborishda xato yuz berdi.")


if __name__ == "__main__":
    main()
