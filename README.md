# LLL Telegram CRM

Готовий базовий Telegram CRM-бот для розгортання на Render.

## Що вміє

- головне меню в Telegram;
- клієнти: додавання, список;
- заявки: створення, список;
- пошук клієнтів і заявок;
- статистика;
- генерація QR-кодів;
- SQLite база даних;
- HTTP health endpoint для Render;
- запуск командою `python bot.py`.

## 1. Локальний запуск

Встанови Python 3.11+.

```bash
pip install -r requirements.txt
```

Скопіюй `.env.example` у `.env` і впиши:

- `BOT_TOKEN` — токен від @BotFather;
- `ADMIN_IDS` — твій числовий Telegram ID.

Потім:

```bash
python bot.py
```

## 2. GitHub

Завантаж у репозиторій всі файли цього проєкту.

## 3. Render

Створи **Web Service** і вибери цей GitHub repository.

Параметри:

- Language: Python 3
- Root Directory: порожньо
- Build Command:
  `pip install -r requirements.txt`
- Start Command:
  `python bot.py`

У **Environment Variables** додай:

`BOT_TOKEN` = токен бота

`ADMIN_IDS` = твій Telegram numeric ID

PORT вручну додавати не обов'язково — Render передає його сам.

## Важливо

Безкоштовний Render може присипляти сервіс. Для Telegram-бота це означає, що після перерви бот може прокидатися із затримкою.

SQLite підходить для тестування та невеликого CRM. Для серйозного багатокористувацького проєкту краще перейти на PostgreSQL.

## Безпека

Не завантажуй `.env` у GitHub. Токен Telegram має зберігатися тільки в Environment Variables Render.
