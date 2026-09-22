name: AI Darslar Bot

on:
  schedule:
    # Kuniga 6 marta: Toshkent vaqti (UTC+5) bilan
    # 08:00 Toshkent  = 03:00 UTC
    # 10:30 Toshkent  = 05:30 UTC
    # 13:00 Toshkent  = 08:00 UTC
    # 15:30 Toshkent  = 10:30 UTC
    # 18:00 Toshkent  = 13:00 UTC
    # 20:30 Toshkent  = 15:30 UTC
    - cron: "0 3 * * *"
    - cron: "30 5 * * *"
    - cron: "0 8 * * *"
    - cron: "30 10 * * *"
    - cron: "0 13 * * *"
    - cron: "30 15 * * *"
  workflow_dispatch: {}  # "Run workflow" tugmasi orqali qo'lda ham ishga tushirish mumkin

permissions:
  contents: write  # lesson_progress.json faylini repo'ga qaytarib commit qilish uchun

jobs:
  run-lessons:
    runs-on: ubuntu-latest
    steps:
      - name: Repo'ni olish
        uses: actions/checkout@v4

      - name: Python o'rnatish
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Kutubxonalarni o'rnatish
        run: pip install -r requirements.txt

      - name: Darsni tayyorlab, kanalga joylash
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
          LOOP_LESSONS: "false"
        run: python lessons.py

      - name: lesson_progress.json o'zgarishini saqlash
        run: |
          git config user.name "ai-lessons-bot"
          git config user.email "actions@github.com"
          git add lesson_progress.json
          git diff --staged --quiet || git commit -m "Navbatdagi dars joylandi"
          git push
