# -*- coding: utf-8 -*-
"""
tg_safe.py — Telegramga rasm yuborishdagi xatolarni avtomatik tuzatadi.

Ishlatish: lessons.py faylining ENG BIRINCHI qatoriga yozing:
    import tg_safe

Nima qiladi:
1) Rasm havolasini Telegram o'zi emas, bot yuklab olib, fayl sifatida yuboradi
   ("failed to get HTTP URL content" xatosi yo'qoladi).
2) Rasm yuklanmasa — dars rasmsiz, oddiy matn sifatida yuboriladi (dars to'xtab qolmaydi).
3) Sarlavha (caption) 1024 belgidan uzun bo'lsa — rasm alohida, matn alohida yuboriladi.
4) Hech narsa yuborilmagan bo'lsa, skript xato bilan tugaydi (GitHub Actions qizil ✗ bo'ladi).
"""
import atexit
import json
import os
import requests

_orig_request = requests.sessions.Session.request
_state = {"ok": 0, "fail": 0}
_MAX_CAPTION = 1024
_MAX_TEXT = 4096


def _post(url, **kw):
    with requests.Session() as s:
        return _orig_request(s, "POST", url, **kw)


def _fields(kw):
    src = {}
    for key in ("params", "json", "data"):
        v = kw.get(key)
        if isinstance(v, dict):
            src.update(v)
    out = {}
    for k, v in src.items():
        if v is None:
            continue
        out[k] = json.dumps(v) if isinstance(v, (dict, list)) else v
    return out


def _fake_ok():
    r = requests.Response()
    r.status_code = 200
    r._content = b'{"ok":true,"result":{"message_id":0}}'
    return r


def _chunks(text, n=_MAX_TEXT):
    parts = []
    while len(text) > n:
        cut = text.rfind("\n", 0, n)
        if cut < n // 2:
            cut = n
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")
    if text:
        parts.append(text)
    return parts


def _send_text(api_base, fields, text):
    resp = None
    parts = _chunks(text)
    for i, part in enumerate(parts):
        f = {k: v for k, v in fields.items()
             if k in ("chat_id", "parse_mode", "message_thread_id")}
        if i == len(parts) - 1 and "reply_markup" in fields:
            f["reply_markup"] = fields["reply_markup"]
        f["text"] = part
        resp = _post(api_base + "/sendMessage", data=f, timeout=30)
        if not resp.ok and "parse_mode" in f:      # format xatosi bo'lsa — formatsiz urinib ko'ramiz
            print("parse_mode xatosi, formatsiz qayta yuborilmoqda:", resp.text[:200])
            f.pop("parse_mode")
            resp = _post(api_base + "/sendMessage", data=f, timeout=30)
        if not resp.ok:
            return resp
    return resp


def _download(photo_url):
    for attempt in (1, 2):
        try:
            r = requests.get(photo_url, timeout=25, headers={"User-Agent": "Mozilla/5.0"})
            ctype = r.headers.get("content-type", "")
            if r.ok and ctype.startswith("image/") and len(r.content) > 1000:
                return r.content
            print("Rasm yuklanmadi (urinish %d): HTTP %s, %s" % (attempt, r.status_code, ctype))
        except Exception as e:
            print("Rasm yuklashda xato (urinish %d): %s" % (attempt, e))
    return None


def _safe_photo(url, kw):
    fields = _fields(kw)
    api_base = url.rsplit("/", 1)[0]
    photo_url = fields.pop("photo")
    caption = fields.get("caption", "") or ""
    img = _download(photo_url)

    if img:
        f = dict(fields)
        long_caption = len(caption) > _MAX_CAPTION
        if long_caption:
            for k in ("caption", "parse_mode", "reply_markup"):
                f.pop(k, None)
        resp = _post(url, data=f, files={"photo": ("lesson.jpg", img)}, timeout=60)
        if resp.ok:
            if long_caption:
                return _send_text(api_base, fields, caption)
            return resp
        print("sendPhoto xato:", resp.text[:300])

    # Rasm bo'lmadi — rasmsiz davom etamiz
    print("Rasm yuborilmadi, dars rasmsiz yuboriladi.")
    if caption:
        return _send_text(api_base, fields, caption)
    return _fake_ok()


def _patched_request(self, method, url, *a, **kw):
    if str(method).upper() == "POST" and isinstance(url, str) and "api.telegram.org" in url:
        if url.endswith("/sendPhoto"):
            photo = _fields(kw).get("photo", "")
            if isinstance(photo, str) and photo.startswith("http") and not kw.get("files"):
                resp = _safe_photo(url, kw)
                _state["ok" if resp.ok else "fail"] += 1
                return resp
        resp = _orig_request(self, method, url, *a, **kw)
        _state["ok" if resp.ok else "fail"] += 1
        return resp
    return _orig_request(self, method, url, *a, **kw)


requests.sessions.Session.request = _patched_request


@atexit.register
def _exit_check():
    # Telegramga hech narsa yetib bormagan bo'lsa — Actions qizil bo'lsin
    if _state["fail"] > 0 and _state["ok"] == 0:
        print("XATO: Telegramga hech narsa yuborilmadi.")
        os._exit(1)
