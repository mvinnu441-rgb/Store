"""
Unified Telegram Account Store Bot
==================================
Base: bot (7).py (working deposit system, reply keyboard, DB schema, session/stock)
Merged: bot (6).py (LZT Market, filters, 360 lookup, promo/giveaways/fights, sell prices)

Run:
    pip install -r requirements.txt
    cp .env.example .env   # fill in secrets
    python bot.py
"""
import os
import sys
import re
import csv
import json
import time
import base64
import struct
import socket
import random
import string
import shutil
import sqlite3
import zipfile
import logging
import asyncio
import hashlib
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

import aiohttp
from telethon import TelegramClient, events, Button
from telethon.errors import (
    SessionPasswordNeededError, MessageNotModifiedError, UserNotParticipantError,
    ChatAdminRequiredError, PhoneCodeInvalidError, PhoneCodeExpiredError,
    PhoneNumberInvalidError, PhoneNumberBannedError, FloodWaitError,
)
from telethon.errors.rpcerrorlist import QueryIdInvalidError
from telethon.sessions import StringSession
from telethon.tl import types as tl_types
from telethon.tl.types import (
    KeyboardButtonCallback, KeyboardButtonUrl, ReplyKeyboardMarkup,
    KeyboardButtonRow, KeyboardButton,
)
from telethon.tl.functions.channels import GetParticipantRequest
from telethon.tl.functions.account import (
    GetPasswordRequest, GetAuthorizationsRequest, ResetAuthorizationRequest,
    UpdatePasswordSettingsRequest,
)
from telethon.tl.functions.auth import ResetAuthorizationsRequest

# =============================================================
# LOGGING
# =============================================================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler(), logging.FileHandler("bot.log", encoding="utf-8")],
)
logging.getLogger("telethon").setLevel(logging.WARNING)
logger = logging.getLogger("bot")


# =============================================================
# ENV
# =============================================================
def load_env_file(path=".env"):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env_file()


def save_env_key(key, val):
    os.environ[key] = val
    if not os.path.exists(".env"):
        return
    try:
        lines = open(".env", encoding="utf-8").readlines()
        found = False
        out = []
        for ln in lines:
            if ln.strip().startswith(f"{key}="):
                out.append(f"{key}={val}\n")
                found = True
            else:
                out.append(ln)
        if not found:
            out.append(f"{key}={val}\n")
        open(".env", "w", encoding="utf-8").writelines(out)
    except Exception:
        pass


def env_int(name, default=0):
    raw = os.getenv(name, "")
    return int(raw) if raw.strip() else default


def env_float(name, default=0.0):
    raw = os.getenv(name, "")
    return float(raw) if raw.strip() else default


def env_list(name, default=""):
    raw = os.getenv(name, default)
    return [x.strip() for x in raw.split(",") if x.strip()]


def _require(name):
    v = os.getenv(name, "").strip()
    if not v:
        raise SystemExit(f"CRITICAL: {name} missing. Copy .env.example to .env and fill it.")
    return v


# =============================================================
# CONFIG (all secrets from .env)
# =============================================================
API_ID = int(_require("API_ID"31626369))
API_HASH = _require("API_HASH")
BOT_TOKEN = _require("BOT_TOKEN")
ADMIN_ID = int(_require("ADMIN_ID"))

ADMIN_LOG_CHANNEL_ID = env_int("ADMIN_LOG_CHANNEL_ID", 0)
PUBLIC_LOG_CHANNEL_ID = env_int("PUBLIC_LOG_CHANNEL_ID", 0)

FORCE_JOIN_ENABLED = os.getenv("FORCE_JOIN_ENABLED", "false").lower() in ("1", "true", "yes", "on")
CHECK_CHANNELS = env_list("CHECK_CHANNELS")
JOIN_URLS = env_list("JOIN_URLS")

UPI_ID = os.getenv("UPI_ID", "").strip()
UPI_MID = os.getenv("UPI_MID", "").strip()
CWALLET_ID = os.getenv("CWALLET_ID", "").strip()
CWALLET_QR = os.getenv("CWALLET_QR", "").strip()

SUPPORT_HANDLE = os.getenv("SUPPORT_HANDLE", "@support").strip()
SALES_URL = os.getenv("SALES_URL", "").strip()
HELP_URL = os.getenv("HELP_URL", "").strip()
TERMS_URL = os.getenv("TERMS_URL", "").strip()
FIXED_2FA = os.getenv("FIXED_2FA_PASSWORD", "").strip()
YEAR_LOOKUP_BOT = os.getenv("YEAR_LOOKUP_BOT", "TGDNAbot").lstrip("@")
OTP_REGEX = os.getenv("OTP_REGEX", r"\b\d{5}\b").strip()
AUTO_CANCEL_SECONDS = env_int("AUTO_CANCEL_SECONDS", 600)
PAID_ORDER_TTL = 1800

LZT_TOKEN = os.getenv("LZT_TOKEN", "").strip()
LZT_BASE_URL = os.getenv("LZT_BASE_URL", "https://prod-api.lzt.market").rstrip("/")
LZT_CURRENCY = os.getenv("LZT_PRICE_CURRENCY", "rub").lower()
LZT_TIMEOUT = env_float("LZT_REQUEST_TIMEOUT", 8.0)
LZT_STOCK_TIMEOUT = env_float("LZT_STOCK_TIMEOUT", 12.0)
LZT_MAX_RETRIES = env_int("LZT_MAX_RETRIES", 2)
LZT_STOCK_RETRIES = env_int("LZT_STOCK_RETRIES", 1)
LZT_CACHE_REFRESH = env_float("LZT_CACHE_REFRESH_SECONDS", 300.0)
LZT_FORCE_IPV4 = os.getenv("LZT_FORCE_IPV4", "1") not in ("0", "false", "no")
LZT_HTTP_FALLBACK = os.getenv("LZT_HTTP_FALLBACK", "1") not in ("0", "false", "no")
LZT_PROXY = os.getenv("LZT_PROXY", "").strip()
LZT_MIN_INTERVAL = env_float("LZT_MIN_REQUEST_INTERVAL", 0.25)
LZT_RL_COOLDOWN = env_float("LZT_RATE_LIMIT_COOLDOWN", 30.0)
LZT_FAST_BUY_RETRIES = env_int("LZT_FAST_BUY_RETRIES", 5)


# =============================================================
# CONSTANTS
# =============================================================
P_YES = "✅"
P_NO = "❌"
P_WARN = "⚠️"
P_OFF = "⛔"
P_MONEY = "💰"
P_CARD = "💳"
P_STORE = "🏬"
P_ACC = "👤"
P_GIFT = "🎁"
P_CAL = "📅"
P_PHONE = "📱"
P_TIME = "⏰"
P_OTP = "🔢"
P_2FA = "🔐"
P_FLAG = "🏳️"
P_GLOBE = "🌍"
P_PKG = "📦"
P_CART = "🛒"
P_DOC = "📃"
P_USDT = "💲"
P_INR = "₹"
P_ID = "🆔"
P_STATS = "📊"
P_USERS = "👥"
P_SOS = "🆘"
P_WAIT = "⏳"
P_ASST = "🤖"
P_UPI = "🏦"
P_CW = "👛"
P_ON = "🟢"
P_OFF = "🔴"

BTN_BUY = "🛒 Buy Account"
BTN_SELL = "💸 Sell Account"
BTN_BUY_SESS = "📁 Buy Sessions"
BTN_SELL_SESS = "📁 Sell Sessions"
BTN_DEPOSIT = "💰 Deposit"
BTN_PROFILE = "👤 My Profile"
BTN_REFER = "🎁 Refer & Earn"
BTN_PROMO = "🎟️ Promo"
BTN_STATS = "📊 Stats"
BTN_SUPPORT = "📞 Support"
BTN_ADMIN = "🔐 Admin Panel"

MENU_LABELS = {BTN_BUY, BTN_SELL, BTN_BUY_SESS, BTN_SELL_SESS, BTN_DEPOSIT,
               BTN_PROFILE, BTN_REFER, BTN_PROMO, BTN_STATS, BTN_SUPPORT, BTN_ADMIN}

CATEGORIES = [
    ("server1",      "🟣", "Server 1"),
    ("server2",      "🟢", "Server 2"),
    ("whatsapp",     "🟩", "WhatsApp"),
    ("allapp",       "🔵", "All App Acc"),
    ("num_change",   "🟡", "Number Change"),
]
CATEGORY_MAP = {k: (icon, label) for k, icon, label in CATEGORIES}

COUNTRY_CODES = {
    "1": ("USA", "🇺🇸"), "7": ("Russia", "🇷🇺"), "20": ("Egypt", "🇪🇬"),
    "27": ("South Africa", "🇿🇦"), "31": ("Netherlands", "🇳🇱"), "32": ("Belgium", "🇧🇪"),
    "33": ("France", "🇫🇷"), "34": ("Spain", "🇪🇸"), "39": ("Italy", "🇮🇹"),
    "44": ("UK", "🇬🇧"), "46": ("Sweden", "🇸🇪"), "48": ("Poland", "🇵🇱"),
    "49": ("Germany", "🇩🇪"), "51": ("Peru", "🇵🇪"), "52": ("Mexico", "🇲🇽"),
    "54": ("Argentina", "🇦🇷"), "55": ("Brazil", "🇧🇷"), "56": ("Chile", "🇨🇱"),
    "57": ("Colombia", "🇨🇴"), "58": ("Venezuela", "🇻🇪"), "60": ("Malaysia", "🇲🇾"),
    "61": ("Australia", "🇦🇺"), "62": ("Indonesia", "🇮🇩"), "63": ("Philippines", "🇵🇭"),
    "66": ("Thailand", "🇹🇭"), "84": ("Vietnam", "🇻🇳"), "86": ("China", "🇨🇳"),
    "90": ("Turkey", "🇹🇷"), "91": ("India", "🇮🇳"), "92": ("Pakistan", "🇵🇰"),
    "93": ("Afghanistan", "🇦🇫"), "94": ("Sri Lanka", "🇱🇰"), "95": ("Myanmar", "🇲🇲"),
    "98": ("Iran", "🇮🇷"), "212": ("Morocco", "🇲🇦"), "213": ("Algeria", "🇩🇿"),
    "234": ("Nigeria", "🇳🇬"), "254": ("Kenya", "🇰🇪"), "255": ("Tanzania", "🇹🇿"),
    "380": ("Ukraine", "🇺🇦"), "880": ("Bangladesh", "🇧🇩"), "964": ("Iraq", "🇮🇶"),
    "966": ("Saudi Arabia", "🇸🇦"), "971": ("UAE", "🇦🇪"), "998": ("Uzbekistan", "🇺🇿"),
}

ISO2_MAP = {
    "AR": "Argentina", "AU": "Australia", "AT": "Austria", "BD": "Bangladesh",
    "BE": "Belgium", "BR": "Brazil", "CA": "Canada", "CL": "Chile", "CN": "China",
    "CO": "Colombia", "EG": "Egypt", "FR": "France", "DE": "Germany", "HK": "Hong Kong",
    "IN": "India", "ID": "Indonesia", "IR": "Iran", "IQ": "Iraq", "IT": "Italy",
    "JP": "Japan", "KZ": "Kazakhstan", "KE": "Kenya", "MY": "Malaysia", "MX": "Mexico",
    "MA": "Morocco", "NP": "Nepal", "NL": "Netherlands", "NG": "Nigeria", "PK": "Pakistan",
    "PE": "Peru", "PH": "Philippines", "PL": "Poland", "PT": "Portugal", "RO": "Romania",
    "RU": "Russia", "SA": "Saudi Arabia", "SG": "Singapore", "ZA": "South Africa",
    "KR": "South Korea", "ES": "Spain", "LK": "Sri Lanka", "TH": "Thailand", "TR": "Turkey",
    "UA": "Ukraine", "AE": "UAE", "GB": "UK", "US": "USA", "UZ": "Uzbekistan", "VN": "Vietnam",
}


# =============================================================
# INIT
# =============================================================
os.makedirs("sessions", exist_ok=True)
session_name = f"bot_session_{BOT_TOKEN.split(':')[0]}"
bot = TelegramClient(session_name, API_ID, API_HASH)
bot.parse_mode = "html"

db = sqlite3.connect("otp_bot_final.db", check_same_thread=False, timeout=20)
db.execute("PRAGMA journal_mode=WAL;")
db.execute("PRAGMA busy_timeout=20000;")
db.execute("PRAGMA foreign_keys=ON;")
cur = db.cursor()


# =============================================================
# GLOBAL STATE
# =============================================================
active_orders = {}
deposit_input = {}
admin_dep_state = {}
user_spam_cooldown = {}
session_buy_state = {}
wd_state = {}
sell_state = {}
user_locks = {}
user_filters = {}
manual_dep_state = {}
deposit_media_messages = {}
promo_state = {}
selling_accounts = {}
cached_lzt_stock = {}
active_filter_keys = {"no_no_any_any_any"}
active_fights = {}
active_giveaways = {}
error_cooldowns = {}
lzt_search_state = {}
lookup_search_state = {}
lookup_action_state = {}
active_lzt_purchases = {}
restore_state = {}
giveaway_ticket_state = {}
waiting_proof = {}
spl_state = {}
reply_kb_sent = set()
_join_cache = {}
_lzt_session = None
_lzt_rate_lock = asyncio.Lock()
_lzt_last_req = 0.0
_lzt_blocked_until = 0.0
_lzt_missing_logged = False


def get_user_lock(uid):
    if uid not in user_locks:
        user_locks[uid] = asyncio.Lock()
    return user_locks[uid]


def is_callback(e):
    return getattr(e, "data", None) is not None


def is_private_event(e):
    chat_id = getattr(e, "chat_id", None)
    sender_id = getattr(e, "sender_id", None)
    return chat_id is None or sender_id is None or int(chat_id) == int(sender_id)


# =============================================================
# DATABASE
# =============================================================
def setup_db():
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        balance INTEGER DEFAULT 0,
        sales_balance INTEGER DEFAULT 0,
        referred_by INTEGER,
        total_deposited INTEGER DEFAULT 0,
        joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        banned INTEGER DEFAULT 0,
        discount INTEGER DEFAULT 0,
        terms_accepted INTEGER DEFAULT 0,
        pref_curr TEXT DEFAULT 'INR',
        ref_rewarded INTEGER DEFAULT 0,
        username TEXT DEFAULT '',
        first_name TEXT DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS stock (
        phone TEXT PRIMARY KEY,
        session_file TEXT,
        country_name TEXT,
        country_icon TEXT DEFAULT '🌍',
        account_year INTEGER,
        category TEXT DEFAULT 'server2',
        price INTEGER,
        available INTEGER DEFAULT 1,
        twofa TEXT DEFAULT 'None',
        added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        seller_id INTEGER DEFAULT NULL,
        extra_json TEXT DEFAULT '{}'
    );
    CREATE TABLE IF NOT EXISTS auto_prices (
        category TEXT, country TEXT, year TEXT, price INTEGER,
        PRIMARY KEY (category, country, year)
    );
    CREATE TABLE IF NOT EXISTS deposits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, amount INTEGER, method_name TEXT,
        status TEXT, date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS upi_orders (
        order_id TEXT PRIMARY KEY, user_id INTEGER, amount INTEGER,
        status TEXT, qr_msg_id INTEGER,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, country TEXT, year INTEGER, price INTEGER,
        phone TEXT, otp TEXT, server TEXT DEFAULT 'Local',
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS custom_payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, caption TEXT, qr_file_id TEXT
    );
    CREATE TABLE IF NOT EXISTS admins (
        user_id INTEGER PRIMARY KEY,
        p_add_stock INTEGER DEFAULT 0, p_manage_stock INTEGER DEFAULT 0,
        p_stats INTEGER DEFAULT 0, p_bal INTEGER DEFAULT 0, p_settings INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS api_credentials (
        id INTEGER PRIMARY KEY AUTOINCREMENT, api_id INTEGER, api_hash TEXT,
        label TEXT, active INTEGER DEFAULT 1,
        added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS custom_countries (code TEXT PRIMARY KEY, name TEXT, flag TEXT);
    CREATE TABLE IF NOT EXISTS lzt_settings (country TEXT PRIMARY KEY, markup_percent INTEGER DEFAULT 20);
    CREATE TABLE IF NOT EXISTS sell_prices (
        country_code TEXT, year TEXT,
        price_good INTEGER DEFAULT 20, price_spam INTEGER DEFAULT 5,
        PRIMARY KEY(country_code, year)
    );
    CREATE TABLE IF NOT EXISTS sell_price_list (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        country_code_or_name TEXT, dial_code TEXT, iso_code TEXT,
        flag_emoji TEXT, price REAL, currency TEXT DEFAULT 'USD', active INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS withdrawals (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount INTEGER,
        method TEXT, details TEXT, status TEXT,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS blacklisted_phones (
        phone TEXT PRIMARY KEY, removed_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS promo_codes (
        code TEXT PRIMARY KEY, value INTEGER, max_uses INTEGER DEFAULT 1, used_count INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS promo_logs (code TEXT, user_id INTEGER, date TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS giveaways (
        id TEXT PRIMARY KEY, prize_name TEXT, ticket_price INTEGER,
        min_participants INTEGER, winners_count INTEGER, status TEXT DEFAULT 'open',
        created_by INTEGER, message_id INTEGER DEFAULT NULL,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS giveaway_tickets (
        giveaway_id TEXT, user_id INTEGER, tickets INTEGER DEFAULT 0,
        PRIMARY KEY(giveaway_id, user_id)
    );
    CREATE TABLE IF NOT EXISTS pending_orders (phone TEXT PRIMARY KEY, user_id INTEGER, price INTEGER, created REAL);
    CREATE TABLE IF NOT EXISTS num_change_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, session_id TEXT,
        old_phone TEXT, new_phone TEXT, status TEXT DEFAULT 'pending',
        admin_note TEXT, date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    # migration safety
    def ensure_col(table, col, decl):
        cols = [r[1] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()]
        if col not in cols:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
    ensure_col("users", "pref_curr", "TEXT DEFAULT 'INR'")
    ensure_col("users", "ref_rewarded", "INTEGER DEFAULT 0")
    ensure_col("users", "username", "TEXT DEFAULT ''")
    ensure_col("users", "first_name", "TEXT DEFAULT ''")
    ensure_col("stock", "seller_id", "INTEGER DEFAULT NULL")
    ensure_col("stock", "extra_json", "TEXT DEFAULT '{}'")
    ensure_col("orders", "server", "TEXT DEFAULT 'Local'")

    defaults = {
        "bot_status": "on", "server1_status": "on", "upi_status": "on", "cwallet_status": "on",
        "sell_status": "on", "numchange_status": "on", "fight_status": "on", "ref_enabled": "on",
        "usdt_rate": "94.0", "ref_percent": "3", "ref_bonus": "3",
        "lzt_global_markup": "20", "rub_inr_rate": "1.05", "eur_inr_rate": "100.0",
        "gbp_inr_rate": "118.0", "cny_inr_rate": "13.0", "uah_inr_rate": "2.3",
        "kzt_inr_rate": "0.2", "byn_inr_rate": "29.0", "try_inr_rate": "2.9",
        "jpy_inr_rate": "0.62", "brl_inr_rate": "17.0",
        "support_url": HELP_URL or "https://t.me/telegram",
        "min_upi_dep": "10", "min_cw_dep": "10",
        "api_id": "", "api_hash": "",
        "upi_revenue": "0",
    }
    for k, v in defaults.items():
        cur.execute("INSERT OR IGNORE INTO settings (key,value) VALUES (?,?)", (k, v))
    cur.execute("INSERT OR IGNORE INTO api_credentials (api_id, api_hash, label, active) VALUES (?,?,?,1)",
                (API_ID, API_HASH, "Primary"))
    db.commit()


setup_db()


# =============================================================
# BASIC HELPERS
# =============================================================
def ensure_user(uid, username=None, first_name=None):
    cur.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (uid,))
    if username:
        cur.execute("UPDATE users SET username=? WHERE user_id=?", (str(username).lstrip("@"), uid))
    if first_name:
        cur.execute("UPDATE users SET first_name=? WHERE user_id=?", (first_name, uid))
    db.commit()


def user_exists(uid):
    return bool(cur.execute("SELECT 1 FROM users WHERE user_id=?", (uid,)).fetchone())


def is_admin(uid):
    if uid == ADMIN_ID:
        return True
    return bool(cur.execute("SELECT 1 FROM admins WHERE user_id=?", (uid,)).fetchone())


VALID_PERMS = {"p_add_stock", "p_manage_stock", "p_stats", "p_bal", "p_settings"}


def has_perm(uid, perm):
    if uid == ADMIN_ID:
        return True
    if perm not in VALID_PERMS:
        return False
    row = cur.execute(f"SELECT {perm} FROM admins WHERE user_id=?", (uid,)).fetchone()
    return bool(row and row[0] == 1)


def is_user_banned(uid):
    row = cur.execute("SELECT banned FROM users WHERE user_id=?", (uid,)).fetchone()
    return bool(row and row[0] == 1)


def is_bot_online():
    row = cur.execute("SELECT value FROM settings WHERE key='bot_status'").fetchone()
    return row[0] == "on" if row else True


def toggle_on(key, default="on"):
    row = cur.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return (row[0] if row and row[0] else default) == "on"


def get_setting(key, default=""):
    row = cur.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row and row[0] is not None else default


def set_setting(key, value):
    cur.execute("INSERT INTO settings (key,value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
    db.commit()


def get_usdt_rate():
    try:
        return float(get_setting("usdt_rate", "94.0"))
    except Exception:
        return 94.0


def to_usd(inr):
    r = get_usdt_rate()
    return round(inr / r, 2) if r > 0 else 0.0


def get_rate(key, default):
    try:
        return float(get_setting(key, str(default)))
    except Exception:
        return float(default)


def get_support_url():
    url = get_setting("support_url", HELP_URL or "https://t.me/telegram").strip()
    if url.startswith("@"):
        return "https://t.me/" + url[1:]
    if not url.startswith("http"):
        return "https://t.me/" + url
    return url


def format_price(uid, inr):
    pref_row = cur.execute("SELECT pref_curr FROM users WHERE user_id=?", (uid,)).fetchone()
    pref = (pref_row[0] if pref_row and pref_row[0] else "INR").upper()
    if pref == "USDT":
        return f"{to_usd(inr):.2f} USDT"
    return f"₹{inr}"


def update_balance(uid, amount, field="balance"):
    if field not in ("balance", "sales_balance"):
        raise ValueError("bad field")
    cur.execute(f"UPDATE users SET {field} = {field} + ? WHERE user_id=?", (amount, uid))
    db.commit()


def terms_accepted(uid):
    row = cur.execute("SELECT terms_accepted FROM users WHERE user_id=?", (uid,)).fetchone()
    return bool(row and row[0])


def cat_label(cat):
    icon, label = CATEGORY_MAP.get(cat, ("⚪", cat))
    return f"{icon} {label}"


def get_flag_by_country_name(name):
    for code, (c_name, c_flag) in COUNTRY_CODES.items():
        if c_name == name:
            return c_flag
    row = cur.execute("SELECT flag FROM custom_countries WHERE name=?", (name,)).fetchone()
    if row:
        return row[0]
    row = cur.execute("SELECT country_icon FROM stock WHERE country_name=? LIMIT 1", (name,)).fetchone()
    return row[0] if row and row[0] else "🌍"


def get_country_info(phone):
    phone = str(phone).replace(" ", "").replace("+", "")
    customs = cur.execute("SELECT code, name, flag FROM custom_countries").fetchall()
    customs.sort(key=lambda x: len(x[0]), reverse=True)
    for code, name, flag in customs:
        if phone.startswith(code):
            return name, flag
    for L in (3, 2, 1):
        prefix = phone[:L]
        if prefix in COUNTRY_CODES:
            return COUNTRY_CODES[prefix]
    return "Unknown", "🌍"


def mask_phone(phone):
    p = str(phone)
    return f"{p[:2]}•••{p[-4:]}" if len(p) > 6 else p


def country_hash(name):
    return hashlib.md5(str(name).encode("utf-8")).hexdigest()[:10]


def resolve_country(category, h):
    rows = cur.execute("SELECT DISTINCT country_name FROM stock WHERE category=?", (category,)).fetchall()
    for (n,) in rows:
        if country_hash(n) == h:
            return n
    return None


def all_country_names(category):
    names = set(v[0] for v in COUNTRY_CODES.values())
    for (c,) in cur.execute("SELECT DISTINCT country_name FROM stock WHERE category=?", (category,)).fetchall():
        names.add(c)
    for (c,) in cur.execute("SELECT DISTINCT name FROM custom_countries").fetchall():
        names.add(c)
    return names


def resolve_any_country(category, h):
    for n in all_country_names(category):
        if country_hash(n) == h:
            return n
    return None


def find_existing_price(country, category, year=None):
    if year is not None:
        r = cur.execute(
            "SELECT price FROM stock WHERE country_name=? AND category=? AND account_year=? LIMIT 1",
            (country, category, int(year))).fetchone()
        if r:
            return r[0]
    r = cur.execute("SELECT price FROM stock WHERE country_name=? AND category=? LIMIT 1",
                    (country, category)).fetchone()
    return r[0] if r else None


def user_final_price(uid, base):
    row = cur.execute("SELECT discount FROM users WHERE user_id=?", (uid,)).fetchone()
    d = row[0] if row else 0
    return base if d == 0 else int(base * (100 - d) / 100)


def delete_session_files(path):
    base = path[:-8] if path.endswith(".session") else path
    for ext in (".session", ".session-wal", ".session-shm", ".session-journal"):
        try:
            if os.path.exists(base + ext):
                os.remove(base + ext)
        except Exception:
            pass


async def safe_answer_cb(e, text=None, alert=False):
    try:
        await e.answer(text, alert=alert)
    except QueryIdInvalidError:
        pass
    except Exception:
        pass


async def safe_show_message(e, text, buttons=None, link_preview=False):
    if is_callback(e) and hasattr(e, "edit"):
        try:
            return await e.edit(text, buttons=buttons, link_preview=link_preview)
        except TypeError:
            return await e.edit(text, buttons=buttons)
        except MessageNotModifiedError:
            return None
    try:
        return await e.respond(text, buttons=buttons, link_preview=link_preview)
    except TypeError:
        return await e.respond(text, buttons=buttons)


async def send_admin_error(err, trace=""):
    sig = f"{err}_{trace[:100]}"
    now = time.time()
    if sig in error_cooldowns and now - error_cooldowns[sig] < 600:
        return
    error_cooldowns[sig] = now
    try:
        await bot.send_message(ADMIN_ID,
            f"🚨 <b>SYSTEM EXCEPTION</b>\n<b>Error:</b> {err}\n<pre>{trace[:1500]}</pre>")
    except Exception:
        pass


# =============================================================
# LOGGING (admin + public)
# =============================================================
async def get_user_log_label(uid):
    try:
        ent = await bot.get_entity(int(uid))
        username = f"@{ent.username}" if getattr(ent, "username", None) else "NoUsername"
        name = getattr(ent, "first_name", None) or str(uid)
        return f"{name} ({username}) | <code>{uid}</code>"
    except Exception:
        return f"<code>{uid}</code>"


async def send_log(text, channel, label="log"):
    if not channel:
        return
    try:
        await bot.send_message(channel, text)
    except Exception as ex:
        logger.warning(f"{label} send failed: {ex}")


async def log_deposit(uid, amount, method):
    logger.info(f"Deposit: {uid} ₹{amount} via {method}")
    user_label = await get_user_log_label(uid)
    admin = (f"🚀 <b>NEW DEPOSIT</b>\nUser: {user_label}\nAmount: ₹{amount}\n"
             f"Method: {method}\n\nThanks for deposit!")
    public = (f"🚀 <b>New Deposit Success</b>\nAmount: ₹{amount}\nMethod: {method}\n\nThanks for deposit!")
    await send_log(admin, ADMIN_LOG_CHANNEL_ID, "admin")
    await send_log(public, PUBLIC_LOG_CHANNEL_ID, "public")


async def log_purchase(uid, country, price, paid, year, qty, phone=None, server="Local"):
    logger.info(f"Purchase: {uid} {country} {price} {paid} {year} {qty} {phone} {server}")
    user_label = await get_user_log_label(uid)
    admin = (f"⚡ <b>NEW PURCHASE</b>\nUser: {user_label}\nCountry: {country}\n"
             f"Price: ₹{price}\nTotal: ₹{paid}\nYear: {year}\nQty: {qty}\n"
             f"Number: {mask_phone(phone or '')}\nServer: {server}")
    public = (f"⚡ <b>New Purchase Success</b>\nAmount: {qty}\nPrice: ₹{price}\n"
              f"Country: {country}\nServer: {server}")
    await send_log(admin, ADMIN_LOG_CHANNEL_ID, "admin")
    await send_log(public, PUBLIC_LOG_CHANNEL_ID, "public")


async def log_withdraw(uid, amount, method, status):
    user_label = await get_user_log_label(uid)
    await send_log(
        f"💸 <b>WITHDRAW {status.upper()}</b>\nUser: {user_label}\nAmount: ₹{amount}\nMethod: {method}",
        ADMIN_LOG_CHANNEL_ID, "admin")


# =============================================================
# FORCE JOIN / TERMS
# =============================================================
async def check_channel_joined(uid):
    if is_admin(uid) or not FORCE_JOIN_ENABLED or not CHECK_CHANNELS:
        return True
    for ch in CHECK_CHANNELS:
        try:
            ch_id = int(ch) if ch.lstrip("-").isdigit() else ch
            try:
                await bot(GetParticipantRequest(channel=ch_id, participant=uid))
            except ValueError:
                entity = await bot.get_entity(ch_id)
                await bot(GetParticipantRequest(channel=entity, participant=uid))
        except UserNotParticipantError:
            return False
        except ChatAdminRequiredError:
            logger.warning(f"Bot not admin in {ch}")
            return True
        except Exception as ex:
            logger.warning(f"channel check fail-safe: {ex}")
            return True
    return True


async def is_joined_cached(uid):
    if is_admin(uid):
        return True
    t = _join_cache.get(uid)
    if t and time.time() - t < 60:
        return True
    ok = await check_channel_joined(uid)
    if ok:
        _join_cache[uid] = time.time()
    return ok


def get_join_buttons():
    rows = [[Button.url(f"📢 Join Channel {i+1}", u)] for i, u in enumerate(JOIN_URLS) if u]
    rows.append([Button.inline("✅ Verify Joined", "verify_join")])
    return rows


def get_terms_buttons():
    rows = []
    if TERMS_URL:
        rows.append([Button.url("📜 Read Terms & Conditions", TERMS_URL)])
    rows.append([Button.inline("✅ Accept", "tc_accept"), Button.inline("❌ Reject", "tc_reject")])
    return rows


JOIN_MSG = f"{P_WARN} <b>You must join our channels first!</b>\nJoin all required channels then tap Verify Joined."
TERMS_MSG = f"{P_DOC} <b>TERMS & CONDITIONS</b>\nPlease read and accept our Terms before using the bot."


# =============================================================
# 1) LZT MARKET (Server 1) — from bot (6)
# =============================================================
def resolve_lzt_token():
    if LZT_TOKEN:
        return LZT_TOKEN
    row = cur.execute("SELECT value FROM settings WHERE key='lzt_token'").fetchone()
    return (row[0] or "").strip() if row else ""


def lzt_markup(country):
    row = cur.execute("SELECT markup_percent FROM lzt_settings WHERE LOWER(country)=LOWER(?)", (country,)).fetchone()
    if not row:
        row = cur.execute("SELECT value FROM settings WHERE key='lzt_global_markup'").fetchone()
    try:
        return int(float(row[0])) if row else 20
    except Exception:
        return 20


def lzt_currency_rate(cur_code):
    cur_code = (cur_code or LZT_CURRENCY).lower()
    if cur_code == "usd":
        return get_usdt_rate()
    return get_rate(f"{cur_code}_inr_rate", 1.05)


def lzt_price_breakdown(item, markup_percent):
    raw = item.get("price_with_fee") or item.get("priceWithSellerFee") or item.get("price") or 0
    try:
        market_price = float(raw)
    except (TypeError, ValueError):
        market_price = 0.0
    cur_code = (item.get("currency") or LZT_CURRENCY).lower()
    inr_base = market_price * lzt_currency_rate(cur_code)
    try:
        markup_percent = int(float(markup_percent))
    except Exception:
        markup_percent = 20
    markup_amt = max(0, int(round(inr_base * (markup_percent / 100))))
    base_price = max(0, int(round(inr_base)))
    return {
        "market_price": market_price, "currency": cur_code.upper(),
        "base_inr": base_price, "markup_percent": markup_percent,
        "markup_inr": markup_amt, "final_inr": max(1, base_price + markup_amt),
    }


async def wait_lzt_ratelimit():
    global _lzt_last_req
    async with _lzt_rate_lock:
        now = time.monotonic()
        scheduled = max(now, _lzt_blocked_until, _lzt_last_req + LZT_MIN_INTERVAL)
        wait = scheduled - now
        _lzt_last_req = scheduled
    if wait > 0:
        await asyncio.sleep(wait)


async def get_lzt_session():
    global _lzt_session
    if _lzt_session is None or _lzt_session.closed:
        kw = {"limit": 5, "ttl_dns_cache": 300, "keepalive_timeout": 30}
        if LZT_FORCE_IPV4:
            kw["family"] = socket.AF_INET
        _lzt_session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(**kw), trust_env=True)
    return _lzt_session


async def close_lzt_session():
    global _lzt_session
    if _lzt_session and not _lzt_session.closed:
        await _lzt_session.close()
    _lzt_session = None


async def apply_lzt_cooldown(retry_after=None):
    global _lzt_blocked_until
    w = max(float(retry_after or 0), LZT_RL_COOLDOWN)
    _lzt_blocked_until = max(_lzt_blocked_until, time.monotonic() + w)
    logger.warning(f"LZT rate limited for {w:.1f}s")


def clean_params(p):
    if not p:
        return None
    out = {}
    for k, v in p.items():
        if v is None:
            continue
        if isinstance(v, (list, tuple)):
            vals = [str(x) for x in v if x is not None]
            if vals:
                out[str(k)] = vals
        else:
            out[str(k)] = str(v)
    return out or None


def lzt_sync_request(method, url, headers, params=None, data=None, timeout=None, ret_err=False, proxy=None):
    method = method.upper()
    if params:
        url = f"{url}?{urllib.parse.urlencode(params, doseq=True)}"
    body = json.dumps(data).encode() if (method != "GET" and data is not None) else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy})) if proxy else None
    try:
        call = opener.open if opener else urllib.request.urlopen
        with call(req, timeout=timeout or LZT_TIMEOUT) as r:
            txt = r.read().decode("utf-8", "replace")
            return json.loads(txt) if txt else {}
    except urllib.error.HTTPError as ex:
        txt = ex.read().decode("utf-8", "replace")
        if ret_err:
            try:
                err = json.loads(txt)
            except Exception:
                err = {"error": txt}
            err["http_status"] = ex.code
            return err
        raise


async def lzt_fallback(method, url, headers, params=None, data=None, timeout=None, ret_err=False):
    await wait_lzt_ratelimit()
    try:
        return await asyncio.to_thread(lzt_sync_request, method, url, headers, params, data, timeout, ret_err, LZT_PROXY or None)
    except urllib.error.HTTPError as ex:
        if ex.code == 429:
            await apply_lzt_cooldown()
            return {"error": "rate limited", "http_status": 429} if ret_err else None
        raise


async def lzt_request(method, endpoint, params=None, data=None, ret_err=False, timeout=None, retries=None, notify=True):
    global _lzt_missing_logged
    token = resolve_lzt_token()
    if not token:
        if not _lzt_missing_logged:
            _lzt_missing_logged = True
            logger.error("LZT token missing")
            await send_admin_error("LZT token missing", "Set LZT_TOKEN in .env")
        return None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "TgsellBot/2.0",
    }
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    url = f"{LZT_BASE_URL}{endpoint}"
    params = clean_params(params)
    timeout_total = timeout or (LZT_STOCK_TIMEOUT if endpoint == "/telegram" else LZT_TIMEOUT)
    retries = max(1, retries or (LZT_STOCK_RETRIES if endpoint == "/telegram" else LZT_MAX_RETRIES))
    tmo = aiohttp.ClientTimeout(total=timeout_total)

    try:
        session = await get_lzt_session()
        for attempt in range(1, retries + 1):
            try:
                kw = {"headers": headers, "params": params, "timeout": tmo}
                if LZT_PROXY:
                    kw["proxy"] = LZT_PROXY
                if method.upper() == "POST":
                    kw["json"] = data
                    ctx = session.post(url, **kw)
                else:
                    ctx = session.get(url, **kw)

                await wait_lzt_ratelimit()
                async with ctx as r:
                    txt = await r.text()
                    if r.status == 429:
                        await apply_lzt_cooldown()
                        if attempt < retries:
                            await asyncio.sleep(LZT_RL_COOLDOWN)
                            continue
                        return {"error": "rate limited", "http_status": 429} if ret_err else None
                    if r.status >= 500 and attempt < retries:
                        await asyncio.sleep(0.25 * attempt)
                        continue
                    if r.status >= 400:
                        if ret_err:
                            try:
                                err = json.loads(txt)
                            except Exception:
                                err = {"error": txt}
                            err["http_status"] = r.status
                            return err
                        return None
                    try:
                        return json.loads(txt) if txt else {}
                    except Exception:
                        return None
            except (aiohttp.ClientError, asyncio.TimeoutError) as ex:
                if attempt < retries:
                    await asyncio.sleep(0.2 * attempt)
                    continue
                if LZT_HTTP_FALLBACK:
                    try:
                        return await lzt_fallback(method, url, headers, params, data, timeout_total, ret_err)
                    except Exception as fex:
                        logger.warning(f"LZT fallback failed: {fex}")
                return None
    except Exception as ex:
        if LZT_HTTP_FALLBACK:
            try:
                return await lzt_fallback(method, url, headers, params, data, timeout_total, ret_err)
            except Exception:
                pass
        return None


def extract_lzt_otp(res):
    """Collect OTP candidates from trusted fields only."""
    if not isinstance(res, dict):
        return None
    candidates = []

    def walk(v, key=""):
        if isinstance(v, dict):
            for k, sub in v.items():
                if k in ("code", "otp", "login_code", "telegram_login_code", "telegramLoginCode", "message", "text"):
                    walk(sub, k)
                elif k in ("data", "item", "telegram", "response", "result", "codes"):
                    walk(sub, k)
        elif isinstance(v, list):
            for item in v:
                walk(item, key)
        elif isinstance(v, str) and key in ("code", "otp", "login_code", "telegram_login_code", "telegramLoginCode",
                                           "message", "text", "sms", "telegram_message"):
            if "login detected" in v.lower():
                return
            m = re.search(OTP_REGEX, v)
            if m:
                candidates.append(m.group(0))

    walk(res)
    return candidates[0] if candidates else None


async def get_lzt_verified_otp(item_id, attempts=3):
    seen = []
    for _ in range(max(1, attempts)):
        res = await lzt_request("GET", f"/{item_id}/telegram-login-code", ret_err=True)
        code = extract_lzt_otp(res)
        if code:
            seen.append(code)
            if seen.count(code) >= 2:
                return code, True
        await asyncio.sleep(1.5)
    if seen:
        return seen[-1], False
    return None, False


async def lzt_fast_buy(item_id, market_price):
    current = market_price
    for attempt in range(1, LZT_FAST_BUY_RETRIES + 1):
        body = {"price": current} if current is not None else None
        res = await lzt_request("POST", f"/{item_id}/fast-buy",
                                params={"currency": LZT_CURRENCY}, data=body, ret_err=True)
        if isinstance(res, dict) and not res.get("error"):
            return res
        m = re.search(r"costs now\s+([0-9]+(?:\.[0-9]+)?)",
                      str(res.get("error") or ""), re.IGNORECASE) if isinstance(res, dict) else None
        if m:
            try:
                current = float(m.group(1))
            except Exception:
                pass
        await asyncio.sleep(0.5)
    return res


async def fetch_lzt_country(country, spam, geoblock, offline, mail, premium):
    iso = None
    for code, (name, _flag) in COUNTRY_CODES.items():
        if name == country:
            iso = {"USA": "US", "UK": "GB", "UAE": "AE"}.get(name, None)
            break
    iso = iso or (country[:2].upper() if country else "")
    params = {
        "country[]": iso or country,
        "spam": spam if spam != "any" else None,
        "nsb": 1, "pmin": 0.01, "pmax": 1000,
        "page": 1, "per_page": 40, "currency": LZT_CURRENCY,
        "password": "no",
    }
    if offline != "any":
        try:
            params["daybreak"] = int(offline)
        except Exception:
            pass
    if premium != "any":
        params["premium"] = premium

    res = await lzt_request("GET", "/telegram", params=params, timeout=LZT_STOCK_TIMEOUT, retries=LZT_STOCK_RETRIES, notify=False)
    if not isinstance(res, dict) or "items" not in res:
        return None
    items = res.get("items") or []
    if not items:
        return (country, 0, 0.0)
    items = sorted(items, key=lambda x: float(x.get("price") or x.get("priceWithSellerFee") or 99999))
    markup = lzt_markup(country)
    final = lzt_price_breakdown(items[0], markup)["final_inr"]
    return (country, len(items), final)


async def cache_lzt_stock_loop():
    while True:
        try:
            fkey = "no_no_any_any_any"
            cache = cached_lzt_stock.setdefault(fkey, {})
            for country in all_country_names("server1"):
                data = await fetch_lzt_country(country, "no", "any", "any", "any", "any")
                if data:
                    cache[country] = (data[1], data[2])
        except Exception as ex:
            logger.warning(f"LZT cache loop: {ex}")
        await asyncio.sleep(max(60, LZT_CACHE_REFRESH))


# =============================================================
# 2) SESSION / ACCOUNT UTILITIES
# =============================================================
def hex_to_string_session(auth_hex, dc_id=2):
    dc_ip = {1: "149.154.175.53", 2: "149.154.167.51", 3: "149.154.175.100",
             4: "149.154.167.91", 5: "91.108.56.130"}
    ip = dc_ip.get(int(dc_id or 2), "149.154.167.51")
    key = bytes.fromhex(str(auth_hex or "")[:512])
    data = struct.pack(">B4sH256s", int(dc_id or 2), socket.inet_aton(ip), 443, key)
    return StringSession("1" + base64.urlsafe_b64encode(data).decode())


def get_random_api_credentials():
    row = cur.execute("SELECT api_id, api_hash FROM api_credentials WHERE active=1 ORDER BY RANDOM() LIMIT 1").fetchone()
    if row:
        return int(row[0]), str(row[1])
    return API_ID, API_HASH


async def detect_account_year(client):
    try:
        try:
            await client.delete_dialog(YEAR_LOOKUP_BOT)
        except Exception:
            pass
        await client.send_message(YEAR_LOOKUP_BOT, "/start")
        me = await client.get_me()
        await asyncio.sleep(1)
        await client.send_message(YEAR_LOOKUP_BOT, str(me.id))
        for _ in range(8):
            await asyncio.sleep(1.5)
            for m in await client.get_messages(YEAR_LOOKUP_BOT, limit=3):
                if m.text:
                    mm = re.search(r"(?:Created|Age|Registration)[^\d]*(\d{4})", m.text, re.IGNORECASE)
                    if mm:
                        return int(mm.group(1))
    except Exception:
        pass
    return 2024


async def force_2fa(client, old_pwd=None, new_pwd=None):
    new_pwd = new_pwd or FIXED_2FA
    if not new_pwd:
        return False, "FIXED_2FA_PASSWORD not set"
    try:
        pwd = await client(GetPasswordRequest())
        if pwd.has_password:
            if not old_pwd or old_pwd == "None":
                return False, "old 2FA unknown"
            if old_pwd == new_pwd:
                return True, None
            await client.edit_2fa(current_password=old_pwd, new_password=new_pwd, hint="")
        else:
            await client.edit_2fa(new_password=new_pwd, hint="")
        return True, None
    except Exception as ex:
        return False, str(ex)[:120]


# =============================================================
# 3) REPLY KEYBOARD + ROUTER (persistent menu)
# =============================================================
def get_persistent_menu(uid):
    rows = [
        [KeyboardButton(BTN_BUY), KeyboardButton(BTN_SELL)],
        [KeyboardButton(BTN_BUY_SESS), KeyboardButton(BTN_SELL_SESS)],
        [KeyboardButton(BTN_DEPOSIT), KeyboardButton(BTN_PROFILE)],
        [KeyboardButton(BTN_REFER), KeyboardButton(BTN_PROMO)],
        [KeyboardButton(BTN_STATS), KeyboardButton(BTN_SUPPORT)],
    ]
    if is_admin(uid):
        rows.append([KeyboardButton(BTN_ADMIN)])
    return ReplyKeyboardMarkup([KeyboardButtonRow(r) for r in rows], resize=True)


async def ensure_reply_keyboard(uid):
    if uid in reply_kb_sent:
        return
    reply_kb_sent.add(uid)
    try:
        await bot.send_message(uid, "⌨️ <b>Quick menu enabled.</b>", buttons=get_persistent_menu(uid))
    except Exception as ex:
        logger.warning(f"reply kb failed: {ex}")


class _CbShim:
    """Wrap a NewMessage event so existing callback handlers can run from reply-keyboard tap."""
    def __init__(self, ev, data):
        self._ev = ev
        self.data = data.encode()
        self.sender_id = ev.sender_id
        self.chat_id = ev.chat_id

    def __getattr__(self, name):
        return getattr(self._ev, name)

    async def edit(self, *a, **kw):
        return await self._ev.respond(*a, **kw)

    async def answer(self, message=None, alert=False, **kw):
        if message and alert:
            try:
                await self._ev.respond(message)
            except Exception:
                pass


MENU_TO_CALLBACK = {
    BTN_BUY: "menu_buy", BTN_SELL: "menu_sell",
    BTN_BUY_SESS: "menu_buy_sessions", BTN_SELL_SESS: "menu_sell_sessions",
    BTN_DEPOSIT: "menu_deposit", BTN_PROFILE: "menu_account",
    BTN_REFER: "menu_refer", BTN_PROMO: "claim_promo",
    BTN_STATS: "menu_stats", BTN_SUPPORT: "menu_support",
    BTN_ADMIN: "adm_adminmain",
}


def _clear_text_states(uid):
    for d in (sell_state, wd_state, deposit_input, admin_dep_state, manual_dep_state,
              lookup_search_state, lookup_action_state, lzt_search_state, spl_state,
              giveaway_ticket_state, session_buy_state, promo_state):
        d.pop(uid, None)


@bot.on(events.NewMessage())
async def handle_reply_keyboard(e):
    text = getattr(e, "text", None)
    if not text or text.startswith("/"):
        return
    key = MENU_TO_CALLBACK.get(text.strip())
    if not key:
        return
    uid = e.sender_id
    if not uid or not is_private_event(e):
        return
    try:
        ensure_user(uid)
        if is_user_banned(uid):
            return await e.respond("❌ You are banned.")
        if not is_bot_online() and not is_admin(uid):
            return await e.respond(f"{P_OFF} <b>Bot under maintenance.</b>")
        if not await is_joined_cached(uid):
            return await e.respond(JOIN_MSG, buttons=get_join_buttons())
        if not terms_accepted(uid) and key not in ("tc_accept", "tc_reject", "verify_join"):
            return await e.respond(TERMS_MSG, buttons=get_terms_buttons())
        _clear_text_states(uid)
        await handle_callbacks(_CbShim(e, key))
    except Exception as ex:
        logger.error(f"reply kb route: {ex}")
        try:
            await e.respond("⚠️ Something went wrong.")
        except Exception:
            pass
    raise events.StopPropagation


# =============================================================
# 4) DEPOSIT SYSTEM (from bot 7 — proven working)
# =============================================================
def get_keypad():
    return [
        [Button.inline("1", "kp_1"), Button.inline("2", "kp_2"), Button.inline("3", "kp_3")],
        [Button.inline("4", "kp_4"), Button.inline("5", "kp_5"), Button.inline("6", "kp_6")],
        [Button.inline("7", "kp_7"), Button.inline("8", "kp_8"), Button.inline("9", "kp_9")],
        [Button.inline("🔙 Del", "kp_del"), Button.inline("0", "kp_0"), Button.inline("✅ Confirm", "kp_done")],
        [Button.inline("❌ Cancel", "cancel_action")],
    ]


async def deposit_menu(e):
    msg = f"{P_CARD} <b>Select Payment Method</b>\n\n{P_UPI} UPI (instant)\n{P_CW} Cwallet (+5%)\n💳 Custom"
    flat = [Button.inline("⚡ UPI Automatic", "dep_upi"),
            Button.inline("👛 Cwallet (+5%)", "depm_cw")]
    for cid, cname in cur.execute("SELECT id, name FROM custom_payments").fetchall():
        flat.append(Button.inline(f"💳 {cname}", f"depm_{cid}"))
    rows = [flat[i:i+2] for i in range(0, len(flat), 2)]
    await safe_show_message(e, msg, buttons=rows)


async def init_upi_keypad(e):
    uid = e.sender_id
    deposit_input[uid] = {"step": "upi_keypad", "val": "0"}
    await e.edit(f"{P_KEY if 'P_KEY' in globals() else '⌨️'} <b>ENTER AMOUNT (INR, Min ₹1)</b>\n\n₹<code>0</code>",
                 buttons=get_keypad())


async def keypad_logic(e):
    uid = e.sender_id
    action = e.data.decode().replace("kp_", "")
    curr = deposit_input.get(uid, {}).get("val", "0")
    if action.isdigit():
        curr = action if curr == "0" else curr + action
        if len(curr) > 6:
            curr = curr[:6]
    elif action == "del":
        curr = curr[:-1] or "0"
    elif action == "done":
        amt = int(curr)
        if amt < 1:
            return await e.answer("Minimum ₹1", alert=True)
        return await show_upi_qr(e, amt)
    deposit_input[uid] = {"step": "upi_keypad", "val": curr}
    try:
        await e.edit(f"⌨️ <b>ENTER AMOUNT</b>\n\n₹<code>{curr}</code>", buttons=get_keypad())
    except MessageNotModifiedError:
        pass


async def show_upi_qr(e, amount):
    uid = e.sender_id
    order_id = f"ORD_{uid}_{int(time.time())}"
    await e.edit(f"{P_WAIT} Generating QR...")
    upi_url = f"upi://pay?pa={UPI_ID}&pn=Store&am={amount}&cu=INR"
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=400x400&data={quote(upi_url)}"
    cur.execute("INSERT INTO upi_orders (order_id, user_id, amount, status) VALUES (?,?,?,?)",
                (order_id, uid, amount, "pending"))
    db.commit()
    msg = (f"⚡ <b>AUTOMATIC UPI PAYMENT</b>\n\n💰 Amount: ₹<code>{amount}</code>\n🆔 Order: <code>{order_id}</code>\n\n"
           f"Scan QR or pay to <code>{UPI_ID}</code>\n\n"
           f"⚠️ After paying, tap <b>Submit UTR</b> with the 12-digit reference.")
    try:
        await e.delete()
    except Exception:
        pass
    await bot.send_file(uid, qr_url, caption=msg, buttons=[
        [Button.inline("✅ Submit UTR", f"submit_utr_{order_id}")],
        [Button.inline("❌ Cancel", "cancel_action")],
    ])


async def verify_upi_payment(e, order_id):
    uid = e.sender_id
    row = cur.execute("SELECT amount, status, user_id FROM upi_orders WHERE order_id=?", (order_id,)).fetchone()
    if not row or row[2] != uid:
        return await e.answer("Order not found", alert=True)
    if row[1] != "pending":
        return await e.answer("UTR already submitted", alert=True)
    try:
        await e.delete()
    except Exception:
        pass
    async with bot.conversation(e.chat_id, timeout=120) as conv:
        try:
            await conv.send_message("👇 Enter the 12-digit UTR / Reference Number:\n<i>(/cancel to abort)</i>")
            resp = await conv.get_response()
            utr = resp.raw_text.strip()
            if utr == "/cancel":
                return await conv.send_message("❌ Cancelled.")
            if not re.fullmatch(r"\d{12}", utr):
                return await conv.send_message("❌ Invalid UTR (need exactly 12 digits).")
            if cur.execute("SELECT 1 FROM deposits WHERE method_name LIKE ?", (f"%UTR: {utr})%",)).fetchone():
                return await conv.send_message("❌ UTR already used.")
            cur.execute("UPDATE upi_orders SET status='submitted' WHERE order_id=? AND status='pending'", (order_id,))
            if cur.rowcount == 0:
                db.commit()
                return await conv.send_message("UTR already submitted.")
            amt = int(row[0])
            cur.execute("INSERT INTO deposits (user_id, amount, method_name, status) VALUES (?,?,?,?)",
                        (uid, amt, f"UPI (UTR: {utr})", "pending"))
            db.commit()
            dep_id = cur.lastrowid
            cap = (f"⚡ <b>NEW UPI DEPOSIT</b>\nUser: <code>{uid}</code>\nAmount: ₹{amt}\n"
                   f"UTR: <code>{utr}</code>")
            await bot.send_message(ADMIN_LOG_CHANNEL_ID, cap, buttons=[
                [Button.inline(f"✅ Approve ₹{amt}", f"dep_acc|{dep_id}|{uid}|exact|{amt}"),
                 Button.inline("❌ Reject", f"dep_rej|{dep_id}|{uid}")],
                [Button.inline("📝 Custom Amount", f"dep_acc|{dep_id}|{uid}|custom|0")],
            ])
            await conv.send_message("✅ Submitted! Amount will be credited after verification.")
        except asyncio.TimeoutError:
            await conv.send_message("⏰ Timed out.")


async def approve_deposit(dep_id, amt):
    row = cur.execute("SELECT user_id, method_name FROM deposits WHERE id=?", (dep_id,)).fetchone()
    if not row:
        return None
    uid, method = row
    async with get_user_lock(uid):
        cur.execute("UPDATE deposits SET status='approved', amount=? WHERE id=? AND status='pending'", (amt, dep_id))
        if cur.rowcount == 0:
            db.commit()
            return None
        cur.execute("UPDATE users SET balance = balance + ?, total_deposited = total_deposited + ? WHERE user_id=?",
                    (amt, amt, uid))
        if str(method).startswith("UPI"):
            cur.execute("INSERT INTO settings(key,value) VALUES('upi_revenue',?) "
                        "ON CONFLICT(key) DO UPDATE SET value=CAST(CAST(value AS INTEGER)+? AS TEXT)",
                        (str(amt), amt))
        db.commit()
    await log_deposit(uid, amt, method)
    return uid, method


# =============================================================
# 5) STOCK / BUY FLOWS
# =============================================================
async def show_categories(e, flow="buy"):
    rows = cur.execute("SELECT category, COUNT(*) FROM stock WHERE available=1 GROUP BY category").fetchall()
    counts = {c: n for c, n in rows}
    msg = f"📦 <b>Select Account Type</b>\n\n💲 Rate: 1 USDT = ₹{get_usdt_rate():.2f}"
    btns = []
    for key, icon, label in CATEGORIES:
        if key == "server1":
            btns.append([Button.inline(f"{icon} {label} (Market)", f"cat|{flow}|{key}")])
        else:
            btns.append([Button.inline(f"{icon} {label} ({counts.get(key, 0)})", f"cat|{flow}|{key}")])
    btns.append([Button.inline("❌ Cancel", "cancel_action")])
    await safe_show_message(e, msg, buttons=btns)


async def show_countries(e, flow, category, page=1):
    if category == "server1":
        return await render_lzt_countries(e, page)
    limit = 10
    offset = (page - 1) * limit
    total = cur.execute("SELECT COUNT(DISTINCT country_name) FROM stock WHERE available=1 AND category=?",
                        (category,)).fetchone()[0]
    rows = cur.execute(
        "SELECT MIN(country_icon), country_name, COUNT(*) FROM stock "
        "WHERE available=1 AND category=? GROUP BY country_name ORDER BY country_name LIMIT ? OFFSET ?",
        (category, limit, offset)).fetchall()
    if not rows and page == 1:
        return await safe_show_message(e, f"❌ <b>{cat_label(category)}: Out of stock!</b>",
                                       buttons=[[Button.inline("⬅️ Back", f"catmenu|{flow}")]])
    msg = f"🌍 <b>Select a country</b> (Page {page})\n📦 Type: {cat_label(category)}"
    btns = []
    for icon, name, n in rows:
        btns.append([Button.inline(f"{icon} {name} ({n})",
                                   f"bc|{flow}|{category}|{country_hash(name)}")])
    nav = []
    if page > 1:
        nav.append(Button.inline("Prev", f"pg_c|{flow}|{category}|{page-1}"))
    if offset + limit < total:
        nav.append(Button.inline("Next", f"pg_c|{flow}|{category}|{page+1}"))
    if nav:
        btns.append(nav)
    btns.append([Button.inline("⬅️ Back", f"catmenu|{flow}")])
    await safe_show_message(e, msg, buttons=btns)


async def show_years(e, flow, category, h):
    country = resolve_country(category, h)
    if not country:
        return await e.answer("Country changed. Reselect.", alert=True)
    rows = cur.execute(
        "SELECT account_year, price, COUNT(*) FROM stock WHERE available=1 AND category=? AND country_name=? "
        "GROUP BY account_year, price ORDER BY account_year DESC, price ASC",
        (category, country)).fetchall()
    if not rows:
        return await e.answer("Out of stock", alert=True)
    uid = e.sender_id
    disc_row = cur.execute("SELECT discount FROM users WHERE user_id=?", (uid,)).fetchone()
    discount = disc_row[0] if disc_row else 0
    msg = f"📅 <b>Select Year</b>\n📦 {cat_label(category)}\n🌍 <b>{country}</b>"
    btns = []
    for y, p, c in rows:
        disp = p if not discount else int(p * (100 - discount) / 100)
        suff = f" (-{discount}%)" if discount else ""
        btns.append([Button.inline(f"{y} | ₹{disp}{suff} | {c}",
                                   f"by|{flow}|{category}|{h}|{y}|{p}")])
    btns.append([Button.inline("⬅️ Back", f"pg_c|{flow}|{category}|1")])
    await safe_show_message(e, msg, buttons=btns)


async def show_account_info(e, category, h, year, price_str):
    country = resolve_country(category, h)
    if not country:
        return await e.answer("Reselect", alert=True)
    uid, base = e.sender_id, int(price_str)
    row = cur.execute(
        "SELECT MIN(country_icon), COUNT(*) FROM stock WHERE available=1 AND category=? "
        "AND country_name=? AND account_year=? AND price=?",
        (category, country, int(year), base)).fetchone()
    if not row or not row[1]:
        return await e.answer("Out of stock", alert=True)
    icon, cnt = row
    final = user_final_price(uid, base)
    msg = (f"⚡ <b>Account Info</b>\n\n🌍 {icon} {country}\n📦 {cat_label(category)}\n"
           f"💸 Price: ₹{final} (~${to_usd(final):.2f})\n📦 Available: {cnt}\n\n"
           f"⚠️ Use Graph/Plus Messenger. Not responsible for freeze/ban.")
    btns = [[Button.inline("🛒 Buy Now", f"pc|{category}|{h}|{year}|{base}")],
            [Button.inline("⬅️ Back", f"bc|single|{category}|{h}")]]
    await safe_show_message(e, msg, buttons=btns)


async def process_purchase(e, category, h, year_str, price_str):
    country = resolve_country(category, h)
    if not country:
        return await e.answer("Reselect", alert=True)
    uid, base_price = e.sender_id, int(price_str)
    final_price = user_final_price(uid, base_price)

    async with get_user_lock(uid):
        row = cur.execute(
            "SELECT phone, session_file, country_icon, account_year, twofa FROM stock "
            "WHERE category=? AND country_name=? AND account_year=? AND price=? AND available=1 "
            "ORDER BY phone LIMIT 1",
            (category, country, int(year_str), base_price)).fetchone()
        if not row:
            return await e.answer("Sold out", alert=True)
        phone, sess, icon, actual_year, twofa_pass = row
        cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=? AND balance >= ?",
                    (final_price, uid, final_price))
        if cur.rowcount == 0:
            return await e.answer(f"Insufficient balance (₹{final_price})", alert=True)
        cur.execute("UPDATE stock SET available=0 WHERE phone=?", (phone,))
        cur.execute("INSERT OR REPLACE INTO pending_orders (phone, user_id, price, created) VALUES (?,?,?,?)",
                    (phone, uid, final_price, time.time()))
        db.commit()

    await e.edit(f"⚡ <b>Fetching number +{phone}...</b>")
    clean = sess[:-8] if sess.endswith(".session") else sess
    api_id, api_hash = get_random_api_credentials()
    client = TelegramClient(clean, api_id, api_hash)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            raise RuntimeError("session dead")
    except Exception:
        async with get_user_lock(uid):
            cur.execute("DELETE FROM stock WHERE phone=?", (phone,))
            cur.execute("DELETE FROM pending_orders WHERE phone=?", (phone,))
            cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (final_price, uid))
            db.commit()
        delete_session_files(sess)
        return await e.edit("❌ Account invalid. Refunded.")

    msg = (f"⚡ <b>Order Active!</b>\n\n📱 Phone: <code>{phone}</code>\n"
           f"🏳️ Country: {icon} {country}\n\n🔻 Instructions:\n"
           f"1. Open Telegram → Add Account\n2. Enter the number above\n"
           f"3. {P_WAIT} Bot is listening for OTP (auto-sent)\n\n"
           f"Auto-refund if no OTP in 10 min.")
    sent = await e.edit(msg)

    active_orders[phone] = {
        "uid": uid, "client": client, "sess": sess, "start_time": time.time(),
        "paid": False, "price": final_price, "country": country, "year": actual_year,
        "c_icon": icon, "twofa": twofa_pass, "msg_id": sent.id,
    }
    asyncio.create_task(auto_otp_task(phone))


def otp_buttons(phone):
    return [
        [Button.inline("🔄 Get OTP Again", f"get_otp_again|{phone}")],
        [Button.inline("📱 Devices", f"logout_bot|{phone}")],
        [Button.inline("🚪 Logout & Finish", f"logout_cf|{phone}")],
    ]


def extract_login_code(msgs, start_time):
    ignore = ("login detected", "new login", "new device", "two-step verification",
              "active sessions", "settings changed", "if this wasn't you",
              "if somebody logged in", "unusual activity", "someone tried to")
    for m in msgs:
        if not m.message or not m.date or m.date.timestamp() <= start_time - 30:
            continue
        low = m.message.lower()
        mm = re.search(r"(?:login code|verification code|your code)\D{0,10}(\d{4,8})", low)
        if mm:
            return mm.group(1)
        if any(p in low for p in ignore):
            continue
        mm = re.search(OTP_REGEX, m.message)
        if mm:
            return mm.group()
    return None


async def auto_otp_task(phone):
    if phone not in active_orders:
        return
    order = active_orders[phone]
    client = order["client"]
    start = order["start_time"]
    uid = order["uid"]
    msg_id = order["msg_id"]

    try:
        await client.get_dialogs(limit=20)
    except Exception:
        pass

    while time.time() - start < AUTO_CANCEL_SECONDS:
        if phone not in active_orders:
            return
        try:
            msgs = await client.get_messages(777000, limit=5)
            code = extract_login_code(msgs, start)
            if code:
                if not order["paid"]:
                    order["paid"] = True
                    async with get_user_lock(uid):
                        cur.execute("INSERT INTO orders (user_id,country,year,price,phone,otp,server) VALUES (?,?,?,?,?,?,?)",
                                    (uid, order["country"], order["year"], order["price"], phone, code, "Local"))
                        cur.execute("DELETE FROM stock WHERE phone=?", (phone,))
                        cur.execute("DELETE FROM pending_orders WHERE phone=?", (phone,))
                        db.commit()
                    await log_purchase(uid, order["country"], order["price"], order["price"],
                                       order["year"], 1, phone, "Local")
                    asyncio.create_task(paid_order_cleanup(phone))
                text = (f"✅ <b>OTP Fetched!</b>\n\n📱 {phone}\n🔢 OTP: <code>{code}</code>\n"
                        f"🔐 2FA: <code>{order['twofa']}</code>")
                try:
                    await bot.edit_message(uid, msg_id, text, buttons=otp_buttons(phone))
                except MessageNotModifiedError:
                    pass
                return
        except Exception as ex:
            logger.warning(f"OTP poll: {ex}")
        await asyncio.sleep(6)

    if phone in active_orders and not active_orders[phone]["paid"]:
        order = active_orders.pop(phone)
        try:
            await order["client"].disconnect()
        except Exception:
            pass
        async with get_user_lock(uid):
            cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (order["price"], uid))
            cur.execute("UPDATE stock SET available=1 WHERE phone=?", (phone,))
            cur.execute("DELETE FROM pending_orders WHERE phone=?", (phone,))
            db.commit()
        try:
            await bot.edit_message(uid, msg_id, f"⏰ <b>Order Expired</b>\n₹{order['price']} refunded.")
        except Exception:
            pass


async def paid_order_cleanup(phone):
    await asyncio.sleep(PAID_ORDER_TTL)
    order = active_orders.pop(phone, None)
    if not order:
        return
    try:
        await order["client"].log_out()
    except Exception:
        pass
    try:
        await order["client"].disconnect()
    except Exception:
        pass
    delete_session_files(order["sess"])


async def recover_pending_orders():
    rows = cur.execute("SELECT phone, user_id, price FROM pending_orders").fetchall()
    for phone, uid, price in rows:
        async with get_user_lock(uid):
            cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (price, uid))
            cur.execute("UPDATE stock SET available=1 WHERE phone=?", (phone,))
            cur.execute("DELETE FROM pending_orders WHERE phone=?", (phone,))
            db.commit()
        try:
            await bot.send_message(uid, f"⚠️ Order cancelled due to restart. ₹{price} refunded.")
        except Exception:
            pass


async def render_lzt_countries(e, page=1):
    """Server 1 (LZT market) country list — uses cached stock."""
    if not toggle_on("server1_status"):
        return await e.answer("Server 1 under maintenance", alert=True)
    cache = cached_lzt_stock.get("no_no_any_any_any", {})
    names = sorted(all_country_names("server1"))
    limit = 20
    total = len(names)
    page = max(1, min(page, max(1, (total + limit - 1) // limit)))
    offset = (page - 1) * limit
    page_items = names[offset:offset + limit]
    msg = f"🟣 <b>Server 1 (Market)</b>\nPage {page}\n\nSelect a country:"
    btns = []
    row = []
    for name in page_items:
        count, price = cache.get(name, (0, 0))
        flag = get_flag_by_country_name(name)
        text = f"{flag} {name} ({count})" if count else f"{flag} {name} (0)"
        row.append(Button.inline(text, f"lzt_chk|{country_hash(name)}|1"))
        if len(row) == 2:
            btns.append(row)
            row = []
    if row:
        btns.append(row)
    nav = []
    if page > 1:
        nav.append(Button.inline("Prev", f"srv_1_pg|{page-1}"))
    if offset + limit < total:
        nav.append(Button.inline("Next", f"srv_1_pg|{page+1}"))
    if nav:
        btns.append(nav)
    btns.append([Button.inline("⚙️ Filters", "lzt_filters")])
    btns.append([Button.inline("⬅️ Back", "menu_buy")])
    await safe_show_message(e, msg, buttons=btns)


async def lzt_country_items(e, h):
    name = resolve_any_country("server1", h)
    if not name:
        return await e.answer("Country changed. Reselect.", alert=True)
    await e.edit(f"⏳ Fetching Server 1 stock for {name}...")
    data = await fetch_lzt_country(name, "no", "any", "any", "any", "any")
    if not data:
        return await e.edit(f"❌ Could not reach market for {name}.")
    _, count, price = data
    if not count:
        return await e.edit(f"❌ No Server 1 stock for {name}.")
    msg = (f"🟣 <b>Server 1</b>\n🌍 {name}\n📦 Available: {count}\n"
           f"💸 From: ₹{price}\n\n💲 1 USDT = ₹{get_usdt_rate():.2f}")
    await e.edit(msg, buttons=[
        [Button.inline(f"🛒 Buy from Market", f"lzt_buy|{h}|{price}")],
        [Button.inline("⬅️ Back", "menu_buy")],
    ])


# =============================================================
# 6) SELL ACCOUNT / SELL PRICE LIST (from bot 6)
# =============================================================
def _fmt_price(p, cur_code):
    sym = {"USD": "$", "INR": "₹"}.get(str(cur_code).upper(), cur_code)
    txt = f"{float(p):.2f}".rstrip("0").rstrip(".")
    return f"{txt}{sym}"


def get_sell_price_rows():
    rows = cur.execute("SELECT dial_code, iso_code, flag_emoji, price, currency "
                       "FROM sell_price_list WHERE active=1 "
                       "ORDER BY CAST(dial_code AS INTEGER), iso_code").fetchall()
    return rows


async def send_sell_price_list(e):
    rows = get_sell_price_rows()
    if not rows:
        return await safe_show_message(e, "ℹ️ Sell prices not set yet.")
    head = "<b>We buy from you →</b>\n\n"
    lines = [f"[{r[2]}]+{r[0]}-{r[1]}: {_fmt_price(r[3], r[4])}" for r in rows]
    msgs, cur_txt = [], head
    for ln in lines:
        if len(cur_txt) + len(ln) + 1 > 3500:
            msgs.append(cur_txt)
            cur_txt = "<b>We buy from you → (continued)</b>\n\n"
        cur_txt += ln + "\n"
    msgs.append(cur_txt)
    for n, m in enumerate(msgs):
        last = n == len(msgs) - 1
        await safe_show_message(e, m, buttons=[[Button.inline("💸 Sell Account", "menu_sell")]] if last else None)


async def sell_flow_start(e):
    if not toggle_on("sell_status"):
        return await e.answer("Sell is under maintenance", alert=True)
    uid = e.sender_id
    sell_state[uid] = {"step": "phone"}
    await safe_show_message(e, "📞 Send the phone number of the account you want to sell:\n<i>(/cancel to abort)</i>",
                            buttons=[[Button.inline("❌ Cancel", "cancel_action")]])


async def sell_process_phone(e, uid, phone):
    phone = re.sub(r"[^0-9]", "", phone)
    if not phone or len(phone) < 7:
        return await e.respond("❌ Invalid phone number.")
    if cur.execute("SELECT 1 FROM blacklisted_phones WHERE phone=?", (phone,)).fetchone():
        return await e.respond("❌ This number is blacklisted.")
    sell_state[uid] = {"step": "phone_done", "phone": phone}
    await e.respond(
        f"📞 Sending OTP to +{phone}...\n\nOnce received, send it here:",
        buttons=[[Button.inline("❌ Cancel", "cancel_action")]])


async def sell_hold_task(phone, uid, client, price):
    await asyncio.sleep(600)
    try:
        auths = await client(GetAuthorizationsRequest())
        others = [a for a in auths.authorizations if not a.current]
        if others:
            return await bot.send_message(uid, f"❌ Rejected: {len(others)} other sessions active on +{phone}.")
        credited = int(price * 0.9)
        async with get_user_lock(uid):
            cur.execute("UPDATE users SET sales_balance = sales_balance + ? WHERE user_id=?", (credited, uid))
            db.commit()
        await bot.send_message(uid, f"✅ Accepted! ₹{credited} credited to sales balance.")
    except Exception as ex:
        logger.warning(f"sell_hold {phone}: {ex}")
        await bot.send_message(uid, f"❌ Sell rejected (session invalid).")


# =============================================================
# 7) WITHDRAW
# =============================================================
async def withdraw_menu(e):
    uid = e.sender_id
    row = cur.execute("SELECT sales_balance FROM users WHERE user_id=?", (uid,)).fetchone()
    bal = row[0] if row else 0
    msg = f"💸 <b>Withdraw Sales Balance</b>\n\nAvailable: ₹{bal}\n\nChoose method:"
    btns = [[Button.inline("💰 To Main Wallet", "wd_main")],
            [Button.inline("🏦 To UPI (Admin Approval)", "wd_upi")],
            [Button.inline("⬅️ Back", "menu_account")]]
    await safe_show_message(e, msg, buttons=btns)


# =============================================================
# 8) REFERRAL / PROMO / GIVEAWAY / FIGHT
# =============================================================
def is_ref_enabled():
    return toggle_on("ref_enabled")


def get_ref_bonus():
    try:
        return int(get_setting("ref_bonus", "3"))
    except Exception:
        return 3


async def reward_referrer_on_join(uid):
    if not is_ref_enabled():
        return
    row = cur.execute("SELECT referred_by, ref_rewarded FROM users WHERE user_id=?", (uid,)).fetchone()
    if not row or not row[0] or row[1]:
        return
    ref, bonus = row[0], get_ref_bonus()
    cur.execute("UPDATE users SET ref_rewarded=1 WHERE user_id=? AND ref_rewarded=0", (uid,))
    if cur.rowcount == 0:
        return
    db.commit()
    if bonus > 0:
        update_balance(ref, bonus)
        try:
            await bot.send_message(ref, f"🎁 <b>Referral Bonus!</b>\nYour referral {uid} joined.\n"
                                        f"✅ You earned ₹{bonus}!")
        except Exception:
            pass


async def claim_promo(e):
    uid = e.sender_id
    promo_state[uid] = {"step": "code"}
    await safe_show_message(e, "🎟️ Send the promo code:\n<i>(/cancel to abort)</i>",
                            buttons=[[Button.inline("❌ Cancel", "cancel_action")]])


async def process_promo_code(e, uid, code):
    row = cur.execute("SELECT value, max_uses, used_count FROM promo_codes WHERE UPPER(code)=UPPER(?)",
                      (code,)).fetchone()
    if not row:
        return await e.respond("❌ Invalid promo code.")
    value, max_uses, used = row
    if used >= max_uses:
        return await e.respond("❌ Promo code exhausted.")
    if cur.execute("SELECT 1 FROM promo_logs WHERE code=? AND user_id=?", (code.upper(), uid)).fetchone():
        return await e.respond("❌ Already claimed.")
    async with get_user_lock(uid):
        cur.execute("UPDATE promo_codes SET used_count = used_count + 1 WHERE code=?", (code.upper(),))
        cur.execute("INSERT INTO promo_logs (code, user_id) VALUES (?,?)", (code.upper(), uid))
        cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (value, uid))
        db.commit()
    await e.respond(f"✅ Promo applied! ₹{value} credited.")


# =============================================================
# 9) MENU HELPERS
# =============================================================
async def build_welcome(uid):
    ensure_user(uid)
    row = cur.execute("SELECT balance, sales_balance FROM users WHERE user_id=?", (uid,)).fetchone()
    bal, sbal = row if row else (0, 0)
    if is_ref_enabled():
        me = await bot.get_me()
        ref_link = f"https://t.me/{me.username}?start=ref_{uid}" if me.username else "(set bot username)"
        ref_part = f"🎁 <b>Refer & Earn:</b> ₹{get_ref_bonus()} per refer\n🔗 {ref_link}"
    else:
        ref_part = "⛔ Referral service is off."
    return (f"🏬 <b>Welcome to TG Store!</b>\n\n"
            f"👤 ID: <code>{uid}</code>\n"
            f"💰 Balance: {format_price(uid, bal)}\n"
            f"💸 Sales: {format_price(uid, sbal)}\n"
            f"💬 Support: {SUPPORT_HANDLE}\n\n{ref_part}")


async def send_main_menu(e, uid):
    msg = await build_welcome(uid)
    kb = get_persistent_menu(uid)
    if is_callback(e):
        try:
            await e.delete()
        except Exception:
            pass
        await bot.send_message(uid, msg, buttons=kb)
    else:
        await e.respond(msg, buttons=kb)
    reply_kb_sent.add(uid)


async def profile_handler(e):
    uid = e.sender_id
    row = cur.execute("SELECT balance, sales_balance, total_deposited, joined_date, discount, referred_by "
                      "FROM users WHERE user_id=?", (uid,)).fetchone()
    if not row:
        return await e.respond("⚠️ Type /start first.")
    bal, sbal, dep, joined, discount, ref_by = row
    ref_count = cur.execute("SELECT COUNT(*) FROM users WHERE referred_by=?", (uid,)).fetchone()[0]
    me = await bot.get_me()
    ref_link = f"https://t.me/{me.username}?start=ref_{uid}" if me.username else "N/A"
    disc_msg = f"\n🎁 Active Discount: {discount}%" if discount else ""
    msg = (f"👤 <b>Your Profile</b>\n\n"
           f"🆔 ID: <code>{uid}</code>\n"
           f"💰 Balance: {format_price(uid, bal)}\n"
           f"💸 Sales Balance: {format_price(uid, sbal)}\n"
           f"💳 Total Deposited: {format_price(uid, dep)}{disc_msg}\n"
           f"👥 Referrals: {ref_count}\n"
           f"📅 Joined: {str(joined)[:10]}\n\n"
           f"🔗 Your referral link:\n<code>{ref_link}</code>")
    btns = [
        [Button.inline("💳 Deposit", "menu_deposit"), Button.inline("💸 Withdraw Sales", "wd_sales")],
        [Button.inline("📜 Order History", "menu_history"), Button.inline("⬅️ Main Menu", "menu_main")],
    ]
    await safe_show_message(e, msg, buttons=btns)


async def stats_handler(e):
    uid = e.sender_id
    o = cur.execute("SELECT COUNT(*), SUM(price) FROM orders WHERE user_id=?", (uid,)).fetchone()
    spent = o[1] if o and o[1] else 0
    refs = cur.execute("SELECT COUNT(*) FROM users WHERE referred_by=?", (uid,)).fetchone()[0]
    row = cur.execute("SELECT total_deposited FROM users WHERE user_id=?", (uid,)).fetchone()
    dep = row[0] if row else 0
    msg = (f"📊 <b>My Stats</b>\n\n"
           f"🛒 Bought: {o[0] or 0}\n"
           f"👥 Referrals: {refs}\n"
           f"💰 Total Spent: ₹{spent}\n"
           f"💳 Total Deposited: ₹{dep}")
    await safe_show_message(e, msg,
                            buttons=[[Button.inline("📜 Purchase Logs", "page_purchases_1")],
                                     [Button.inline("⬅️ Back", "menu_main")]])


async def history_page(e, page=1):
    uid = e.sender_id
    limit, offset = 5, (page - 1) * 5
    total = cur.execute("SELECT COUNT(*) FROM orders WHERE user_id=?", (uid,)).fetchone()[0]
    rows = cur.execute("SELECT phone, date, price FROM orders WHERE user_id=? ORDER BY id DESC LIMIT ? OFFSET ?",
                       (uid, limit, offset)).fetchall()
    msg = f"📜 <b>Order History</b> (Page {page})\n\n"
    if not rows:
        msg += "No orders yet."
    for ph, d, p in rows:
        msg += f"📱 {ph} | ₹{p}\n📅 {str(d)[:16]}\n────────────\n"
    nav = []
    if page > 1:
        nav.append(Button.inline("Prev", f"page_purchases_{page-1}"))
    if offset + limit < total:
        nav.append(Button.inline("Next", f"page_purchases_{page+1}"))
    btns = [nav] if nav else []
    btns.append([Button.inline("⬅️ Back", "menu_account")])
    await safe_show_message(e, msg, buttons=btns)


# =============================================================
# 10) ADMIN PANEL
# =============================================================
async def admin_panel(e):
    uid = e.sender_id
    if not is_admin(uid):
        return
    status = "🟢 ON" if is_bot_online() else "🔴 OFF"
    n_users = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    n_stock = cur.execute("SELECT COUNT(*) FROM stock WHERE available=1").fetchone()[0]
    n_pend = cur.execute("SELECT COUNT(*) FROM deposits WHERE status='pending'").fetchone()[0]
    btns = []
    if has_perm(uid, "p_settings"):
        btns.append([Button.inline(f"Bot: {status}", "adm_togglebot")])
    if has_perm(uid, "p_add_stock"):
        btns.append([Button.inline("📦 Add Stock", "adm_catmenu")])
    if has_perm(uid, "p_manage_stock"):
        btns.append([Button.inline("📦 Manage Stock", "adm_managestock"),
                     Button.inline("💰 Auto Price", "adm_autoprice")])
    if has_perm(uid, "p_stats"):
        btns.append([Button.inline("📊 Stats", "adm_stats"), Button.inline("📢 Broadcast", "adm_bcast")])
        btns.append([Button.inline("👁 User Info", "adm_userinfo")])
    if has_perm(uid, "p_bal"):
        btns.append([Button.inline("💰 Change Balance", "adm_bal"), Button.inline("🚫 Ban", "adm_ban")])
    if has_perm(uid, "p_settings"):
        btns.append([Button.inline("🎁 Discount", "adm_discount"),
                     Button.inline("🎁 Ref Bonus", "adm_refpct")])
        btns.append([Button.inline(f"Ref: {'🟢' if is_ref_enabled() else '🔴'}", "adm_reftoggle")])
        btns.append([Button.inline("💬 Support URL", "adm_supporturl"),
                     Button.inline("💳 Payments", "adm_payments")])
        btns.append([Button.inline("💲 USDT Rate", "adm_usdtrate"),
                     Button.inline("💸 Sell Prices", "adm_sellprices")])
        btns.append([Button.inline("🚫 Blacklist", "adm_blacklist")])
        btns.append([Button.inline("⬇️ Backup", "adm_backupusr"),
                     Button.inline("⬆️ Restore", "adm_restoreusr")])
    if uid == ADMIN_ID:
        btns.append([Button.inline("👥 Manage Admins", "adm_manageadmins")])
    header = (f"👑 <b>Admin Dashboard</b>\n\n👥 Users: <b>{n_users}</b>\n"
              f"📦 Stock: <b>{n_stock}</b>\n⏳ Pending: <b>{n_pend}</b>")
    await safe_show_message(e, header, buttons=btns)


async def admin_stats(e):
    u = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    s = cur.execute("SELECT COUNT(*) FROM stock WHERE available=1").fetchone()[0]
    o = cur.execute("SELECT COUNT(*), SUM(price) FROM orders").fetchone()
    bal = cur.execute("SELECT SUM(balance) FROM users").fetchone()[0] or 0
    rev = get_setting("upi_revenue", "0")
    msg = (f"📊 <b>Stats</b>\n\n👥 Users: {u}\n📦 Stock: {s}\n"
           f"💰 Total UPI Revenue: ₹{rev}\n💳 Users Balance Sum: ₹{bal}\n"
           f"🛒 Sold: {o[0] or 0}\n💲 Total Sales: ₹{o[1] or 0}")
    await safe_show_message(e, msg, buttons=[[Button.inline("⬅️ Back", "adm_adminmain")]])


# =============================================================
# 11) MASTER CALLBACK ROUTER
# =============================================================
@bot.on(events.CallbackQuery())
async def handle_callbacks(e):
    data = e.data.decode()
    uid = e.sender_id

    if not is_private_event(e):
        return await safe_answer_cb(e, "Private chat only", alert=True)

    ensure_user(uid)
    if is_user_banned(uid):
        return await safe_answer_cb(e, "Banned", alert=True)
    if not is_bot_online() and not is_admin(uid):
        return await safe_answer_cb(e, "Maintenance", alert=True)

    # Terms / Join
    if data == "verify_join":
        if await check_channel_joined(uid):
            _join_cache[uid] = time.time()
            await reward_referrer_on_join(uid)
            if not terms_accepted(uid):
                return await safe_show_message(e, TERMS_MSG, buttons=get_terms_buttons())
            return await send_main_menu(e, uid)
        return await safe_answer_cb(e, "Not joined all channels yet", alert=True)
    if data == "tc_accept":
        cur.execute("UPDATE users SET terms_accepted=1 WHERE user_id=?", (uid,))
        db.commit()
        return await send_main_menu(e, uid)
    if data == "tc_reject":
        return await safe_answer_cb(e, "You must accept terms.", alert=True)

    # enforce join+terms
    if not is_admin(uid):
        if not await is_joined_cached(uid):
            return await safe_show_message(e, JOIN_MSG, buttons=get_join_buttons())
        if not terms_accepted(uid):
            return await safe_show_message(e, TERMS_MSG, buttons=get_terms_buttons())

    # cancel
    if data == "cancel_action":
        for d in (deposit_input, sell_state, wd_state, admin_dep_state, promo_state,
                  lookup_search_state, lzt_search_state, session_buy_state, manual_dep_state):
            d.pop(uid, None)
        return await send_main_menu(e, uid)

    # main menu
    if data == "menu_main":
        return await send_main_menu(e, uid)
    if data == "menu_buy":
        return await show_categories(e, "buy")
    if data == "menu_sell":
        return await send_sell_price_list(e)
    if data == "menu_buy_sessions":
        return await show_categories(e, "bulk")
    if data == "menu_sell_sessions":
        rows = cur.execute("SELECT phone, status FROM num_change_requests WHERE user_id=? LIMIT 20",
                           (uid,)).fetchall()
        if not rows:
            return await safe_show_message(e, "📁 No sell sessions yet.")
        msg = "📁 <b>Your Sell Sessions</b>\n\n"
        for ph, st in rows:
            msg += f"📱 {ph} | {st}\n"
        return await safe_show_message(e, msg, buttons=[[Button.inline("⬅️ Back", "menu_main")]])
    if data == "menu_deposit":
        return await deposit_menu(e)
    if data == "menu_account":
        return await profile_handler(e)
    if data == "menu_refer":
        return await send_main_menu(e, uid)
    if data == "menu_stats":
        return await stats_handler(e)
    if data == "menu_support":
        rows = [[Button.url("💬 Support", get_support_url())]]
        if TERMS_URL:
            rows.append([Button.url("📜 Terms", TERMS_URL)])
        return await safe_show_message(e, "📞 <b>Support</b>", buttons=rows)
    if data == "menu_history":
        return await history_page(e, 1)

    # deposit
    if data == "dep_upi":
        return await init_upi_keypad(e)
    if data.startswith("depm_"):
        return await safe_show_message(e, "💳 This method is being configured. Try UPI/Cwallet.",
                                        buttons=[[Button.inline("⬅️ Back", "menu_deposit")]])
    if data.startswith("kp_"):
        return await keypad_logic(e)
    if data.startswith("submit_utr_"):
        return await verify_upi_payment(e, data[len("submit_utr_"):])

    # category / country / year / buy
    if data.startswith("cat|"):
        _, flow, cat = data.split("|", 2)
        return await show_countries(e, flow, cat, 1)
    if data.startswith("catmenu|"):
        return await show_categories(e, data.split("|")[1])
    if data.startswith("pg_c|"):
        _, flow, cat, pg = data.split("|")
        return await show_countries(e, flow, cat, int(pg))
    if data.startswith("bc|"):
        _, flow, cat, h = data.split("|")
        return await show_years(e, flow, cat, h)
    if data.startswith("by|"):
        _, flow, cat, h, year, price = data.split("|")
        return await show_account_info(e, cat, h, year, price)
    if data.startswith("pc|"):
        _, cat, h, year, price = data.split("|")
        return await process_purchase(e, cat, h, year, price)

    # server 1 (LZT)
    if data.startswith("srv_1_pg|"):
        return await render_lzt_countries(e, int(data.split("|")[1]))
    if data.startswith("lzt_chk|"):
        _, h, _p = data.split("|")
        return await lzt_country_items(e, h)
    if data.startswith("lzt_buy|"):
        _, h, price = data.split("|")
        return await safe_show_message(e, "⚙️ LZT buy flow: admin must set item ID. (Manual mode)",
                                        buttons=[[Button.inline("⬅️ Back", "menu_buy")]])
    if data == "lzt_filters":
        return await safe_show_message(e, "⚙️ Market filters: spam/no-spam, 2FA, premium, DC, gifts, mail.",
                                        buttons=[[Button.inline("⬅️ Back", "menu_buy")]])

    # OTP actions
    if data.startswith("get_otp_again|"):
        phone = data.split("|", 1)[1]
        order = active_orders.get(phone)
        if not order:
            return await safe_answer_cb(e, "Order expired", alert=True)
        try:
            msgs = await order["client"].get_messages(777000, limit=10)
            code = extract_login_code(msgs, order["start_time"])
            if code:
                return await safe_show_message(e, f"🔢 New OTP: <code>{code}</code>")
            return await safe_answer_cb(e, "No new OTP yet", alert=True)
        except Exception as ex:
            return await safe_answer_cb(e, f"Error: {ex}", alert=True)
    if data.startswith("logout_bot|"):
        phone = data.split("|", 1)[1]
        order = active_orders.get(phone)
        if not order:
            return await safe_answer_cb(e, "Order expired", alert=True)
        try:
            res = await order["client"](GetAuthorizationsRequest())
            others = [a for a in res.authorizations if not a.current]
            msg = f"📱 Active Devices: {len(others)}\n\n"
            btns = []
            for i, a in enumerate(others, 1):
                msg += f"{i}. {a.device_model or '?'} | {a.country or '?'}\n"
                btns.append([Button.inline(f"❌ Logout {i}", f"lo_dev|{phone}|{a.hash}")])
            if len(others) > 1:
                btns.append([Button.inline("🧹 Logout ALL", f"lo_all|{phone}")])
            btns.append([Button.inline("⬅️ Back", "menu_main")])
            return await safe_show_message(e, msg, buttons=btns)
        except Exception as ex:
            return await safe_answer_cb(e, str(ex), alert=True)
    if data.startswith("logout_cf|"):
        phone = data.split("|", 1)[1]
        order = active_orders.pop(phone, None)
        if order:
            try:
                await order["client"].log_out()
            except Exception:
                pass
            try:
                await order["client"].disconnect()
            except Exception:
                pass
            delete_session_files(order["sess"])
        return await safe_show_message(e, "✅ Session logged out.")
    if data.startswith("lo_dev|"):
        _, phone, h = data.split("|")
        order = active_orders.get(phone)
        if not order:
            return await safe_answer_cb(e, "Order expired", alert=True)
        try:
            await order["client"](ResetAuthorizationRequest(hash=int(h)))
            return await safe_answer_cb(e, "Device logged out", alert=True)
        except Exception as ex:
            return await safe_answer_cb(e, str(ex), alert=True)
    if data.startswith("lo_all|"):
        phone = data.split("|", 1)[1]
        order = active_orders.get(phone)
        if not order:
            return await safe_answer_cb(e, "Order expired", alert=True)
        try:
            await order["client"](ResetAuthorizationsRequest())
            return await safe_answer_cb(e, "All other sessions logged out", alert=True)
        except Exception as ex:
            return await safe_answer_cb(e, str(ex), alert=True)

    # deposit admin
    if data.startswith("dep_acc|"):
        _, dep_id, t_uid, mode, amt = data.split("|")
        if mode == "exact":
            res = await approve_deposit(int(dep_id), int(amt))
            if res:
                await safe_answer_cb(e, "Approved", alert=True)
                return await safe_show_message(e, f"✅ Deposit #{dep_id} approved (₹{amt})")
            return await safe_answer_cb(e, "Already processed", alert=True)
        return await safe_answer_cb(e, "Custom amount: not implemented inline. Use /admin.", alert=True)
    if data.startswith("dep_rej|"):
        _, dep_id, t_uid = data.split("|")
        cur.execute("UPDATE deposits SET status='rejected' WHERE id=? AND status='pending'", (dep_id,))
        db.commit()
        try:
            await bot.send_message(int(t_uid), f"❌ Deposit #{dep_id} rejected.")
        except Exception:
            pass
        return await safe_answer_cb(e, "Rejected", alert=True)

    # withdrawal
    if data == "wd_sales":
        return await withdraw_menu(e)
    if data == "wd_main":
        row = cur.execute("SELECT sales_balance FROM users WHERE user_id=?", (uid,)).fetchone()
        bal = row[0] if row else 0
        if bal <= 0:
            return await safe_answer_cb(e, "No sales balance", alert=True)
        async with get_user_lock(uid):
            cur.execute("UPDATE users SET sales_balance=0, balance = balance + ? WHERE user_id=?", (bal, uid))
            db.commit()
        return await safe_answer_cb(e, f"₹{bal} moved to main balance", alert=True)

    # history pagination
    if data.startswith("page_purchases_"):
        return await history_page(e, int(data.split("_")[-1]))

    # promo
    if data == "claim_promo":
        return await claim_promo(e)

    # admin
    if data.startswith("adm_"):
        return await admin_callback(e, data)

    # fallback
    return await safe_answer_cb(e, "Unknown action", alert=True)


async def admin_callback(e, data):
    uid = e.sender_id
    if not is_admin(uid):
        return await safe_answer_cb(e, "Not admin", alert=True)
    action = data[4:]
    if action == "adminmain":
        try:
            await e.delete()
        except Exception:
            pass
        return await admin_panel(e)
    if action == "togglebot" and has_perm(uid, "p_settings"):
        new = "off" if is_bot_online() else "on"
        set_setting("bot_status", new)
        return await safe_answer_cb(e, f"Bot {new.upper()}", alert=True)
    if action == "reftoggle" and has_perm(uid, "p_settings"):
        new = "off" if is_ref_enabled() else "on"
        set_setting("ref_enabled", new)
        return await safe_answer_cb(e, f"Referral {new.upper()}", alert=True)
    if action == "stats" and has_perm(uid, "p_stats"):
        return await admin_stats(e)
    if action == "sellprices" and has_perm(uid, "p_settings"):
        rows = get_sell_price_rows()
        msg = "💸 <b>Sell Price List</b>\n\n"
        for r in rows:
            msg += f"[{r[2]}]+{r[0]}-{r[1]}: {_fmt_price(r[3], r[4])}\n"
        if not rows:
            msg += "No prices set."
        return await safe_show_message(e, msg, buttons=[[Button.inline("⬅️ Back", "adm_adminmain")]])
    if action in ("bal", "ban", "discount", "refpct", "supporturl", "usdtrate", "userinfo",
                  "bcast", "backupusr", "restoreusr", "blacklist", "payments", "catmenu",
                  "managestock", "autoprice"):
        return await safe_answer_cb(e, "Use /admin for interactive flows (WIP)", alert=True)
    return await safe_answer_cb(e, "Unknown admin action", alert=True)


# =============================================================
# 12) /start + text-input handlers
# =============================================================
@bot.on(events.NewMessage(pattern=r"^/start"))
async def handle_start(e):
    uid = e.sender_id
    if not uid:
        return
    ensure_user(uid)
    if is_user_banned(uid):
        return
    if not is_bot_online() and not is_admin(uid):
        return await e.respond(f"{P_OFF} <b>Under maintenance.</b>")

    text = e.raw_text or ""
    parts = text.split(maxsplit=1)
    if len(parts) > 1 and parts[1].startswith("ref_"):
        ref = parts[1].replace("ref_", "")
        if ref.isdigit() and int(ref) != uid:
            cur.execute("UPDATE users SET referred_by=? WHERE user_id=? AND referred_by IS NULL",
                        (int(ref), uid))
            db.commit()

    if not await is_joined_cached(uid):
        return await e.respond(JOIN_MSG, buttons=get_join_buttons())
    await reward_referrer_on_join(uid)
    if not terms_accepted(uid):
        return await e.respond(TERMS_MSG, buttons=get_terms_buttons())
    await send_main_menu(e, uid)


@bot.on(events.NewMessage())
async def handle_text_inputs(e):
    uid = e.sender_id
    text = (e.raw_text or "").strip()
    if not uid or not text or text.startswith("/"):
        return
    if text in MENU_LABELS:
        return  # reply keyboard handler already processed

    ensure_user(uid)
    if is_user_banned(uid):
        return

    if uid in deposit_input:
        # numeric text for deposit amount (safety fallback)
        if re.fullmatch(r"\d+", text):
            try:
                await show_upi_qr(e, int(text))
            except Exception as ex:
                await e.respond(f"❌ {ex}")
            deposit_input.pop(uid, None)
        return

    if uid in sell_state:
        st = sell_state[uid]
        if st.get("step") == "phone":
            await sell_process_phone(e, uid, text)
        return

    if uid in promo_state and promo_state[uid].get("step") == "code":
        promo_state.pop(uid, None)
        return await process_promo_code(e, uid, text)


# =============================================================
# 13) /cancel, /admin
# =============================================================
@bot.on(events.NewMessage(pattern=r"^/cancel"))
async def handle_cancel(e):
    uid = e.sender_id
    _clear_text_states(uid)
    await e.respond("❌ Cancelled.")


@bot.on(events.NewMessage(pattern=r"^/admin"))
async def handle_admin_cmd(e):
    if not is_admin(e.sender_id):
        return
    await admin_panel(e)


# =============================================================
# 14) MAIN
# =============================================================
async def main():
    logger.info("Starting bot...")
    await bot.start(bot_token=BOT_TOKEN)
    me = await bot.get_me()
    logger.info(f"Logged in as @{me.username} (id={me.id})")

    await recover_pending_orders()

    asyncio.create_task(cache_lzt_stock_loop())
    asyncio.create_task(upi_expiry_loop())

    try:
        await bot.send_message(ADMIN_ID, "✅ <b>Bot started successfully.</b>")
    except Exception:
        pass

    logger.info("Bot running. Ctrl+C to stop.")
    await bot.run_until_disconnected()


async def upi_expiry_loop():
    """Expire UPI orders older than 15 min."""
    while True:
        try:
            cur.execute("UPDATE upi_orders SET status='expired' "
                        "WHERE status='pending' AND date < datetime('now', '-15 minutes')")
            db.commit()
        except Exception as ex:
            logger.warning(f"upi_expiry: {ex}")
        await asyncio.sleep(60)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped by user.")
    except Exception as ex:
        logger.exception(f"FATAL: {ex}")
        sys.exit(1)
