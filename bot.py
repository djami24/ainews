"""
AI yangiliklarini avtomatik joylovchi Telegram bot.

Ishlash mantig'i:
1. HackerNews'dan (Algolia API orqali) so'nggi soatlar ichidagi
   AI-mavzudagi eng ko'p ball (popularity) to'plagan postlarni oladi
   — bu "eng ko'p odamlar ko'rgan/muhokama qilgan" degan ma'noni beradi
2. Agar yetarlicha topilmasa, oddiy RSS manbalaridan to'ldiradi
3. Barchasini ball (popularity) bo'yicha saralaydi
4. Avval joylanmagan (seen.json'da yo'q) eng yuqoridagilarni tanlaydi
5. Sarlavhalar original ingliz tilida qoldiriladi (tarjima o'chirilgan —
   avtomatik tarjima ko'pincha noto'g'ri/tushunarsiz chiqardi)
6. Bir nechta yangilikni BITTA digest postga yig'adi:
   "AI dunyosida nima gap?" sarlavhasi + har biri o'z havolasiga
   bog'langan sarlavhalar ro'yxati + eng pastda kanal linki
7. Telegram kanaliga joylaydi va linklarni seen.json'ga yozadi

Bu skript har 30 daqiqada GitHub Actions orqali avtomatik ishga tushadi
(.github/workflows/post.yml faylida sozlangan).
"""

import json
import os
import re
import time
from pathlib import Path

import feedparser
import requests

# ---------- SOZLAMALAR ----------

# --- HackerNews orqali popularity bo'yicha qidiruv ---
# HN'da AI-mavzuda qidiriladigan kalit so'zlar
HN_KEYWORDS = ["AI", "LLM", "GPT", "Claude", "OpenAI", "Anthropic", "machine learning"]
# Necha soat oldingi postlargacha qaraladi
HN_LOOKBACK_HOURS = 24
# Kamida shuncha ball (points) to'plagan postlar "mashhur" hisoblanadi
HN_MIN_POINTS = 15

# --- RSS manbalari (HN'dan yetarli topilmasa, shulardan to'ldiriladi) ---
RSS_FEEDS = [
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "https://www.anthropic.com/news/rss.xml",
    "https://openai.com/news/rss.xml",
    "https://www.wired.com/feed/tag/ai/latest/rss",
]

# Maqola AI-mavzuda deb hisoblanishi uchun sarlavha/xulosada shu so'zlardan
# kamida bittasi bo'lishi kerak
KEYWORDS = [
    "ai", "artificial intelligence", "llm", "gpt", "claude", "gemini",
    "chatbot", "machine learning", "openai", "anthropic", "deepmind",
    "model", "neural",
]

# Bir digest postda nechta yangilik bo'lsin
NEWS_PER_DIGEST = 4

# Digest postining tepasidagi sarlavha va kirish qatori (ingliz tilida)
DIGEST_TITLE = "What's happening in AI?"
DIGEST_SUBTITLE = "The most popular news right now:"

# Har bir postning eng pastida ko'rinadigan kanal linki
CHANNEL_LINK = "https://t.me/aiyangiliklaruz"

# Ko'rilgan linklar saqlanadigan fayl
SEEN_FILE = Path(__file__).parent / "seen.json"

# Telegram sozlamalari — GitHub Secrets orqali beriladi
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# ---------- YORDAMCHI FUNKSIYALAR ----------


def load_seen() -> set[str]:
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text(encoding="utf-8")))
    return set()


def save_seen(seen: set[str]) -> None:
    trimmed = list(seen)[-500:]
    SEEN_FILE.write_text(json.dumps(trimmed, ensure_ascii=False, indent=2), encoding="utf-8")


def is_relevant(title: str, summary: str = "") -> bool:
    if not KEYWORDS:
        return True
    text = f"{title} {summary}".lower()
    return any(kw in text for kw in KEYWORDS)


def clean_summary(raw_summary: str, max_len: int = 220) -> str:
    text = re.sub(r"<[^>]+>", "", raw_summary or "")
    text = " ".join(text.split())
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0] + "..."
    return text


def fetch_hn_stories() -> list[dict]:
    """HackerNews'dan (Algolia Search API) so'nggi HN_LOOKBACK_HOURS soat
    ichidagi, ballari HN_MIN_POINTS'dan yuqori bo'lgan AI-mavzudagi
    postlarni oladi. Natija: [{"title", "link", "points"}, ...]"""
    since = int(time.time()) - HN_LOOKBACK_HOURS * 3600
    found: dict[str, dict] = {}

    for kw in HN_KEYWORDS:
        url = (
            "https://hn.algolia.com/api/v1/search"
            f"?query={requests.utils.quote(kw)}"
            "&tags=story"
            f"&numericFilters=created_at_i>{since},points>{HN_MIN_POINTS}"
        )
        try:
            resp = requests.get(url, timeout=20)
            resp.raise_for_status()
            hits = resp.json().get("hits", [])
        except Exception as e:
            print(f"HackerNews so'rovida xato ({kw}): {e}")
            continue

        for hit in hits:
            title = hit.get("title") or hit.get("story_title") or ""
            link = hit.get("url") or hit.get("story_url")
            if not link:
                link = f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
            if not title or link in found:
                continue
            found[link] = {
                "title": title,
                "link": link,
                "points": hit.get("points", 0) or 0,
            }

    return list(found.values())


def fetch_rss_stories() -> list[dict]:
    """RSS manbalaridan so'nggi maqolalarni oladi (popularity ma'lumoti
    bo'lmagani uchun points=0 qo'yiladi, ya'ni HN natijalaridan pastroq
    turadi)."""
    results = []
    for feed_url in RSS_FEEDS:
        print(f"RSS tekshirilmoqda: {feed_url}")
        try:
            feed = feedparser.parse(feed_url)
        except Exception as e:
            print(f"Feed o'qilmadi: {feed_url} -> {e}")
            continue

        for entry in feed.entries[:10]:
            link = entry.get("link", "")
            title = entry.get("title", "")
            raw_summary = entry.get("summary", "") or entry.get("description", "")
            summary = clean_summary(raw_summary)

            if not link or not is_relevant(title, summary):
                continue

            results.append({"title": title, "link": link, "points": 0})

    return results


def build_digest_text(items: list[dict]) -> str:
    """items: [{"title": str, "link": str}, ...] ro'yxatidan bitta
    digest xabar matnini yasaydi."""
    lines = [f"<b>{DIGEST_TITLE}</b>", DIGEST_SUBTITLE, ""]
    for item in items:
        lines.append(f"● <a href='{item['link']}'>{item['title']}</a>")
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

    print("HackerNews'dan mashhur AI yangiliklari qidirilmoqda...")
    candidates = fetch_hn_stories()
    print(f"HackerNews'dan topildi: {len(candidates)} ta nomzod")

    # Agar HN'dan yetarlicha yangi (ko'rilmagan) post topilmasa, RSS bilan to'ldiramiz
    unseen_hn = [c for c in candidates if c["link"] not in seen]
    if len(unseen_hn) < NEWS_PER_DIGEST:
        print("HN'dan yetarli topilmadi, RSS manbalari bilan to'ldirilmoqda...")
        candidates += fetch_rss_stories()

    # Eng yuqori ball (popularity) bo'yicha saralaymiz
    candidates.sort(key=lambda c: c["points"], reverse=True)

    collected: list[dict] = []
    for c in candidates:
        if len(collected) >= NEWS_PER_DIGEST:
            break
        if c["link"] in seen:
            continue
        collected.append({"title": c["title"], "link": c["link"]})
        seen.add(c["link"])
        print(f"Digestga qo'shildi (points={c['points']}): {c['title']}")

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
