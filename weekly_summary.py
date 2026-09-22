"""
Haftalik AI darslar to'plami — PDF kitob shaklida Telegram kanaliga yuboradi.

Ishlash mantig'i:
1. lesson_progress.json dan hozirgi index o'qiladi
2. O'tgan 7 kun ichida joylangan darslar aniqlanadi (oxirgi 28 ta: 7kun * 4dars)
3. Har bir mavzu uchun Gemini'dan TO'LIQ dars matni so'raladi (500-700 so'z)
4. Barcha to'liq darslar chiroyli PDF kitob sifatida yig'iladi
5. PDF Telegram kanaliga yuboriladi

Har yakshanba 20:30 Toshkent vaqtida ishga tushadi.
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path

import requests
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
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
                print(f"  Gemini: model={model}, urinish={attempt}")
                return _call_gemini_once(prompt, model)
            except Exception as e:
                last_error = e
                print(f"    -> xato: {e}")
                if attempt < GEMINI_MAX_RETRIES:
                    time.sleep(GEMINI_RETRY_DELAY_SEC)
        print(f"  '{model}' ishlamadi, keyingisiga o'tilmoqda...")
    raise RuntimeError(f"Barcha modellar ishlamadi. Oxirgi xato: {last_error}")


def get_full_lesson(module: str, topic: str, lesson_no: int, total: int) -> str:
    """Bitta mavzu uchun to'liq dars matni oladi (PDF kitob uchun)."""
    prompt = (
        "O'zbek tilida, \"SUN'IY INTELLEKT: 0 DAN BOSHLAB\" kursi uchun to'liq dars matni yoz.\n\n"
        f"Kurs bo'limi: {module}\n"
        f"Mavzu: {topic}\n"
        f"Bu kursning {lesson_no}-darsi, jami {total} ta dars bor.\n\n"
        "Talablar:\n"
        "- O'quvchi: AI bilan tanish bo'lmagan oddiy kattalar (25-35 yosh).\n"
        "- Sodda va tushunarli yoz, lekin bolalarcha emas.\n"
        "- Ohang: yaxshi do'sting tushuntirayotgandek — samimiy, aniq.\n"
        "- Tuzilish (har bo'limni katta harflar bilan yoz: KIRISH, ASOSIY TUSHUNTIRISH va h.k.):\n"
        "  1) KIRISH — real hayotiy holat yoki savol bilan boshlang\n"
        "  2) ASOSIY TUSHUNTIRISH — batafsil, qiyoslar va misollar bilan\n"
        "  3) AMALIY MISOLLAR — 2-3 ta real misol (ChatGPT, ish, biznes kabi)\n"
        "  4) ESDA TUTING — 3-4 ta asosiy xulosa\n"
        "  5) MUSTAQIL MASHQ — o'quvchi sinab ko'rishi mumkin bo'lgan topshiriq\n"
        "- Faqat sof matn: hech qanday HTML teg, markdown (*,#,-), emoji ishlatma.\n"
        "- Hajm: 500-700 so'z atrofida.\n"
        "- Faqat tayyor dars matnini yoz, boshqa izoh qo'shma."
    )
    return call_gemini(prompt)


# ---------- SHRIFT ----------

def register_fonts():
    try:
        pdfmetrics.registerFont(TTFont(
            "DejaVu", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
        pdfmetrics.registerFont(TTFont(
            "DejaVu-Bold", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"))
        pdfmetrics.registerFont(TTFont(
            "DejaVu-Italic", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"))
        return "DejaVu", "DejaVu-Bold", "DejaVu-Italic"
    except Exception:
        return "Helvetica", "Helvetica-Bold", "Helvetica-Oblique"


# ---------- PDF ----------

def build_pdf(week_lessons: list[dict], week_num: int, date_range: str) -> Path:
    font_n, font_b, font_i = register_fonts()

    DARK_BLUE  = colors.HexColor("#1a237e")
    ACCENT     = colors.HexColor("#1565c0")
    LIGHT_BLUE = colors.HexColor("#e8eaf6")
    CARD_BG    = colors.HexColor("#f5f5f5")
    TEXT       = colors.HexColor("#212121")
    MUTED      = colors.HexColor("#757575")

    doc = SimpleDocTemplate(
        str(PDF_PATH),
        pagesize=A4,
        rightMargin=2.2 * cm,
        leftMargin=2.2 * cm,
        topMargin=2.5 * cm,
        bottomMargin=2.5 * cm,
    )

    W = A4[0] - 4.4 * cm  # sahifa kengligi

    s = {
        "cover_title": ParagraphStyle("cover_title",
            fontName=font_b, fontSize=28, textColor=DARK_BLUE,
            alignment=TA_CENTER, spaceAfter=6),
        "cover_sub": ParagraphStyle("cover_sub",
            fontName=font_n, fontSize=14, textColor=ACCENT,
            alignment=TA_CENTER, spaceAfter=4),
        "cover_meta": ParagraphStyle("cover_meta",
            fontName=font_n, fontSize=11, textColor=MUTED,
            alignment=TA_CENTER, spaceAfter=4),
        "toc_head": ParagraphStyle("toc_head",
            fontName=font_b, fontSize=10, textColor=colors.white),
        "toc_num": ParagraphStyle("toc_num",
            fontName=font_b, fontSize=10, textColor=ACCENT,
            alignment=TA_CENTER),
        "toc_item": ParagraphStyle("toc_item",
            fontName=font_n, fontSize=10, textColor=TEXT, leading=15),
        "module_label": ParagraphStyle("module_label",
            fontName=font_b, fontSize=10, textColor=colors.white, leftIndent=6),
        "dars_num": ParagraphStyle("dars_num",
            fontName=font_n, fontSize=10, textColor=MUTED, spaceAfter=4),
        "dars_title": ParagraphStyle("dars_title",
            fontName=font_b, fontSize=16, textColor=DARK_BLUE, spaceAfter=6),
        "section_head": ParagraphStyle("section_head",
            fontName=font_b, fontSize=11, textColor=ACCENT,
            spaceBefore=10, spaceAfter=4),
        "body": ParagraphStyle("body",
            fontName=font_n, fontSize=11, textColor=TEXT,
            leading=18, alignment=TA_JUSTIFY, spaceAfter=6),
        "footer": ParagraphStyle("footer",
            fontName=font_n, fontSize=9, textColor=MUTED,
            alignment=TA_CENTER),
    }

    story = []

    # ── MUQOVA ──────────────────────────────────────────────────────────────
    story.append(Spacer(1, 3.5 * cm))
    story.append(Paragraph("SUN'IY INTELLEKT", s["cover_title"]))
    story.append(Paragraph("0 DAN BOSHLAB", s["cover_title"]))
    story.append(Spacer(1, 0.6 * cm))
    story.append(HRFlowable(width="55%", thickness=2, color=ACCENT, hAlign="CENTER"))
    story.append(Spacer(1, 0.6 * cm))
    story.append(Paragraph(f"{week_num}-HAFTA — TO'LIQ DARSLAR", s["cover_sub"]))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(date_range, s["cover_meta"]))
    story.append(Paragraph(
        f"Jami {len(week_lessons)} ta dars  |  "
        f"Dars {week_lessons[0]['lesson_no']}–{week_lessons[-1]['lesson_no']}",
        s["cover_meta"],
    ))
    story.append(Spacer(1, 3 * cm))
    story.append(Paragraph(CHANNEL_LINK, s["footer"]))
    story.append(PageBreak())

    # ── MUNDARIJA ───────────────────────────────────────────────────────────
    story.append(Paragraph("MUNDARIJA", s["dars_title"]))
    story.append(HRFlowable(width="100%", thickness=1, color=ACCENT))
    story.append(Spacer(1, 0.4 * cm))

    toc_data = [[
        Paragraph("Dars", s["toc_head"]),
        Paragraph("Mavzu", s["toc_head"]),
        Paragraph("Bo'lim", s["toc_head"]),
    ]]
    for item in week_lessons:
        toc_data.append([
            Paragraph(str(item["lesson_no"]), s["toc_num"]),
            Paragraph(item["topic"], s["toc_item"]),
            Paragraph(item["module"].split(".")[0], s["toc_item"]),
        ])

    toc = Table(toc_data, colWidths=[1.4 * cm, 10 * cm, 5.2 * cm])
    toc.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, 0), ACCENT),
        ("TEXTCOLOR",    (0, 0), (-1, 0), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, CARD_BG]),
        ("GRID",         (0, 0), (-1, -1), 0.3, colors.HexColor("#e0e0e0")),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",   (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
        ("LEFTPADDING",  (0, 0), (-1, -1), 6),
    ]))
    story.append(toc)
    story.append(PageBreak())

    # ── HAR BIR DARS — TO'LIQ MATN ─────────────────────────────────────────
    SECTION_KEYWORDS = {
        "KIRISH", "ASOSIY TUSHUNTIRISH", "AMALIY MISOLLAR",
        "ESDA TUTING", "MUSTAQIL MASHQ",
    }

    current_module = None
    for item in week_lessons:
        # Yangi modul sarlavhasi
        if item["module"] != current_module:
            current_module = item["module"]
            mod_tbl = Table(
                [[Paragraph(current_module, s["module_label"])]],
                colWidths=[W],
            )
            mod_tbl.setStyle(TableStyle([
                ("BACKGROUND",   (0, 0), (-1, -1), ACCENT),
                ("TOPPADDING",   (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING",(0, 0), (-1, -1), 7),
                ("LEFTPADDING",  (0, 0), (-1, -1), 10),
            ]))
            story.append(mod_tbl)
            story.append(Spacer(1, 0.2 * cm))

        # Dars yangi sahifadan
        story.append(PageBreak())
        story.append(Paragraph(f"Dars {item['lesson_no']} / 160", s["dars_num"]))
        story.append(Paragraph(item["topic"], s["dars_title"]))
        story.append(HRFlowable(width="100%", thickness=1, color=ACCENT))
        story.append(Spacer(1, 0.5 * cm))

        # Dars matnini paragraflar bo'yicha ajratib chiqarish
        raw_text = item["body"]
        paragraphs = [p.strip() for p in raw_text.split("\n\n") if p.strip()]

        for para in paragraphs:
            # Bir qatorli sarlavhami? (KATTA HARFLAR, 60 belgidan qisqa)
            first_line = para.split("\n")[0].strip()
            is_section = (
                first_line.upper() == first_line
                and len(first_line) < 70
                and any(kw in first_line for kw in SECTION_KEYWORDS)
            )
            if is_section:
                story.append(Spacer(1, 0.3 * cm))
                story.append(Paragraph(first_line, s["section_head"]))
                # Sarlavhadan keyingi qolgan qism bor bo'lsa
                rest = "\n".join(para.split("\n")[1:]).strip()
                if rest:
                    story.append(Paragraph(rest, s["body"]))
            else:
                # Oddiy paragraf — ichidagi \n larni bo'shliq bilan almashtir
                clean = para.replace("\n", " ")
                story.append(Paragraph(clean, s["body"]))

        story.append(Spacer(1, 0.5 * cm))
        story.append(HRFlowable(
            width="100%", thickness=0.5,
            color=colors.HexColor("#e0e0e0"),
        ))

    # ── OXIRGI SAHIFA ───────────────────────────────────────────────────────
    story.append(PageBreak())
    story.append(Spacer(1, 5 * cm))
    story.append(HRFlowable(width="60%", thickness=1, color=ACCENT, hAlign="CENTER"))
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph("Kanalga obuna bo'ling:", s["footer"]))
    story.append(Paragraph(CHANNEL_LINK, s["footer"]))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(
        f"Keyingi hafta yana {LESSONS_PER_WEEK} ta yangi dars.", s["footer"]))

    doc.build(story)
    print(f"PDF tayyor: {PDF_PATH} ({PDF_PATH.stat().st_size // 1024} KB)")
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
        current_index = int(
            json.loads(PROGRESS_FILE.read_text(encoding="utf-8")).get("index", 0)
        )

    end_index   = current_index
    start_index = max(0, end_index - LESSONS_PER_WEEK)

    if end_index <= start_index:
        print("Hali yetarlicha dars joylangan emas (kamida 1 ta bo'lishi kerak).")
        return

    week_lessons_raw = topics[start_index:end_index]
    print(f"Darslar: {start_index + 1}–{end_index} ({len(week_lessons_raw)} ta)")

    today    = datetime.now()
    week_num = (end_index // LESSONS_PER_WEEK) + 1
    date_str = today.strftime("%d.%m.%Y")

    # Har bir dars uchun to'liq matn olish
    week_lessons = []
    for i, item in enumerate(week_lessons_raw):
        lesson_no = start_index + i + 1
        print(f"  [{lesson_no}/{total}] {item['topic']}")
        try:
            body = get_full_lesson(item["module"], item["topic"], lesson_no, total)
        except Exception as e:
            print(f"    Xato: {e}")
            body = f"{item['topic']} mavzusi bo'yicha dars o'tildi."
        week_lessons.append({
            "lesson_no": lesson_no,
            "module":    item["module"],
            "topic":     item["topic"],
            "body":      body,
        })
        time.sleep(3)

    print("PDF yaratilmoqda...")
    date_range = f"{date_str} — {week_num}-hafta"
    pdf_path = build_pdf(week_lessons, week_num, date_range)

    first_no = week_lessons[0]["lesson_no"]
    last_no  = week_lessons[-1]["lesson_no"]
    caption = (
        f"<b>Haftalik darslar to'plami — {week_num}-hafta</b>\n\n"
        f"O'tgan hafta o'tilgan {len(week_lessons)} ta darsning to'liq matni:\n"
        f"<i>Dars {first_no} — Dars {last_no}</i>\n\n"
        f"PDF ni yuklab olib, takrorlang.\n\n"
        f"{CHANNEL_LINK}"
    )
    ok = send_pdf_to_telegram(pdf_path, caption)
    if ok:
        print("Haftalik PDF muvaffaqiyatli yuborildi.")
    else:
        print("PDF yuborishda xato yuz berdi.")


if __name__ == "__main__":
    main()
