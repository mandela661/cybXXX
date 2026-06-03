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
    return {"settings": load_settings(), "current_year": datetime.now().year}


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
    total = cfg["price"] * hours
    db.execute(
        "INSERT INTO bookings (user_id,config_name,hours,total,status,created_at) VALUES (?,?,?,?,?,?)",
        (session["user_id"], cfg["name"], hours, total, "new", now()))
    db.commit()
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
    total_hours = sum(b["hours"] for b in bookings)
    total_spent = sum(b["total"] for b in bookings)
    return render_template("cabinet.html", active="cabinet", user=user, bookings=bookings,
                           total_hours=total_hours, total_spent=total_spent)


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
