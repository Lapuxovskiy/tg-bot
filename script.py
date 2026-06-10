import os
import re
import sqlite3
import asyncio
import threading
import logging
from datetime import datetime

import telebot
import aiohttp
from dotenv import load_dotenv

# ─────────────────────────────────────────────
# КОНФИГУРАЦИЯ
# ─────────────────────────────────────────────

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

bot = telebot.TeleBot(BOT_TOKEN)

# ─────────────────────────────────────────────
# БАЗА ДАННЫХ
# ─────────────────────────────────────────────

DB_PATH = "kufar.db"


def get_conn() -> sqlite3.Connection:
    """Новое соединение на каждый вызов — потокобезопасно."""
    return sqlite3.connect(DB_PATH)


def init_db():
    with get_conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                city        TEXT    NOT NULL,
                max_price   INTEGER NOT NULL DEFAULT 999999
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS seen_ads (
                ad_id TEXT PRIMARY KEY
            )
        """)


def upsert_user(tid: int, city: str):
    with get_conn() as c:
        c.execute("""
            INSERT INTO users(telegram_id, city)
            VALUES(?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET city = excluded.city
        """, (tid, city))


def set_price(tid: int, price: int):
    with get_conn() as c:
        c.execute(
            "UPDATE users SET max_price = ? WHERE telegram_id = ?",
            (price, tid)
        )


def get_user(tid: int) -> tuple | None:
    with get_conn() as c:
        return c.execute(
            "SELECT city, max_price FROM users WHERE telegram_id = ?",
            (tid,)
        ).fetchone()


def get_all_users() -> list[tuple]:
    with get_conn() as c:
        return c.execute(
            "SELECT telegram_id, city, max_price FROM users"
        ).fetchall()


def is_seen(ad_id: str) -> bool:
    with get_conn() as c:
        return c.execute(
            "SELECT 1 FROM seen_ads WHERE ad_id = ?", (ad_id,)
        ).fetchone() is not None


def mark_seen(ad_id: str):
    with get_conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO seen_ads(ad_id) VALUES(?)", (ad_id,)
        )


# ─────────────────────────────────────────────
# ФИЛЬТРАЦИЯ
# ─────────────────────────────────────────────

_BAD_WORDS = [
    "на запчасти", "не работает", "разбит", "после воды",
    "не включается", "треснут", "icloud lock", "заблокирован",
    "требует ремонта", "нерабочий",
]


def is_bad_ad(text: str) -> bool:
    t = text.lower()
    return any(w in t for w in _BAD_WORDS)


# ─────────────────────────────────────────────
# ОПРЕДЕЛЕНИЕ МОДЕЛИ
# ─────────────────────────────────────────────

# Порядок важен: более длинные варианты — раньше
_MODELS = [
    (r'iphone\s?16\s?pro\s?max', 'iPhone 16 Pro Max'),
    (r'iphone\s?16\s?pro',       'iPhone 16 Pro'),
    (r'iphone\s?16\s?plus',      'iPhone 16 Plus'),
    (r'iphone\s?16',             'iPhone 16'),
    (r'iphone\s?15\s?pro\s?max', 'iPhone 15 Pro Max'),
    (r'iphone\s?15\s?pro',       'iPhone 15 Pro'),
    (r'iphone\s?15\s?plus',      'iPhone 15 Plus'),
    (r'iphone\s?15',             'iPhone 15'),
    (r'iphone\s?14\s?pro\s?max', 'iPhone 14 Pro Max'),
    (r'iphone\s?14\s?pro',       'iPhone 14 Pro'),
    (r'iphone\s?14\s?plus',      'iPhone 14 Plus'),
    (r'iphone\s?14',             'iPhone 14'),
    (r'iphone\s?13\s?pro\s?max', 'iPhone 13 Pro Max'),
    (r'iphone\s?13\s?pro',       'iPhone 13 Pro'),
    (r'iphone\s?13\s?mini',      'iPhone 13 Mini'),
    (r'iphone\s?13',             'iPhone 13'),
    (r'iphone\s?12\s?pro\s?max', 'iPhone 12 Pro Max'),
    (r'iphone\s?12\s?pro',       'iPhone 12 Pro'),
    (r'iphone\s?12\s?mini',      'iPhone 12 Mini'),
    (r'iphone\s?12',             'iPhone 12'),
    (r'iphone\s?11\s?pro\s?max', 'iPhone 11 Pro Max'),
    (r'iphone\s?11\s?pro',       'iPhone 11 Pro'),
    (r'iphone\s?11',             'iPhone 11'),
    (r'iphone\s?xs\s?max',       'iPhone XS Max'),
    (r'iphone\s?xs',             'iPhone XS'),
    (r'iphone\s?xr',             'iPhone XR'),
    (r'iphone\s?x[^s]',         'iPhone X'),
    (r'iphone\s?se',             'iPhone SE'),
]


def detect_model(text: str) -> str:
    t = text.lower()
    for pattern, label in _MODELS:
        if re.search(pattern, t):
            return label
    return "Не определена"


# ─────────────────────────────────────────────
# ГОРОД → KUFAR SLUG
# ─────────────────────────────────────────────

_CITY_SLUGS = {
    "минск":       "minsk",
    "брест":       "brest",
    "витебск":     "vitebsk",
    "гомель":      "gomel",
    "гродно":      "grodno",
    "могилёв":     "mogilev",
    "могилев":     "mogilev",
    "барановичи":  "baranovichi",
    "бобруйск":    "bobruisk",
    "борисов":     "borisov",
    "пинск":       "pinsk",
    "орша":        "orsha",
    "мозырь":      "mozyr",
    "солигорск":   "soligorsk",
    "новополоцк":  "novopolotsk",
    "лида":        "lida",
    "молодечно":   "molodechno",
    "жлобин":      "zhlobin",
}


def to_slug(city: str) -> str:
    return _CITY_SLUGS.get(city.lower().strip(), city.lower().strip())


# ─────────────────────────────────────────────
# KUFAR API
# ─────────────────────────────────────────────

_API_URL = (
    "https://cre-api.kufar.by/items-search/v1/engine/v1/"
    "search/rendered-paginated"
)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept":  "application/json",
    "Referer": "https://www.kufar.by/",
}
_TIMEOUT = aiohttp.ClientTimeout(total=30)
_SEARCH_QUERIES = ["iphone", "айфон"]


async def _api_fetch(
    session: aiohttp.ClientSession, query: str, rgn: str
) -> list[dict]:
    params = {
        "query": query,
        "cat":   "1010",  # Смартфоны и телефоны
        "rgn":   rgn,
        "cur":   "BYR",
        "size":  "50",
        "lang":  "ru",
    }
    try:
        async with session.get(
            _API_URL, params=params, headers=_HEADERS, timeout=_TIMEOUT
        ) as resp:
            if resp.status != 200:
                logging.warning(
                    f"Kufar API: статус {resp.status} | query={query!r} | rgn={rgn!r}"
                )
                return []

            data = await resp.json(content_type=None)
            logging.info(f"Ответ API: {str(data)[:500]}")  # ← добавь эту строку
            ads = data.get("ads", [])
            logging.info(f"Kufar API: получено {len(ads)} объявлений | query={query!r}")
            return ads
    except Exception as e:
        logging.error(f"Ошибка запроса к Kufar: {e}")
        return []


def _parse_price(raw: dict) -> tuple[str, int]:
    """
    Kufar хранит цены в центах:
      price_usd = 45000  →  450 USD
      price_byr = 150000 →  1500 BYN
    Возвращает (строка для вывода, int для фильтрации в USD).
    BYN не фильтруется — нет актуального курса.
    """
    byr = raw.get("price_byr")
    if byr:
        val = int(byr) // 100
        return f"{val} BYN", val

    usd = raw.get("price_usd")
    if usd:
        val = int(usd) // 100
        return f"{val} USD", 999999

    return "Не указана", 999999


def _parse_image(raw: dict) -> str | None:
    images = raw.get("images", [])
    if not images:
        return None
    img = images[0]
    img_id = img.get("id", "")
    if len(img_id) >= 4:
        return (
            f"https://rms.kufar.by/v1/gallery/"
            f"{img_id[:2]}/{img_id[2:4]}/{img_id}.jpg"
        )
    return None


async def fetch_new_ads(city: str, max_price: int) -> list[dict]:
    rgn = to_slug(city)
    seen_in_run: set[str] = set()
    result = []

    async with aiohttp.ClientSession() as session:
        for query in _SEARCH_QUERIES:
            raw_list = await _api_fetch(session, query, rgn)

            for raw in raw_list:
                ad_id = str(raw.get("ad_id", ""))
                if not ad_id:
                    continue
                if ad_id in seen_in_run or is_seen(ad_id):
                    continue

                title = (raw.get("subject") or "").strip()
                if not title or is_bad_ad(title):
                    continue

                price_str, price_int = _parse_price(raw)
                if price_int > max_price:
                    continue

                ad_link = raw.get("ad_link") or f"https://www.kufar.by/item/{ad_id}"
                if not ad_link.startswith("http"):
                    ad_link = "https://www.kufar.by" + ad_link

                seen_in_run.add(ad_id)
                result.append({
                    "id":    ad_id,
                    "title": title,
                    "model": detect_model(title),
                    "price": price_str,
                    "city":  city,
                    "url":   ad_link,
                    "image": _parse_image(raw),
                    "date":  datetime.now().strftime("%d.%m.%Y %H:%M"),
                })

    return result


# ─────────────────────────────────────────────
# СООБЩЕНИЕ И ОТПРАВКА
# ─────────────────────────────────────────────

def build_text(ad: dict) -> str:
    return (
        f"📱 Новый iPhone на Kufar\n\n"
        f"Модель:    {ad['model']}\n"
        f"Заголовок: {ad['title']}\n"
        f"Цена:      {ad['price']}\n"
        f"Город:     {ad['city']}\n"
        f"Дата:      {ad['date']}\n\n"
        f"🔗 {ad['url']}"
    )


def send_ad(tid: int, ad: dict):
    text = build_text(ad)
    try:
        if ad["image"]:
            bot.send_photo(tid, ad["image"], caption=text)
            return
    except Exception:
        pass  # если фото недоступно — отправляем текстом
    bot.send_message(tid, text)


# ─────────────────────────────────────────────
# TELEGRAM HANDLERS
# ─────────────────────────────────────────────

_state: dict[int, str] = {}


@bot.message_handler(commands=["start"])
def on_start(msg):
    _state[msg.chat.id] = "city"
    bot.send_message(msg.chat.id, "Напиши город для поиска.\n\nПример: Минск")


@bot.message_handler(commands=["price"])
def on_price(msg):
    row = get_user(msg.chat.id)
    if not row:
        bot.send_message(msg.chat.id, "Сначала настрой город — /start")
        return
    _state[msg.chat.id] = "price"
    bot.send_message(msg.chat.id, "Введи максимальную цену в BYN.\n\nПример: 600")


@bot.message_handler(commands=["info"])
def on_info(msg):
    row = get_user(msg.chat.id)
    if row:
        city, max_price = row
        bot.send_message(
            msg.chat.id,
            f"Город:      {city}\n"
            f"Макс. цена: {max_price} BYN\n\n"
            f"/start — сменить город\n"
            f"/price — сменить цену"
        )
    else:
        bot.send_message(msg.chat.id, "Настройки не найдены. Напиши /start")


@bot.message_handler(func=lambda m: True)
def on_text(msg):
    tid = msg.chat.id
    text = msg.text.strip()
    state = _state.pop(tid, None)

    if state == "city":
        upsert_user(tid, text)
        bot.send_message(
            tid,
            f"✅ Город: {text}\n"
            f"Бот проверяет объявления каждые 5 минут.\n\n"
            f"/price — задать макс. цену\n"
            f"/info — текущие настройки"
        )

    elif state == "price":
        if text.isdigit() and int(text) > 0:
            set_price(tid, int(text))
            bot.send_message(tid, f"✅ Макс. цена: {text} BYN")
        else:
            _state[tid] = "price"  # ждём правильный ввод
            bot.send_message(tid, "Введи целое число больше 0, например: 500")

    else:
        bot.send_message(
            tid,
            "/start — настроить город\n"
            "/price — задать цену\n"
            "/info — текущие настройки"
        )


# ─────────────────────────────────────────────
# МОНИТОРИНГ
# ─────────────────────────────────────────────

async def monitor():
    while True:
        logging.info("Проверка объявлений...")
        users = get_all_users()

        if not users:
            logging.info("Нет пользователей — пропуск")
        else:
            for tid, city, max_price in users:
                try:
                    ads = await fetch_new_ads(city, max_price)
                    logging.info(f"[{city}] новых объявлений: {len(ads)}")

                    for ad in ads:
                        try:
                            # send_ad — синхронная, запускаем в потоке
                            await asyncio.to_thread(send_ad, tid, ad)
                            mark_seen(ad["id"])
                            logging.info(f"Отправлено: {ad['id']}")
                        except Exception as e:
                            logging.error(f"Ошибка отправки {ad['id']}: {e}")

                except Exception as e:
                    logging.error(f"Ошибка мониторинга [{city}]: {e}")

        await asyncio.sleep(300)


# ─────────────────────────────────────────────
# ЗАПУСК
# ─────────────────────────────────────────────
 
async def main():
    init_db()
    asyncio.create_task(monitor())
    logging.info("Бот запущен")
    thread = threading.Thread(target=bot.infinity_polling, daemon=True)
    thread.start()
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())