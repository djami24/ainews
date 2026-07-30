"""
AI yangiliklarini avtomatik joylovchi Telegram bot.

Ishlash mantig'i:
1. RSS manbalaridan so'nggi maqolalarni o'qiydi
2. Kalit so'zlar bo'yicha AI-mavzudagi maqolalarni ajratadi
3. Avval joylanmagan (seen.json'da yo'q) maqolalarni tanlaydi
4. Sarlavhalarni o'zbek tiliga tarjima qiladi
5. Bir nechta yangilikni BITTA digest postga yig'adi:
   "AI dunyosida nima gap?" sarlavhasi + har biri o'z havolasiga
   bog'langan sarlavhalar ro'yxati + eng pastda kanal linki
6. Telegram kanaliga joylaydi va linklarni seen.json'ga yozadi
"""

import json
import os
from pathlib import Path

import feedparser
import requests
from deep_translator import GoogleTranslator

# ---------- SOZLAMALAR ----------

# Kuzatiladigan RSS manbalari. Xohlagancha qo'shishingiz/o'chirishingiz mumkin.
RSS_FEEDS = [
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "https://www.anthropic.com/news/rss.xml",
    "https://openai.com/news/rss.xml",
    "https://www.wired.com/feed/tag/ai/latest/rss",
]

# Maqola AI-mavzuda deb hisoblanishi uchun sarlavha/xulosada shu so'zlardan
# kamida bittasi bo'lishi kerak (agar barcha feedlar allaqachon AI-mavzuda
# bo'lsa, bu ro'yxatni bo'sh qoldirsangiz ham bo'ladi).
KEYWORDS = [
    "ai", "artificial intelligence", "llm", "gpt", "claude", "gemini",
    "chatbot", "machine learning", "openai", "anthropic", "deepmind",
    "model", "neural",
]

# Bir digest postda nechta yangilik bo'lsin
NEWS_PER_DIGEST = 4

# Digest postining tepasidagi sarlavha va kirish qatori
DIGEST_TITLE = "AI dunyosida nima gap?"
DIGEST_SUBTITLE = "Hozirgi soatgacha bo'lgan yangiliklar:"

# Har bir postning eng pastida ko'rinadigan kanal linki
CHANNEL_LINK = "https://t.me/aiyangiliklaruz"

# Ko'rilgan linklar saqlanadigan fayl
SEEN_FILE = Path(__file__).parent / "seen.json"

# Telegram sozlamalari — GitHub Secrets orqali beriladi (pastga qarang)
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# ---------- YORDAMCHI FUNKSIYALAR ----------


def load_seen() -> set[str]:
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text(encoding="utf-8")))
    return set()


def save_seen(seen: set[str]) -> None:
    # Fayl cheksiz o'smasligi uchun oxirgi 500 tasini saqlaymiz
    trimmed = list(seen)[-500:]
    SEEN_FILE.write_text(json.dumps(trimmed, ensure_ascii=False, indent=2), encoding="utf-8")


def is_relevant(title: str, summary: str) -> bool:
    if not KEYWORDS:
        return True
    text = f"{title} {summary}".lower()
    return any(kw in text for kw in KEYWORDS)


def translate_to_uz(text: str) -> str:
    if not text:
        return text
    try:
        return GoogleTranslator(source="auto", target="uz").translate(text)
    except Exception as e:
        print(f"Tarjima xatosi, asl matn qoldiriladi: {e}")
        return text


def clean_summary(raw_summary: str, max_len: int = 220) -> str:
    # RSS summary'lardagi HTML teglarni olib tashlaymiz (oddiy usul)
    import re

    text = re.sub(r"<[^>]+>", "", raw_summary or "")
    text = " ".join(text.split())
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0] + "..."
    return text


def build_digest_text(items: list[dict]) -> str:
    """items: [{"title_uz": str, "link": str}, ...] ro'yxatidan bitta
    digest xabar matnini yasaydi (rasmdagi 'ai mastava' formatiga o'xshash)."""
    lines = [f"<b>{DIGEST_TITLE}</b>", DIGEST_SUBTITLE, ""]
    for item in items:
        lines.append(f"● <a href='{item['link']}'>{item['title_uz']}</a>")
    lines.append("")
    lines.append(CHANNEL_LINK)
    return "\n".join(lines)


def send_digest_to_telegram(items: list[dict]) -> bool:
    text = build_digest_text(items)
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    resp = requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        },
        timeout=30,
    )
    if not resp.ok:
        print(f"Telegramga yuborishda xato: {resp.status_code} {resp.text}")
    return resp.ok


# ---------- ASOSIY MANTIQ ----------


def main() -> None:
    seen = load_seen()
    collected: list[dict] = []

    for feed_url in RSS_FEEDS:
        if len(collected) >= NEWS_PER_DIGEST:
            break

        print(f"Tekshirilmoqda: {feed_url}")
        try:
            feed = feedparser.parse(feed_url)
        except Exception as e:
            print(f"Feed o'qilmadi: {feed_url} -> {e}")
            continue

        for entry in feed.entries[:10]:
            if len(collected) >= NEWS_PER_DIGEST:
                break

            link = entry.get("link", "")
            title = entry.get("title", "")
            raw_summary = entry.get("summary", "") or entry.get("description", "")

            if not link or link in seen:
                continue

            summary = clean_summary(raw_summary)

            if not is_relevant(title, summary):
                continue

            title_uz = translate_to_uz(title)
            collected.append({"title_uz": title_uz, "link": link})
            seen.add(link)
            print(f"Digestga qo'shildi: {title}")

    if not collected:
        print("Yangi mos yangilik topilmadi, post joylanmadi.")
        return

    ok = send_digest_to_telegram(collected)
    if ok:
        save_seen(seen)
        print(f"Digest joylandi: {len(collected)} ta yangilik")
    else:
        print("Digest joylanmadi, xato yuz berdi.")


if __name__ == "__main__":
    main()
