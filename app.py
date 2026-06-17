"""
CyberX — многостраничный сайт киберспортивного клуба.
Backend: Flask + SQLite (через стандартный модуль sqlite3).

Запуск:
    pip install -r requirements.txt
    python app.py
Открыть: http://127.0.0.1:5000

Демо-доступы:
    Админ:        admin / admin123
    Пользователь: demo  / demo123
"""
import os
import sqlite3
from datetime import datetime
from functools import wraps
from html import escape

from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, g, abort)
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Путь к БД можно переопределить переменной окружения (например, для
# монтированного диска на хостинге): DATABASE_PATH=/var/data/cyberx.db
DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(BASE_DIR, "cyberx.db"))

app = Flask(__name__)
# В продакшене задайте переменную окружения SECRET_KEY
app.secret_key = os.environ.get("SECRET_KEY", "cyberx-dev-secret-change-me")


# ----------------------------------------------------------------------------
# ПОДКЛЮЧЕНИЕ К БАЗЕ ДАННЫХ
# Чтобы перейти на MySQL/PostgreSQL — замените get_db() на соответствующий
# драйвер (PyMySQL / psycopg2) и адаптируйте SQL-запросы (плейсхолдеры %s).
# ----------------------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row          # доступ к колонкам по имени
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    phone         TEXT,
    role          TEXT NOT NULL DEFAULT 'user',
    balance       INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS configs (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT NOT NULL,
    tag     TEXT NOT NULL,
    price   INTEGER NOT NULL,
    cpu     TEXT, gpu TEXT, ram TEXT, storage TEXT,
    icon    TEXT DEFAULT 'fa-desktop'
);
CREATE TABLE IF NOT EXISTS bookings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    config_name TEXT NOT NULL,
    hours       INTEGER NOT NULL,
    total       INTEGER NOT NULL,
    status      TEXT NOT NULL DEFAULT 'new',
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    author     TEXT NOT NULL,
    rating     INTEGER NOT NULL,
    text       TEXT NOT NULL,
    approved   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS peripherals (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    name   TEXT NOT NULL,
    descr  TEXT,
    specs  TEXT,
    badge  TEXT,
    category TEXT DEFAULT 'Прочее',
    icon   TEXT DEFAULT 'fa-keyboard'
);
CREATE TABLE IF NOT EXISTS games (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  TEXT NOT NULL,
    genre TEXT,
    icon  TEXT DEFAULT 'fa-gamepad'
);
CREATE TABLE IF NOT EXISTS promotions (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    title    TEXT NOT NULL,
    descr    TEXT,
    discount INTEGER DEFAULT 0,
    period   TEXT,
    active   INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS game_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    hours INTEGER NOT NULL DEFAULT 0,
    rating INTEGER NOT NULL DEFAULT 1000,
    wins INTEGER NOT NULL DEFAULT 0,
    achievements TEXT,
    last_played TEXT,
    UNIQUE(user_id, game_id)
);
"""

# Тексты сайта, которые админ может менять прямо из панели (хранятся в БД).
DEFAULT_SETTINGS = {
    "site_title":     "CyberX",
    "hero_kicker":    "КИБЕРСПОРТИВНЫЙ КЛУБ НОВОГО ПОКОЛЕНИЯ",
    "hero_title":     "ИГРАЙ НА МАКСИМУМЕ",
    "hero_subtitle":  "RTX 4090, мониторы 360 Гц и топовая периферия. "
                      "Заходи, бронируй ПК и побеждай.",
    "about_title":    "О НАС",
    "about_text":     "CyberX — это пространство, созданное игроками для игроков. "
                      "Мощное железо, выверенная атмосфера и сервис, который "
                      "позволяет сосредоточиться только на игре.",
    "stat_pc":        "40",
    "stat_hours":     "24/7",
    "stat_years":     "5",
    "stat_players":   "12000",
    "contact_phone":  "+7 (965) 737-82-51",
    "contact_email":  "hello@cyberx.ru",
    "contact_address":"г. Москва, ул. Киберспортивная, 1",
    "contact_hours":  "Круглосуточно, без выходных",
    "social_tg":      "https://t.me/",
    "social_vk":      "https://vk.com/",
    "social_dis":     "https://discord.com/",
    "map_lat":        "55.7558",
    "map_lng":        "37.6173",
    "map_zoom":       "15",
}


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _table_columns(db, table):
    return {r["name"] for r in db.execute(f"PRAGMA table_info({table})").fetchall()}


def migrate(db):
    """Идемпотентные миграции — выполняются при каждом старте."""
    db.executescript(SCHEMA)
    # peripherals.category мог отсутствовать в старой БД
    if "category" not in _table_columns(db, "peripherals"):
        db.execute("ALTER TABLE peripherals ADD COLUMN category TEXT DEFAULT 'Прочее'")
    # настройки по умолчанию
    for k, v in DEFAULT_SETTINGS.items():
        if not db.execute("SELECT 1 FROM settings WHERE key=?", (k,)).fetchone():
            db.execute("INSERT INTO settings (key,value) VALUES (?,?)", (k, v))
    db.commit()


def init_db():
    """Создаёт таблицы, выполняет миграции и наполняет стартовыми данными."""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    migrate(db)

    # --- пользователи по умолчанию ---
    if not db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
        db.execute(
            "INSERT INTO users (username,email,password_hash,phone,role,balance,created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            ("admin", "admin@cyberx.ru", generate_password_hash("admin123"),
             "+7 (965) 737-82-51", "admin", 0, now()))
        db.execute(
            "INSERT INTO users (username,email,password_hash,phone,role,balance,created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            ("demo", "demo@cyberx.ru", generate_password_hash("demo123"),
             "+7 (900) 000-00-00", "user", 1500, now()))

    # --- конфигурации ---
    if not db.execute("SELECT 1 FROM configs LIMIT 1").fetchone():
        db.executemany(
            "INSERT INTO configs (name,tag,price,cpu,gpu,ram,storage,icon) VALUES (?,?,?,?,?,?,?,?)",
            [
                ("Standart", "STANDART", 250, "Intel Core i5-13400F", "RTX 4060 Ti",
                 "16GB DDR5", "512GB NVMe", "fa-desktop"),
                ("Pro", "PRO", 400, "Intel Core i7-14700K", "RTX 4080 Super",
                 "32GB DDR5", "1TB NVMe Gen4", "fa-tower-broadcast"),
                ("Stream", "STREAM", 600, "Intel Core i9-14900K", "RTX 4090",
                 "64GB DDR5", "2TB NVMe Gen5", "fa-server"),
            ])

    # --- периферия ---
    if not db.execute("SELECT 1 FROM peripherals LIMIT 1").fetchone():
        db.executemany(
            "INSERT INTO peripherals (name,descr,specs,badge,category,icon) VALUES (?,?,?,?,?,?)",
            [
                ("Razer BlackWidow V4 Pro", "Механическая клавиатура с оптическими свитчами",
                 "Оптические свитчи|Полная раскладка|RGB Chroma", "ТОП", "Клавиатуры", "fa-keyboard"),
                ("Logitech G Pro X Superlight 2", "Беспроводная мышь 63г для киберспорта",
                 "63г|2 кГц опрос|95ч работы", "ХИТ", "Мыши", "fa-computer-mouse"),
                ("SteelSeries Arctis Nova Pro", "Беспроводная гарнитура с шумоподавлением",
                 "ANC|Мультиплатформа|ClearCast микрофон", "ПРЕМИУМ", "Гарнитуры", "fa-headset"),
                ("ASUS ROG Swift PG27AQN", "Монитор 27\" 1440p с частотой 360Hz",
                 "360 Гц|1440p IPS|G-SYNC", "ЭКСКЛЮЗИВ", "Мониторы", "fa-display"),
                ("HyperX QuadCast S", "Студийный микрофон с RGB подсветкой",
                 "4 диаграммы|RGB|Plug & Play", "НОВИНКА", "Микрофоны", "fa-microphone"),
                ("Secretlab Titan Evo", "Эргономичное кресло для киберспорта",
                 "4D подлокотники|Регулировка поясницы|Кожа Prime 2.0", "VIP", "Кресла", "fa-chair"),
                ("Corsair K100 RGB", "Клавиатура с OPX свитчами",
                 "4000 Гц|PBT колпачки|RGB 44 зоны", "НОВИНКА", "Клавиатуры", "fa-keyboard"),
                ("Razer Viper V3 Pro", "Проводная мышь 54г",
                 "54г|HyperPolling 4k|100ч", "ТОП", "Мыши", "fa-computer-mouse"),
            ])

    # --- игры ---
    if not db.execute("SELECT 1 FROM games LIMIT 1").fetchone():
        games = [
            ("CS2", "Шутер", "fa-crosshairs"), ("Dota 2", "MOBA", "fa-shield-halved"),
            ("Valorant", "Шутер", "fa-bullseye"), ("Apex Legends", "Battle Royale", "fa-person-rifle"),
            ("Fortnite", "Battle Royale", "fa-hammer"), ("GTA V", "Экшен", "fa-car"),
            ("Cyberpunk 2077", "RPG", "fa-robot"), ("The Witcher 3", "RPG", "fa-dragon"),
            ("Minecraft", "Песочница", "fa-cube"), ("League of Legends", "MOBA", "fa-khanda"),
            ("PUBG", "Battle Royale", "fa-parachute-box"), ("Rust", "Выживание", "fa-fire"),
            ("Warzone", "Шутер", "fa-helicopter"), ("Elden Ring", "RPG", "fa-ring"),
            ("Rainbow Six Siege", "Шутер", "fa-house-crack"), ("Rocket League", "Спорт", "fa-futbol"),
            ("Overwatch 2", "Шутер", "fa-jet-fighter"), ("World of Tanks", "Экшен", "fa-truck-monster"),
        ]
        db.executemany("INSERT INTO games (name,genre,icon) VALUES (?,?,?)", games)

    # --- игровая статистика пользователей ---
    for user in db.execute("SELECT id FROM users").fetchall():
        ensure_user_game_stats(db, user["id"])
    db.commit()

    # --- отзывы (одобренные) ---
    if not db.execute("SELECT 1 FROM reviews LIMIT 1").fetchone():
        db.executemany(
            "INSERT INTO reviews (author,rating,text,approved,created_at) VALUES (?,?,?,?,?)",
            [
                ("Андрей", 5, "Лучший клуб в городе! RTX 4090 тянет всё на ультрах, пинг минимальный.", 1, now()),
                ("Мария", 5, "Чисто, уютно, периферия топовая. Кресла Secretlab — отдельная любовь.", 1, now()),
                ("Дмитрий", 4, "Отличное место, иногда бывает многолюдно вечером, но это того стоит.", 1, now()),
                ("Игорь", 5, "360Гц мониторы — это другое измерение. Рекомендую всем!", 1, now()),
            ])

    # --- акции ---
    if not db.execute("SELECT 1 FROM promotions LIMIT 1").fetchone():
        db.executemany(
            "INSERT INTO promotions (title,descr,discount,period,active) VALUES (?,?,?,?,?)",
            [
                ("Счастливые часы", "Скидка на любую конфигурацию в будние дни в дневное время.", 30, "Будни 9:00–17:00", 1),
                ("Ночной марафон", "Фиксированная цена за всю ночь — играй сколько хочешь.", 50, "Ежедневно 23:00–8:00", 1),
                ("Приведи друга", "Приведи друга и получите по бонусу на баланс каждый.", 0, "Постоянно", 1),
                ("Турнирные выходные", "Участвуй в турнирах по CS2 и Dota 2 с призовым фондом.", 0, "Сб–Вс", 1),
            ])
    db.commit()
    db.close()


# ----------------------------------------------------------------------------
# НАСТРОЙКИ САЙТА (доступны во всех шаблонах как `settings`)
# ----------------------------------------------------------------------------
def load_settings():
    rows = get_db().execute("SELECT key,value FROM settings").fetchall()
    data = dict(DEFAULT_SETTINGS)
    data.update({r["key"]: r["value"] for r in rows})
    return data


@app.context_processor
def inject_globals():
    return {"settings": load_settings(), "current_year": datetime.now().year, "discount_levels": DISCOUNT_LEVELS}


# ----------------------------------------------------------------------------
# ДЕКОРАТОРЫ ДОСТУПА
# ----------------------------------------------------------------------------
def login_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if not session.get("user_id"):
            flash("Войдите, чтобы продолжить", "info")
            return redirect(url_for("login"))
        return view(*a, **kw)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if session.get("role") != "admin":
            abort(403)
        return view(*a, **kw)
    return wrapped


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return get_db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()


def _int(value, default=0, lo=None, hi=None):
    try:
        v = int(value)
    except (TypeError, ValueError):
        v = default
    if lo is not None:
        v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return v





# ----------------------------------------------------------------------------
# НЕОНОВАЯ ЗАЦИКЛЕННАЯ БЕГУЩАЯ ЛИНИЯ НА ГЛАВНОЙ
# ----------------------------------------------------------------------------
RUNNING_LINE_CSS = """
<style id="cx-running-line-style">
.cx-running-line {
    --cx-red: #ff0033;
    --cx-dark: #050506;
    width: 100vw;
    margin-left: calc(50% - 50vw);
    margin-right: calc(50% - 50vw);
    position: relative;
    z-index: 7;
    overflow: hidden;
    min-height: 60px;
    margin-top: clamp(18px, 2.2vw, 34px);
    margin-bottom: clamp(8px, 1vw, 14px);
    display: flex;
    align-items: center;
    background:
        radial-gradient(circle at 14% 50%, rgba(255, 0, 51, .24), transparent 25%),
        radial-gradient(circle at 86% 50%, rgba(255, 0, 51, .18), transparent 25%),
        linear-gradient(180deg, rgba(255, 255, 255, .035) 0%, rgba(255, 255, 255, 0) 45%),
        linear-gradient(90deg, #050506 0%, #101012 45%, #050506 100%);
    border-top: 2px solid rgba(255, 0, 51, .9);
    border-bottom: 2px solid rgba(255, 0, 51, .9);
    box-shadow:
        0 0 0 1px rgba(255, 0, 51, .16),
        0 0 34px rgba(255, 0, 51, .26),
        0 16px 44px rgba(0, 0, 0, .46),
        inset 0 1px 0 rgba(255, 255, 255, .055),
        inset 0 -1px 0 rgba(255, 255, 255, .035);
}
.cx-running-line::before,
.cx-running-line::after {
    position: absolute;
    top: 50%;
    z-index: 4;
    transform: translateY(-50%);
    color: var(--cx-red);
    font-size: clamp(22px, 2.1vw, 34px);
    line-height: 1;
    font-weight: 300;
    text-shadow: 0 0 18px rgba(255, 0, 51, .9);
    pointer-events: none;
}
.cx-running-line::before {
    content: "‹";
    left: 14px;
}
.cx-running-line::after {
    content: "›";
    right: 14px;
}
.cx-running-line__viewport {
    width: 100%;
    overflow: hidden;
    white-space: nowrap;
    -webkit-mask-image: linear-gradient(90deg, transparent 0%, #000 7%, #000 93%, transparent 100%);
    mask-image: linear-gradient(90deg, transparent 0%, #000 7%, #000 93%, transparent 100%);
}
.cx-running-line__track {
    display: inline-flex;
    width: max-content;
    align-items: center;
    gap: 34px;
    padding: 13px 0;
    animation: cx-running-line-move 32s linear infinite;
    will-change: transform;
}
.cx-running-line__group {
    display: inline-flex;
    align-items: center;
    gap: 34px;
    padding-right: 34px;
}
.cx-running-line__item {
    display: inline-flex;
    align-items: center;
    gap: 11px;
    color: #f4f4f4;
    font-family: Unbounded, Manrope, Arial, sans-serif;
    font-size: clamp(12px, .98vw, 16px);
    font-weight: 800;
    letter-spacing: .045em;
    line-height: 1;
    text-transform: uppercase;
    text-shadow: 0 0 14px rgba(255, 255, 255, .08);
}
.cx-running-line__icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 25px;
    height: 25px;
    flex: 0 0 auto;
    color: var(--cx-red);
    font-size: 18px;
    text-shadow: 0 0 18px rgba(255, 0, 51, .92);
}
.cx-running-line__text strong {
    color: #fff;
    font-weight: 900;
}
.cx-running-line__text em {
    color: var(--cx-red);
    font-style: normal;
    font-weight: 900;
    text-shadow: 0 0 16px rgba(255, 0, 51, .72);
}
.cx-running-line__dot {
    width: 5px;
    height: 5px;
    flex: 0 0 auto;
    border-radius: 50%;
    background: var(--cx-red);
    box-shadow: 0 0 16px rgba(255, 0, 51, .95);
}
@keyframes cx-running-line-move {
    from { transform: translateX(0); }
    to { transform: translateX(-50%); }
}
@media (max-width: 700px) {
    .cx-running-line { min-height: 46px; margin-top: 16px; margin-bottom: 8px; }
    .cx-running-line__track,
    .cx-running-line__group { gap: 26px; }
    .cx-running-line__track { padding: 10px 0; animation-duration: 24s; }
    .cx-running-line__item { gap: 8px; font-size: 10.5px; letter-spacing: .025em; }
    .cx-running-line__icon { width: 20px; height: 20px; font-size: 14px; }
    .cx-running-line__dot { width: 4px; height: 4px; }
}
.cx-promo-strip:not(.cx-running-line),
.cx-promo-ticker:not(.cx-running-line),
.cx-promo-cards,
.cx-promo-card,
.hero-line:not(.cx-running-line),
.hero__line:not(.cx-running-line),
.hero-running-line:not(.cx-running-line),
.running-line:not(.cx-running-line),
.marquee-line:not(.cx-running-line),
.ticker-line:not(.cx-running-line),
.hero-marquee:not(.cx-running-line),
.hero-ticker:not(.cx-running-line),
.promo-marquee:not(.cx-running-line) {
    display: none !important;
}
</style>
"""

RUNNING_LINE_JS = """
<script id="cx-running-line-script">
(function () {
    function placeRunningLine() {
        const line = document.querySelector('[data-cx-running-line]');
        if (!line || line.dataset.ready === '1') return;

        const oldSelectors = [
            '.cx-promo-strip', '.cx-promo-ticker', '.hero-line', '.hero__line',
            '.hero-running-line', '.running-line', '.marquee-line', '.ticker-line',
            '.hero-marquee', '.hero-ticker', '.promo-marquee'
        ];
        const oldLine = oldSelectors
            .map(selector => document.querySelector(selector))
            .find(el => el && el !== line && !el.contains(line));

        if (oldLine) {
            oldLine.replaceWith(line);
        } else {
            const hero = document.querySelector('.hero, .hero-section, #hero, main, .main');
            if (hero && !hero.contains(line)) {
                hero.insertBefore(line, hero.firstChild);
            }
        }
        line.dataset.ready = '1';
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', placeRunningLine);
    } else {
        placeRunningLine();
    }
})();
</script>
"""


def _running_line_icon(title, discount=0):
    text = (title or "").lower()
    if discount:
        return "fa-percent"
    if "ноч" in text or "марафон" in text:
        return "fa-moon"
    if "друг" in text:
        return "fa-user-group"
    if "турнир" in text or "выход" in text:
        return "fa-trophy"
    if "rtx" in text or "пк" in text or "комп" in text:
        return "fa-display"
    if "24" in text or "час" in text:
        return "fa-bolt"
    return "fa-bolt"


def _running_line_items():
    rows = get_db().execute(
        "SELECT title, descr, discount, period FROM promotions WHERE active=1 ORDER BY id"
    ).fetchall()

    items = []
    for promo in rows:
        title = str(promo["title"] or "Акция").strip().upper()
        period = str(promo["period"] or "").strip().upper()
        discount = int(promo["discount"] or 0)

        label = title
        if discount:
            label = f"{label} <em>−{discount}%</em>"
        elif "ДРУГ" in title:
            label = f"{label} — <em>БОНУС ОБОИМ</em>"
        elif "ТУРНИР" in title:
            label = f"{label} <em>CS2 / DOTA 2</em>"

        if period and len(period) <= 24:
            label = f"{label} {period}"

        items.append({
            "icon": _running_line_icon(title, discount),
            "html": label,
        })

    # Постоянные сообщения клуба — чтобы лента выглядела насыщенно, как в примере.
    items.extend([
        {"icon": "fa-display", "html": "RTX 4090 <em>•</em> 360 ГЦ <em>•</em> ТОПОВАЯ ПЕРИФЕРИЯ"},
        {"icon": "fa-bolt", "html": "РАБОТАЕМ <em>24/7</em>"},
        {"icon": "fa-headset", "html": "VIP-ЗОНЫ <em>•</em> КОМАНДНЫЕ БУТКЕМПЫ"},
    ])

    if not items:
        items = [
            {"icon": "fa-percent", "html": "СЧАСТЛИВЫЕ ЧАСЫ <em>−30%</em>"},
            {"icon": "fa-moon", "html": "НОЧНОЙ МАРАФОН <em>23:00–8:00</em>"},
            {"icon": "fa-user-group", "html": "ПРИВЕДИ ДРУГА — <em>БОНУС ОБОИМ</em>"},
            {"icon": "fa-trophy", "html": "ТУРНИРНЫЕ ВЫХОДНЫЕ <em>CS2 / DOTA 2</em>"},
            {"icon": "fa-display", "html": "RTX 4090 <em>•</em> 360 ГЦ <em>•</em> ТОПОВАЯ ПЕРИФЕРИЯ"},
            {"icon": "fa-bolt", "html": "РАБОТАЕМ <em>24/7</em>"},
        ]
    return items


def _running_line_html():
    item_html = []
    for item in _running_line_items():
        icon = escape(item["icon"])
        # label уже формируется только сервером, пользовательские части экранируются ниже.
        # Разрешаем только наши <em> для красных акцентов.
        label = str(item["html"])
        label = label.replace("<em>", "[[EM]]").replace("</em>", "[[/EM]]")
        label = escape(label).replace("[[EM]]", "<em>").replace("[[/EM]]", "</em>")
        item_html.append(
            f'<span class="cx-running-line__item">'
            f'<span class="cx-running-line__icon" aria-hidden="true"><i class="fa-solid {icon}"></i></span>'
            f'<span class="cx-running-line__text"><strong>{label}</strong></span>'
            f'<span class="cx-running-line__dot" aria-hidden="true"></span>'
            f'</span>'
        )
    group = "\n".join(item_html)
    # Две одинаковые группы нужны для бесшовного бесконечного цикла.
    return f"""
{RUNNING_LINE_CSS}
<section class="cx-running-line" aria-label="Бегущая строка с акциями" data-cx-running-line>
    <div class="cx-running-line__viewport">
        <div class="cx-running-line__track">
            <div class="cx-running-line__group">{group}</div>
            <div class="cx-running-line__group" aria-hidden="true">{group}</div>
        </div>
    </div>
</section>
"""


def _insert_after_opening_body(document, chunk):
    lower = document.lower()
    body_pos = lower.find("<body")
    if body_pos == -1:
        return chunk + document
    body_end = lower.find(">", body_pos)
    if body_end == -1:
        return chunk + document
    return document[:body_end + 1] + chunk + document[body_end + 1:]


@app.after_request
def inject_running_line(response):
    """Добавляет на главную неоновую зацикленную строку в стиле CyberX."""
    if request.endpoint != "index":
        return response
    if not response.content_type or "text/html" not in response.content_type.lower():
        return response

    document = response.get_data(as_text=True)
    if "data-cx-running-line" in document:
        return response

    chunk = _running_line_html() + RUNNING_LINE_JS
    document = _insert_after_opening_body(document, chunk)
    response.set_data(document)
    response.headers["Content-Length"] = str(len(response.get_data()))
    return response



# ----------------------------------------------------------------------------
# КЛИКАБЕЛЬНЫЕ FLIP-КАРТОЧКИ В БЛОКЕ О НАС
# ----------------------------------------------------------------------------
ABOUT_FLIP_CARDS_CSS = """
<style id="cx-about-flip-style-v2">
/* CyberX: превращаем уже существующие карточки блока «О нас» в аккуратные flip-карточки. */
.cx-about-flip-card {
    --cx-card-h: 248px;
    position: relative !important;
    min-height: var(--cx-card-h) !important;
    height: auto !important;
    perspective: 1400px !important;
    cursor: pointer !important;
    background: transparent !important;
    border: 0 !important;
    box-shadow: none !important;
    padding: 0 !important;
    overflow: visible !important;
    outline: none !important;
    transform: none !important;
    isolation: isolate !important;
}
.cx-about-flip-card::before {
    content: "" !important;
    position: absolute !important;
    inset: 18px 16px 6px !important;
    z-index: -1 !important;
    border-radius: 30px !important;
    background: radial-gradient(circle, rgba(255, 0, 51, .45), rgba(255, 0, 51, 0) 70%) !important;
    filter: blur(26px) !important;
    opacity: .48 !important;
    transition: opacity .35s ease, transform .35s ease !important;
    pointer-events: none !important;
}
.cx-about-flip-card:hover::before,
.cx-about-flip-card.is-flipped::before {
    opacity: .92 !important;
    transform: translateY(5px) scale(.98) !important;
}
.cx-about-flip-card:focus-visible .cx-about-flip-inner {
    box-shadow: 0 0 0 3px rgba(255, 0, 51, .70), 0 0 52px rgba(255, 0, 51, .42) !important;
}
.cx-about-flip-inner {
    position: relative !important;
    display: grid !important;
    width: 100% !important;
    min-height: var(--cx-card-h) !important;
    transform-style: preserve-3d !important;
    transition: transform .72s cubic-bezier(.18, .86, .24, 1), filter .28s ease !important;
    will-change: transform !important;
}
.cx-about-flip-card:hover .cx-about-flip-inner {
    filter: brightness(1.07) saturate(1.08) !important;
}
.cx-about-flip-card.is-flipped .cx-about-flip-inner {
    transform: rotateY(180deg) !important;
}
.cx-about-flip-front,
.cx-about-flip-back {
    grid-area: 1 / 1 !important;
    position: relative !important;
    display: flex !important;
    min-height: var(--cx-card-h) !important;
    width: 100% !important;
    overflow: hidden !important;
    border: 1px solid rgba(255, 0, 51, .55) !important;
    border-radius: 30px !important;
    background:
        linear-gradient(135deg, rgba(255, 0, 51, .18), transparent 20%),
        radial-gradient(circle at 50% -10%, rgba(255, 0, 51, .30), transparent 44%),
        radial-gradient(circle at 105% 105%, rgba(255, 0, 51, .18), transparent 34%),
        linear-gradient(150deg, rgba(255, 255, 255, .10), rgba(255, 255, 255, .025) 46%, rgba(0, 0, 0, .30)),
        linear-gradient(180deg, #151519 0%, #070708 100%) !important;
    box-shadow:
        0 24px 62px rgba(0, 0, 0, .56),
        0 0 0 1px rgba(255, 255, 255, .04),
        0 0 36px rgba(255, 0, 51, .13),
        inset 0 1px 0 rgba(255, 255, 255, .14),
        inset 0 -1px 0 rgba(255, 0, 51, .24) !important;
    backface-visibility: hidden !important;
    -webkit-backface-visibility: hidden !important;
}
.cx-about-flip-front {
    align-items: center !important;
    justify-content: center !important;
    flex-direction: column !important;
    gap: 18px !important;
    padding: 30px !important;
    z-index: 2 !important;
}
.cx-about-flip-back {
    align-items: stretch !important;
    justify-content: center !important;
    padding: 26px !important;
    transform: rotateY(180deg) !important;
    z-index: 1 !important;
}
.cx-about-flip-front::before,
.cx-about-flip-back::before {
    content: "" !important;
    position: absolute !important;
    inset: 13px !important;
    border: 1px solid rgba(255, 255, 255, .085) !important;
    border-radius: 23px !important;
    pointer-events: none !important;
}
.cx-about-flip-front::after,
.cx-about-flip-back::after {
    content: "" !important;
    position: absolute !important;
    inset: 0 !important;
    background:
        repeating-linear-gradient(120deg, transparent 0 19px, rgba(255, 255, 255, .026) 19px 20px),
        linear-gradient(90deg, transparent, rgba(255, 0, 51, .14), transparent) !important;
    opacity: .48 !important;
    pointer-events: none !important;
}
.cx-about-flip-icon {
    position: relative !important;
    z-index: 1 !important;
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    width: 106px !important;
    height: 106px !important;
    border-radius: 30px !important;
    color: #fff !important;
    font-size: 52px !important;
    background:
        radial-gradient(circle at 30% 18%, rgba(255, 255, 255, .34), transparent 26%),
        linear-gradient(145deg, #ff0033, #8f001c) !important;
    border: 1px solid rgba(255, 255, 255, .20) !important;
    box-shadow:
        0 0 0 9px rgba(255, 0, 51, .08),
        0 0 36px rgba(255, 0, 51, .66),
        0 18px 38px rgba(0, 0, 0, .46),
        inset 0 1px 0 rgba(255, 255, 255, .34) !important;
    transform: rotate(-5deg) translateY(0) !important;
    transition: transform .35s ease, box-shadow .35s ease !important;
}
.cx-about-flip-card:hover .cx-about-flip-icon {
    transform: rotate(0deg) translateY(-4px) scale(1.04) !important;
    box-shadow:
        0 0 0 12px rgba(255, 0, 51, .11),
        0 0 50px rgba(255, 0, 51, .82),
        0 22px 42px rgba(0, 0, 0, .48),
        inset 0 1px 0 rgba(255, 255, 255, .38) !important;
}
.cx-about-flip-hint {
    position: relative !important;
    z-index: 1 !important;
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    padding: 11px 22px !important;
    border-radius: 999px !important;
    border: 1px solid rgba(255, 0, 51, .72) !important;
    color: #fff !important;
    background: rgba(255, 0, 51, .17) !important;
    box-shadow: inset 0 0 18px rgba(255, 0, 51, .14), 0 0 24px rgba(255, 0, 51, .20) !important;
    font-family: Unbounded, Manrope, Arial, sans-serif !important;
    font-size: 12px !important;
    font-weight: 900 !important;
    letter-spacing: .18em !important;
    line-height: 1 !important;
    text-transform: uppercase !important;
    text-shadow: 0 0 16px rgba(255, 0, 51, .68) !important;
}
.cx-about-flip-original {
    position: relative !important;
    z-index: 1 !important;
    display: flex !important;
    flex-direction: column !important;
    justify-content: center !important;
    width: 100% !important;
    max-width: 100% !important;
    min-height: calc(var(--cx-card-h) - 52px) !important;
    color: #f7f7f7 !important;
    text-align: left !important;
}
.cx-about-flip-original h1,
.cx-about-flip-original h2,
.cx-about-flip-original h3,
.cx-about-flip-original h4,
.cx-about-flip-original h5,
.cx-about-flip-original h6,
.cx-about-flip-original .title,
.cx-about-flip-original [class*="title"] {
    color: #fff !important;
    margin-top: 0 !important;
    margin-bottom: 10px !important;
    font-family: Unbounded, Manrope, Arial, sans-serif !important;
    font-weight: 900 !important;
    letter-spacing: .02em !important;
    line-height: 1.18 !important;
    text-transform: uppercase !important;
    text-shadow: 0 0 20px rgba(255, 0, 51, .22) !important;
}
.cx-about-flip-original p,
.cx-about-flip-original li,
.cx-about-flip-original span {
    color: rgba(255, 255, 255, .80) !important;
    line-height: 1.55 !important;
}
.cx-about-flip-original p:last-child,
.cx-about-flip-original ul:last-child,
.cx-about-flip-original ol:last-child {
    margin-bottom: 0 !important;
}
.cx-about-flip-original i[class*="fa-"] {
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    width: 36px !important;
    height: 36px !important;
    min-height: 36px !important;
    margin: 0 0 12px !important;
    border-radius: 12px !important;
    color: #ff0033 !important;
    background: rgba(255, 0, 51, .11) !important;
    box-shadow: 0 0 22px rgba(255, 0, 51, .21) !important;
    font-size: 18px !important;
}
.cx-about-extra-hidden,
.cx-about-force-hidden {
    display: none !important;
    visibility: hidden !important;
    height: 0 !important;
    min-height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
    overflow: hidden !important;
}
@media (max-width: 700px) {
    .cx-about-flip-card { --cx-card-h: 220px; }
    .cx-about-flip-front,
    .cx-about-flip-back { border-radius: 22px !important; }
    .cx-about-flip-front { gap: 16px !important; padding: 24px !important; }
    .cx-about-flip-icon { width: 84px !important; height: 84px !important; font-size: 40px !important; border-radius: 24px !important; }
    .cx-about-flip-hint { padding: 10px 18px !important; font-size: 11px !important; }
    .cx-about-flip-back { padding: 22px !important; }
}
</style>
"""

ABOUT_FLIP_CARDS_JS = r"""
<script id="cx-about-flip-script-v2">
(function () {
    const iconFallbacks = ['fa-microchip', 'fa-display', 'fa-keyboard', 'fa-bolt', 'fa-user-group', 'fa-trophy', 'fa-wifi', 'fa-chair'];

    function cleanText(value) {
        return (value || '').replace(/\s+/g, ' ').trim();
    }

    function isBadArea(node) {
        return !node || !node.closest || Boolean(node.closest('nav, header, footer, form, script, style, [data-cx-running-line]'));
    }

    function isLayoutOnly(node) {
        if (!node || !node.matches) return true;
        const cls = String(node.className || '').toLowerCase();
        return node.matches('section, main, .container, .row, .grid, [class*="grid"], [class*="wrap"], [class*="container"]')
            || /(section|container|wrapper|wrap|grid|row|col|content|inner)/.test(cls);
    }

    function scoreAboutCandidate(node) {
        if (!node || isBadArea(node)) return -1;
        const text = cleanText(node.innerText).toLowerCase();
        const cls = String(node.className || '').toLowerCase();
        const id = String(node.id || '').toLowerCase();
        let score = 0;
        if (id === 'about' || /(^|[-_ ])about($|[-_ ])/.test(id)) score += 90;
        if (/about/.test(cls)) score += 45;
        if (node.querySelector('h1,h2,h3') && /\bо\s*нас\b|преимуществ|почему выбирают|комфорт|железо/i.test(cleanText(node.querySelector('h1,h2,h3').innerText))) score += 95;
        if (/\bо\s*нас\b|преимуществ|почему выбирают|создано игроками|пространство/i.test(text)) score += 50;
        const cardCount = collectCards(node, true).length;
        score += Math.min(cardCount, 10) * 12;
        if (cardCount < 2) score -= 60;
        return score;
    }

    function findAboutSection() {
        const candidates = Array.from(new Set([
            ...document.querySelectorAll('#about, section#about, section.about, .about-section, .section-about, [data-section="about"]'),
            ...document.querySelectorAll('main section, main > div, section, .section, [class*="about"], [id*="about"]')
        ])).filter(node => !isBadArea(node));

        let best = null;
        let bestScore = -1;
        candidates.forEach(node => {
            const score = scoreAboutCandidate(node);
            if (score > bestScore) {
                best = node;
                bestScore = score;
            }
        });
        return bestScore > 0 ? best : null;
    }

    function looksLikeCard(node, loose) {
        if (!node || isBadArea(node)) return false;
        if (node.dataset && (node.dataset.cxAboutFlip === '1' || node.dataset.cxAboutRemoved === '1')) return false;
        if (node.closest && node.closest('.cx-about-flip-inner, .cx-about-extra-hidden, .cx-about-force-hidden')) return false;
        const tag = (node.tagName || '').toLowerCase();
        if (!['div', 'article', 'li'].includes(tag)) return false;
        if (!loose && isLayoutOnly(node)) return false;

        const text = cleanText(node.innerText);
        if (text.length < (loose ? 2 : 8) || text.length > (loose ? 1000 : 900)) return false;

        const cls = String(node.className || '').toLowerCase();
        const classHint = /(card|item|advantage|feature|benefit|why|plus|glass|stat|step|metric|counter)/.test(cls);
        const hasTitle = Boolean(node.querySelector('h3, h4, h5, .title, .card-title, [class*="title"]'));
        const hasText = Boolean(node.querySelector('p, .text, .descr, .description, [class*="text"], [class*="descr"]'));
        const hasIcon = Boolean(node.querySelector('i[class*="fa-"], svg, [class*="icon"]'));

        if (loose) return classHint || hasTitle || hasIcon || text.length >= 2;
        return classHint || (hasTitle && (hasText || hasIcon));
    }

    function collectCards(section, quiet) {
        if (!section) return [];
        const selectors = [
            '.about-card', '.about__card', '.about-item', '.about__item',
            '.feature-card', '.features-card', '.feature-item', '.features__item', '.feature',
            '.advantage-card', '.advantages-card', '.advantage-item', '.advantages__item', '.advantage',
            '.benefit-card', '.benefit-item', '.why-card', '.plus-card', '.info-card', '.glass-card',
            '[class*="about-card"]', '[class*="about__card"]', '[class*="feature"]',
            '[class*="advantage"]', '[class*="benefit"]', '[class*="why"]', '[class*="plus"]'
        ].join(',');

        let cards = Array.from(section.querySelectorAll(selectors)).filter(node => looksLikeCard(node, false));

        // Если классы нестандартные, берём повторяющиеся прямые элементы контейнера.
        Array.from(section.querySelectorAll('div, ul, ol')).forEach(parent => {
            if (isBadArea(parent)) return;
            const children = Array.from(parent.children).filter(child => looksLikeCard(child, false));
            if (children.length >= 2 && children.length <= 12) cards.push(...children);
        });

        cards = cards.filter((card, index, arr) => arr.indexOf(card) === index);
        // Оставляем самые внутренние карточки, чтобы не переворачивать контейнер целиком.
        cards = cards.filter(card => !cards.some(other => other !== card && card.contains(other)));

        if (!quiet && cards.length > 12) return cards.slice(0, 12);
        return cards.slice(0, 12);
    }

    function chooseIcon(card, index) {
        const oldIcon = card.querySelector('i[class*="fa-"]');
        if (oldIcon) {
            const iconClass = Array.from(oldIcon.classList).find(name => name.startsWith('fa-') && !['fa-solid', 'fa-regular', 'fa-brands', 'fa-light', 'fa-thin', 'fa-duotone'].includes(name));
            if (iconClass) return iconClass;
        }
        return iconFallbacks[index % iconFallbacks.length];
    }

    function extractTitle(card, index) {
        const titleNode = card.querySelector('h3, h4, h5, .title, .card-title, [class*="title"]');
        const title = cleanText(titleNode && titleNode.innerText).replace(/^нажми$/i, '');
        if (title) return title;
        const text = cleanText(card.innerText).replace(/^нажми\s*/i, '');
        return text.split(/[.!?]/)[0].slice(0, 72) || ('Карточка ' + (index + 1));
    }

    function sameRow(nodes) {
        if (nodes.length !== 3) return false;
        const rects = nodes.map(node => node.getBoundingClientRect()).filter(rect => rect.width > 0 && rect.height > 0);
        if (rects.length !== 3) return true;
        const top = Math.min(...rects.map(rect => rect.top));
        const bottom = Math.max(...rects.map(rect => rect.top));
        return Math.abs(bottom - top) < 95;
    }

    function hideElement(node) {
        if (!node || (node.dataset && node.dataset.cxAboutKeep === '1')) return;
        node.classList.add('cx-about-extra-hidden', 'cx-about-force-hidden');
        node.setAttribute('aria-hidden', 'true');
        if (node.dataset) node.dataset.cxAboutRemoved = '1';
    }

    function directExtraChildren(parent, excludeSet) {
        return Array.from(parent.children || []).filter(child => {
            if (excludeSet.has(child)) return false;
            if (child.dataset && (child.dataset.cxAboutFlip === '1' || child.dataset.cxAboutRemoved === '1')) return false;
            if (child.querySelector && child.querySelector('.cx-about-flip-card, .cx-about-flip-inner')) return false;
            return looksLikeCard(child, true);
        });
    }

    function findThreeCardContainer(root, excludeSet, minTop) {
        if (!root || isBadArea(root)) return null;
        const containers = [root, ...Array.from(root.querySelectorAll('div, ul, ol, .row, .grid, [class*="grid"], [class*="cards"], [class*="list"], [class*="stat"], [class*="step"], [class*="counter"]'))];
        for (const parent of containers) {
            if (!parent || (parent.dataset && parent.dataset.cxAboutRemoved === '1')) continue;
            if (parent.querySelector && parent.querySelector('.cx-about-flip-card, .cx-about-flip-inner')) continue;
            const children = directExtraChildren(parent, excludeSet);
            if (children.length !== 3 || !sameRow(children)) continue;
            const rect = parent.getBoundingClientRect();
            if (Number.isFinite(minTop) && rect.bottom > 0 && rect.top < minTop - 28) continue;
            return { parent, children };
        }
        return null;
    }

    function removeThreeCardsUnderAbout(section, flipCards) {
        const excludeSet = new Set(flipCards);
        const rects = flipCards.map(card => card.getBoundingClientRect()).filter(rect => rect.width > 0 || rect.height > 0);
        const lastFlipBottom = rects.length ? Math.max(...rects.map(rect => rect.bottom)) : 0;

        // 1) Лишний ряд из трёх карточек внутри этого же блока.
        const inside = findThreeCardContainer(section, excludeSet, lastFlipBottom);
        if (inside) {
            hideElement(inside.parent);
            return;
        }

        // 2) Следующий блок после «О нас»: скрываем первый ближайший ряд/секцию из трёх карточек.
        let sibling = section.nextElementSibling;
        let checked = 0;
        while (sibling && checked < 6) {
            const text = cleanText(sibling.innerText);
            if (!text) {
                sibling = sibling.nextElementSibling;
                checked += 1;
                continue;
            }
            const found = findThreeCardContainer(sibling, excludeSet, -Infinity);
            if (found) {
                const target = found.parent === sibling ? sibling : found.parent;
                hideElement(target);
                return;
            }
            sibling = sibling.nextElementSibling;
            checked += 1;
        }
    }

    function splitExtraCards(cards) {
        // Если старый блок собрал 8 карточек «О нас» + 3 лишние карточки снизу — последние 3 скрываем.
        if (cards.length >= 11) {
            const lastThree = cards.slice(-3);
            const firstPart = cards.slice(0, -3);
            const sameParent = lastThree.every(card => card.parentElement === lastThree[0].parentElement);
            if (sameParent || sameRow(lastThree)) return { flipCards: firstPart, extraCards: lastThree };
        }
        return { flipCards: cards, extraCards: [] };
    }

    function makeFlip(card, index) {
        if (!card || (card.dataset && card.dataset.cxAboutFlip === '1')) return;

        const title = extractTitle(card, index);
        const icon = chooseIcon(card, index);
        const originalHtml = card.innerHTML;

        card.dataset.cxAboutFlip = '1';
        card.classList.add('cx-about-flip-card');
        card.setAttribute('tabindex', '0');
        card.setAttribute('role', 'button');
        card.setAttribute('aria-pressed', 'false');
        card.setAttribute('aria-label', title + ': нажмите, чтобы открыть информацию');

        card.innerHTML = `
            <div class="cx-about-flip-inner">
                <div class="cx-about-flip-front" aria-hidden="false">
                    <span class="cx-about-flip-icon" aria-hidden="true"><i class="fa-solid ${icon}"></i></span>
                    <span class="cx-about-flip-hint">Нажми</span>
                </div>
                <div class="cx-about-flip-back" aria-hidden="true">
                    <div class="cx-about-flip-original">${originalHtml}</div>
                </div>
            </div>`;

        function toggle() {
            const flipped = card.classList.toggle('is-flipped');
            card.setAttribute('aria-pressed', flipped ? 'true' : 'false');
            const front = card.querySelector('.cx-about-flip-front');
            const back = card.querySelector('.cx-about-flip-back');
            if (front) front.setAttribute('aria-hidden', flipped ? 'true' : 'false');
            if (back) back.setAttribute('aria-hidden', flipped ? 'false' : 'true');
        }

        card.addEventListener('click', event => {
            if (event.target.closest('a, button, input, textarea, select, label')) return;
            toggle();
        });
        card.addEventListener('keydown', event => {
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                toggle();
            }
        });
    }

    function init() {
        const section = findAboutSection();
        if (!section || (section.dataset && section.dataset.cxAboutFlipReady === '2')) return;

        const collectedCards = collectCards(section, false);
        if (!collectedCards.length) return;

        const split = splitExtraCards(collectedCards);
        split.extraCards.forEach(hideElement);
        split.flipCards.forEach(makeFlip);
        window.requestAnimationFrame(() => removeThreeCardsUnderAbout(section, split.flipCards));
        if (section.dataset) section.dataset.cxAboutFlipReady = '2';
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init, { once: true });
    } else {
        init();
    }
})();
</script>
"""


@app.after_request
def inject_about_flip_cards(response):
    """Меняет существующие карточки блока «О нас» на красивые flip-карточки и скрывает лишний ряд из трёх карточек."""
    if request.endpoint != "index":
        return response
    if not response.content_type or "text/html" not in response.content_type.lower():
        return response

    document = response.get_data(as_text=True)
    if "cx-about-flip-script-v2" in document:
        return response

    chunk = ABOUT_FLIP_CARDS_CSS + ABOUT_FLIP_CARDS_JS
    document = _insert_after_opening_body(document, chunk)
    response.set_data(document)
    response.headers["Content-Length"] = str(len(response.get_data()))
    return response


# ----------------------------------------------------------------------------
# ИГРОВЫЕ УРОВНИ, СКИДКИ И СТАТИСТИКА
# ----------------------------------------------------------------------------
DISCOUNT_LEVELS = [
    {"name": "Новичок", "min_hours": 0, "percent": 0, "icon": "fa-seedling"},
    {"name": "Bronze", "min_hours": 10, "percent": 5, "icon": "fa-medal"},
    {"name": "Silver", "min_hours": 25, "percent": 7, "icon": "fa-shield-halved"},
    {"name": "Gold", "min_hours": 50, "percent": 10, "icon": "fa-crown"},
    {"name": "Legend", "min_hours": 100, "percent": 15, "icon": "fa-trophy"},
]


def user_total_hours(user_id):
    row = get_db().execute(
        "SELECT COALESCE(SUM(hours), 0) h FROM bookings WHERE user_id=? AND status != 'cancelled'",
        (user_id,),
    ).fetchone()
    return int(row["h"] or 0)


def discount_for_hours(hours):
    hours = int(hours or 0)
    current = DISCOUNT_LEVELS[0]
    for level in DISCOUNT_LEVELS:
        if hours >= level["min_hours"]:
            current = level
    return dict(current)


def next_discount_level(hours):
    hours = int(hours or 0)
    for level in DISCOUNT_LEVELS:
        if hours < level["min_hours"]:
            result = dict(level)
            result["hours_left"] = level["min_hours"] - hours
            return result
    return None


def ensure_user_game_stats(db, user_id):
    db.execute("""
CREATE TABLE IF NOT EXISTS game_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    hours INTEGER NOT NULL DEFAULT 0,
    rating INTEGER NOT NULL DEFAULT 1000,
    wins INTEGER NOT NULL DEFAULT 0,
    achievements TEXT,
    last_played TEXT,
    UNIQUE(user_id, game_id)
);
""")
    games = db.execute("SELECT id, name FROM games ORDER BY id LIMIT 8").fetchall()
    for idx, game in enumerate(games):
        exists = db.execute(
            "SELECT 1 FROM game_stats WHERE user_id=? AND game_id=?",
            (user_id, game["id"]),
        ).fetchone()
        if exists:
            continue
        hours = ((int(user_id) * 11 + int(game["id"]) * 7) % 48) + idx
        wins = max(1, hours * (idx % 5 + 2))
        rating = 900 + hours * 14 + idx * 37
        achievements = [
            "Первый матч",
            "Стабильная серия",
            "Командный игрок" if idx % 2 == 0 else "Точный выстрел",
        ]
        if hours >= 20:
            achievements.append("Опытный игрок")
        if hours >= 40:
            achievements.append("Легенда клуба")
        db.execute(
            """
            INSERT INTO game_stats (user_id, game_id, hours, rating, wins, achievements, last_played)
            VALUES (?,?,?,?,?,?,?)
            """,
            (user_id, game["id"], hours, rating, wins, "|".join(achievements), now()),
        )
    db.commit()


def get_user_game_stats(user_id):
    db = get_db()
    ensure_user_game_stats(db, user_id)
    return db.execute(
        """
        SELECT gs.*, g.name AS game_name, g.genre AS game_genre, g.icon AS game_icon
        FROM game_stats gs
        JOIN games g ON g.id = gs.game_id
        WHERE gs.user_id=?
        ORDER BY gs.hours DESC, g.name
        """,
        (user_id,),
    ).fetchall()


# ----------------------------------------------------------------------------
# ПУБЛИЧНЫЕ СТРАНИЦЫ
# ----------------------------------------------------------------------------
@app.route("/")
def index():
    db = get_db()
    configs = db.execute("SELECT * FROM configs ORDER BY price").fetchall()
    reviews = db.execute("SELECT * FROM reviews WHERE approved=1 ORDER BY id DESC LIMIT 3").fetchall()
    promos = db.execute("SELECT * FROM promotions WHERE active=1 ORDER BY id LIMIT 3").fetchall()
    return render_template("index.html", active="index",
                           configs=configs, reviews=reviews, promos=promos)


@app.route("/configs")
def configs():
    rows = get_db().execute("SELECT * FROM configs ORDER BY price").fetchall()
    return render_template("configs.html", active="configs", configs=rows)


@app.route("/peripherals")
def peripherals():
    rows = get_db().execute("SELECT * FROM peripherals ORDER BY id").fetchall()
    cats = sorted({(r["category"] or "Прочее") for r in rows})
    return render_template("peripherals.html", active="peripherals", items=rows, categories=cats)


@app.route("/games")
def games():
    rows = get_db().execute("SELECT * FROM games ORDER BY name").fetchall()
    genres = sorted({(r["genre"] or "Прочее") for r in rows})
    return render_template("games.html", active="games", games=rows, genres=genres)


@app.route("/promotions")
def promotions():
    rows = get_db().execute("SELECT * FROM promotions WHERE active=1 ORDER BY id").fetchall()
    return render_template("promotions.html", active="promotions", promos=rows)


@app.route("/reviews")
def reviews():
    db = get_db()
    rows = db.execute("SELECT * FROM reviews WHERE approved=1 ORDER BY id DESC").fetchall()
    avg = db.execute("SELECT COALESCE(AVG(rating),0) a FROM reviews WHERE approved=1").fetchone()["a"]
    return render_template("reviews.html", active="reviews", reviews=rows, avg=avg)


@app.route("/contacts")
def contacts():
    return render_template("contacts.html", active="contacts")


# ----------------------------------------------------------------------------
# БРОНИРОВАНИЕ
# ----------------------------------------------------------------------------
@app.route("/book", methods=["POST"])
@login_required
def book():
    db = get_db()
    cfg = db.execute("SELECT * FROM configs WHERE id=?", (request.form.get("config_id"),)).fetchone()
    if not cfg:
        flash("Конфигурация не найдена", "error")
        return redirect(url_for("configs"))
    hours = _int(request.form.get("hours", 1), default=1, lo=1, hi=24)
    base_total = cfg["price"] * hours
    discount = discount_for_hours(user_total_hours(session["user_id"]))
    total = int(round(base_total * (100 - discount["percent"]) / 100))
    db.execute(
        "INSERT INTO bookings (user_id,config_name,hours,total,status,created_at) VALUES (?,?,?,?,?,?)",
        (session["user_id"], cfg["name"], hours, total, "new", now()))
    db.commit()
    if discount["percent"]:
        flash(f"ПК «{cfg['name']}» забронирован на {hours} ч — {total} ₽, скидка {discount['percent']}% ({discount['name']})", "success")
    else:
        flash(f"ПК «{cfg['name']}» забронирован на {hours} ч — {total} ₽", "success")
    return redirect(url_for("cabinet"))


# ----------------------------------------------------------------------------
# ОТЗЫВЫ (добавление)
# ----------------------------------------------------------------------------
@app.route("/reviews/add", methods=["POST"])
def add_review():
    db = get_db()
    user = current_user()
    author = user["username"] if user else (request.form.get("author") or "Гость").strip()
    text = (request.form.get("text") or "").strip()
    rating = _int(request.form.get("rating", 5), default=5, lo=1, hi=5)
    if len(text) < 10:
        flash("Отзыв слишком короткий", "error")
        return redirect(url_for("reviews"))
    db.execute("INSERT INTO reviews (author,rating,text,approved,created_at) VALUES (?,?,?,0,?)",
               (author, rating, text, now()))
    db.commit()
    flash("Спасибо! Отзыв отправлен на модерацию.", "success")
    return redirect(url_for("reviews"))


# ----------------------------------------------------------------------------
# АВТОРИЗАЦИЯ
# ----------------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        user = get_db().execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            flash(f"Добро пожаловать, {user['username']}!", "success")
            return redirect(url_for("admin" if user["role"] == "admin" else "cabinet"))
        flash("Неверный логин или пароль", "error")
        return render_template("login.html", active="login", open_tab="login")
    if session.get("user_id"):
        return redirect(url_for("admin" if session.get("role") == "admin" else "cabinet"))
    return render_template("login.html", active="login")


@app.route("/register", methods=["POST"])
def register():
    db = get_db()
    username = (request.form.get("username") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    phone = (request.form.get("phone") or "").strip()
    if len(username) < 3 or len(password) < 6 or "@" not in email:
        flash("Проверьте корректность данных (логин ≥3, пароль ≥6, валидный email)", "error")
        return render_template("login.html", active="login", open_tab="register")
    if db.execute("SELECT 1 FROM users WHERE username=? OR email=?", (username, email)).fetchone():
        flash("Пользователь с таким логином или email уже существует", "error")
        return render_template("login.html", active="login", open_tab="register")
    db.execute(
        "INSERT INTO users (username,email,password_hash,phone,role,balance,created_at) VALUES (?,?,?,?,?,?,?)",
        (username, email, generate_password_hash(password), phone, "user", 0, now()))
    db.commit()
    user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    session.update(user_id=user["id"], username=user["username"], role=user["role"])
    flash("Регистрация прошла успешно!", "success")
    return redirect(url_for("cabinet"))


@app.route("/logout")
def logout():
    session.clear()
    flash("Вы вышли из аккаунта", "info")
    return redirect(url_for("index"))


# ----------------------------------------------------------------------------
# ЛИЧНЫЙ КАБИНЕТ
# ----------------------------------------------------------------------------
@app.route("/cabinet")
@login_required
def cabinet():
    db = get_db()
    user = current_user()
    if user["role"] == "admin":
        return redirect(url_for("admin"))
    bookings = db.execute(
        "SELECT * FROM bookings WHERE user_id=? ORDER BY id DESC", (user["id"],)).fetchall()
    total_hours = user_total_hours(user["id"])
    total_spent = sum(b["total"] for b in bookings)
    discount = discount_for_hours(total_hours)
    next_discount = next_discount_level(total_hours)
    game_stats = get_user_game_stats(user["id"])
    return render_template("cabinet.html", active="cabinet", user=user, bookings=bookings, total_hours=total_hours, total_spent=total_spent, discount=discount, next_discount=next_discount, game_stats=game_stats)


@app.route("/topup", methods=["POST"])
@login_required
def topup():
    amount = _int(request.form.get("amount", 0), default=0, lo=0)
    db = get_db()
    db.execute("UPDATE users SET balance = balance + ? WHERE id=?", (amount, session["user_id"]))
    db.commit()
    flash(f"Баланс пополнен на {amount} ₽", "success")
    return redirect(url_for("cabinet"))


# ----------------------------------------------------------------------------
# АДМИН-ПАНЕЛЬ
# ----------------------------------------------------------------------------
@app.route("/admin")
@admin_required
def admin():
    db = get_db()
    tab = request.args.get("tab", "dashboard")
    stats = {
        "users":           db.execute("SELECT COUNT(*) c FROM users").fetchone()["c"],
        "bookings":        db.execute("SELECT COUNT(*) c FROM bookings").fetchone()["c"],
        "revenue":         db.execute("SELECT COALESCE(SUM(total),0) s FROM bookings").fetchone()["s"],
        "pending_reviews": db.execute("SELECT COUNT(*) c FROM reviews WHERE approved=0").fetchone()["c"],
        "configs":         db.execute("SELECT COUNT(*) c FROM configs").fetchone()["c"],
        "peripherals":     db.execute("SELECT COUNT(*) c FROM peripherals").fetchone()["c"],
        "games":           db.execute("SELECT COUNT(*) c FROM games").fetchone()["c"],
        "promos":          db.execute("SELECT COUNT(*) c FROM promotions").fetchone()["c"],
    }
    ctx = dict(
        active="admin", tab=tab, stats=stats,
        bookings=db.execute("SELECT b.*, u.username FROM bookings b JOIN users u ON u.id=b.user_id ORDER BY b.id DESC").fetchall(),
        users=db.execute("SELECT * FROM users ORDER BY id").fetchall(),
        all_reviews=db.execute("SELECT * FROM reviews ORDER BY approved, id DESC").fetchall(),
        all_promos=db.execute("SELECT * FROM promotions ORDER BY id").fetchall(),
        configs=db.execute("SELECT * FROM configs ORDER BY id").fetchall(),
        peripherals=db.execute("SELECT * FROM peripherals ORDER BY id").fetchall(),
        games=db.execute("SELECT * FROM games ORDER BY id").fetchall(),
        settings_rows=db.execute("SELECT key,value FROM settings ORDER BY key").fetchall(),
    )
    return render_template("admin.html", **ctx)


# ----- БРОНИРОВАНИЯ -----
@app.route("/admin/booking/<int:bid>/status", methods=["POST"])
@admin_required
def admin_booking_status(bid):
    status = request.form.get("status", "done")
    if status not in ("new", "done", "cancelled"):
        status = "done"
    db = get_db()
    db.execute("UPDATE bookings SET status=? WHERE id=?", (status, bid))
    db.commit()
    flash("Статус бронирования обновлён", "success")
    return redirect(url_for("admin", tab="bookings"))


@app.route("/admin/booking/<int:bid>/delete", methods=["POST"])
@admin_required
def admin_booking_delete(bid):
    db = get_db()
    db.execute("DELETE FROM bookings WHERE id=?", (bid,))
    db.commit()
    flash("Бронирование удалено", "info")
    return redirect(url_for("admin", tab="bookings"))


# ----- ОТЗЫВЫ -----
@app.route("/admin/review/<int:rid>/approve", methods=["POST"])
@admin_required
def admin_review_approve(rid):
    db = get_db()
    db.execute("UPDATE reviews SET approved=1 WHERE id=?", (rid,))
    db.commit()
    flash("Отзыв одобрен", "success")
    return redirect(url_for("admin", tab="reviews"))


@app.route("/admin/review/<int:rid>/delete", methods=["POST"])
@admin_required
def admin_review_delete(rid):
    db = get_db()
    db.execute("DELETE FROM reviews WHERE id=?", (rid,))
    db.commit()
    flash("Отзыв удалён", "info")
    return redirect(url_for("admin", tab="reviews"))


# ----- АКЦИИ -----
@app.route("/admin/promo/add", methods=["POST"])
@admin_required
def admin_promo_add():
    db = get_db()
    discount = _int(request.form.get("discount", 0), default=0, lo=0, hi=100)
    db.execute("INSERT INTO promotions (title,descr,discount,period,active) VALUES (?,?,?,?,1)",
               ((request.form.get("title") or "").strip(),
                (request.form.get("descr") or "").strip(),
                discount, (request.form.get("period") or "").strip()))
    db.commit()
    flash("Акция добавлена", "success")
    return redirect(url_for("admin", tab="promos"))


@app.route("/admin/promo/<int:pid>/edit", methods=["POST"])
@admin_required
def admin_promo_edit(pid):
    db = get_db()
    discount = _int(request.form.get("discount", 0), default=0, lo=0, hi=100)
    db.execute("UPDATE promotions SET title=?, descr=?, discount=?, period=? WHERE id=?",
               ((request.form.get("title") or "").strip(),
                (request.form.get("descr") or "").strip(),
                discount, (request.form.get("period") or "").strip(), pid))
    db.commit()
    flash("Акция обновлена", "success")
    return redirect(url_for("admin", tab="promos"))


@app.route("/admin/promo/<int:pid>/toggle", methods=["POST"])
@admin_required
def admin_promo_toggle(pid):
    db = get_db()
    db.execute("UPDATE promotions SET active = 1 - active WHERE id=?", (pid,))
    db.commit()
    return redirect(url_for("admin", tab="promos"))


@app.route("/admin/promo/<int:pid>/delete", methods=["POST"])
@admin_required
def admin_promo_delete(pid):
    db = get_db()
    db.execute("DELETE FROM promotions WHERE id=?", (pid,))
    db.commit()
    flash("Акция удалена", "info")
    return redirect(url_for("admin", tab="promos"))


# ----- КОНФИГУРАЦИИ -----
@app.route("/admin/config/add", methods=["POST"])
@admin_required
def admin_config_add():
    db = get_db()
    f = request.form
    db.execute(
        "INSERT INTO configs (name,tag,price,cpu,gpu,ram,storage,icon) VALUES (?,?,?,?,?,?,?,?)",
        ((f.get("name") or "").strip(), (f.get("tag") or "").strip().upper(),
         _int(f.get("price", 0), 0, lo=0), (f.get("cpu") or "").strip(),
         (f.get("gpu") or "").strip(), (f.get("ram") or "").strip(),
         (f.get("storage") or "").strip(), (f.get("icon") or "fa-desktop").strip()))
    db.commit()
    flash("Конфигурация добавлена", "success")
    return redirect(url_for("admin", tab="configs"))


@app.route("/admin/config/<int:cid>/edit", methods=["POST"])
@admin_required
def admin_config_edit(cid):
    db = get_db()
    f = request.form
    db.execute(
        "UPDATE configs SET name=?, tag=?, price=?, cpu=?, gpu=?, ram=?, storage=?, icon=? WHERE id=?",
        ((f.get("name") or "").strip(), (f.get("tag") or "").strip().upper(),
         _int(f.get("price", 0), 0, lo=0), (f.get("cpu") or "").strip(),
         (f.get("gpu") or "").strip(), (f.get("ram") or "").strip(),
         (f.get("storage") or "").strip(), (f.get("icon") or "fa-desktop").strip(), cid))
    db.commit()
    flash("Конфигурация обновлена", "success")
    return redirect(url_for("admin", tab="configs"))


@app.route("/admin/config/<int:cid>/delete", methods=["POST"])
@admin_required
def admin_config_delete(cid):
    db = get_db()
    db.execute("DELETE FROM configs WHERE id=?", (cid,))
    db.commit()
    flash("Конфигурация удалена", "info")
    return redirect(url_for("admin", tab="configs"))


# ----- ПЕРИФЕРИЯ -----
@app.route("/admin/peripheral/add", methods=["POST"])
@admin_required
def admin_peripheral_add():
    db = get_db()
    f = request.form
    db.execute(
        "INSERT INTO peripherals (name,descr,specs,badge,category,icon) VALUES (?,?,?,?,?,?)",
        ((f.get("name") or "").strip(), (f.get("descr") or "").strip(),
         (f.get("specs") or "").strip(), (f.get("badge") or "").strip(),
         (f.get("category") or "Прочее").strip(), (f.get("icon") or "fa-keyboard").strip()))
    db.commit()
    flash("Периферия добавлена", "success")
    return redirect(url_for("admin", tab="peripherals"))


@app.route("/admin/peripheral/<int:pid>/edit", methods=["POST"])
@admin_required
def admin_peripheral_edit(pid):
    db = get_db()
    f = request.form
    db.execute(
        "UPDATE peripherals SET name=?, descr=?, specs=?, badge=?, category=?, icon=? WHERE id=?",
        ((f.get("name") or "").strip(), (f.get("descr") or "").strip(),
         (f.get("specs") or "").strip(), (f.get("badge") or "").strip(),
         (f.get("category") or "Прочее").strip(), (f.get("icon") or "fa-keyboard").strip(), pid))
    db.commit()
    flash("Периферия обновлена", "success")
    return redirect(url_for("admin", tab="peripherals"))


@app.route("/admin/peripheral/<int:pid>/delete", methods=["POST"])
@admin_required
def admin_peripheral_delete(pid):
    db = get_db()
    db.execute("DELETE FROM peripherals WHERE id=?", (pid,))
    db.commit()
    flash("Периферия удалена", "info")
    return redirect(url_for("admin", tab="peripherals"))


# ----- ИГРЫ -----
@app.route("/admin/game/add", methods=["POST"])
@admin_required
def admin_game_add():
    db = get_db()
    f = request.form
    db.execute("INSERT INTO games (name,genre,icon) VALUES (?,?,?)",
               ((f.get("name") or "").strip(), (f.get("genre") or "").strip(),
                (f.get("icon") or "fa-gamepad").strip()))
    db.commit()
    flash("Игра добавлена", "success")
    return redirect(url_for("admin", tab="games"))


@app.route("/admin/game/<int:gid>/edit", methods=["POST"])
@admin_required
def admin_game_edit(gid):
    db = get_db()
    f = request.form
    db.execute("UPDATE games SET name=?, genre=?, icon=? WHERE id=?",
               ((f.get("name") or "").strip(), (f.get("genre") or "").strip(),
                (f.get("icon") or "fa-gamepad").strip(), gid))
    db.commit()
    flash("Игра обновлена", "success")
    return redirect(url_for("admin", tab="games"))


@app.route("/admin/game/<int:gid>/delete", methods=["POST"])
@admin_required
def admin_game_delete(gid):
    db = get_db()
    db.execute("DELETE FROM games WHERE id=?", (gid,))
    db.commit()
    flash("Игра удалена", "info")
    return redirect(url_for("admin", tab="games"))


# ----- ПОЛЬЗОВАТЕЛИ -----
@app.route("/admin/user/<int:uid>/edit", methods=["POST"])
@admin_required
def admin_user_edit(uid):
    db = get_db()
    f = request.form
    role = f.get("role", "user")
    if role not in ("user", "admin"):
        role = "user"
    balance = _int(f.get("balance", 0), default=0, lo=0)
    db.execute("UPDATE users SET role=?, balance=?, phone=? WHERE id=?",
               (role, balance, (f.get("phone") or "").strip(), uid))
    db.commit()
    flash("Пользователь обновлён", "success")
    return redirect(url_for("admin", tab="users"))


@app.route("/admin/user/<int:uid>/delete", methods=["POST"])
@admin_required
def admin_user_delete(uid):
    if uid == session.get("user_id"):
        flash("Нельзя удалить самого себя", "error")
        return redirect(url_for("admin", tab="users"))
    db = get_db()
    db.execute("DELETE FROM game_stats WHERE user_id=?", (uid,))
    db.execute("DELETE FROM bookings WHERE user_id=?", (uid,))
    db.execute("DELETE FROM users WHERE id=?", (uid,))
    db.commit()
    flash("Пользователь удалён", "info")
    return redirect(url_for("admin", tab="users"))


# ----- НАСТРОЙКИ САЙТА -----
@app.route("/admin/settings", methods=["POST"])
@admin_required
def admin_settings():
    db = get_db()
    for key in request.form:
        if key.startswith("set_"):
            real = key[4:]
            db.execute(
                "INSERT INTO settings (key,value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (real, request.form.get(key, "")))
    db.commit()
    flash("Настройки сайта сохранены", "success")
    return redirect(url_for("admin", tab="settings"))


# ----------------------------------------------------------------------------


@app.route("/privacy")
def privacy():
    return render_template("privacy.html", active="legal")


@app.route("/personal-data")
def personal_data():
    return render_template("personal_data.html", active="legal")


@app.route("/cookies")
def cookies_policy():
    return render_template("cookies.html", active="legal")


@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", code=403,
                           message="Доступ запрещён"), 403


@app.errorhandler(404)
def notfound(e):
    return render_template("error.html", code=404,
                           message="Страница не найдена"), 404


# Инициализация БД при импорте модуля — нужно для запуска под gunicorn
# (на Render и подобных), где блок __main__ не выполняется.
init_db()


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="127.0.0.1", port=port)
