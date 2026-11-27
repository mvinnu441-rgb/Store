import os
import sqlite3
import re
import asyncio
import time
import logging
import csv
import struct
import base64
from telethon.sessions import StringSession
from telethon.tl.functions.account import SendChangePhoneCodeRequest, ChangePhoneRequest
from telethon.tl.types import CodeSettings
import aiohttp
import traceback
import urllib.parse
import socket
import json
from telethon.errors import QueryIdInvalidError
import random
import zipfile
import shutil
import html
import hashlib
import string as _string
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

from telethon import TelegramClient, events, Button
from telethon.errors import (
    SessionPasswordNeededError,
    MessageNotModifiedError,
    UserNotParticipantError,
    ChatAdminRequiredError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    PhoneNumberInvalidError,
    PhoneNumberBannedError,
    FloodWaitError,
)
from telethon.tl.types import ReplyKeyboardMarkup, KeyboardButtonRow, KeyboardButton
from telethon.extensions import html as tl_html
from telethon.tl import types as tl_types
from telethon.tl.functions.channels import GetParticipantRequest
from telethon.tl.functions.account import GetPasswordRequest, GetAuthorizationsRequest, ResetAuthorizationRequest
from telethon.tl.functions.auth import ResetAuthorizationsRequest

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO,
    handlers=[logging.FileHandler("bot.log", encoding="utf-8"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


# ================= CONFIGURATION =================
def load_env_file(path=".env"):
    if not os.path.exists(path):
        return
    try:
        with open(path, encoding="utf-8") as env_file:
            for raw_line in env_file:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                os.environ.setdefault(key, value)
    except Exception as ex:
        print(f"Failed to load {path}: {ex}")


load_env_file()


def env_int(name, default=0):
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    return int(str(raw).strip())


def env_list(name, default_csv):
    raw = os.getenv(name, default_csv)
    return [item.strip() for item in raw.split(",") if item.strip()]


# [SECURITY] Secrets code me nahi hain. Inhe .env file me rakho:
# API_ID=...  API_HASH=...  BOT_TOKEN=...  ADMIN_ID=...
API_ID = env_int("API_ID", 0)
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = env_int("ADMIN_ID", 0)

# CHANNELS
# Admin log channel (deposit/withdraw requests) + public log channel (purchases/deposits feed)
LOG_CHANNEL_ID = env_int("ADMIN_LOG_CHANNEL_ID", env_int("LOG_CHANNEL_ID", 0))
LOOG_CHANNEL_ID = env_int("PUBLIC_LOG_CHANNEL_ID", env_int("LOOG_CHANNEL_ID", 0))
CHECK_CHANNELS = env_list("CHECK_CHANNELS", "")
JOIN_URLS = env_list("JOIN_URLS", "")

# LINKS & MEDIA
TERMS_URL = os.getenv("TERMS_URL", "https://t.me/")
if not TERMS_URL.startswith("http"):
    TERMS_URL = "https://" + TERMS_URL
CWALLET_QR = os.getenv("CWALLET_QR", "")
CWALLET_ID = os.getenv("CWALLET_ID", "")

# UPI API DETAILS
UPI_MID = os.getenv("UPI_MID", "")
UPI_ID = os.getenv("UPI_ID", "")

# Server 1 (LZT Market) settings - all optional, token can also be set from Admin Panel
LZT_TOKEN = os.getenv("LZT_TOKEN", "").strip()
LZT_BASE_URL = os.getenv("LZT_BASE_URL", "https://prod-api.lzt.market").rstrip("/")
LZT_PROXY = os.getenv("LZT_PROXY", "").strip()
LZT_REQUEST_TIMEOUT = float(os.getenv("LZT_REQUEST_TIMEOUT", "8") or 8)
FORCE_JOIN_ENABLED = os.getenv("FORCE_JOIN_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")

OTP_REGEX = r"\b\d{4,8}\b"
AUTO_CANCEL_SECONDS = 600          # OTP nahi aaya to 10 min baad refund
PAID_ORDER_TTL = 1800              # OTP milne ke 30 min baad bot session auto-logout

# Security/system notifications me OTP nahi dhoondna.
# NOTE: "if you didn't request this" yaha NAHI hai kyunki asli login code message me bhi yehi line hoti hai.
OTP_IGNORE_PHRASES = (
    "login detected", "new login", "new device", "two-step verification",
    "active sessions", "account from a new device", "account was used to",
    "settings changed", "password and/or email were changed",
    "if this wasn't you", "if somebody logged in",
    "if you think that somebody", "unusual activity", "someone tried to",
    "this device was logged in", "was deleted", "terminate that session",
)


def extract_login_code(msgs, start_time):
    """777000 (Telegram) ke messages me se sirf ASLI login code dhoondta hai."""
    for m in msgs:
        if not m.message or not m.date or m.date.timestamp() <= start_time - 30:
            continue
        txt = m.message
        low = txt.lower()
        mt = re.search(r"(?:login code|verification code|your code)\D{0,10}(\d{4,8})", low)
        if mt:
            return mt.group(1)
        if any(p in low for p in OTP_IGNORE_PHRASES):
            continue
        mt = re.search(OTP_REGEX, txt)
        if mt:
            return mt.group()
    return None


# ================= PREMIUM EMOJIS =================
# Premium emoji na chale (ya USE_PREMIUM_EMOJIS=0 ho) to neeche wale normal emoji dikhte hain.
USE_PREMIUM_EMOJIS = os.getenv("USE_PREMIUM_EMOJIS", "1").strip().lower() not in {"0", "false", "no", "off"}
PREMIUM_EMOJIS = {
    "heart_fire": "5042225965518816316",
    "lightning": "5042334757040423886",
    "location": "5039775669496579510",
    "flower": "6073117703965511893",
    "check": "6147460667281511517",
    "crown": "6235252066554484059",
    "kiss": "6116282026506065674",
    "skull": "6089128873893563936",
    "xmas": "6267071898702583835",
    "monkey": "6273627839862411998",
    "gift": "5893175870096414393",
    "angel": "5893411041030707544",
    "devil": "5893079628469246474",
}


def tg_emoji(name, fallback):
    emoji_id = PREMIUM_EMOJIS.get(name)
    if USE_PREMIUM_EMOJIS and emoji_id:
        return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'
    return fallback


# Premium emoji -> normal fallback emoji
PE_HEART = tg_emoji("heart_fire", "💖")      # ❤️‍🔥 -> 💖  (welcome, thanks)
PE_LIGHTNING = tg_emoji("lightning", "⚡")   # ⚡ -> ⚡    (orders, deposits)
PE_LOCATION = tg_emoji("location", "🌍")     # 📍 -> 🌍    (country lines)
PE_FLOWER = tg_emoji("flower", "♻️")         # 🌸 -> ♻️    (year select, terms)
PE_CHECK = tg_emoji("check", "✅")           # ✅ -> ✅    (success)
PE_CROWN = tg_emoji("crown", "☠️")           # 👑 -> ☠️    (admin, stats)
PE_KISS = tg_emoji("kiss", "👤")             # 😘 -> 👤    (profile)
PE_SKULL = tg_emoji("skull", "💀")
PE_XMAS = tg_emoji("xmas", "🎄")
PE_MONKEY = tg_emoji("monkey", "🐵")
PE_GIFT = tg_emoji("gift", "🎁")             # 🎁 -> 🎁    (refer, bulk purchase)
PE_ANGEL = tg_emoji("angel", "🎧")           # 😇 -> 🎧    (support)
PE_DEVIL = tg_emoji("devil", "😈")

# ================= UI ICONS =================
P_YES = PE_CHECK
P_NO = '❌'
P_PKG = '📦'
P_MONEY = '💰'
P_USDT = '💲'
P_INR = '₹'
P_TG = '✈️'
P_GIFT = PE_GIFT
P_STATS = '📊'
P_CARD = '💳'
P_USERS = '👥'
P_CAL = '📅'
P_PC = '💻'
P_EYE = '👁️'
P_UPI = '🏦'
P_CW = '👛'
P_ON = '🟢'
P_OFF = '🔴'
P_ID = '🆔'
P_KEY = '⌨️'
P_GLOBE = PE_LOCATION
P_CART = '🛒'
P_STORE = '🏬'
P_OTP = '🔢'
P_2FA = '🔐'
P_FLAG = '🏳️'
P_PHONE = '📱'
P_WAIT = '⏳'
P_TIME = '⏰'
P_WARN = '⚠️'
P_DOC = '📃'
P_SOS = '🆘'
P_ASST = '🤖'
P_ACC = '👤'
P_CASH = '💰'
P_TADA = '🎉'
P_SHIELD = '🛡'
P_BANK = '🏦'

# Persistent menu labels (button text aur handler dono yahi use karte hain)
BTN_BUY = "🛒 Buy Account"
BTN_SELL = "💸 Sell Account"
BTN_SESSIONS = "📁 Buy Sessions"
BTN_SELL_SESSIONS = "📁 Sell Sessions"
BTN_DEPOSIT = "💰 Deposit"
BTN_PROFILE = "👤 My Profile"
BTN_REFER = "🎁 Refer & Earn"
BTN_PROMO = "🎟️ Promo"
BTN_STATS = "📊 Stats"
BTN_SUPPORT = "📞 Support"
BTN_ADMIN = "🔐 Admin Panel"
MENU_LABELS = {BTN_BUY, BTN_SELL, BTN_SESSIONS, BTN_SELL_SESSIONS, BTN_DEPOSIT, BTN_PROFILE,
               BTN_REFER, BTN_PROMO, BTN_STATS, BTN_SUPPORT, BTN_ADMIN}


def validate_config():
    missing = []
    if API_ID <= 0:
        missing.append("API_ID")
    if not API_HASH:
        missing.append("API_HASH")
    if not BOT_TOKEN or ":" not in BOT_TOKEN:
        missing.append("BOT_TOKEN")
    if ADMIN_ID <= 0:
        missing.append("ADMIN_ID")
    if LOG_CHANNEL_ID == 0:
        missing.append("LOG_CHANNEL_ID")
    if missing:
        raise RuntimeError(
            "Missing/invalid required config: " + ", ".join(missing) +
            ". Set them in .env file or environment variables before starting the bot."
        )
    if not CHECK_CHANNELS:
        logger.warning("CHECK_CHANNELS is empty; join verification will be ineffective.")
    if not JOIN_URLS:
        logger.warning("JOIN_URLS is empty; users will not see join buttons.")
    if CHECK_CHANNELS and JOIN_URLS and len(CHECK_CHANNELS) != len(JOIN_URLS):
        logger.warning(
            "CHECK_CHANNELS (%s) and JOIN_URLS (%s) lengths differ.",
            len(CHECK_CHANNELS), len(JOIN_URLS)
        )


# Client banne se PEHLE config check
validate_config()

# ================= TEXT STYLE (Bold Serif CAPS + Small Caps) =================
_SMALL_CAPS = "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢ"
assert len(_SMALL_CAPS) == 26
STYLE_MAP = {}
for _i, _c in enumerate(_string.ascii_uppercase):
    STYLE_MAP[_c] = chr(0x1D400 + _i)
for _c, _sc in zip(_string.ascii_lowercase, _SMALL_CAPS):
    STYLE_MAP[_c] = _sc

STYLE_SKIP_RE = re.compile(r"@\w+|https?://\S+|t\.me/\S+|(?<!\S)/\w+")
_PROTECTED_NAMES = ("MessageEntityCode", "MessageEntityPre", "MessageEntityUrl", "MessageEntityMention",
                    "MessageEntityMentionName", "InputMessageEntityMentionName", "MessageEntityBotCommand",
                    "MessageEntityHashtag", "MessageEntityEmail", "MessageEntityCustomEmoji")
STYLE_PROTECTED = tuple(getattr(tl_types, n) for n in _PROTECTED_NAMES if hasattr(tl_types, n))


def style_plain(text, entities, protected=STYLE_PROTECTED):
    if not text:
        return text, entities
    n = len(text)
    prot = [False] * n
    for m in STYLE_SKIP_RE.finditer(text):
        for i in range(m.start(), m.end()):
            prot[i] = True

    pos, u = [], 0
    for ch in text:
        pos.append(u)
        u += 2 if ord(ch) > 0xFFFF else 1
    total = u

    for en in (entities or []):
        if isinstance(en, protected):
            a, b = en.offset, en.offset + en.length
            for i, pu in enumerate(pos):
                if a <= pu < b:
                    prot[i] = True

    out, mp, newu = [], [0] * (total + 2), 0
    for i, ch in enumerate(text):
        new_ch = ch if prot[i] else STYLE_MAP.get(ch, ch)
        w_old = 2 if ord(ch) > 0xFFFF else 1
        w_new = 2 if ord(new_ch) > 0xFFFF else 1
        for k in range(w_old):
            mp[pos[i] + k] = newu
        out.append(new_ch)
        newu += w_new
    mp[total] = newu
    mp[total + 1] = newu

    for en in (entities or []):
        a = mp[min(en.offset, total)]
        b = mp[min(en.offset + en.length, total)]
        en.offset, en.length = a, max(b - a, 0)
    return "".join(out), entities


class StyledHTML:
    def parse(self, message):
        text, entities = tl_html.parse(message)
        return style_plain(text, entities)

    def unparse(self, text, entities):
        return tl_html.unparse(text, entities)


# ================= INITIALIZATION =================
os.makedirs("sessions", exist_ok=True)

session_name = f"bot_session_{BOT_TOKEN.split(':')[0] or 'bot'}"
bot = TelegramClient(session_name, API_ID, API_HASH)
bot.parse_mode = StyledHTML()

db = sqlite3.connect("otp_bot_final.db", check_same_thread=False, timeout=20)
db.execute("PRAGMA journal_mode=WAL;")
cur = db.cursor()

active_orders = {}
waiting_proof = {}
deposit_input = {}
admin_dep_state = {}
user_spam_cooldown = {}
session_buy_state = {}
custom_dep_amt = {}
_join_cache = {}

user_locks = {}


def get_user_lock(uid):
    if uid not in user_locks:
        user_locks[uid] = asyncio.Lock()
    return user_locks[uid]


class AdminCancelled(Exception):
    pass


# ================= DATABASE SCHEMA =================
def setup_db():
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        balance INTEGER DEFAULT 0,
        referred_by INTEGER,
        total_deposited INTEGER DEFAULT 0,
        joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        banned INTEGER DEFAULT 0,
        discount INTEGER DEFAULT 0,
        terms_accepted INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS stock (
        phone TEXT PRIMARY KEY,
        session_file TEXT,
        country_name TEXT,
        country_icon TEXT DEFAULT '🌍',
        account_year INTEGER,
        category TEXT DEFAULT 'Good',
        price INTEGER,
        available INTEGER DEFAULT 1,
        twofa TEXT DEFAULT 'None',
        added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS auto_prices (
        country TEXT,
        year TEXT,
        price INTEGER,
        PRIMARY KEY (country, year)
    );
    CREATE TABLE IF NOT EXISTS deposits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount INTEGER,
        method_name TEXT,
        status TEXT,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS upi_orders (
        order_id TEXT PRIMARY KEY,
        user_id INTEGER,
        amount INTEGER,
        status TEXT,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        country TEXT,
        year INTEGER,
        price INTEGER,
        phone TEXT,
        otp TEXT,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS custom_payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        caption TEXT,
        qr_file_id TEXT
    );
    CREATE TABLE IF NOT EXISTS admins (
        user_id INTEGER PRIMARY KEY,
        p_add_stock INTEGER DEFAULT 0,
        p_manage_stock INTEGER DEFAULT 0,
        p_stats INTEGER DEFAULT 0,
        p_bal INTEGER DEFAULT 0,
        p_settings INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS custom_countries (
        code TEXT PRIMARY KEY,
        name TEXT,
        flag TEXT
    );
    CREATE TABLE IF NOT EXISTS pending_orders (
        phone TEXT PRIMARY KEY,
        user_id INTEGER,
        price INTEGER,
        created REAL
    );
    CREATE TABLE IF NOT EXISTS api_credentials (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        api_id INTEGER,
        api_hash TEXT
    );
    CREATE TABLE IF NOT EXISTS lzt_settings (country TEXT PRIMARY KEY, markup_percent INTEGER DEFAULT 20);
    CREATE TABLE IF NOT EXISTS user_filters (
        user_id INTEGER PRIMARY KEY,
        profile TEXT DEFAULT 'default',
        filters_json TEXT DEFAULT '{}'
    );
    CREATE TABLE IF NOT EXISTS sell_prices (
        country_code TEXT,
        year TEXT,
        price_good INTEGER DEFAULT 20,
        price_spam INTEGER DEFAULT 5,
        PRIMARY KEY (country_code, year)
    );
    CREATE TABLE IF NOT EXISTS sell_submissions (
        phone TEXT PRIMARY KEY,
        user_id INTEGER,
        country TEXT,
        flag TEXT,
        year INTEGER,
        price INTEGER,
        is_spam INTEGER DEFAULT 0,
        twofa TEXT,
        msg_id INTEGER,
        status TEXT DEFAULT 'holding',
        reason TEXT,
        created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS withdrawals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount INTEGER,
        method TEXT,
        details TEXT,
        status TEXT DEFAULT 'pending',
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS blacklisted_phones (phone TEXT PRIMARY KEY, removed_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS promo_codes (
        code TEXT PRIMARY KEY,
        value INTEGER,
        max_uses INTEGER DEFAULT 1,
        used_count INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS promo_logs (
        code TEXT,
        user_id INTEGER,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS giveaways (
        id TEXT PRIMARY KEY,
        prize_name TEXT,
        ticket_price INTEGER,
        min_participants INTEGER,
        winners_count INTEGER DEFAULT 1,
        status TEXT DEFAULT 'open',
        created_by INTEGER,
        message_id INTEGER DEFAULT NULL,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS giveaway_tickets (
        giveaway_id TEXT,
        user_id INTEGER,
        tickets INTEGER DEFAULT 0,
        PRIMARY KEY (giveaway_id, user_id)
    );
    CREATE TABLE IF NOT EXISTS number_change_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        old_phone TEXT,
        new_phone TEXT,
        fee INTEGER,
        status TEXT DEFAULT 'pending',
        note TEXT,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS manual_sell_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        kind TEXT,
        phone TEXT,
        details TEXT,
        status TEXT DEFAULT 'pending',
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS fight_games (
        id TEXT PRIMARY KEY,
        creator_id INTEGER,
        amount INTEGER,
        status TEXT DEFAULT 'open',
        created REAL DEFAULT 0
    );
    """)
    db.commit()


setup_db()

try:
    cur.execute("ALTER TABLE users ADD COLUMN ref_rewarded INTEGER DEFAULT 0")
    cur.execute("UPDATE users SET ref_rewarded=1")
    db.commit()
except sqlite3.OperationalError:
    pass

try:
    cur.execute("UPDATE stock SET category='spam_free' WHERE category IS NULL OR category NOT IN ('spam_free','limit_spam','premium','whatsapp','allapp')")
    db.commit()
except sqlite3.OperationalError:
    pass

try:
    cols = [r[1] for r in cur.execute("PRAGMA table_info(auto_prices)").fetchall()]
    if 'category' not in cols:
        cur.execute("ALTER TABLE auto_prices RENAME TO auto_prices_old")
        cur.execute("""CREATE TABLE auto_prices (
            category TEXT,
            country TEXT,
            year TEXT,
            price INTEGER,
            PRIMARY KEY (category, country, year)
        )""")
        cur.execute("INSERT INTO auto_prices (category, country, year, price) SELECT 'spam_free', country, year, price FROM auto_prices_old")
        cur.execute("DROP TABLE auto_prices_old")
        db.commit()
except sqlite3.OperationalError:
    pass


def _add_column(table, column, ddl):
    """Safe ALTER TABLE ADD COLUMN (ignores if column already exists)."""
    cols = [r[1] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        db.commit()


for _t, _c, _d in [
    ("users", "sales_balance", "INTEGER DEFAULT 0"),
    ("users", "username", "TEXT DEFAULT ''"),
    ("users", "first_name", "TEXT DEFAULT ''"),
    ("upi_orders", "created_ts", "REAL DEFAULT 0"),
    ("orders", "server", "TEXT DEFAULT 'Server 2'"),
    ("orders", "item_ref", "TEXT"),
    ("users", "pref_curr", "TEXT DEFAULT 'INR'"),
    ("upi_orders", "qr_msg_id", "INTEGER DEFAULT 0"),
    ("stock", "seller_id", "INTEGER"),
    ("stock", "spam_status", "TEXT DEFAULT 'clean'"),
    ("stock", "has_premium", "INTEGER DEFAULT 0"),
    ("stock", "origin", "TEXT DEFAULT ''"),
    ("stock", "breakout_days", "INTEGER DEFAULT 0"),
    ("stock", "has_mail", "INTEGER DEFAULT 0"),
    ("stock", "dc_id", "INTEGER DEFAULT 0"),
    ("stock", "gifts", "INTEGER DEFAULT 0"),
    ("stock", "stars", "INTEGER DEFAULT 0"),
    ("stock", "is_admin_acc", "INTEGER DEFAULT 0"),
    ("stock", "app_name", "TEXT DEFAULT ''"),
    ("stock", "delivery_data", "TEXT DEFAULT ''"),
]:
    try:
        _add_column(_t, _c, _d)
    except sqlite3.OperationalError as _ex:
        logger.warning("Migration %s.%s skipped: %s", _t, _c, _ex)


# ================= COUNTRY HASH HELPERS =================
# Telegram callback data max 64 bytes hota hai. Lambe country naam seedha button me bhejne par fail hote the.
# Isliye poore naam ka chhota hash bhejte hain aur DB se EXACT naam wapas nikalte hain.
def country_hash(name):
    return hashlib.md5(str(name).encode("utf-8")).hexdigest()[:10]


def resolve_country(category, h):
    """Stock ke us category me se exact country naam nikalta hai."""
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
    """Admin panel ke liye: stock + built-in + custom saare countries me se exact naam."""
    for n in all_country_names(category):
        if country_hash(n) == h:
            return n
    return None


def find_existing_price(country, category, year=None):
    """Same EXACT naam + same category ka price. Pehle same year, nahi to us naam ka koi bhi."""
    if year is not None:
        r = cur.execute("SELECT price FROM stock WHERE country_name=? AND category=? AND account_year=? LIMIT 1",
                        (country, category, int(year))).fetchone()
        if r:
            return r[0]
    r = cur.execute("SELECT price FROM stock WHERE country_name=? AND category=? LIMIT 1", (country, category)).fetchone()
    return r[0] if r else None


# ================= HELPER FUNCTIONS =================
def is_bot_online():
    res = cur.execute("SELECT value FROM settings WHERE key='bot_status'").fetchone()
    return res[0] == 'on' if res else True


def is_admin(uid):
    if uid == ADMIN_ID:
        return True
    row = cur.execute("SELECT user_id FROM admins WHERE user_id=?", (uid,)).fetchone()
    return bool(row)


def has_perm(uid, perm):
    if uid == ADMIN_ID:
        return True
    if perm not in ("p_add_stock", "p_manage_stock", "p_stats", "p_bal", "p_settings"):
        return False
    row = cur.execute(f"SELECT {perm} FROM admins WHERE user_id=?", (uid,)).fetchone()
    return bool(row and row[0] == 1)


def ensure_user(uid):
    cur.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (uid,))
    db.commit()


def user_exists(uid):
    return bool(cur.execute("SELECT 1 FROM users WHERE user_id=?", (uid,)).fetchone())


def get_usdt_rate():
    res = cur.execute("SELECT value FROM settings WHERE key='usdt_rate'").fetchone()
    try:
        return float(res[0]) if res else 94.0
    except Exception:
        return 94.0


def get_support_url():
    res = cur.execute("SELECT value FROM settings WHERE key='support_url'").fetchone()
    url = res[0] if res and res[0] else "https://t.me/vinnu_exe"
    if not url.startswith("http"):
        url = "https://" + url.replace("@", "t.me/")
    return url


def to_usd(inr):
    return round(inr / get_usdt_rate(), 2)


def is_user_banned(uid):
    res = cur.execute("SELECT banned FROM users WHERE user_id=?", (uid,)).fetchone()
    return res and res[0] == 1


def update_balance(uid, amount):
    cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, uid))
    db.commit()


def add_upi_revenue(method, amt):
    """UPI se approve hui deposit ko 'upi_revenue' me jodta hai (commit caller karega)."""
    if str(method).startswith("UPI"):
        cur.execute(
            "INSERT INTO settings(key,value) VALUES('upi_revenue',?) "
            "ON CONFLICT(key) DO UPDATE SET value=CAST(CAST(value AS INTEGER)+? AS TEXT)",
            (str(int(amt)), int(amt)))


def delete_session_files(session_path):
    base = session_path if not session_path.endswith('.session') else session_path[:-8]
    for ext in ['.session', '.session-wal', '.session-shm', '.session-journal']:
        try:
            if os.path.exists(base + ext):
                os.remove(base + ext)
        except Exception:
            pass


async def check_channel_joined(uid):
    if is_admin(uid):
        return True
    for ch in CHECK_CHANNELS:
        try:
            ch_id = int(ch.strip()) if str(ch).strip().lstrip('-').isdigit() else ch.strip()
            try:
                await bot(GetParticipantRequest(channel=ch_id, participant=uid))
            except ValueError:
                entity = await bot.get_entity(ch_id)
                await bot(GetParticipantRequest(channel=entity, participant=uid))
        except UserNotParticipantError:
            return False
        except ChatAdminRequiredError:
            logger.error(f"Bot is not admin in channel: {ch}")
            return False
        except Exception as e:
            logger.error(f"Channel Check Error for {ch}: {e}")
            return False
    return True


async def is_joined_cached(uid):
    """Har message/click par API na lage isliye 60 sec ka cache (sirf success ka)."""
    if is_admin(uid):
        return True
    t = _join_cache.get(uid)
    if t and time.time() - t < 60:
        return True
    ok = await check_channel_joined(uid)
    if ok:
        _join_cache[uid] = time.time()
    return ok


def terms_accepted(uid):
    row = cur.execute("SELECT terms_accepted FROM users WHERE user_id=?", (uid,)).fetchone()
    return bool(row and row[0])


COUNTRY_CODES = {
    '1': ('USA', '🇺🇸'), '7': ('Russia', '🇷🇺'), '20': ('Egypt', '🇪🇬'),
    '27': ('South Africa', '🇿🇦'), '31': ('Netherlands', '🇳🇱'), '32': ('Belgium', '🇧🇪'),
    '33': ('France', '🇫🇷'), '34': ('Spain', '🇪🇸'), '39': ('Italy', '🇮🇹'),
    '44': ('UK', '🇬🇧'), '46': ('Sweden', '🇸🇪'), '48': ('Poland', '🇵🇱'),
    '49': ('Germany', '🇩🇪'), '51': ('Peru', '🇵🇪'), '52': ('Mexico', '🇲🇽'),
    '54': ('Argentina', '🇦🇷'), '55': ('Brazil', '🇧🇷'), '56': ('Chile', '🇨🇱'),
    '57': ('Colombia', '🇨🇴'), '58': ('Venezuela', '🇻🇪'), '60': ('Malaysia', '🇲🇾'),
    '61': ('Australia', '🇦🇺'), '62': ('Indonesia', '🇮🇩'), '63': ('Philippines', '🇵🇭'),
    '66': ('Thailand', '🇹🇭'), '84': ('Vietnam', '🇻🇳'), '86': ('China', '🇨🇳'),
    '90': ('Turkey', '🇹🇷'), '91': ('India', '🇮🇳'), '92': ('Pakistan', '🇵🇰'),
    '93': ('Afghanistan', '🇦🇫'), '94': ('Sri Lanka', '🇱🇰'), '95': ('Myanmar', '🇲🇲'),
    '98': ('Iran', '🇮🇷'), '212': ('Morocco', '🇲🇦'), '213': ('Algeria', '🇩🇿'),
    '234': ('Nigeria', '🇳🇬'), '254': ('Kenya', '🇰🇪'), '255': ('Tanzania', '🇹🇿'),
    '380': ('Ukraine', '🇺🇦'), '880': ('Bangladesh', '🇧🇩'), '964': ('Iraq', '🇮🇶'),
    '966': ('Saudi Arabia', '🇸🇦'), '971': ('UAE', '🇦🇪'), '998': ('Uzbekistan', '🇺🇿')
}


def get_flag_by_country_name(name):
    for code, (c_name, c_flag) in COUNTRY_CODES.items():
        if c_name == name:
            return c_flag
    try:
        row = cur.execute("SELECT flag FROM custom_countries WHERE name=?", (name,)).fetchone()
        if row:
            return row[0]
        row = cur.execute("SELECT country_icon FROM stock WHERE country_name=? LIMIT 1", (name,)).fetchone()
        if row and row[0]:
            return row[0]
    except Exception:
        pass
    return "🌍"


def get_country_info(phone):
    phone = str(phone).replace(' ', '').replace('+', '')
    if not phone:
        return "Unknown", "🌍"

    try:
        customs = cur.execute("SELECT code, name, flag FROM custom_countries").fetchall()
        customs.sort(key=lambda x: len(x[0]), reverse=True)
        for code, name, flag in customs:
            if phone.startswith(code):
                return name, flag
    except Exception:
        pass

    for length in (3, 2, 1):
        prefix = phone[:length]
        if prefix in COUNTRY_CODES:
            return COUNTRY_CODES[prefix]
    return "Unknown", "🌍"


async def detect_account_year(client):
    year = 2024
    try:
        try:
            await client.delete_dialog('TGrv_bot')
        except Exception:
            pass
        await client.send_message('TGrv_bot', '/start')
        me = await client.get_me()
        await asyncio.sleep(1)
        await client.send_message('TGrv_bot', str(me.id))
        for _ in range(8):
            await asyncio.sleep(1.5)
            msgs = await client.get_messages('TGrv_bot', limit=3)
            for m in msgs:
                if m.text and ('Created:' in m.text or 'Age:' in m.text or 'Registration' in m.text):
                    match = re.search(r'(?:Created|Age|Registration)[^\d]*(\d{4})', m.text, re.IGNORECASE)
                    if match:
                        return int(match.group(1))
    except Exception:
        pass
    return year


NEW_2FA = "2007"


async def force_2fa_2007(client, old_password=None):
    """Account ka 2FA password 2007 kar deta hai. Return: (ok, error_text)"""
    try:
        pwd = await client(GetPasswordRequest())
        if pwd.has_password:
            if not old_password or old_password == "None":
                return False, "purana 2FA password pata nahi"
            if old_password == NEW_2FA:
                return True, None
            await client.edit_2fa(current_password=old_password, new_password=NEW_2FA, hint="")
        else:
            await client.edit_2fa(new_password=NEW_2FA, hint="")
        return True, None
    except Exception as ex:
        return False, str(ex)[:120]


# ================= REFERRAL SYSTEM (FLAT ₹ PER REFER) =================
def is_ref_enabled():
    r = cur.execute("SELECT value FROM settings WHERE key='ref_enabled'").fetchone()
    return r[0] == 'on' if r else True


def get_ref_bonus():
    r = cur.execute("SELECT value FROM settings WHERE key='ref_bonus'").fetchone()
    try:
        return int(r[0]) if r else 1
    except Exception:
        return 1


# ================= LOGGING LOGIC =================
async def log_primary_deposit(uid, amt, method):
    try:
        try:
            user = await bot.get_entity(int(uid))
            username = html.escape(user.username) if user.username else "NoUsername"
        except Exception:
            username = "NoUsername"
        t = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        msg = (f"{PE_GIFT} <b>NEW DEPOSIT SUCCESSFUL</b>\n\n"
               f"{P_ACC} Uꜱᴇʀ ID: <code>{uid}</code>\n"
               f"👤 Uꜱᴇʀɴᴀᴍᴇ: @{username}\n"
               f"{P_MONEY} Aᴍᴏᴜɴᴛ: {P_INR}{amt}\n"
               f"{P_CARD} Mᴇᴛʜᴏᴅ: {html.escape(str(method))}\n"
               f"{P_TIME} Tɪᴍᴇ: {t}\n\n"
               f"<i>{PE_HEART} Thanks for depositing in Vinnu Account Store!</i>")
        try:
            await bot.send_message(LOG_CHANNEL_ID, msg)
        except Exception as e:
            logger.error(f"Failed Log: {e}")
    except Exception as e:
        logger.error(f"Global Dep Log Err: {e}")


async def log_primary_purchase(uid, country, price, amount, year, qty):
    try:
        t = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        msg = (f"{PE_LIGHTNING} <b>NEW PURCHASE SUCCESSFUL</b>\n\n"
               f'{P_ID} Uꜱᴇʀ Iᴅ: <code>******{str(uid)[-4:]}</code>\n'
               f"{P_GLOBE} Cᴏᴜɴᴛʀʏ: {html.escape(str(country))}\n"
               f"{P_MONEY} Pʀɪᴄᴇ: {P_INR}{price}\n"
               f"{P_CARD} Tᴏᴛᴀʟ Pᴀɪᴅ: {P_INR}{amount}\n"
               f"{P_CAL} Yᴇᴀʀ: {year}\n"
               f"{P_PKG} Qᴜᴀɴᴛɪᴛʏ: {qty}\n"
               f"{P_TIME} Tɪᴍᴇ: {t}")
        try:
            await bot.send_message(LOOG_CHANNEL_ID, msg)
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Pur Log Err: {e}")


# ================= MENU HELPERS =================
def get_persistent_menu(uid):
    rows = [
        [KeyboardButton(BTN_BUY), KeyboardButton(BTN_SELL)],
        [KeyboardButton(BTN_SESSIONS), KeyboardButton(BTN_SELL_SESSIONS)],
        [KeyboardButton(BTN_DEPOSIT), KeyboardButton(BTN_PROFILE)],
        [KeyboardButton(BTN_REFER), KeyboardButton(BTN_PROMO)],
        [KeyboardButton(BTN_STATS), KeyboardButton(BTN_SUPPORT)],
    ]
    if is_admin(uid):
        rows.append([KeyboardButton(BTN_ADMIN)])
    return ReplyKeyboardMarkup([KeyboardButtonRow(r) for r in rows], resize=True)


def get_terms_buttons():
    return [
        [Button.url("📜 Read Terms & Conditions", TERMS_URL)],
        [Button.inline("✅ Accept", "tc_accept"), Button.inline("❌ Reject", "tc_reject")]
    ]


def get_support_buttons():
    buttons = [
        [Button.url("📩 Support", get_support_url())],
        [Button.url("📜 Terms & Conditions", TERMS_URL)]
    ]
    if JOIN_URLS:
        buttons.append([Button.url("📢 Channel", JOIN_URLS[0])])
    return buttons


def get_join_buttons():
    buttons = [[Button.url(f"📢 Join Channel {i+1}", link)] for i, link in enumerate(JOIN_URLS) if link]
    buttons.append([Button.inline("✅ Verify Joined", "verify_join")])
    return buttons


JOIN_MSG = (f"{PE_FLOWER} <b>You must join our channels first!</b>\n"
            f"{PE_LOCATION} Join all required channels and then tap <b>Verify Joined</b>.")
TERMS_MSG = (f"{PE_FLOWER} <b>TERMS & CONDITIONS</b>\n"
             f"Please read and accept our Terms & Conditions before using the bot.")


async def build_welcome(uid):
    if is_ref_enabled():
        me = await bot.get_me()
        link = (f"{P_GLOBE} <code>https://t.me/{me.username}?start=ref_{uid}</code>"
                if me.username else f"{P_GLOBE} <i>Set a public bot username.</i>")
        ref_part = (f"{P_GIFT} <b>Refer & Earn:</b>\n"
                    f"Invite friends and earn per refer {P_INR}{get_ref_bonus()}\n{link}")
    else:
        ref_part = (f"{P_OFF} <b>Referral service is temporarily off.</b>\n\n"
                    f"Please check back later.")
    return (f"{PE_HEART} <b>Welcome to Vinnu Account Store!</b>\n\n"
            f"{PE_GIFT} <b>Premium services:</b> Buy accounts, sessions, and top up instantly.\n"
            f"{ref_part}\n\n"
            f"👨‍💻 <b>Developer:</b> @vinnu_exe")


async def refer_handler(event):
    await bot.send_message(event.chat_id, await build_welcome(event.sender_id))


async def send_main_menu(event, uid):
    msg = await build_welcome(uid)
    if isinstance(event, events.CallbackQuery.Event):
        try:
            await event.delete()
        except Exception:
            pass
        await bot.send_message(uid, msg, buttons=get_persistent_menu(uid))
    else:
        await event.respond(msg, buttons=get_persistent_menu(uid))


# ================= DEPOSIT HANDLERS =================
def format_payment_buttons(buttons):
    n = len(buttons)
    res = []
    for i in range(0, n, 2):
        res.append(buttons[i:i+2])
    return res


async def deposit_menu(event):
    msg = (f"{P_CARD} <b>Select Payment Method:</b>\n\n"
           f"{PE_LIGHTNING} Choose Automatic for instant credit.\n"
           f"{P_WAIT} Choose Manual for other methods.")
    flat_buttons = []
    if is_method_on("upi_status"):
        flat_buttons.append(Button.inline("⚡ UPI Automatic", "dep_upi"))
    if is_method_on("cwallet_status"):
        flat_buttons.append(Button.inline("👛 Cwallet ( +5% )", "depm_cw"))
    # Naam ki jagah ID bhejte hain (callback data 64 byte limit)
    customs = cur.execute("SELECT id, name FROM custom_payments").fetchall()
    for cid, cname in customs:
        flat_buttons.append(Button.inline(f"💳 {cname}", f"depm_{cid}"))

    btns = format_payment_buttons(flat_buttons)
    await bot.send_message(event.chat_id, msg, buttons=btns)


def get_keypad():
    return [
        [Button.inline("1", "kp_1"), Button.inline("2", "kp_2"), Button.inline("3", "kp_3")],
        [Button.inline("4", "kp_4"), Button.inline("5", "kp_5"), Button.inline("6", "kp_6")],
        [Button.inline("7", "kp_7"), Button.inline("8", "kp_8"), Button.inline("9", "kp_9")],
        [Button.inline("🔙 Del", "kp_del"), Button.inline("0", "kp_0"), Button.inline("✅ Confirm", "kp_done")],
        [Button.inline("❌ Cancel", "cancel_action")]
    ]


def get_admin_custom_keypad(dep_id):
    return [
        [Button.inline("1", f"dkp|{dep_id}|1"), Button.inline("2", f"dkp|{dep_id}|2"), Button.inline("3", f"dkp|{dep_id}|3")],
        [Button.inline("4", f"dkp|{dep_id}|4"), Button.inline("5", f"dkp|{dep_id}|5"), Button.inline("6", f"dkp|{dep_id}|6")],
        [Button.inline("7", f"dkp|{dep_id}|7"), Button.inline("8", f"dkp|{dep_id}|8"), Button.inline("9", f"dkp|{dep_id}|9")],
        [Button.inline("🔙 Del", f"dkp|{dep_id}|del"), Button.inline("0", f"dkp|{dep_id}|0"), Button.inline("✅ Confirm", f"dkp|{dep_id}|conf")],
        [Button.inline("❌ Cancel", f"dkp|{dep_id}|cancel")]
    ]


def deposit_request_buttons(dep_id, uid, amt, with_custom=True):
    # Method naam callback me nahi bhejte; DB se dep_id se nikalte hain.
    rows = [[Button.inline(f"✅ Accept (₹{amt})", f"dep_acc|{dep_id}|{uid}|exact|{amt}"),
             Button.inline("❌ Reject", f"dep_rej|{dep_id}|{uid}")]]
    if with_custom:
        rows.append([Button.inline("📝 Custom Amount", f"dep_acc|{dep_id}|{uid}|custom|0")])
    return rows


async def manual_deposit_init(event, key):
    uid = event.sender_id
    if key == "cw":
        method = "Cwallet"
    else:
        try:
            row = cur.execute("SELECT name FROM custom_payments WHERE id=?", (int(key),)).fetchone()
        except ValueError:
            row = None
        if not row:
            return await event.answer("❌ Ye payment method ab available nahi hai.", alert=True)
        method = row[0]
    deposit_input[uid] = {'step': 'wait_amt', 'method': method}
    await event.edit(f"{P_CARD} <b>{html.escape(method)} Deposit</b>\n\n👇 Reply to this message with the <b>AMOUNT</b> in ₹ (INR) you want to deposit.",
                     buttons=[[Button.inline("❌ Cancel", "cancel_action")]])


async def init_upi_keypad(event):
    uid = event.sender_id
    deposit_input[uid] = {'step': 'upi_keypad', 'val': '0'}
    await event.edit(f"{P_KEY} <b>ENTER AMOUNT IN INR (Min ₹1)</b>\n\n{P_MONEY} <code>₹0</code>", buttons=get_keypad())


async def keypad_logic(event):
    uid = event.sender_id
    action = event.data.decode().replace("kp_", "")
    curr = deposit_input.get(uid, {}).get('val', "0")

    if action.isdigit():
        if curr == "0":
            curr = action
        else:
            curr += action
        if len(curr) > 5:
            curr = curr[:5]
    elif action == "del":
        curr = curr[:-1] or "0"
    elif action == "done":
        amt = int(curr)
        if amt < 1:
            return await event.answer("⚠️ Minimum Deposit is ₹1", alert=True)
        return await show_upi_qr(event, amt)

    deposit_input[uid] = {'step': 'upi_keypad', 'val': curr}
    try:
        await event.edit(f"{P_KEY} <b>ENTER AMOUNT IN INR</b>\n\n{P_MONEY} <code>₹{curr}</code>", buttons=get_keypad())
    except MessageNotModifiedError:
        pass


async def show_upi_qr(event, amount):
    uid = event.sender_id
    order_id = f"ORDER_{uid}_{int(time.time())}"
    await event.edit(f"{P_WAIT} Generating Payment QR...")

    upi_url = f"upi://pay?pa={UPI_ID}&pn=VinnuAccountStore&am={amount}&cu=INR"
    encoded_upi = quote(upi_url)
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=400x400&data={encoded_upi}"

    try:
        cur.execute("INSERT INTO upi_orders (order_id, user_id, amount, status, created_ts) VALUES (?,?,?,?,?)", (order_id, uid, amount, "pending", time.time()))
        db.commit()

        msg = (f"{PE_LIGHTNING} <b>AUTOMATIC UPI PAYMENT</b>\n\n"
               f"{P_MONEY} Amount: <code>₹{amount}</code>\n"
               f"{P_ID} Order ID: <code>{order_id}</code>\n\n"
               f"👇 <b>Scan the QR below or Pay to:</b>\n<code>{UPI_ID}</code>\n\n"
               f"⚠️ <b>AFTER PAYING:</b> Tap the button below to submit your 12-Digit UTR/Reference Number.")

        await event.delete()
        qr_msg = await bot.send_file(uid, qr_url, caption=msg, buttons=[
            [Button.inline("✅ Submit UTR (12 Digit)", f"submit_utr_{order_id}")],
            [Button.inline("❌ Cancel", "cancel_action")]
        ])
        cur.execute("UPDATE upi_orders SET qr_msg_id=? WHERE order_id=?", (getattr(qr_msg, "id", 0) or 0, order_id))
        db.commit()
    except Exception as e:
        await bot.send_message(uid, f"{P_NO} Error: {html.escape(str(e))}")


async def verify_upi_payment(event, order_id):
    uid = event.sender_id
    row = cur.execute("SELECT amount, status, user_id FROM upi_orders WHERE order_id=?", (order_id,)).fetchone()
    if not row or row[2] != uid:
        return await event.answer("❌ Order not found.", alert=True)
    if row[1] not in ('pending', 'expired'):
        return await event.answer("⚠️ Is order ka UTR pehle hi submit ho chuka hai.", alert=True)

    chat = event.chat_id
    await event.delete()

    async with bot.conversation(chat, timeout=120) as conv:
        try:
            await conv.send_message("👇 <b>Please enter the 12-Digit UTR / Reference Number of your payment:</b>\n\n<i>(Type /cancel to abort)</i>")
            resp = await conv.get_response()
            utr_number = resp.raw_text.strip()

            if utr_number == "/cancel":
                return await conv.send_message("❌ Cancelled.")
            if not re.fullmatch(r"\d{12}", utr_number):
                return await conv.send_message("❌ Invalid UTR. Exactly 12 digits chahiye. Dobara try karo.")
            if cur.execute("SELECT 1 FROM deposits WHERE method_name LIKE ?", (f"%UTR: {utr_number})%",)).fetchone():
                return await conv.send_message("❌ Ye UTR pehle use ho chuka hai.")

            # Order ko atomically 'submitted' mark karo (double submit roko)
            cur.execute("UPDATE upi_orders SET status='submitted' WHERE order_id=? AND status IN ('pending','expired')", (order_id,))
            if cur.rowcount == 0:
                db.commit()
                return await conv.send_message("⚠️ Is order ka UTR pehle hi submit ho chuka hai.")

            await conv.send_message(f"⏳ Verifying UTR: <code>{html.escape(utr_number)}</code>...\n<i>Please wait...</i>")

            amt = int(row[0])

            cur.execute("INSERT INTO deposits (user_id, amount, method_name, status) VALUES (?,?,?,?)",
                        (uid, amt, f"UPI (UTR: {utr_number})", "pending"))
            db.commit()
            dep_id = cur.lastrowid

            cap = (f"{PE_LIGHTNING} <b>NEW UPI DEPOSIT (Needs Approval)</b>\n"
                   f"{P_ACC} User: <code>{uid}</code>\n"
                   f"{P_MONEY} Amount: <b>₹{amt}</b>\n"
                   f"🧾 UTR Submitted: <code>{html.escape(utr_number)}</code>\n"
                   f"Please verify this UTR in your Payment app.")

            await bot.send_message(LOG_CHANNEL_ID, cap, buttons=deposit_request_buttons(dep_id, uid, amt, with_custom=False))
            await conv.send_message("✅ <b>UTR Submitted successfully!</b>\nAmount will be added to your balance as soon as our system/admin verifies the payment.")

        except asyncio.TimeoutError:
            await conv.send_message("❌ Time out. Dobara 'Submit UTR' dabao.")
        except Exception as e:
            logger.error(f"UTR error: {e}")
            await conv.send_message("❌ Error aaya. Try again.")


async def approve_deposit(dep_id, amt):
    """Deposit ko ATOMICALLY approve karta hai (double credit nahi hoga).
    Return: (t_uid, method, prev_bal) ya None agar pehle hi process ho chuka."""
    row = cur.execute("SELECT user_id, method_name FROM deposits WHERE id=?", (dep_id,)).fetchone()
    if not row:
        return None
    t_uid, method = row
    async with get_user_lock(t_uid):
        cur.execute("UPDATE deposits SET status='approved', amount=? WHERE id=? AND status='pending'", (amt, dep_id))
        if cur.rowcount == 0:
            db.commit()
            return None
        prev_row = cur.execute("SELECT balance FROM users WHERE user_id=?", (t_uid,)).fetchone()
        prev_bal = prev_row[0] if prev_row else 0
        cur.execute("UPDATE users SET balance = balance + ?, total_deposited = total_deposited + ? WHERE user_id=?", (amt, amt, t_uid))
        add_upi_revenue(method, amt)
        db.commit()
    return t_uid, method, prev_bal


# ================= BUYING FLOW =================
CATEGORIES = [
    ("spam_free", "🟢", "Spam Free"),
    ("limit_spam", "🔴", "Limit / Spam"),
    ("premium",   "🔵", "Premium"),
    ("whatsapp",  "🟩", "WhatsApp Account"),
    ("allapp",    "📱", "All App Acc"),
]
# Categories that are delivered as text/credentials (no Telegram session / OTP polling)
MANUAL_DELIVERY_CATS = {"whatsapp", "allapp"}
CATEGORY_MAP = {k: (icon, label) for k, icon, label in CATEGORIES}


def cat_label(cat):
    icon, label = CATEGORY_MAP.get(cat, ("⚪", cat or "Unknown"))
    return f"{icon} {label}"


def cat_icon(cat):
    return CATEGORY_MAP.get(cat, ("⚪", cat or "Unknown"))[0]


async def show_categories(event, flow):
    rows = cur.execute("SELECT category, COUNT(*) FROM stock WHERE available=1 GROUP BY category").fetchall()
    counts = {c: n for c, n in rows}
    title = f"{PE_LIGHTNING} <b>Bulk Sessions Menu</b>" if flow == 'bulk' else f"{PE_HEART} <b>Single Account Menu</b>"
    msg = f"{title}\n\n📦 <b>Choose Account Type:</b>\n\n{P_USDT} Rate: 1 USDT = {P_INR}{get_usdt_rate()}"

    btns = []
    for key, icon, label in CATEGORIES:
        n = counts.get(key, 0)
        btns.append([Button.inline(f"{icon} {label} ({n})", f"cat|{flow}|{key}")])
    btns.append([Button.inline("Cancel", "cancel_action")])

    if not counts:
        msg += f"\n\n{P_NO} <b>Stock is Empty right now. Check back later!</b>"

    if isinstance(event, events.CallbackQuery.Event):
        await event.edit(msg, buttons=btns)
    else:
        await event.respond(msg, buttons=btns)


async def show_countries(event, flow, category, page=1):
    limit = 10
    offset = (page - 1) * limit

    total_row = cur.execute("SELECT COUNT(DISTINCT country_name) FROM stock WHERE available=1 AND category=?", (category,)).fetchone()
    total = total_row[0] if total_row else 0
    # Har EXACT country naam alag row
    rows = cur.execute("SELECT MIN(country_icon), country_name, COUNT(*) FROM stock WHERE available=1 AND category=? GROUP BY country_name ORDER BY country_name ASC LIMIT ? OFFSET ?", (category, limit, offset)).fetchall()

    if not rows and page == 1:
        err_msg = f"{P_NO} <b>{cat_label(category)}: Stock is Empty right now. Check back later!</b>"
        btns = [[Button.inline("⬅️ Back", f"catmenu|{flow}")]]
        if isinstance(event, events.CallbackQuery.Event):
            return await event.edit(err_msg, buttons=btns)
        else:
            return await event.respond(err_msg, buttons=btns)

    title = f"{PE_LIGHTNING} <b>Bulk Sessions Menu</b>" if flow == 'bulk' else f"{PE_HEART} <b>Single Account Menu</b>"
    msg = (f"{title}\n📦 Type: {cat_label(category)}\n\n"
           f"{P_GLOBE} <b>Select a region below to view available numbers (Page {page}).</b>\n"
           f"{P_USDT} Rate: 1 USDT = {P_INR}{get_usdt_rate()}\n\n")

    btns = []
    for (i, n, c) in rows:
        btns.append([Button.inline(f"{i} {n} ({c})", f"bc|{flow}|{category}|{country_hash(n)}")])

    nav = []
    if page > 1:
        nav.append(Button.inline("Prev", f"pg_c|{flow}|{category}|{page-1}"))
    if offset + limit < total:
        nav.append(Button.inline("Next", f"pg_c|{flow}|{category}|{page+1}"))
    if nav:
        btns.append(nav)
    btns.append([Button.inline("⬅️ Back", f"catmenu|{flow}")])
    btns.append([Button.inline("Cancel", "cancel_action")])

    if isinstance(event, events.CallbackQuery.Event):
        await event.edit(msg, buttons=btns)
    else:
        await event.respond(msg, buttons=btns)


async def show_years(event, flow, category, h):
    country = resolve_country(category, h)
    if not country:
        return await event.answer("❌ Stock changed, please go back and reselect.", alert=True)

    rows = cur.execute("SELECT account_year, price, COUNT(*) FROM stock WHERE available=1 AND category=? AND country_name=? GROUP BY account_year, price ORDER BY account_year DESC, price ASC", (category, country)).fetchall()
    if not rows:
        return await event.answer("❌ Out of stock for this country.", alert=True)

    uid = event.sender_id
    disc_row = cur.execute("SELECT discount FROM users WHERE user_id=?", (uid,)).fetchone()
    discount = disc_row[0] if disc_row else 0

    msg = f"{PE_FLOWER} <b>Select Account Year</b>\n📦 Type: {cat_label(category)}\n{P_GLOBE} Country: <b>{html.escape(country)}</b>\n\n"
    btns = []

    for (y, p, c) in rows:
        disp_p = p if discount == 0 else int(p * (100 - discount) / 100)
        disc_text = f" (-{discount}%)" if discount > 0 else ""
        btns.append([Button.inline(f"{y} | ₹{disp_p}{disc_text} | {c}", f"by|{flow}|{category}|{h}|{y}|{p}")])

    btns.append([Button.inline("Back to Countries", f"pg_c|{flow}|{category}|1")])
    await event.edit(msg, buttons=btns)


def mask_phone(phone):
    p = str(phone)
    return f"{p[:2]}•••{p[-4:]}" if len(p) > 6 else p


def usd_inr(inr):
    return f"${to_usd(inr):.2f} • {P_INR}{inr}"


def user_final_price(uid, base):
    row = cur.execute("SELECT discount FROM users WHERE user_id=?", (uid,)).fetchone()
    d = row[0] if row else 0
    return base if d == 0 else int(base * (100 - d) / 100)


async def show_account_info(event, category, h, year, price_str):
    country = resolve_country(category, h)
    if not country:
        return await event.answer("❌ Stock changed, please go back and reselect.", alert=True)

    uid, base = event.sender_id, int(price_str)
    row = cur.execute("SELECT MIN(country_icon), COUNT(*) FROM stock WHERE available=1 AND category=? AND country_name=? AND account_year=? AND price=?", (category, country, int(year), base)).fetchone()
    if not row or not row[1]:
        return await event.answer("❌ Out of stock!", alert=True)
    icon, cnt = row
    final = user_final_price(uid, base)
    msg = (f"⚡ <b>{cat_label(category)} Info</b>\n\n"
           f"🌍 <b>Country :</b> {icon} {html.escape(country)}\n"
           f"📦 <b>Type :</b> {cat_label(category)}\n"
           f"💸 <b>Price :</b> {usd_inr(final)}\n"
           f"📦 <b>Available :</b> {cnt}\n"
           f"🔍 Reliable | Affordable | Good Quality\n\n"
           f"⚠️ <b>Important:</b> Please use Graph Manager / Plus Messenger.\n"
           f"🚫 We are not responsible for any freeze/ban")
    btns = [[Button.inline("🛒 Buy Now", f"pc|{category}|{h}|{year}|{base}")],
            [Button.inline("⬅️ Back", f"bc|single|{category}|{h}")]]
    await event.edit(msg, buttons=btns)


async def confirm_purchase(event, category, h, year, price_str):
    country = resolve_country(category, h)
    if not country:
        return await event.answer("❌ Stock changed, please go back and reselect.", alert=True)

    uid, base = event.sender_id, int(price_str)
    acc = cur.execute("SELECT phone, country_icon, account_year, twofa FROM stock WHERE available=1 AND category=? AND country_name=? AND account_year=? AND price=? ORDER BY phone LIMIT 1", (category, country, int(year), base)).fetchone()
    if not acc:
        return await event.answer("❌ Sold out!", alert=True)
    phone, icon, yr, twofa = acc

    bal_row = cur.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
    bal = bal_row[0] if bal_row else 0
    final = user_final_price(uid, base)
    age_y = max(datetime.now().year - int(yr), 0)
    has_2fa = "✅ Yes" if twofa and twofa != "None" else "❌ No"
    after_line = f"💸 After: {usd_inr(bal - final)}" if bal >= final else "💸 After: ⚠️ Insufficient Balance"

    msg = (f"━━━━━━━━━━━━━━━━━━━━\n"
           f"🛒 <b>PURCHASE CONFIRMATION</b>\n"
           f"━━━━━━━━━━━━━━━━━━━━\n\n"
           f"🏷️ {icon} {html.escape(country)}\n"
           f"📦 Type: {cat_label(category)}\n\n"
           f"<b>Account Details:</b>\n"
           f"📞 Phone: <code>{mask_phone(phone)}</code>\n"
           f"⏰ Age: {yr} ({age_y}Y)\n"
           f"🔐 2FA: {has_2fa}\n\n"
           f"<b>Payment:</b>\n"
           f"💰 Price: {usd_inr(final)}\n"
           f"💵 Balance: {usd_inr(bal)}\n"
           f"{after_line}\n\n"
           f"✅ Please use Plus Messenger.\n"
           f"🚫 We are not responsible for any freeze/ban")
    btns = [[Button.inline("✅ Confirm Purchase", f"buy_cf|{category}|{h}|{year}|{base}")],
            [Button.inline("❌ Cancel", "cancel_action")]]
    await event.edit(msg, buttons=btns)


async def process_purchase(event, category, h, year_str, price_str):
    if category in MANUAL_DELIVERY_CATS:
        return await process_manual_purchase(event, category, h, year_str, price_str)
    country = resolve_country(category, h)
    if not country:
        return await event.answer("❌ Stock changed, please go back and reselect.", alert=True)

    uid, base_price = event.sender_id, int(price_str)

    disc_row = cur.execute("SELECT discount FROM users WHERE user_id=?", (uid,)).fetchone()
    discount = disc_row[0] if disc_row else 0
    final_price = base_price if discount == 0 else int(base_price * (100 - discount) / 100)

    async with get_user_lock(uid):
        row = cur.execute("SELECT phone, session_file, country_icon, account_year, twofa FROM stock WHERE category=? AND country_name=? AND account_year=? AND price=? AND available=1 ORDER BY phone LIMIT 1", (category, country, int(year_str), base_price)).fetchone()

        if not row:
            return await event.answer("❌ Sold out! Another user just bought this account.", alert=True)

        phone, sess, c_icon, actual_year, twofa_pass = row

        cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=? AND balance >= ?", (final_price, uid, final_price))
        if cur.rowcount == 0:
            return await event.answer(f"❌ Insufficient Balance! Need ₹{final_price}", alert=True)

        cur.execute("UPDATE stock SET available=0 WHERE phone=?", (phone,))
        # Restart ho jaye to paisa wapas karne ke liye DB me record
        cur.execute("INSERT OR REPLACE INTO pending_orders (phone, user_id, price, created) VALUES (?,?,?,?)",
                    (phone, uid, final_price, time.time()))
        db.commit()

    await event.edit(f"{PE_LIGHTNING} <b>Fetching Number (+{phone})...</b>")
    clean_sess = sess if not sess.endswith(".session") else sess[:-8]
    client = TelegramClient(clean_sess, API_ID, API_HASH)

    try:
        await client.connect()
        if not await client.is_user_authorized():
            raise Exception("Session dead")
    except Exception:
        async with get_user_lock(uid):
            cur.execute("DELETE FROM stock WHERE phone=?", (phone,))
            cur.execute("DELETE FROM pending_orders WHERE phone=?", (phone,))
            cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (final_price, uid))
            db.commit()
        try:
            await client.disconnect()
        except Exception:
            pass
        delete_session_files(sess)
        return await event.edit(f"{P_NO} <b>Account Invalid.</b> Money refunded. Try buying another.")

    msg = (f"{PE_LIGHTNING} <b>Order Active!</b>\n\n"
           f"{P_PHONE} <b>Phone:</b> <code>{phone}</code>\n"
           f"{P_FLAG} <b>Country:</b> {c_icon} {html.escape(country)}\n\n"
           f"🔻 <b>INSTRUCTIONS:</b>\n"
           f"1. Open Telegram & Add Account\n"
           f"2. Enter the number above.\n"
           f"3. {P_WAIT} <b>Please wait!</b> The bot is actively listening for your OTP and will send it automatically once Telegram delivers it.\n\n"
           f"<i>Note: If no OTP is received within 10 minutes, the bot will auto-cancel and refund your balance automatically.</i>")

    sent_msg = await event.edit(msg)

    active_orders[phone] = {
        'uid': uid,
        'client': client, 'sess': sess, 'start_time': time.time(),
        'paid': False, 'price': final_price, 'country': country, 'year': actual_year,
        'c_icon': c_icon, 'twofa': twofa_pass, 'msg_id': sent_msg.id
    }
    asyncio.create_task(auto_otp_task(phone))


def otp_buttons(phone):
    return [[Button.inline("🔄 Get OTP Again", f"get_otp_again|{phone}")],
            [Button.inline("🚪 Finish & Logout", f"logout_bot|{phone}")]]


def otp_message(order, phone, code, title):
    twofa_text = (f"{P_2FA} <b>2FA:</b> <code>{html.escape(str(order['twofa']))}</code>"
                  if order['twofa'] != "None" else f"🔓 <b>2FA:</b> <code>Disabled (No Password)</code>")
    return (f"{title}\n\n"
            f"{P_PHONE} <b>Phone:</b> <code>{phone}</code>\n"
            f"{P_FLAG} <b>Country:</b> {order['c_icon']} {html.escape(order['country'])}\n"
            f"{P_OTP} <b>OTP:</b> <code>{code}</code>\n"
            f"{twofa_text}")


async def paid_order_cleanup(phone):
    """OTP milne ke PAID_ORDER_TTL baad bot ka session khud logout + files delete."""
    await asyncio.sleep(PAID_ORDER_TTL)
    order = active_orders.pop(phone, None)
    if not order:
        return
    try:
        await order['client'].log_out()
    except Exception:
        pass
    try:
        await order['client'].disconnect()
    except Exception:
        pass
    delete_session_files(order['sess'])
    try:
        await bot.send_message(order['uid'], f"{P_TIME} <b>Session auto-closed</b> for <code>{phone}</code> (30 min complete). Bot ka session logout ho gaya.")
    except Exception:
        pass


async def auto_otp_task(phone):
    if phone not in active_orders:
        return

    order = active_orders[phone]
    client = order['client']
    start_time = order['start_time']
    uid = order['uid']
    msg_id = order['msg_id']

    # 777000 (Telegram) ka entity cache me laane ke liye warm-up
    try:
        await client.get_dialogs(limit=20)
    except Exception as ex:
        logger.warning(f"dialogs warmup {phone}: {ex}")

    while time.time() - start_time < AUTO_CANCEL_SECONDS:
        if phone not in active_orders:
            return
        try:
            msgs = await client.get_messages(777000, limit=5)
            code = extract_login_code(msgs, start_time)

            if code:
                if not order['paid']:
                    order['paid'] = True
                    async with get_user_lock(uid):
                        cur.execute("INSERT INTO orders (user_id, country, year, price, phone, otp) VALUES (?,?,?,?,?,?)", (uid, order['country'], order['year'], order['price'], phone, code))
                        cur.execute("DELETE FROM stock WHERE phone=?", (phone,))
                        cur.execute("DELETE FROM pending_orders WHERE phone=?", (phone,))
                        db.commit()

                    await log_primary_purchase(uid, order['country'], order['price'], order['price'], order['year'], 1)
                    asyncio.create_task(paid_order_cleanup(phone))

                msg_text = otp_message(order, phone, code, f"{PE_CHECK} <b>Latest OTP Fetched!</b>")
                try:
                    await bot.edit_message(uid, msg_id, msg_text, buttons=otp_buttons(phone))
                except MessageNotModifiedError:
                    pass
                except Exception:
                    await bot.send_message(uid, msg_text, buttons=otp_buttons(phone))
                return
        except Exception as ex:
            logger.warning(f"OTP poll error {phone}: {ex}")
        await asyncio.sleep(6)

    if phone in active_orders and not active_orders[phone]['paid']:
        order = active_orders.pop(phone)
        try:
            await order['client'].disconnect()
        except Exception:
            pass

        async with get_user_lock(uid):
            cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (order['price'], uid))
            cur.execute("UPDATE stock SET available=1 WHERE phone=?", (phone,))
            cur.execute("DELETE FROM pending_orders WHERE phone=?", (phone,))
            db.commit()

        try:
            await bot.edit_message(uid, msg_id, f"{P_TIME} <b>Order Expired!</b>\nThe 10-minute limit for <code>{phone}</code> ran out. Your money ({P_INR}{order['price']}) has been automatically refunded.")
        except Exception:
            pass


async def recover_pending_orders():
    """Bot restart ke baad: jo orders me OTP nahi aaya tha unka paisa wapas + stock wapas."""
    rows = cur.execute("SELECT phone, user_id, price FROM pending_orders").fetchall()
    for phone, uid, price in rows:
        async with get_user_lock(uid):
            cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (price, uid))
            cur.execute("UPDATE stock SET available=1 WHERE phone=?", (phone,))
            cur.execute("DELETE FROM pending_orders WHERE phone=?", (phone,))
            db.commit()
        logger.info(f"Recovered pending order {phone} for {uid}, refunded {price}")
        try:
            await bot.send_message(uid, f"{P_WARN} <b>Bot restart ki wajah se order cancel hua.</b>\n{P_INR}{price} aapke balance me refund kar diye gaye.")
        except Exception:
            pass


async def init_session_purchase(event, category, country, year, price_str):
    """country yaha RESOLVED exact naam hai (hash nahi)."""
    uid, price = event.sender_id, int(price_str)
    stock_row = cur.execute("SELECT COUNT(*) FROM stock WHERE category=? AND country_name=? AND account_year=? AND price=? AND available=1", (category, country, int(year), price)).fetchone()
    stock = stock_row[0] if stock_row else 0
    if stock == 0:
        return await event.answer("❌ Out of stock!", alert=True)

    session_buy_state[uid] = {'category': category, 'country': country, 'year': year, 'price': price, 'stock': stock}
    disc_row = cur.execute("SELECT discount FROM users WHERE user_id=?", (uid,)).fetchone()
    discount = disc_row[0] if disc_row else 0
    p_disp = price if discount == 0 else int(price * (100 - discount) / 100)

    msg = (f"{PE_GIFT} <b>Buy {html.escape(country)} ({year}) Sessions</b>\n"
           f"📦 Type: {cat_label(category)}\n\n"
           f"{P_MONEY} <b>Price per session:</b> {P_INR}{p_disp}\n"
           f"{P_PKG} <b>Available Stock:</b> {stock}\n\n"
           f"👇 <b>Reply to this message</b> with the <b>Number of Sessions</b> you want to buy.")
    await event.edit(msg, buttons=[[Button.inline("Cancel", "cancel_action")]])


async def process_bulk_sessions(event, uid, qty, state, final_cost):
    category, country, year, price = state['category'], state['country'], int(state['year']), int(state['price'])
    await event.respond(f"{PE_LIGHTNING} <b>Processing your sessions...</b>")

    async with get_user_lock(uid):
        rows = cur.execute("SELECT phone, session_file, twofa, account_year FROM stock WHERE category=? AND country_name=? AND account_year=? AND price=? AND available=1 LIMIT ?", (category, country, year, price, qty)).fetchall()
        if len(rows) < qty:
            return await event.respond(f"{P_NO} Stock changed during processing. Purchase Cancelled.")

        cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=? AND balance >= ?", (final_cost, uid, final_cost))
        if cur.rowcount == 0:
            return await event.respond(f"{P_NO} Insufficient Balance! Purchase Cancelled.")

        phones = [r[0] for r in rows]
        placeholders = ",".join("?" for _ in phones)
        cur.execute(f"UPDATE stock SET available=0 WHERE phone IN ({placeholders})", phones)

        price_per_acc = final_cost // qty
        for p in phones:
            cur.execute("INSERT INTO orders (user_id, country, year, price, phone, otp) VALUES (?,?,?,?,?,?)", (uid, country, year, price_per_acc, p, "SESSION_FILES"))
        db.commit()

    zip_name = f"sessions_{uid}_{int(time.time())}.zip"
    numbers_txt = ""
    sent = False

    try:
        with zipfile.ZipFile(zip_name, 'w') as zf:
            for phone, sess_file, twofa_pass, y in rows:
                base_s = sess_file if not sess_file.endswith(".session") else sess_file[:-8]
                for ext in ['.session', '.session-wal', '.session-shm', '.session-journal']:
                    src = base_s + ext
                    if os.path.exists(src):
                        zf.write(src, os.path.basename(src))

                pass_text = twofa_pass if twofa_pass != "None" else "No_Password"
                numbers_txt += f"+{phone} | pass:{pass_text}\n"

            numbers_txt += "\n\nPurchased from @Vinnutgsales\n"
            zf.writestr("numbers.txt", numbers_txt)

        caption = (
            f"{PE_GIFT} <b>Bulk Purchase Successful!</b>\n\n"
            f"{P_FLAG} Country: {html.escape(country)}\n"
            f"📦 Type: {cat_label(category)}\n"
            f"{P_PKG} Quantity: {qty}\n"
            f"{P_CARD} Total Paid: {P_INR}{final_cost}\n"
            f"{P_2FA} 2FA: 2007\n\n"
            f"<i>(Note: Sessions are safely provided, the bot does not keep them active)</i>")

        await bot.send_file(uid, zip_name, caption=caption)
        sent = True
    except Exception as e:
        logger.error(f"Bulk zip error: {e}")
        if not sent:
            # Zip/send fail hua: paisa + stock wapas
            async with get_user_lock(uid):
                cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (final_cost, uid))
                cur.execute(f"UPDATE stock SET available=1 WHERE phone IN ({placeholders})", phones)
                cur.execute(f"DELETE FROM orders WHERE user_id=? AND otp='SESSION_FILES' AND phone IN ({placeholders})", [uid] + phones)
                db.commit()
            await event.respond(f"{P_WARN} Error creating zip: {html.escape(str(e))}\nMoney refunded.")
    finally:
        if os.path.exists(zip_name):
            os.remove(zip_name)

    if sent:
        await log_primary_purchase(uid, country, price, final_cost, year, qty)


# ================= STATS & PROFILE FUNCTIONS =================
async def profile_handler(event):
    uid = event.sender_id
    row = cur.execute("SELECT balance, total_deposited, joined_date, discount FROM users WHERE user_id=?", (uid,)).fetchone()
    if not row:
        return await bot.send_message(event.chat_id, "⚠️ Error: Please type /start to initialize your account.")

    bal, dep, date, discount = row
    sales_row = cur.execute("SELECT COALESCE(sales_balance,0) FROM users WHERE user_id=?", (uid,)).fetchone()
    sales_bal = sales_row[0] if sales_row else 0
    ref_count_row = cur.execute("SELECT COUNT(*) FROM users WHERE referred_by=?", (uid,)).fetchone()
    ref_count = ref_count_row[0] if ref_count_row else 0
    me = await bot.get_me()
    bot_username = me.username or ""
    ref_link = f"https://t.me/{bot_username}?start=ref_{uid}" if bot_username else None
    disc_msg = f"\n{P_GIFT} Active Discount: <b>{discount}% OFF</b>" if discount > 0 else ""
    ref_block = (f"{P_USERS} <b>Your Referral Link:</b>\n<code>{ref_link}</code>\n\n"
                 if ref_link else
                 f"{P_USERS} <b>Referral Link:</b>\n<i>Set a public bot username to enable referrals.</i>\n\n")

    msg = (f"{PE_KISS} <b>USER PROFILE</b>\n\n"
           f"{P_ID} User ID: <code>{uid}</code>\n"
           f"{P_MONEY} Balance: <code>${to_usd(bal):.2f} (₹{bal})</code>\n"
           f"{P_CARD} Deposited: <code>${to_usd(dep):.2f} (₹{dep})</code>{disc_msg}\n"
           f"🤝 Sales Balance: <code>₹{sales_bal}</code>\n"
           f"{P_USERS} Referred Users: <b>{ref_count}</b>\n"
           f"{P_CAL} Joined: {str(date)[:10]}\n\n"
           f"{ref_block}"
           f"<i>(Share this link with your friends to earn bonuses!)</i>")
    pbtns = [[Button.inline("🤝 Withdraw Sales Balance", "wd_sales")]] if sales_bal > 0 else None
    await bot.send_message(event.chat_id, msg, buttons=pbtns)


async def stats_handler(event, is_callback=False):
    uid = event.sender_id
    row = cur.execute("SELECT total_deposited FROM users WHERE user_id=?", (uid,)).fetchone()
    if not row:
        return
    dep = row[0]
    o_row = cur.execute("SELECT COUNT(*), SUM(price) FROM orders WHERE user_id=?", (uid,)).fetchone()
    total_orders = o_row[0] if o_row else 0
    spent = o_row[1] if o_row and o_row[1] else 0
    ref_row = cur.execute("SELECT COUNT(*) FROM users WHERE referred_by=?", (uid,)).fetchone()
    ref_count = ref_row[0] if ref_row else 0

    msg = (f"{PE_CROWN} <b>My Statistics</b>\n\n"
           f"{P_CART} <b>Accounts Bought:</b> {total_orders}\n"
           f"{P_USERS} <b>Referrals:</b> {ref_count}\n"
           f"{P_MONEY} <b>Total Spent:</b>\n${to_usd(spent):.2f}\n"
           f"{P_CARD} <b>Total Deposited:</b>\n${to_usd(dep):.2f}")

    btns = [[Button.inline("View Purchase Logs", "page_purchases_1")], [Button.inline("Referral Logs", "view_referrals")]]
    if is_callback:
        try:
            await event.edit(msg, buttons=btns)
        except MessageNotModifiedError:
            pass
    else:
        await bot.send_message(event.chat_id, msg, buttons=btns)


async def send_purchase_page(event, uid, page):
    limit = 5
    offset = (page - 1) * limit
    t_row = cur.execute("SELECT COUNT(*) FROM orders WHERE user_id=?", (uid,)).fetchone()
    total = t_row[0] if t_row else 0
    rows = cur.execute("SELECT phone, date FROM orders WHERE user_id=? ORDER BY id DESC LIMIT ? OFFSET ?", (uid, limit, offset)).fetchall()

    msg = f"{PE_FLOWER} <b>Purchase History</b>\nPage {page}\n\n"
    if not rows:
        msg += "No purchases found."
    else:
        for ph, d in rows:
            try:
                dt = datetime.strptime(d, "%Y-%m-%d %H:%M:%S")
                d_str = dt.strftime("%a %b %d %H:%M:%S %Y")
            except Exception:
                d_str = d
            msg += f"{P_PHONE} {ph}\n{P_CAL} {d_str}\n────────────────\n"

    nav = []
    if page > 1:
        nav.append(Button.inline("Prev", f"page_purchases_{page-1}"))
    nav.append(Button.inline("Back", "back_to_stats"))
    if offset + limit < total:
        nav.append(Button.inline("Next", f"page_purchases_{page+1}"))
    await event.edit(msg, buttons=[nav])


async def view_referrals(event):
    refs = cur.execute("SELECT user_id FROM users WHERE referred_by=?", (event.sender_id,)).fetchall()
    await event.answer(f"👥 You have referred {len(refs)} user(s).", alert=True)


# ================= ADMIN ACTIONS =================
async def admin_panel_handler(event):
    uid = event.sender_id
    if not is_admin(uid):
        return

    status_text = "🟢 Bot is ON" if is_bot_online() else "🔴 Bot is OFF"
    total_users = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    total_stock = cur.execute("SELECT COUNT(*) FROM stock WHERE available=1").fetchone()[0]
    pending_deposits = cur.execute("SELECT COUNT(*) FROM deposits WHERE status='pending'").fetchone()[0]
    btns = []

    if uid == ADMIN_ID or has_perm(uid, 'p_settings'):
        btns.append([Button.inline(f"Status: {status_text}", "adm_togglebot")])

    r1 = []
    if uid == ADMIN_ID or has_perm(uid, 'p_add_stock'):
        r1.append(Button.inline("📦 Add Stock (Category)", "adm_catmenu"))
    if r1:
        btns.append(r1)

    r2 = []
    if uid == ADMIN_ID or has_perm(uid, 'p_manage_stock'):
        r2.extend([Button.inline("📦 Manage Stock", "adm_managestock"), Button.inline("📦 Auto Price", "adm_autoprice")])
    if r2:
        btns.append(r2)

    r3 = []
    if uid == ADMIN_ID or has_perm(uid, 'p_stats'):
        r3.extend([Button.inline("Statistics", "adm_stats"), Button.inline("Broadcast", "adm_bcast")])
        r3.append(Button.inline("User Info", "adm_userinfo"))
    if r3:
        btns.append(r3)

    r4 = []
    if uid == ADMIN_ID or has_perm(uid, 'p_bal'):
        r4.extend([Button.inline("Change Balance", "adm_bal"), Button.inline("Ban User", "adm_ban")])
    if r4:
        btns.append(r4)

    r5 = []
    if uid == ADMIN_ID or has_perm(uid, 'p_settings'):
        r5.extend([Button.inline("Discount", "adm_discount"), Button.inline("Ref ₹ Amount", "adm_refpct")])
        btns.append(r5)
        btns.append([Button.inline(f"Referral: {'🟢 ON' if is_ref_enabled() else '🔴 OFF'}", "adm_reftoggle")])
        btns.append([Button.inline("Support URL", "adm_supporturl"), Button.inline("Payments", "adm_payments")])
        btns.append([Button.inline("Set USDT Rate", "adm_usdtrate")])
        btns.append([Button.inline("💸 Sell / Promo / Withdraw", "adm_sellmenu")])
        btns.append([Button.inline("🌐 Server 1 (LZT) Settings", "adm_lztset")])
        btns.append([Button.inline("🔁 Number Change", "adm_ncmenu")])
        btns.append([Button.inline("🧰 Admin Tools (Giveaway · Warn · API · Backup)", "adm_tools")])
        btns.append([Button.inline("Backup Users", "adm_backupusr"), Button.inline("Restore Users", "adm_restoreusr")])

    if uid == ADMIN_ID:
        btns.append([Button.inline("Manage Admins", "adm_manageadmins")])

    header = (f"{PE_CROWN} <b>ADVANCED ADMIN DASHBOARD</b>\n\n"
              f"{P_USERS} Users: <b>{total_users}</b>\n"
              f"{P_PKG} Available Stock: <b>{total_stock}</b>\n"
              f"{P_WAIT} Pending Deposits: <b>{pending_deposits}</b>")
    await bot.send_message(event.chat_id, header, buttons=btns)


async def manage_admins_menu(event):
    rows = cur.execute("SELECT user_id FROM admins").fetchall()
    msg = f"{PE_CROWN} <b>Manage Sub-Admins</b>\n\n"
    for r in rows:
        msg += f"{P_ACC} <code>{r[0]}</code>\n"
    btns = [[Button.inline("Add Admin", "adm_addadmin"), Button.inline("Edit Admin", "adm_editadminreq")],
            [Button.inline("Back", "adm_adminmain")]]
    await event.edit(msg, buttons=btns)


async def edit_admin_menu(event, target_id):
    row = cur.execute("SELECT p_add_stock, p_manage_stock, p_stats, p_bal, p_settings FROM admins WHERE user_id=?", (target_id,)).fetchone()
    if not row:
        return await event.answer("Admin not found", alert=True)
    p = ["✅" if x == 1 else "❌" for x in row]

    btns = [
        [Button.inline(f"Add Stock: {p[0]}", f"adm_tglperm|{target_id}|p_add_stock")],
        [Button.inline(f"Manage Stock: {p[1]}", f"adm_tglperm|{target_id}|p_manage_stock")],
        [Button.inline(f"Stats & Bcast: {p[2]}", f"adm_tglperm|{target_id}|p_stats")],
        [Button.inline(f"Bal & Users: {p[3]}", f"adm_tglperm|{target_id}|p_bal")],
        [Button.inline(f"Settings: {p[4]}", f"adm_tglperm|{target_id}|p_settings")],
        [Button.inline("Remove Admin", f"adm_deladmin|{target_id}")],
        [Button.inline("Back", "adm_manageadmins")]
    ]
    await event.edit(f"✏️ <b>Editing Admin:</b> <code>{target_id}</code>", buttons=btns)


async def send_managestock_catmenu(event):
    btns = [[Button.inline(f"{icon} {label}", f"adm_mscat|{key}")] for key, icon, label in CATEGORIES]
    btns.append([Button.inline("Back", "adm_adminmain")])
    await event.edit(f"{PE_LOCATION} <b>Manage Stock</b>\nSelect a category:", buttons=btns)


async def send_manage_stock_page(event, category, page):
    limit = 10
    offset = (page - 1) * limit
    rows = cur.execute("SELECT DISTINCT country_name FROM stock WHERE category=? ORDER BY country_name", (category,)).fetchall()
    total = len(rows)
    countries = rows[offset:offset+limit]

    btns = []
    for (c,) in countries:
        flag = get_flag_by_country_name(c)
        btns.append([Button.inline(f"{flag} {c}", f"adm_msc|{category}|{country_hash(c)}")])

    nav = []
    if page > 1:
        nav.append(Button.inline("Prev", f"adm_mspg|{category}|{page-1}"))
    if offset + limit < total:
        nav.append(Button.inline("Next", f"adm_mspg|{category}|{page+1}"))
    if nav:
        btns.append(nav)
    btns.append([Button.inline("Back", "adm_managestock")])
    if not countries:
        return await event.edit(f"{PE_LOCATION} <b>Manage Stock</b>\n📦 {cat_label(category)}\n\n{P_NO} Is category me koi stock nahi hai.", buttons=btns)
    await event.edit(f"{PE_LOCATION} <b>Manage Stock</b> (Page {page})\n📦 {cat_label(category)}\nSelect a country to edit its properties:", buttons=btns)


async def send_manage_stock_country(event, category, h):
    c_name = resolve_country(category, h)
    if not c_name:
        return await event.answer("❌ Country not found (list refresh karo).", alert=True)
    years = cur.execute("SELECT DISTINCT account_year FROM stock WHERE category=? AND country_name=? ORDER BY account_year DESC", (category, c_name)).fetchall()
    flag = get_flag_by_country_name(c_name)
    btns = [
        [Button.inline("Edit Country Name", f"adm_msedit|name|{category}|{h}"), Button.inline("Edit Flag", f"adm_msedit|flag|{category}|{h}")],
        [Button.inline("Edit Common Price (All Years)", f"adm_msedit|cprice|{category}|{h}")],
        [Button.inline("🔀 Move to Another Category", f"adm_msmove|{category}|{h}")]
    ]
    y_btns = []
    for (y,) in years:
        y_btns.append(Button.inline(f"{y}", f"adm_msedit|yprice|{category}|{h}|{y}"))

    for i in range(0, len(y_btns), 3):
        btns.append(y_btns[i:i+3])
    btns.append([Button.inline("Back", f"adm_mspg|{category}|1")])
    await event.edit(f"{flag} <b>Managing: {html.escape(c_name)}</b>\n📦 {cat_label(category)}\nSelect an option to edit:", buttons=btns)


async def send_autoprice_catmenu(event):
    btns = [[Button.inline(f"{icon} {label}", f"adm_apcat|{key}")] for key, icon, label in CATEGORIES]
    btns.append([Button.inline("Back", "adm_adminmain")])
    await event.edit(f"{PE_LIGHTNING} <b>Auto Price Setup</b>\nSelect a category:", buttons=btns)


async def send_autoprice_page(event, category, page):
    limit = 10
    offset = (page - 1) * limit
    c_list = sorted(all_country_names(category))
    total = len(c_list)
    countries = c_list[offset:offset+limit]

    btns = []
    for c in countries:
        flag = get_flag_by_country_name(c)
        btns.append([Button.inline(f"{flag} {c}", f"adm_apc|{category}|{country_hash(c)}")])

    nav = []
    if page > 1:
        nav.append(Button.inline("Prev", f"adm_appg|{category}|{page-1}"))
    if offset + limit < total:
        nav.append(Button.inline("Next", f"adm_appg|{category}|{page+1}"))
    if nav:
        btns.append(nav)
    btns.append([Button.inline("Add Custom Country", f"adm_ap_add_country|{category}")])
    btns.append([Button.inline("Back", "adm_autoprice")])
    await event.edit(f"{PE_LIGHTNING} <b>Auto Price Setup</b> (Page {page})\n📦 {cat_label(category)}\nSelect a country to set fixed prices:", buttons=btns)


async def send_autoprice_country(event, category, h):
    c_name = resolve_any_country(category, h)
    if not c_name:
        return await event.answer("❌ Country not found (list refresh karo).", alert=True)
    flag = get_flag_by_country_name(c_name)
    btns = [[Button.inline("Set Common Price", f"adm_apset|{category}|{h}|Common")]]
    y_btns = []
    for y in range(datetime.now().year, 1999, -1):
        y_btns.append(Button.inline(f"{y}", f"adm_apset|{category}|{h}|{y}"))
    for i in range(0, len(y_btns), 4):
        btns.append(y_btns[i:i+4])
    btns.append([Button.inline("Back", f"adm_appg|{category}|1")])
    await event.edit(f"{flag} <b>Auto Price: {html.escape(c_name)}</b>\n📦 {cat_label(category)}\nSelect 'Common' for default price, or specific years:", buttons=btns)


async def admin_actions(event):
    data_full = event.data.decode()
    if not data_full.startswith("adm_"):
        return
    uid = event.sender_id
    action_data = data_full[4:]
    chat = event.chat_id

    if await phase2_admin(event, action_data, uid, chat) or await phase3_admin(event, action_data, uid, chat) or await phase4_admin(event, action_data, uid, chat) or await phase5_admin(event, action_data, uid, chat):
        return

    if action_data == "adminmain":
        await event.delete()

        class FakeEvent:
            chat_id = chat
            sender_id = uid
        return await admin_panel_handler(FakeEvent())

    if action_data == "catmenu" and has_perm(uid, 'p_add_stock'):
        btns = [[Button.inline(f"{icon} {label}", f"adm_catpick|{key}")] for key, icon, label in CATEGORIES]
        btns.append([Button.inline("Back", "adm_adminmain")])
        return await event.edit(f"📦 <b>Select category to add stock into:</b>", buttons=btns)

    if action_data.startswith("catpick|") and has_perm(uid, 'p_add_stock'):
        cat = action_data.split("|")[1]
        btns = [[Button.inline("Add Single Acc", f"adm_addstock|{cat}"), Button.inline("Add ZIP", f"adm_addzip|{cat}")],
                [Button.inline("Back", "adm_catmenu")]]
        return await event.edit(f"📦 <b>Category:</b> {cat_label(cat)}\n\nChoose how to add stock:", buttons=btns)

    if action_data == "togglebot" and has_perm(uid, 'p_settings'):
        new_status = 'off' if is_bot_online() else 'on'
        cur.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('bot_status',?)", (new_status,))
        db.commit()
        await event.answer(f"Bot turned {new_status.upper()}", alert=True)

        class FakeEvent:
            chat_id = chat
            sender_id = uid
        await admin_panel_handler(FakeEvent())
        await event.delete()
        return

    if action_data == "reftoggle" and has_perm(uid, 'p_settings'):
        new = 'off' if is_ref_enabled() else 'on'
        cur.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('ref_enabled',?)", (new,))
        db.commit()
        await event.answer(f"Referral {new.upper()}", alert=True)

        class FakeEvent:
            chat_id = chat
            sender_id = uid
        await admin_panel_handler(FakeEvent())
        await event.delete()
        return

    elif action_data == "stats" and has_perm(uid, 'p_stats'):
        u_row = cur.execute("SELECT COUNT(*) FROM users").fetchone()
        u = u_row[0] if u_row else 0
        s_row = cur.execute("SELECT COUNT(*) FROM stock WHERE available=1").fetchone()
        s = s_row[0] if s_row else 0
        r_row = cur.execute("SELECT value FROM settings WHERE key='upi_revenue'").fetchone()
        r = r_row[0] if r_row else "0"
        bal_row = cur.execute("SELECT SUM(balance) FROM users").fetchone()
        total_bal = bal_row[0] if bal_row and bal_row[0] else 0
        o_row = cur.execute("SELECT COUNT(*), SUM(price) FROM orders").fetchone()
        total_orders = o_row[0] if o_row else 0
        total_spent = o_row[1] if o_row and o_row[1] else 0

        msg = (f"{P_STATS} <b>ADVANCED STATS</b>\n\n{P_USERS} <b>Total Users:</b> {u}\n{P_PKG} <b>Accounts in Stock:</b> {s}\n"
               f"{P_MONEY} <b>Total UPI Revenue:</b> {P_INR}{r}\n\n{P_CARD} <b>Overall Users Balance:</b> {P_INR}{total_bal}\n"
               f"{P_CART} <b>Total Accounts Sold:</b> {total_orders}\n{P_USDT} <b>Overall Sales Amount:</b> {P_INR}{total_spent}")
        return await event.edit(msg, buttons=[[Button.inline("Back", "adm_adminmain")]])

    elif action_data == "payments" and has_perm(uid, 'p_settings'):
        btns = [
            [Button.inline("Add Payment Method", "adm_addpay")],
            [Button.inline("Remove Payment Method", "adm_delpay")],
            [Button.inline("Back to Admin", "adm_adminmain")]
        ]
        return await event.edit(f"{P_CARD} <b>Manage Payment Methods</b>", buttons=btns)

    elif action_data == "manageadmins" and uid == ADMIN_ID:
        return await manage_admins_menu(event)

    elif action_data.startswith("tglperm|") and uid == ADMIN_ID:
        _, t_id, p_name = action_data.split("|")
        if p_name not in ("p_add_stock", "p_manage_stock", "p_stats", "p_bal", "p_settings"):
            return await event.answer("Invalid permission", alert=True)
        cur.execute(f"UPDATE admins SET {p_name} = CASE WHEN {p_name}=1 THEN 0 ELSE 1 END WHERE user_id=?", (t_id,))
        db.commit()
        return await edit_admin_menu(event, t_id)

    elif action_data.startswith("deladmin|") and uid == ADMIN_ID:
        t_id = action_data.split("|")[1]
        cur.execute("DELETE FROM admins WHERE user_id=?", (t_id,))
        db.commit()
        await event.answer("✅ Admin Removed", alert=True)
        return await manage_admins_menu(event)

    elif action_data == "managestock" and has_perm(uid, 'p_manage_stock'):
        return await send_managestock_catmenu(event)
    elif action_data.startswith("mscat|") and has_perm(uid, 'p_manage_stock'):
        return await send_manage_stock_page(event, action_data.split("|")[1], 1)
    elif action_data.startswith("mspg|") and has_perm(uid, 'p_manage_stock'):
        _p = action_data.split("|")
        return await send_manage_stock_page(event, _p[1], int(_p[2]))
    elif action_data.startswith("msc|") and has_perm(uid, 'p_manage_stock'):
        _p = action_data.split("|")
        return await send_manage_stock_country(event, _p[1], _p[2])
    elif action_data.startswith("msmove|") and has_perm(uid, 'p_manage_stock'):
        _p = action_data.split("|")
        category, h = _p[1], _p[2]
        c_name = resolve_country(category, h)
        if not c_name:
            return await event.answer("❌ Country not found (list refresh karo).", alert=True)
        n = cur.execute("SELECT COUNT(*) FROM stock WHERE category=? AND country_name=?", (category, c_name)).fetchone()[0]
        btns = [[Button.inline(f"{icon} {label}", f"adm_msmv2|{category}|{h}|{key}")]
                for key, icon, label in CATEGORIES if key != category]
        btns.append([Button.inline("Back", f"adm_msc|{category}|{h}")])
        return await event.edit(
            f"🔀 <b>Move: {html.escape(c_name)}</b>\n📦 From: {cat_label(category)}\n"
            f"{P_PKG} Accounts: <b>{n}</b> (saare years)\n\nKis category me move karna hai?", buttons=btns)

    elif action_data.startswith("msmv2|") and has_perm(uid, 'p_manage_stock'):
        _p = action_data.split("|")
        category, h, new_cat = _p[1], _p[2], _p[3]
        if new_cat not in CATEGORY_MAP or new_cat == category:
            return await event.answer("❌ Invalid category.", alert=True)
        c_name = resolve_country(category, h)
        if not c_name:
            return await event.answer("❌ Country not found (list refresh karo).", alert=True)
        cur.execute("UPDATE stock SET category=? WHERE country_name=? AND category=?", (new_cat, c_name, category))
        moved = cur.rowcount
        db.commit()
        await event.answer(f"✅ {moved} accounts moved to {CATEGORY_MAP[new_cat][1]}", alert=True)
        return await send_manage_stock_country(event, new_cat, h)

    elif action_data == "autoprice" and has_perm(uid, 'p_manage_stock'):
        return await send_autoprice_catmenu(event)
    elif action_data.startswith("apcat|") and has_perm(uid, 'p_manage_stock'):
        return await send_autoprice_page(event, action_data.split("|")[1], 1)
    elif action_data.startswith("appg|") and has_perm(uid, 'p_manage_stock'):
        _p = action_data.split("|")
        return await send_autoprice_page(event, _p[1], int(_p[2]))
    elif action_data.startswith("apc|") and has_perm(uid, 'p_manage_stock'):
        _p = action_data.split("|")
        return await send_autoprice_country(event, _p[1], _p[2])

    elif action_data == "backupusr" and has_perm(uid, 'p_settings'):
        cur.execute("SELECT * FROM users")
        with open("users_backup.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([i[0] for i in cur.description])
            w.writerows(cur.fetchall())
        await bot.send_file(chat, "users_backup.csv", caption=f"{P_USERS} <b>Users Backup CSV</b>")
        os.remove("users_backup.csv")
        return await event.answer("✅ Backup Generated!", alert=True)

    async with bot.conversation(chat, timeout=600) as conv:
        async def get_reply(txt):
            await conv.send_message(txt + "\n\n<i>(Type /cancel to abort)</i>")
            resp = await conv.get_response()
            if resp.raw_text == "/cancel":
                raise AdminCancelled()
            return resp

        try:
            if action_data.startswith("ap_add_country") and has_perm(uid, 'p_manage_stock'):
                code = (await get_reply(f"{P_PHONE} <b>Enter Country Calling Code (without +):</b>\n<i>Example: 91</i>")).raw_text.replace("+", "").strip()
                flag = (await get_reply(f"{P_FLAG} <b>Enter Country Flag Emoji:</b>\n<i>Example: 🇮🇳</i>")).raw_text.strip()
                name = (await get_reply(f"{P_GLOBE} <b>Enter Country Name:</b>\n<i>Example: India</i>")).raw_text.strip()

                cur.execute("INSERT OR REPLACE INTO custom_countries (code, name, flag) VALUES (?,?,?)", (code, name, flag))
                db.commit()
                await conv.send_message(f"{P_YES} <b>Custom Country Added Successfully!</b>\n{flag} {html.escape(name)} (+{code})\n\n<i>It will now automatically be recognized when adding stock!</i>")

            elif action_data == "userinfo" and has_perm(uid, 'p_stats'):
                t_uid = int((await get_reply(f"{P_ACC} <b>Enter User ID:</b>")).raw_text)
                u_row = cur.execute("SELECT balance, total_deposited, joined_date, banned, discount FROM users WHERE user_id=?", (t_uid,)).fetchone()
                if not u_row:
                    return await conv.send_message(f"{P_NO} User not found.")

                o_row = cur.execute("SELECT COUNT(*), SUM(price) FROM orders WHERE user_id=?", (t_uid,)).fetchone()
                up_row = cur.execute("SELECT SUM(amount) FROM upi_orders WHERE user_id=? AND status='success'", (t_uid,)).fetchone()

                bal, dep, joined, is_banned, disc = u_row
                o_count = o_row[0] if o_row else 0
                o_spent = o_row[1] if o_row and o_row[1] else 0
                u_upi = up_row[0] if up_row and up_row[0] else 0

                msg = (f"{P_ACC} <b>USER INFO:</b> <code>{t_uid}</code>\n\n"
                       f"{P_MONEY} Balance: {P_INR}{bal}\n"
                       f"{P_CARD} Total Deposited: {P_INR}{dep}\n"
                       f"{P_UPI} UPI Deposited: {P_INR}{u_upi}\n"
                       f"{P_CART} Total Orders: {o_count}\n"
                       f"{P_USDT} Total Spent: {P_INR}{o_spent}\n"
                       f"{P_GIFT} Discount: {disc}%\n"
                       f"{P_CAL} Joined: {joined}\n"
                       f"{P_OFF} Banned: {'Yes' if is_banned else 'No'}")
                await conv.send_message(msg)

            elif action_data == "addadmin" and uid == ADMIN_ID:
                new_ad = int((await get_reply(f"{P_ACC} <b>Enter User ID for new Admin:</b>")).raw_text)
                cur.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (new_ad,))
                db.commit()
                await conv.send_message(f"{P_YES} Admin added!")

                class FakeEvent:
                    async def edit(self, text, buttons):
                        await bot.send_message(chat, text, buttons=buttons)

                    async def answer(self, txt, alert):
                        pass
                await edit_admin_menu(FakeEvent(), new_ad)

            elif action_data == "editadminreq" and uid == ADMIN_ID:
                t_id = int((await get_reply(f"{P_ACC} <b>Enter User ID to edit:</b>")).raw_text)

                class FakeEvent:
                    async def edit(self, text, buttons):
                        await bot.send_message(chat, text, buttons=buttons)

                    async def answer(self, txt, alert):
                        pass
                await edit_admin_menu(FakeEvent(), t_id)

            elif action_data.startswith("msedit|") and has_perm(uid, 'p_manage_stock'):
                parts = action_data.split("|")
                action, category, h = parts[1], parts[2], parts[3]
                c_name = resolve_country(category, h)
                if not c_name:
                    return await conv.send_message(f"{P_NO} Country not found. Manage Stock list dobara kholo.")
                e_name = html.escape(c_name)

                if action == "name":
                    new_name = (await get_reply(f"{P_DOC} <b>Enter NEW Name for {e_name}:</b>")).raw_text.strip()
                    if not new_name:
                        return await conv.send_message(f"{P_NO} Name empty nahi ho sakta.")
                    cur.execute("UPDATE stock SET country_name=? WHERE country_name=? AND category=?", (new_name, c_name, category))
                    cur.execute("UPDATE auto_prices SET country=? WHERE country=? AND category=?", (new_name, c_name, category))
                    db.commit()
                    await conv.send_message(f"{P_YES} {cat_label(category)}: Country '{e_name}' successfully renamed to '{html.escape(new_name)}'!")

                elif action == "flag":
                    new_flag = (await get_reply(f"{P_FLAG} <b>Enter NEW Flag Emoji for {e_name}:</b>")).raw_text.strip()
                    cur.execute("UPDATE stock SET country_icon=? WHERE country_name=? AND category=?", (new_flag, c_name, category))
                    db.commit()
                    await conv.send_message(f"{P_YES} Flag updated to {new_flag} for '{e_name}' ({cat_label(category)})!")

                elif action == "cprice":
                    new_p = int((await get_reply(f"{P_MONEY} <b>Enter NEW Common Price for all {e_name} accounts:</b>")).raw_text)
                    cur.execute("UPDATE stock SET price=? WHERE country_name=? AND category=?", (new_p, c_name, category))
                    db.commit()
                    await conv.send_message(f"{P_YES} All existing '{e_name}' ({cat_label(category)}) accounts updated to {P_INR}{new_p}!")

                elif action == "yprice":
                    year = int(parts[4])
                    new_p = int((await get_reply(f"{P_MONEY} <b>Enter NEW Price for {e_name} ({year}):</b>")).raw_text)
                    cur.execute("UPDATE stock SET price=? WHERE country_name=? AND account_year=? AND category=?", (new_p, c_name, year, category))
                    db.commit()
                    await conv.send_message(f"{P_YES} All existing '{e_name}' ({year}, {cat_label(category)}) accounts updated to {P_INR}{new_p}!")

            elif action_data.startswith("apset|") and has_perm(uid, 'p_manage_stock'):
                parts = action_data.split("|")
                category, h, year = parts[1], parts[2], parts[3]
                c_name = resolve_any_country(category, h)
                if not c_name:
                    return await conv.send_message(f"{P_NO} Country not found. Auto Price list dobara kholo.")
                e_name = html.escape(c_name)
                new_p = int((await get_reply(f"{P_ASST} <b>Enter Auto-Price for {e_name} ({year}, {cat_label(category)}):</b>\n<i>(Enter 0 to remove this auto-price)</i>")).raw_text)
                if new_p == 0:
                    cur.execute("DELETE FROM auto_prices WHERE country=? AND year=? AND category=?", (c_name, year, category))
                    await conv.send_message(f"{P_YES} Auto-Price for {e_name} ({year}, {cat_label(category)}) removed!")
                else:
                    cur.execute("INSERT OR REPLACE INTO auto_prices (category, country, year, price) VALUES (?,?,?,?)", (category, c_name, year, new_p))
                    await conv.send_message(f"{P_YES} Auto-Price for {e_name} ({year}, {cat_label(category)}) set to {P_INR}{new_p}! Incoming accounts will use this price automatically.")
                db.commit()

            elif action_data == "addpay" and has_perm(uid, 'p_settings'):
                # Naam RAW store hota hai; display par html.escape lagta hai
                name = (await get_reply(f"{P_CARD} <b>Enter Payment Method Name:</b>\n<i>(e.g., Binance Pay, TRX)</i>")).raw_text.strip()
                if not name:
                    return await conv.send_message(f"{P_NO} Name empty nahi ho sakta.")
                qr_msg = await get_reply(f"📸 <b>Send QR Code Image:</b>\n<i>(Or type <code>skip</code> if no QR needed)</i>")
                qr_path = ""
                if qr_msg.photo:
                    qr_path = f"qr_{int(time.time())}.jpg"
                    await bot.download_media(qr_msg, qr_path)

                cap_msg = (await get_reply(f"{P_DOC} <b>Enter Payment Caption:</b>\n<i>(Use <code>text</code> to make wallet IDs or UPI copyable)</i>")).raw_text
                cap_msg = html.escape(cap_msg).replace("&lt;code&gt;", "<code>").replace("&lt;/code&gt;", "</code>")
                cur.execute("INSERT INTO custom_payments (name, caption, qr_file_id) VALUES (?,?,?)", (name, cap_msg, qr_path))
                db.commit()
                await conv.send_message(f"{P_YES} Payment Method '{html.escape(name)}' added successfully!")

            elif action_data == "delpay" and has_perm(uid, 'p_settings'):
                rows = cur.execute("SELECT id, name FROM custom_payments").fetchall()
                if not rows:
                    return await conv.send_message(f"{P_NO} No custom payment methods.")
                msg = f"{P_DOC} <b>Reply with the ID of the method to delete:</b>\n\n"
                for r in rows:
                    msg += f"ID: {r[0]} - {html.escape(r[1])}\n"
                del_id = (await get_reply(msg)).raw_text
                try:
                    del_id = int(del_id)
                    file_path = cur.execute("SELECT qr_file_id FROM custom_payments WHERE id=?", (del_id,)).fetchone()
                    if file_path and file_path[0] and os.path.exists(file_path[0]):
                        os.remove(file_path[0])
                    cur.execute("DELETE FROM custom_payments WHERE id=?", (del_id,))
                    db.commit()
                    await conv.send_message(f"{P_YES} Deleted!")
                except Exception:
                    await conv.send_message(f"{P_NO} Invalid ID.")

            elif action_data.startswith("addzip") and has_perm(uid, 'p_add_stock'):
                zip_parts = action_data.split("|")
                add_category = zip_parts[1] if len(zip_parts) > 1 else "spam_free"
                resp = await get_reply(f"{P_PKG} <b>Category:</b> {cat_label(add_category)}\n<b>Send the ZIP file containing <code>.session</code> files:</b>")
                if not resp.file or not resp.file.name.endswith('.zip'):
                    return await conv.send_message(f"{P_NO} Invalid file.")

                await conv.send_message(f"{P_WAIT} <b>Extracting & Scanning Accounts...</b>")
                zip_path = await bot.download_media(resp, "temp_sessions.zip")
                extracted_dir = f"temp_extracted_{int(time.time())}"
                os.makedirs(extracted_dir, exist_ok=True)
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(extracted_dir)

                groups = {}
                for root, _dirs, files in os.walk(extracted_dir):
                    for file in files:
                        if not file.endswith(".session"):
                            continue
                        sess_path = os.path.join(root, file)
                        clean_path = sess_path[:-8]
                        try:
                            client = TelegramClient(clean_path, API_ID, API_HASH)
                            await client.connect()
                            if not await client.is_user_authorized():
                                await client.disconnect()
                                continue
                            me = await client.get_me()
                            phone = getattr(me, 'phone', None)
                            if not phone:
                                await client.disconnect()
                                continue

                            c_name, c_icon = get_country_info(phone)
                            pwd = await client(GetPasswordRequest())
                            has_2fa = pwd.has_password
                            year = await detect_account_year(client)
                            await client.disconnect()

                            key = (c_name, year, has_2fa)
                            if key not in groups:
                                groups[key] = []
                            groups[key].append({"phone": phone, "path": clean_path, "c_icon": c_icon})
                        except Exception as e:
                            logger.error(f"Scan error: {e}")

                for key in list(groups.keys()):
                    if key[0] == "Unknown":
                        sample_phone = groups[key][0]["phone"]
                        await conv.send_message(f"{P_WARN} <b>Country not recognized for +{sample_phone}!</b>")
                        new_icon = (await get_reply(f"{P_FLAG} <b>Enter Country Flag Emoji:</b>\n<i>Example: 🇮🇳</i>")).raw_text.strip()
                        new_name = (await get_reply(f"{P_GLOBE} <b>Enter Country Name:</b>\n<i>Example: India</i>")).raw_text.strip()
                        new_key = (new_name, key[1], key[2])
                        if new_key in groups:
                            groups[new_key].extend(groups.pop(key))
                        else:
                            groups[new_key] = groups.pop(key)
                        for acc in groups[new_key]:
                            acc["c_icon"] = new_icon

                success = 0
                failed_2fa = []
                for (c_name, year, has_2fa), accs in groups.items():
                    c_icon = accs[0]["c_icon"]
                    e_name = html.escape(c_name)
                    twofa_pass = "None"
                    raw_pwd = None
                    if has_2fa:
                        raw_pwd = (await get_reply(f"{P_2FA} <b>Enter 2FA Password for {len(accs)}x {e_name} accounts:</b>")).raw_text.strip()
                        twofa_pass = raw_pwd   # RAW store; display par escape hoga

                    auto_row = cur.execute("SELECT price FROM auto_prices WHERE country=? AND year=? AND category=?", (c_name, str(year), add_category)).fetchone()
                    if not auto_row:
                        auto_row = cur.execute("SELECT price FROM auto_prices WHERE country=? AND year='Common' AND category=?", (c_name, add_category)).fetchone()

                    if auto_row:
                        price = auto_row[0]
                        await conv.send_message(f"⚡ <b>Auto-Price Applied:</b> {len(accs)}x {e_name} ({year}) at {P_INR}{price}.")
                    else:
                        existing_price = find_existing_price(c_name, add_category, year)
                        if existing_price is not None:
                            price = existing_price
                            await conv.send_message(f"⚡ <b>Auto-Added:</b> {len(accs)}x {e_name} at {P_INR}{price} (Copied from same name + category).")
                        else:
                            price = int((await get_reply(f"📌 Found {len(accs)}x {e_name} ({year}).\n{P_MONEY} Enter Price (₹):")).raw_text)

                    for acc in accs:
                        acc_twofa = twofa_pass
                        try:
                            c2 = TelegramClient(acc['path'], API_ID, API_HASH)
                            await c2.connect()
                            ok, err = await force_2fa_2007(c2, raw_pwd)
                            await c2.disconnect()
                        except Exception as ex2:
                            ok, err = False, str(ex2)[:120]
                        if ok:
                            acc_twofa = NEW_2FA
                        else:
                            failed_2fa.append(f"+{acc['phone']} ({err})")
                        perm_base = f"sessions/{acc['phone']}"
                        for ext in ['.session', '.session-wal', '.session-shm', '.session-journal']:
                            if os.path.exists(acc['path'] + ext):
                                shutil.move(acc['path'] + ext, perm_base + ext)
                        cur.execute("INSERT OR REPLACE INTO stock (phone, session_file, country_name, country_icon, account_year, category, price, available, twofa) VALUES (?,?,?,?,?,?,?,?,?)",
                                    (acc['phone'], perm_base + ".session", c_name, c_icon, year, add_category, price, 1, acc_twofa))
                        success += 1
                db.commit()
                os.remove(zip_path)
                shutil.rmtree(extracted_dir)
                fail_txt = ("\n" + P_WARN + " <b>2FA 2007 nahi ho paya:</b>\n" + html.escape("\n".join(failed_2fa))) if failed_2fa else ""
                await conv.send_message(f"{P_YES} <b>Bulk Interactive Upload Complete!</b>\n{P_ON} Added: {success}\n{P_2FA} 2FA: {NEW_2FA}{fail_txt}")

            elif action_data.startswith("addstock") and has_perm(uid, 'p_add_stock'):
                stock_parts = action_data.split("|")
                add_category = stock_parts[1] if len(stock_parts) > 1 else "spam_free"
                phone = (await get_reply(f"{P_PHONE} <b>Category:</b> {cat_label(add_category)}\nEnter Phone (+919999...):")).raw_text.replace(" ", "").replace("+", "")
                sp = f"sessions/{phone}"
                delete_session_files(sp)
                client = TelegramClient(sp, API_ID, API_HASH)
                year = None
                try:
                    await client.connect()
                    sreq = await client.send_code_request(phone)

                    twofa_pass = "None"
                    raw_2fa = None
                    try:
                        otp = (await get_reply(f"{P_OTP} OTP:")).raw_text.strip()
                        await client.sign_in(phone, otp, phone_code_hash=sreq.phone_code_hash)
                    except SessionPasswordNeededError:
                        raw_2fa = (await get_reply(f"{P_2FA} 2FA Pass required. Enter it now:")).raw_text.strip()
                        twofa_pass = raw_2fa   # RAW store
                        await client.sign_in(password=raw_2fa)
                    except (PhoneCodeInvalidError, PhoneCodeExpiredError):
                        await conv.send_message(f"{P_NO} <b>OTP galat ya expire ho gaya.</b> Phir se 'Add Single Acc' dabao.")
                        return

                    c_name, c_icon = get_country_info(phone)

                    if c_name == "Unknown":
                        await conv.send_message(f"{P_WARN} <b>Country not recognized for +{phone}!</b>")
                        c_icon = (await get_reply(f"{P_FLAG} <b>Enter Country Flag Emoji:</b>\n<i>Example: 🇮🇳</i>")).raw_text.strip()
                        c_name = (await get_reply(f"{P_GLOBE} <b>Enter Country Name:</b>\n<i>Example: India</i>")).raw_text.strip()

                    auto_year = await detect_account_year(client)
                    ok, err = await force_2fa_2007(client, raw_2fa)
                    if ok:
                        twofa_pass = NEW_2FA
                        await conv.send_message(f"{P_2FA} <b>2FA password change ho kar {NEW_2FA} ho gaya.</b>")
                    else:
                        await conv.send_message(f"{P_WARN} <b>2FA 2007 nahi ho paya:</b> {html.escape(str(err))}")

                    year = int((await get_reply(f"{P_CAL} Detected Year: <b>{auto_year}</b>\nReply with Year to confirm or change:")).raw_text)
                except PhoneNumberInvalidError:
                    await conv.send_message(f"{P_NO} <b>Ye phone number valid nahi hai.</b>")
                    return
                except PhoneNumberBannedError:
                    await conv.send_message(f"{P_NO} <b>Ye number Telegram se banned hai.</b>")
                    return
                except FloodWaitError as fw:
                    await conv.send_message(f"{P_WARN} <b>Telegram ne rate-limit laga diya.</b> {fw.seconds} seconds baad try karo.")
                    return
                except asyncio.TimeoutError:
                    await conv.send_message(f"{P_WARN} <b>10 minute me reply nahi aaya, process cancel ho gaya.</b> Phir se 'Add Single Acc' dabao.")
                    return
                finally:
                    try:
                        await client.disconnect()
                    except Exception:
                        pass

                if year is None:
                    return
                e_name = html.escape(c_name)
                auto_row = cur.execute("SELECT price FROM auto_prices WHERE country=? AND year=? AND category=?", (c_name, str(year), add_category)).fetchone()
                if not auto_row:
                    auto_row = cur.execute("SELECT price FROM auto_prices WHERE country=? AND year='Common' AND category=?", (c_name, add_category)).fetchone()

                if auto_row:
                    price = auto_row[0]
                    await conv.send_message(f"⚡ <b>Auto-Price Applied:</b> {P_INR}{price} for {e_name} ({year})")
                else:
                    existing_price = find_existing_price(c_name, add_category, year)
                    if existing_price is not None:
                        price = existing_price
                        await conv.send_message(f"⚡ <b>Auto-detected Price:</b> {P_INR}{price} for {e_name}")
                    else:
                        price = int((await get_reply(f"{P_MONEY} Price (₹):")).raw_text)

                cur.execute("INSERT OR REPLACE INTO stock (phone, session_file, country_name, country_icon, account_year, category, price, available, twofa) VALUES (?,?,?,?,?,?,?,?,?)",
                            (phone, sp + ".session", c_name, c_icon, year, add_category, price, 1, twofa_pass))
                db.commit()
                await conv.send_message(f"{P_YES} Added! {P_GIFT} Category: {cat_label(add_category)}")

            elif action_data == "supporturl" and has_perm(uid, 'p_settings'):
                url = (await get_reply("🔗 Enter new Support URL (must start with http:// or https://):")).raw_text
                if not url.startswith("http"):
                    url = "https://" + url.replace("@", "t.me/")
                cur.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('support_url',?)", (url,))
                db.commit()
                await conv.send_message(f"{P_YES} Support URL updated.")

            elif action_data == "bcast" and has_perm(uid, 'p_stats'):
                txt = (await get_reply(f"{P_DOC} <b>Message (Supports HTML & tg-emoji tags):</b>")).raw_text
                btn_name = (await get_reply(f"🔘 <b>Button Name (or 'skip'):</b>")).raw_text
                url = (await get_reply("🔗 <b>URL:</b>")).raw_text if btn_name.lower() != 'skip' else None
                btns = [[Button.url(btn_name, url)]] if url else None
                users = cur.execute("SELECT user_id FROM users").fetchall()
                s, f = 0, 0
                await conv.send_message(f"{P_TG} Broadcasting...")
                for (u_id,) in users:
                    try:
                        await bot.send_message(int(u_id), txt, buttons=btns, parse_mode='html')
                        s += 1
                    except Exception:
                        f += 1
                    await asyncio.sleep(0.1)
                await conv.send_message(f"{P_YES} Done! Sent: {s} | Failed: {f}")

            elif action_data == "bal" and has_perm(uid, 'p_bal'):
                t_uid = int((await get_reply(f"{P_ACC} <b>User ID:</b>")).raw_text)
                if not user_exists(t_uid):
                    return await conv.send_message(f"{P_NO} User not found.")
                amt = int((await get_reply(f"{P_MONEY} <b>Amount (Negative to deduct):</b>")).raw_text)
                update_balance(t_uid, amt)
                await conv.send_message(f"{P_YES} Balance changed by {P_INR}{amt} for {t_uid}.")

            elif action_data == "discount" and has_perm(uid, 'p_settings'):
                t_uid = int((await get_reply(f"{P_ACC} <b>User ID:</b>")).raw_text)
                if not user_exists(t_uid):
                    return await conv.send_message(f"{P_NO} User not found.")
                pct = int((await get_reply(f"{P_GIFT} <b>Discount % (0 to remove):</b>")).raw_text)
                if not 0 <= pct <= 100:
                    return await conv.send_message(f"{P_NO} Discount 0 se 100 ke beech hona chahiye.")
                cur.execute("UPDATE users SET discount=? WHERE user_id=?", (pct, t_uid))
                db.commit()
                await conv.send_message(f"{P_YES} User {t_uid} has {pct}% discount.")

            elif action_data == "refpct" and has_perm(uid, 'p_settings'):
                amt = int((await get_reply(f"{P_USERS} <b>Referral bonus per refer (₹):</b>")).raw_text)
                cur.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('ref_bonus',?)", (str(amt),))
                db.commit()
                await conv.send_message(f"{P_YES} Referral bonus set to {P_INR}{amt}.")

            elif action_data == "usdtrate" and has_perm(uid, 'p_settings'):
                r = float((await get_reply(f"{P_USDT} <b>New USDT Rate (INR):</b>")).raw_text)
                if r <= 0:
                    return await conv.send_message(f"{P_NO} Rate 0 se bada hona chahiye.")
                cur.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('usdt_rate',?)", (str(r),))
                db.commit()
                await conv.send_message(f"{P_YES} Rate set to {r}.")

            elif action_data == "restoreusr" and has_perm(uid, 'p_settings'):
                resp = await get_reply(f"📤 <b>Send the <code>users_backup.csv</code> file:</b>")
                if not resp.file or not resp.file.name.endswith('.csv'):
                    return await conv.send_message(f"{P_NO} Invalid file.")
                await bot.download_media(resp, "temp_restore.csv")
                with open("temp_restore.csv", "r", encoding="utf-8") as f:
                    reader = csv.reader(f)
                    next(reader)
                    count = 0
                    for row in reader:
                        try:
                            ref_rewarded = int(row[8]) if len(row) > 8 and row[8] != "" else 1
                            cur.execute("INSERT OR REPLACE INTO users (user_id, balance, referred_by, total_deposited, joined_date, banned, discount, terms_accepted, ref_rewarded) VALUES (?,?,?,?,?,?,?,?,?)",
                                        (int(row[0]), int(row[1]), row[2] if row[2] else None, int(row[3]), row[4], int(row[5]), int(row[6]), int(row[7]), ref_rewarded))
                            count += 1
                        except Exception:
                            pass
                db.commit()
                os.remove("temp_restore.csv")
                await conv.send_message(f"{P_YES} Restored {count} users.")

            elif action_data == "ban" and has_perm(uid, 'p_bal'):
                t_uid = int((await get_reply(f"{P_ACC} <b>User ID:</b>")).raw_text)
                is_ban = cur.execute("SELECT banned FROM users WHERE user_id=?", (t_uid,)).fetchone()
                if not is_ban:
                    return await conv.send_message(f"{P_NO} User not found.")
                ns = 0 if is_ban[0] == 1 else 1
                cur.execute("UPDATE users SET banned=? WHERE user_id=?", (ns, t_uid))
                db.commit()
                await conv.send_message(f"User {t_uid} is {'Banned 🚫' if ns == 1 else 'Unbanned ✅'}.")

        except AdminCancelled:
            await conv.send_message(f"{P_NO} Cancelled.")
        except asyncio.TimeoutError:
            await conv.send_message(f"{P_WARN} Time out ho gaya (10 min). Dobara try karo.")
        except ValueError:
            await conv.send_message(f"{P_NO} Invalid input (number chahiye tha). Dobara try karo.")
        except Exception as e:
            logger.error(f"Admin action error: {e}")
            await conv.send_message(f"{P_NO} Error: {html.escape(str(e) or type(e).__name__)}")


IST = timezone(timedelta(hours=5, minutes=30))


def to_ist(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST).strftime('%d %b %Y, %I:%M %p IST')


async def render_sessions(e, phone, note=""):
    order = active_orders.get(phone)
    if not order:
        return await e.answer("⚠️ No active order found or already logged out.", alert=True)
    res = await order['client'](GetAuthorizationsRequest())
    others = [a for a in res.authorizations if not a.current]

    lines, btns = [], []
    for n, a in enumerate(others, 1):
        dev = html.escape(f"{a.device_model or 'Unknown'} | {a.app_name or ''} {a.platform or ''}".strip())
        loc = html.escape(a.country or "Unknown")
        when = to_ist(a.date_active) if a.date_active else "-"
        lines.append(f"📱 <b>Device {n}</b>\n    {dev}\n    🌍 {loc} | 🕒 {when}")
        short = (a.device_model or 'Unknown')[:14]
        btns.append([Button.inline(f"❌ Logout Device {n} ({short})", f"lo_dev|{phone}|{a.hash}")])

    if others:
        body = f"{P_YES} <b>Login devices: {len(others)}</b>\n\n" + "\n\n".join(lines)
        if len(others) > 1:
            btns.append([Button.inline("🧹 Logout ALL Other Devices", f"lo_all|{phone}")])
    else:
        body = f"{P_WARN} <b>Koi dusra device login nahi hai.</b>"

    msg = ((note + "\n\n") if note else "")
    msg += (f"{P_2FA} <b>Active Sessions</b>\n{P_PHONE} <code>{phone}</code>\n\n{body}\n\n"
            f"🤖 Bot ka apna session abhi bhi login hai.\n"
            f"<i>Jis device ko hatana hai uska button dabao. Kaam khatam hone par Bot Session logout karo.</i>")
    btns.append([Button.inline("🔄 Refresh", f"logout_bot|{phone}")])
    btns.append([Button.inline("🚪 Logout Bot Session (Finish)", f"logout_cf|{phone}")])
    btns.append([Button.inline("↩️ Cancel", f"logout_no|{phone}")])
    try:
        await e.edit(msg, buttons=btns)
    except MessageNotModifiedError:
        pass


# ================= CORE EVENT ROUTERS =================
# ======================================================================
# PHASE 2: SELL SYSTEM + SELL PRICE LIST + WITHDRAWALS + PROMO CODES
# ======================================================================
from telethon.errors import SessionPasswordNeededError, AuthKeyUnregisteredError, PhoneCodeInvalidError as _PCI

sell_state = {}        # uid -> in-progress sell conversation (holds live Telethon client)
selling_accounts = {}  # phone -> account in 10-minute hold
wd_state = {}          # uid -> {'amount': int} waiting for UPI ID
promo_state = {}       # uid -> True while waiting for a promo code

SELL_HOLD_SECONDS = 600
SELL_ADMIN_FEE_PCT = 10     # user gets 90% of sell price
SELL_BLACKLIST_DAYS = 90
MIN_UPI_WITHDRAW = 50


def is_sell_on():
    r = cur.execute("SELECT value FROM settings WHERE key='sell_status'").fetchone()
    return (r[0] if r and r[0] else "on") == "on"


def get_random_api_credentials():
    """Pick an API id/hash from the admin-managed pool; fall back to .env credentials."""
    rows = cur.execute("SELECT api_id, api_hash FROM api_credentials").fetchall()
    if rows:
        return random.choice(rows)
    return API_ID, API_HASH


def split_message(text, limit=3800):
    """Split a long message on line boundaries so each part fits Telegram's limit."""
    parts, buf = [], ""
    for line in text.split("\n"):
        if len(buf) + len(line) + 1 > limit:
            parts.append(buf)
            buf = ""
        buf += line + "\n"
    if buf.strip():
        parts.append(buf)
    return parts or [text]


def flag_to_iso(flag):
    letters = [chr(ord(c) - 0x1F1E6 + 65) for c in str(flag) if 0x1F1E6 <= ord(c) <= 0x1F1FF]
    return "".join(letters[:2]) or "--"


def sell_price_rows():
    """One row per country code: (code, best normal price INR, best spam price INR)."""
    rows = cur.execute("SELECT country_code, MAX(price_good), MAX(price_spam) FROM sell_prices GROUP BY country_code ORDER BY country_code").fetchall()
    return rows


def build_sell_price_list():
    rows = sell_price_rows()
    rate = get_usdt_rate() or 94.0
    lines = ["<b>We buy from you →</b>", ""]
    for code, pg, ps in rows:
        name, flag = get_country_info(code)
        lines.append(f"[{flag}]+{code}-{flag_to_iso(flag)}: {pg / rate:.2f}$")
    return "\n".join(lines)


def find_sell_country_code(phone):
    codes = {r[0] for r in cur.execute("SELECT DISTINCT country_code FROM sell_prices").fetchall()}
    for length in (4, 3, 2, 1):
        if phone[:length] in codes:
            return phone[:length]
    return None


def lookup_sell_price(c_code, year):
    row = cur.execute("SELECT price_good, price_spam FROM sell_prices WHERE country_code=? AND year=?", (c_code, str(year))).fetchone()
    if not row:
        row = cur.execute("SELECT price_good, price_spam FROM sell_prices WHERE country_code=? AND year='Common'", (c_code,)).fetchone()
    return row


async def sell_cleanup_state(uid, delete_files=True):
    """Drop a half-finished sell conversation and release its Telethon client."""
    st = sell_state.pop(uid, None)
    if st and st.get("client"):
        try:
            await st["client"].disconnect()
        except Exception:
            pass
        if delete_files and st.get("phone") and st["phone"] not in selling_accounts:
            delete_session_files(f"sessions/{st['phone']}")


async def show_sell_menu(event):
    uid = event.sender_id
    if not is_sell_on():
        return await event.reply(f"{P_NO} <b>Selling is currently disabled by admin.</b>")
    if not sell_price_rows():
        return await event.reply(f"{P_NO} <b>No sell prices have been set yet.</b>")
    await sell_cleanup_state(uid)
    guide = cur.execute("SELECT value FROM settings WHERE key='sell_guide_url'").fetchone()
    btns = [[Button.inline("🟩 Sell WhatsApp Account", "wa_sell")], [Button.inline("❌ Cancel", "cancel_action")]]
    if guide and guide[0]:
        btns.insert(0, [Button.url("🎥 How to sell (Guide)", guide[0])])
    header = build_sell_price_list()
    footer = (f"\n\n<i>Note: a {SELL_ADMIN_FEE_PCT}% admin fee is charged; you receive {100 - SELL_ADMIN_FEE_PCT}% of the price.</i>\n\n"
              f"👇 <b>Send the phone number you want to sell (e.g. +919999999999):</b>")
    parts = split_message(header + footer)
    for i, part in enumerate(parts):
        await event.respond(part, buttons=btns if i == len(parts) - 1 else None)
    sell_state[uid] = {"step": "wait_num"}


async def handle_sell_text(e, uid, text):
    """Drives the sell conversation: phone -> OTP -> (2FA) -> hold. Returns True if consumed."""
    st = sell_state.get(uid)
    if not st:
        return False
    step = st["step"]

    if step == "wait_num":
        phone = re.sub(r"\D", "", text)
        if len(phone) < 7:
            await e.reply(f"{P_NO} Invalid format. Send the number with country code, digits only.")
            return True
        bl = cur.execute("SELECT removed_date FROM blacklisted_phones WHERE phone=?", (phone,)).fetchone()
        if bl:
            try:
                removed = datetime.strptime(str(bl[0])[:19], "%Y-%m-%d %H:%M:%S")
            except Exception:
                removed = datetime.utcnow()
            if (datetime.utcnow() - removed).days < SELL_BLACKLIST_DAYS:
                sell_state.pop(uid, None)
                await e.reply(f"{P_NO} <b>This number is blacklisted.</b>\nIt can be listed again {SELL_BLACKLIST_DAYS} days after removal.")
                return True
            cur.execute("DELETE FROM blacklisted_phones WHERE phone=?", (phone,))
            db.commit()
        if cur.execute("SELECT 1 FROM stock WHERE phone=?", (phone,)).fetchone() or phone in selling_accounts:
            sell_state.pop(uid, None)
            await e.reply(f"{P_NO} This number is already listed or being verified.")
            return True
        c_code = find_sell_country_code(phone)
        if not c_code:
            sell_state.pop(uid, None)
            await e.reply(f"{P_NO} Selling is not allowed for this country code right now.")
            return True

        await e.reply("🔄 Checking number and requesting OTP...")
        os.makedirs("sessions", exist_ok=True)
        api_id, api_hash = get_random_api_credentials()
        client = TelegramClient(f"sessions/{phone}", int(api_id), api_hash)
        try:
            await client.connect()
            sreq = await client.send_code_request(phone)
        except PhoneNumberInvalidError:
            sell_state.pop(uid, None)
            try: await client.disconnect()
            except Exception: pass
            delete_session_files(f"sessions/{phone}")
            await e.reply(f"{P_NO} Invalid phone number.")
            return True
        except Exception as ex:
            sell_state.pop(uid, None)
            try: await client.disconnect()
            except Exception: pass
            delete_session_files(f"sessions/{phone}")
            await e.reply(f"{P_NO} Error: {html.escape(str(ex)[:150])}")
            return True
        name, flag = get_country_info(phone)
        sell_state[uid] = {"step": "wait_otp", "phone": phone, "client": client, "hash": sreq.phone_code_hash,
                           "c_code": c_code, "c_name": name, "c_icon": flag}
        await e.reply("📩 <b>Enter the login code you received in Telegram.</b>\n<i>Tip: type it with spaces/dashes (e.g. 1-2-3-4-5) so Telegram doesn't block it.</i>",
                      buttons=[[Button.inline("❌ Cancel", "cancel_action")]])
        return True

    if step in ("wait_otp", "wait_2fa"):
        client, phone = st["client"], st["phone"]
        try:
            if step == "wait_otp":
                code = re.sub(r"\D", "", text)
                await client.sign_in(phone, code, phone_code_hash=st["hash"])
            else:
                await client.sign_in(password=text.strip())
                st["old_pw"] = text.strip()
        except SessionPasswordNeededError:
            st["step"] = "wait_2fa"
            await e.reply("🔐 <b>This account has 2FA enabled.</b>\nSend the current 2FA password:", buttons=[[Button.inline("❌ Cancel", "cancel_action")]])
            return True
        except (PhoneCodeInvalidError, PhoneCodeExpiredError):
            await e.reply(f"{P_NO} Wrong or expired code. Try again, or Cancel and restart.")
            return True
        except Exception as ex:
            if step == "wait_2fa":
                await e.reply(f"{P_NO} Wrong password or error: {html.escape(str(ex)[:120])}\nTry again.")
                return True
            await sell_cleanup_state(uid)
            await e.reply(f"{P_NO} Login failed: {html.escape(str(ex)[:150])}")
            return True

        # Logged in: secure the account with a fresh 2FA password
        new_pass = generate_sell_password()
        try:
            await client.edit_2fa(current_password=st.get("old_pw"), new_password=new_pass, hint="")
        except Exception as ex:
            logger.warning("edit_2fa failed for %s: %s", phone, ex)
            new_pass = st.get("old_pw") or "None"

        is_spam = False
        try:
            await client.send_message("spambot", "/start")
            await asyncio.sleep(2)
            msgs = await client.get_messages("spambot", limit=1)
            if msgs and msgs[0].message and "Good news" not in msgs[0].message:
                is_spam = True
        except Exception:
            pass

        year = await detect_account_year(client)
        row = lookup_sell_price(st["c_code"], year)
        if not row:
            await sell_cleanup_state(uid)
            await e.reply(f"{P_NO} Admin has not set a purchase price for this country/year. Sale rejected.")
            return True
        base_val = int(row[1] if is_spam else row[0])

        msg = await e.reply(
            f"{P_YES} <b>Logged in!</b>\n⏱ {SELL_HOLD_SECONDS // 60}-minute hold started.\n"
            f"💰 Offer: {P_INR}{base_val} ({'Spam' if is_spam else 'Clean'}, {year})\n\n"
            f"⚠️ Terminate <b>ALL other active sessions</b> in your Telegram app now.",
            buttons=[[Button.inline("🔍 Check Active Sessions", f"sell_chk|{phone}")],
                     [Button.inline("↩️ Cancel & Get Account Back", f"sell_cancel|{phone}")]])
        selling_accounts[phone] = {"uid": uid, "client": client, "msg_id": msg.id, "c_name": st["c_name"],
                                   "c_icon": st["c_icon"], "year": year, "is_spam": is_spam,
                                   "new_pass": new_pass, "base": base_val, "cancelled": False}
        cur.execute("INSERT OR REPLACE INTO sell_submissions (phone, user_id, country, flag, year, price, is_spam, twofa, msg_id, status) VALUES (?,?,?,?,?,?,?,?,?, 'holding')",
                    (phone, uid, st["c_name"], st["c_icon"], year, base_val, int(is_spam), new_pass, msg.id))
        db.commit()
        sell_state.pop(uid, None)
        asyncio.create_task(sell_hold_task(phone))
        return True
    return False


def generate_sell_password(length=12):
    return "".join(random.choice(_string.ascii_letters + _string.digits) for _ in range(length))


async def _sell_client_for(phone):
    api_id, api_hash = get_random_api_credentials()
    c = TelegramClient(f"sessions/{phone}", int(api_id), api_hash)
    await c.connect()
    return c


async def sell_hold_task(phone, delay=SELL_HOLD_SECONDS):
    """After the hold: reject if other sessions exist / session invalid, else accept & pay 90%."""
    await asyncio.sleep(delay)
    st = selling_accounts.get(phone)
    if not st or st.get("cancelled"):
        return
    uid = st["uid"]
    client = st.get("client")
    try:
        if client is None or not client.is_connected():
            client = await _sell_client_for(phone)
            st["client"] = client
        auths = await client(GetAuthorizationsRequest())
        valid = True
        reason = ""
        if len(auths.authorizations) > 1:
            valid, reason = False, "other active sessions still exist"
    except AuthKeyUnregisteredError:
        valid, reason = False, "session is no longer valid"
        auths = None
    except Exception as ex:
        valid, reason = False, f"session check failed ({str(ex)[:60]})"

    if not valid:
        cur.execute("UPDATE sell_submissions SET status='rejected', reason=? WHERE phone=? AND status='holding'", (reason, phone))
        db.commit()
        selling_accounts.pop(phone, None)
        try: await client.disconnect()
        except Exception: pass
        txt = f"{P_NO} <b>Sell Rejected!</b>\nNumber: <code>{phone}</code>\nReason: {html.escape(reason)}.\nTap below to get your account back."
        try:
            await bot.edit_message(uid, st["msg_id"], txt, buttons=[[Button.inline("🔑 Get Login Info", f"sell_get|{phone}")]])
        except Exception:
            try: await bot.send_message(uid, txt, buttons=[[Button.inline("🔑 Get Login Info", f"sell_get|{phone}")]])
            except Exception: pass
        return

    # ACCEPT: list in stock + credit 90% to sales_balance (atomic, once)
    base = st["base"]
    payout = base - int(base * SELL_ADMIN_FEE_PCT / 100)
    cat = "limit_spam" if st["is_spam"] else "spam_free"
    list_price = find_existing_price(st["c_name"], cat, st["year"]) or int(base * 1.5)
    async with get_user_lock(uid):
        cur.execute("UPDATE sell_submissions SET status='accepted' WHERE phone=? AND status='holding'", (phone,))
        if cur.rowcount == 0:
            db.commit()
            return
        cur.execute("INSERT OR REPLACE INTO stock (phone, session_file, country_name, country_icon, account_year, category, price, available, twofa, seller_id, spam_status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (phone, f"sessions/{phone}.session", st["c_name"], st["c_icon"], st["year"], cat, list_price, 1, st["new_pass"], uid, "spam" if st["is_spam"] else "clean"))
        cur.execute("UPDATE users SET sales_balance = COALESCE(sales_balance,0) + ? WHERE user_id=?", (payout, uid))
        db.commit()
    selling_accounts.pop(phone, None)
    try: await client.disconnect()
    except Exception: pass
    txt = (f"{P_YES} <b>Sell Accepted!</b>\nNumber: <code>{phone}</code> passed all checks.\n"
           f"💰 Credited to Sales Balance: {P_INR}{payout}")
    try:
        await bot.edit_message(uid, st["msg_id"], txt)
    except Exception:
        try: await bot.send_message(uid, txt)
        except Exception: pass
    for ch in (LOG_CHANNEL_ID, LOOG_CHANNEL_ID):
        if ch:
            try: await bot.send_message(ch, f"💸 <b>NEW ACCOUNT PURCHASED FROM USER</b>\nUser: <code>{uid}</code>\nNumber: {mask_phone(phone)}\nPaid: {P_INR}{payout}")
            except Exception: pass


async def recover_sell_holds():
    """Resume 10-minute holds that were interrupted by a bot restart."""
    rows = cur.execute("SELECT phone, user_id, country, flag, year, price, is_spam, twofa, msg_id, created FROM sell_submissions WHERE status='holding'").fetchall()
    for phone, uid, country, flag, year, price, is_spam, twofa, msg_id, created in rows:
        try:
            age = (datetime.utcnow() - datetime.strptime(str(created)[:19], "%Y-%m-%d %H:%M:%S")).total_seconds()
        except Exception:
            age = SELL_HOLD_SECONDS
        selling_accounts[phone] = {"uid": uid, "client": None, "msg_id": msg_id, "c_name": country, "c_icon": flag,
                                   "year": year, "is_spam": bool(is_spam), "new_pass": twofa, "base": price, "cancelled": False}
        asyncio.create_task(sell_hold_task(phone, delay=max(5, SELL_HOLD_SECONDS - age)))
    if rows:
        logger.info("Recovered %s sell holds", len(rows))


async def sell_login_info(e, phone, uid):
    """Show the latest login OTP for an account the user sold/cancelled (so they can log back in)."""
    row = cur.execute("SELECT user_id, status FROM sell_submissions WHERE phone=?", (phone,)).fetchone()
    owner_ok = (row and row[0] == uid and row[1] in ("rejected", "cancelled", "removed")) or is_admin(uid)
    if not owner_ok:
        return await e.answer("❌ Not available for this account.", alert=True)
    code = "Not found"
    client = None
    try:
        client = await _sell_client_for(phone)
        msgs = await client.get_messages(777000, limit=5)
        for m in msgs:
            low = (m.message or "").lower()
            if not low or any(x in low for x in OTP_IGNORE_PHRASES):
                continue
            mm = re.search(OTP_REGEX, m.message)
            if mm:
                code = mm.group()
                break
    except Exception as ex:
        code = f"error: {str(ex)[:60]}"
    finally:
        if client:
            try: await client.disconnect()
            except Exception: pass
    twofa = cur.execute("SELECT twofa FROM sell_submissions WHERE phone=?", (phone,)).fetchone()
    msg = (f"{P_YES} <b>Account Retrieval Info</b>\n\n{P_PHONE} Phone: <code>{phone}</code>\n"
           f"{P_TIME} OTP: <code>{code}</code>\n🔐 2FA: <code>{html.escape(str(twofa[0]) if twofa else 'None')}</code>\n\n"
           f"<i>Log in with this code, then delete the bot's session.</i>")
    try:
        await e.edit(msg, buttons=[[Button.inline("🔄 Refresh OTP", f"sell_get|{phone}")],
                                   [Button.inline("🚪 Delete Bot Session", f"sell_rm_final|{phone}")]])
    except MessageNotModifiedError:
        pass


async def show_sell_sessions(event, uid, page=1):
    limit = 5
    total = cur.execute("SELECT COUNT(*) FROM sell_submissions WHERE user_id=?", (uid,)).fetchone()[0]
    rows = cur.execute("SELECT phone, country, flag, year, price, status, reason FROM sell_submissions WHERE user_id=? ORDER BY created DESC LIMIT ? OFFSET ?",
                       (uid, limit, (page - 1) * limit)).fetchall()
    icons = {"holding": "⏳ Holding", "accepted": "✅ Accepted", "rejected": "❌ Rejected", "cancelled": "↩️ Cancelled", "removed": "🗑 Removed"}
    s_bal = cur.execute("SELECT COALESCE(sales_balance,0) FROM users WHERE user_id=?", (uid,)).fetchone()[0]
    msg = f"📁 <b>Your Sold Sessions</b> (page {page})\n💰 Sales Balance: {P_INR}{s_bal}\n\n"
    btns = []
    if not rows:
        msg += "No submissions yet. Use 💸 Sell Account to start."
    for phone, country, flag, year, price, status, reason in rows:
        extra = f" — {html.escape(reason)}" if (status == "rejected" and reason) else ""
        msg += f"{flag} <code>+{phone}</code> | {year} | {P_INR}{price}\n{icons.get(status, status)}{extra}\n────────────\n"
        if status == "accepted" and cur.execute("SELECT 1 FROM stock WHERE phone=? AND seller_id=? AND available=1", (phone, uid)).fetchone():
            btns.append([Button.inline(f"🗑 Remove +{phone}", f"sell_rm|{phone}")])
        if status in ("rejected", "cancelled", "removed"):
            btns.append([Button.inline(f"🔑 Login Info +{phone}", f"sell_get|{phone}")])
    nav = []
    if page > 1:
        nav.append(Button.inline("⬅️ Prev", f"ss_pg|{page - 1}"))
    if page * limit < total:
        nav.append(Button.inline("Next ➡️", f"ss_pg|{page + 1}"))
    if nav:
        btns.append(nav)
    btns.append([Button.inline("🤝 Withdraw Sales Balance", "wd_sales")])
    if isinstance(event, events.CallbackQuery.Event):
        try: await event.edit(msg, buttons=btns)
        except MessageNotModifiedError: pass
    else:
        await event.respond(msg, buttons=btns)


async def show_purchased_sessions(event, uid, page=1):
    return await send_purchase_page(event, uid, page)


# ---------------- PROMO ----------------
async def start_promo(event):
    promo_state[event.sender_id] = True
    await event.respond(f"{P_GIFT} <b>Claim Promo Code</b>\n\nSend your promo code now:", buttons=[[Button.inline("❌ Cancel", "cancel_action")]])


async def handle_promo_text(e, uid, text):
    if uid not in promo_state:
        return False
    promo_state.pop(uid, None)
    code = text.strip()
    async with get_user_lock(uid):
        row = cur.execute("SELECT value, max_uses, used_count FROM promo_codes WHERE code=?", (code,)).fetchone()
        if not row:
            await e.reply(f"{P_NO} Invalid promo code. Check the spelling.")
            return True
        if cur.execute("SELECT 1 FROM promo_logs WHERE code=? AND user_id=?", (code, uid)).fetchone():
            await e.reply(f"{P_NO} You have already claimed this promo code.")
            return True
        cur.execute("UPDATE promo_codes SET used_count = used_count + 1 WHERE code=? AND used_count < max_uses", (code,))
        if cur.rowcount == 0:
            db.commit()
            await e.reply(f"{P_NO} This promo code has reached its maximum usage limit.")
            return True
        cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (row[0], uid))
        cur.execute("INSERT INTO promo_logs (code, user_id) VALUES (?,?)", (code, uid))
        db.commit()
    await e.reply(f"🎁 <b>Promo Code Claimed!</b>\n\n{P_INR}{row[0]} added to your main balance.")
    return True


# ---------------- WITHDRAWALS ----------------
async def handle_wd_text(e, uid, text):
    if uid not in wd_state:
        return False
    upi_id = text.strip()
    if not re.match(r"^[\w.\-]{2,}@[\w.\-]{2,}$", upi_id):
        await e.reply(f"{P_NO} That doesn't look like a valid UPI ID (e.g. name@bank). Try again.")
        return True
    amt = wd_state.pop(uid)["amount"]
    async with get_user_lock(uid):
        cur.execute("UPDATE users SET sales_balance = sales_balance - ? WHERE user_id=? AND sales_balance >= ?", (amt, uid, amt))
        if cur.rowcount == 0:
            db.commit()
            await e.reply(f"{P_NO} Sales balance changed. Please try again.")
            return True
        cur.execute("INSERT INTO withdrawals (user_id, amount, method, details, status) VALUES (?,?,?,?,?)", (uid, amt, "UPI", upi_id, "pending"))
        wd_id = cur.lastrowid
        db.commit()
    await e.reply(f"{P_YES} <b>Withdrawal request submitted!</b>\nAn admin will review it shortly.")
    adm = (f"🔔 <b>NEW WITHDRAWAL REQUEST #{wd_id}</b>\n\n👤 User: <code>{uid}</code>\n💰 Amount: {P_INR}{amt}\n🏦 UPI: <code>{html.escape(upi_id)}</code>")
    btns = [[Button.inline("✅ Approve", f"wd_act|app|{wd_id}"), Button.inline("❌ Reject", f"wd_act|rej|{wd_id}")]]
    sent = False
    for ch in {ADMIN_ID, LOG_CHANNEL_ID}:
        if ch:
            try:
                await bot.send_message(ch, adm, buttons=btns)
                sent = True
            except Exception as ex:
                logger.warning("wd notify %s failed: %s", ch, ex)
    return True


# ---------------- CALLBACKS ----------------
async def phase2_callbacks(e, uid, data):
    """Returns True when the callback was handled here."""
    if data == "cancel_action":
        await sell_cleanup_state(uid)
        promo_state.pop(uid, None)
        wd_state.pop(uid, None)
        return False  # let the original handler also clear its own state

    if data.startswith("ss_pg|"):
        await show_sell_sessions(e, uid, int(data.split("|")[1]))
        return True

    if data.startswith("sell_chk|"):
        phone = data.split("|")[1]
        st = selling_accounts.get(phone)
        if not st:
            await e.answer("Verification finished or expired.", alert=True)
            return True
        if st["uid"] != uid and not is_admin(uid):
            await e.answer("❌ Unauthorized.", alert=True)
            return True
        try:
            cl = st.get("client") or await _sell_client_for(phone)
            st["client"] = cl
            auths = await cl(GetAuthorizationsRequest())
            n = len(auths.authorizations)
            await e.answer(f"⚠️ Active sessions: {n}. Terminate the others in Telegram!" if n > 1 else "✅ Only 1 session active. Verification will complete soon.", alert=True)
        except Exception as ex:
            await e.answer(f"Error: {str(ex)[:100]}", alert=True)
        return True

    if data.startswith("sell_cancel|"):
        phone = data.split("|")[1]
        st = selling_accounts.get(phone)
        if not st or (st["uid"] != uid and not is_admin(uid)):
            await e.answer("Nothing to cancel.", alert=True)
            return True
        st["cancelled"] = True
        selling_accounts.pop(phone, None)
        cur.execute("UPDATE sell_submissions SET status='cancelled' WHERE phone=? AND status='holding'", (phone,))
        db.commit()
        try:
            if st.get("client"):
                await st["client"].disconnect()
        except Exception:
            pass
        await sell_login_info(e, phone, uid)
        return True

    if data.startswith("sell_get|"):
        await sell_login_info(e, data.split("|")[1], uid)
        return True

    if data.startswith("sell_rm|"):
        phone = data.split("|")[1]
        row = cur.execute("SELECT seller_id FROM stock WHERE phone=? AND available=1", (phone,)).fetchone()
        if not row or (row[0] != uid and not is_admin(uid)):
            await e.answer("❌ Not available / unauthorized.", alert=True)
            return True
        cur.execute("DELETE FROM stock WHERE phone=?", (phone,))
        cur.execute("INSERT OR REPLACE INTO blacklisted_phones (phone, removed_date) VALUES (?, datetime('now'))", (phone,))
        cur.execute("UPDATE sell_submissions SET status='removed' WHERE phone=?", (phone,))
        db.commit()
        await e.edit(f"{P_YES} Account removed from the market.\n<i>You can't re-list this number for {SELL_BLACKLIST_DAYS} days.</i>",
                     buttons=[[Button.inline("🔑 Get Login / OTP", f"sell_get|{phone}")]])
        return True

    if data.startswith("sell_rm_final|"):
        phone = data.split("|")[1]
        row = cur.execute("SELECT user_id FROM sell_submissions WHERE phone=?", (phone,)).fetchone()
        if not row or (row[0] != uid and not is_admin(uid)):
            await e.answer("❌ Unauthorized.", alert=True)
            return True
        try:
            c = await _sell_client_for(phone)
            await c.log_out()
        except Exception:
            pass
        delete_session_files(f"sessions/{phone}")
        await e.edit(f"{P_YES} <b>Bot session deleted and logged out.</b>")
        return True

    if data == "wd_sales":
        s_bal = cur.execute("SELECT COALESCE(sales_balance,0) FROM users WHERE user_id=?", (uid,)).fetchone()[0]
        if s_bal <= 0:
            await e.answer("❌ Sales balance is 0.", alert=True)
            return True
        await bot.send_message(uid, f"🤝 <b>Withdraw Sales Balance</b>\n\nAvailable: {P_INR}{s_bal}\nChoose method:",
                               buttons=[[Button.inline("➡️ To Main Balance (instant)", "wd_to_main")],
                                        [Button.inline(f"🏦 To UPI (min {P_INR}{MIN_UPI_WITHDRAW})", "wd_to_upi")]])
        await e.answer()
        return True

    if data == "wd_to_main":
        async with get_user_lock(uid):
            s_bal = cur.execute("SELECT COALESCE(sales_balance,0) FROM users WHERE user_id=?", (uid,)).fetchone()[0]
            if s_bal <= 0:
                await e.answer("❌ Nothing to transfer.", alert=True)
                return True
            cur.execute("UPDATE users SET sales_balance = 0, balance = balance + ? WHERE user_id=?", (s_bal, uid))
            db.commit()
        await e.edit(f"{P_YES} <b>Transferred {P_INR}{s_bal} to your main balance!</b>")
        return True

    if data == "wd_to_upi":
        s_bal = cur.execute("SELECT COALESCE(sales_balance,0) FROM users WHERE user_id=?", (uid,)).fetchone()[0]
        if s_bal < MIN_UPI_WITHDRAW:
            await e.answer(f"❌ Minimum {MIN_UPI_WITHDRAW} required for UPI withdrawal.", alert=True)
            return True
        wd_state[uid] = {"amount": s_bal}
        await e.edit(f"{P_BANK} <b>Send your UPI ID to withdraw {P_INR}{s_bal}:</b>", buttons=[[Button.inline("❌ Cancel", "cancel_action")]])
        return True

    if data.startswith("wd_act|") and has_perm(uid, "p_bal"):
        _, action, wd_id = data.split("|")
        wd_id = int(wd_id)
        row = cur.execute("SELECT user_id, amount, status FROM withdrawals WHERE id=?", (wd_id,)).fetchone()
        if not row or row[2] != "pending":
            await e.answer("⚠️ Already processed.", alert=True)
            return True
        t_uid, amt = row[0], row[1]
        new_status = "approved" if action == "app" else "rejected"
        cur.execute("UPDATE withdrawals SET status=? WHERE id=? AND status='pending'", (new_status, wd_id))
        if cur.rowcount == 0:
            db.commit()
            await e.answer("⚠️ Already processed.", alert=True)
            return True
        if action != "app":  # auto-refund to the sales balance
            cur.execute("UPDATE users SET sales_balance = COALESCE(sales_balance,0) + ? WHERE user_id=?", (amt, t_uid))
        db.commit()
        try:
            await e.edit(f"{'✅ Approved' if action == 'app' else '❌ Rejected (refunded)'} withdrawal #{wd_id} of {P_INR}{amt} for <code>{t_uid}</code>.")
        except MessageNotModifiedError:
            pass
        try:
            await bot.send_message(t_uid, f"✅ Your withdrawal of {P_INR}{amt} was approved and paid." if action == "app"
                                   else f"❌ Your withdrawal of {P_INR}{amt} was rejected. The amount was returned to your Sales Balance.")
        except Exception:
            pass
        return True
    return False


# ---------------- ADMIN: SELL / PROMO / WITHDRAW CONTROLS ----------------
async def phase2_admin(event, action_data, uid, chat):
    """Handles adm_sellmenu & friends. Returns True if handled."""
    if action_data == "sellmenu" and has_perm(uid, "p_settings"):
        on = is_sell_on()
        btns = [
            [Button.inline("➕ Set Sell Price", "adm_sp_set"), Button.inline("➖ Remove Sell Price", "adm_sp_del")],
            [Button.inline("📋 View Sell Prices", "adm_sp_view"), Button.inline(f"Sell: {'🟢 ON' if on else '🔴 OFF'}", "adm_sp_toggle")],
            [Button.inline("🎟 Create Promo", "adm_promo_new"), Button.inline("🗑 Delete Promo", "adm_promo_del")],
            [Button.inline("🚫 Blacklist Phone", "adm_bl_add"), Button.inline("♻️ Un-blacklist", "adm_bl_del")],
            [Button.inline("🎥 Sell Guide URL", "adm_sp_guide"), Button.inline("🏦 Pending Withdrawals", "adm_wd_list")],
            [Button.inline("Back", "adm_adminmain")],
        ]
        await event.edit(f"{PE_CROWN} <b>Sell / Promo / Withdraw Controls</b>", buttons=btns)
        return True

    if action_data == "sp_toggle" and has_perm(uid, "p_settings"):
        ns = "off" if is_sell_on() else "on"
        cur.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('sell_status',?)", (ns,))
        db.commit()
        await event.answer(f"Sell {ns.upper()}", alert=True)
        return await phase2_admin(event, "sellmenu", uid, chat)

    if action_data == "sp_view" and has_perm(uid, "p_settings"):
        rows = cur.execute("SELECT country_code, year, price_good, price_spam FROM sell_prices ORDER BY country_code, year").fetchall()
        txt = "<b>Sell Prices (₹)</b>\n\n" + ("\n".join(f"+{c} | {y} | Clean {g} | Spam {s}" for c, y, g, s in rows) or "None set.")
        await event.edit(txt[:3900], buttons=[[Button.inline("Back", "adm_sellmenu")]])
        return True

    if action_data == "wd_list" and has_perm(uid, "p_bal"):
        rows = cur.execute("SELECT id, user_id, amount, details FROM withdrawals WHERE status='pending' ORDER BY id LIMIT 10").fetchall()
        if not rows:
            await event.answer("No pending withdrawals.", alert=True)
            return True
        for wid, t_uid, amt, det in rows:
            await bot.send_message(chat, f"🔔 <b>Withdrawal #{wid}</b>\nUser: <code>{t_uid}</code>\nAmount: {P_INR}{amt}\nUPI: <code>{html.escape(str(det))}</code>",
                                   buttons=[[Button.inline("✅ Approve", f"wd_act|app|{wid}"), Button.inline("❌ Reject", f"wd_act|rej|{wid}")]])
        await event.answer()
        return True

    prompts = {"sp_set", "sp_del", "promo_new", "promo_del", "bl_add", "bl_del", "sp_guide"}
    if action_data in prompts and has_perm(uid, "p_settings"):
        async with bot.conversation(chat, timeout=300) as conv:
            async def ask(t):
                await conv.send_message(t + "\n\n<i>(Type /cancel to abort)</i>")
                r = await conv.get_response()
                if r.raw_text == "/cancel":
                    raise AdminCancelled()
                return r.raw_text.strip()
            try:
                if action_data == "sp_set":
                    c = (await ask("📞 Country code (no +), e.g. <code>91</code>")).replace("+", "")
                    y = await ask("📅 Year (e.g. <code>2022</code>) or <code>Common</code> for all years")
                    g = int(await ask("💰 Clean account price in ₹"))
                    s = int(await ask("💰 Spam/limited account price in ₹"))
                    cur.execute("INSERT OR REPLACE INTO sell_prices (country_code, year, price_good, price_spam) VALUES (?,?,?,?)", (c, y, g, s))
                    db.commit()
                    await conv.send_message(f"{P_YES} Sell price saved for +{c} ({y}).")
                elif action_data == "sp_del":
                    c = (await ask("📞 Country code to remove")).replace("+", "")
                    y = await ask("📅 Year to remove (or <code>all</code>)")
                    if y.lower() == "all":
                        cur.execute("DELETE FROM sell_prices WHERE country_code=?", (c,))
                    else:
                        cur.execute("DELETE FROM sell_prices WHERE country_code=? AND year=?", (c, y))
                    db.commit()
                    await conv.send_message(f"{P_YES} Removed.")
                elif action_data == "promo_new":
                    code = await ask("🎟 Promo code text (leave exact, case-sensitive)")
                    val = int(await ask("💰 Amount in ₹ credited per claim"))
                    mx = int(await ask("🔢 Max number of claims"))
                    if cur.execute("SELECT 1 FROM promo_codes WHERE code=?", (code,)).fetchone():
                        return await conv.send_message(f"{P_NO} That code already exists.")
                    cur.execute("INSERT INTO promo_codes (code, value, max_uses, used_count) VALUES (?,?,?,0)", (code, val, mx))
                    db.commit()
                    await conv.send_message(f"{P_YES} Promo <code>{html.escape(code)}</code> created: {P_INR}{val} x {mx}.")
                elif action_data == "promo_del":
                    code = await ask("🗑 Promo code to delete")
                    cur.execute("DELETE FROM promo_codes WHERE code=?", (code,))
                    db.commit()
                    await conv.send_message(f"{P_YES} Deleted (if it existed).")
                elif action_data == "bl_add":
                    ph = re.sub(r"\D", "", await ask("🚫 Phone number to blacklist"))
                    cur.execute("INSERT OR REPLACE INTO blacklisted_phones (phone, removed_date) VALUES (?, datetime('now'))", (ph,))
                    db.commit()
                    await conv.send_message(f"{P_YES} Blacklisted {ph}.")
                elif action_data == "bl_del":
                    ph = re.sub(r"\D", "", await ask("♻️ Phone number to un-blacklist"))
                    cur.execute("DELETE FROM blacklisted_phones WHERE phone=?", (ph,))
                    db.commit()
                    await conv.send_message(f"{P_YES} Removed from blacklist.")
                elif action_data == "sp_guide":
                    u = await ask("🎥 Guide/video URL (send <code>none</code> to remove)")
                    cur.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('sell_guide_url',?)", ("" if u.lower() == "none" else u,))
                    db.commit()
                    await conv.send_message(f"{P_YES} Saved.")
            except AdminCancelled:
                await conv.send_message(f"{P_NO} Cancelled.")
            except (ValueError, TypeError):
                await conv.send_message(f"{P_NO} Invalid number. Cancelled.")
        return True
    return False


# ======================================================================
# SERVER 1 (LZT) CONSTANTS, COUNTRY DATA AND MARKET CLIENT (ported from the 6k bot)
# ======================================================================
LZT_TOKEN = os.getenv("LZT_TOKEN", "").strip()
LZT_BASE_URL = os.getenv("LZT_BASE_URL", "https://prod-api.lzt.market").rstrip("/")
LZT_REQUEST_TIMEOUT = float(os.getenv("LZT_REQUEST_TIMEOUT", "8"))
LZT_STOCK_TIMEOUT = float(os.getenv("LZT_STOCK_TIMEOUT", "12"))
LZT_MAX_RETRIES = int(os.getenv("LZT_MAX_RETRIES", "2"))
LZT_STOCK_RETRIES = int(os.getenv("LZT_STOCK_RETRIES", "1"))
LZT_CACHE_CONCURRENCY = int(os.getenv("LZT_CACHE_CONCURRENCY", "1"))
LZT_CACHE_REFRESH_SECONDS = float(os.getenv("LZT_CACHE_REFRESH_SECONDS", "300"))
LZT_FORCE_IPV4 = os.getenv("LZT_FORCE_IPV4", "1").strip().lower() not in ("0", "false", "no", "off")
LZT_HTTP_FALLBACK = os.getenv("LZT_HTTP_FALLBACK", "1").strip().lower() not in ("0", "false", "no", "off")
LZT_PROXY = os.getenv("LZT_PROXY", "").strip()
LZT_REQUEST_DEBUG = os.getenv("LZT_REQUEST_DEBUG", "1").strip().lower() not in ("0", "false", "no", "off")
LZT_FAST_BUY_RETRIES = int(os.getenv("LZT_FAST_BUY_RETRIES", "5"))
LZT_PRICE_CURRENCY = os.getenv("LZT_PRICE_CURRENCY", "rub").strip().lower() or "rub"
LZT_MIN_REQUEST_INTERVAL = max(0.2, float(os.getenv("LZT_MIN_REQUEST_INTERVAL", "0.25")))
LZT_RATE_LIMIT_COOLDOWN = float(os.getenv("LZT_RATE_LIMIT_COOLDOWN", "30"))
AUTO_CANCEL_SECONDS = int(os.getenv("AUTO_CANCEL_SECONDS", "600"))

cached_lzt_stock = {}
active_filter_keys = set()
user_filters = {}
error_cooldowns = {}
lzt_search_state = {}
active_lzt_purchases = {}
_lzt_missing_logged = False
_lzt_session = None
_lzt_rate_lock = asyncio.Lock()
_lzt_last_request_at = 0.0
_lzt_blocked_until = 0.0

LZT_COUNTRIES = {
    "Argentina": ("AR", "🇦🇷"), "Australia": ("AU", "🇦🇺"), "Austria": ("AT", "🇦🇹"),
    "Bangladesh": ("BD", "🇧🇩"), "Belgium": ("BE", "🇧🇪"), "Brazil": ("BR", "🇧🇷"),
    "Canada": ("CA", "🇨🇦"), "Chile": ("CL", "🇨🇱"), "China": ("CN", "🇨🇳"),
    "Colombia": ("CO", "🇨🇴"), "Egypt": ("EG", "🇪🇬"), "France": ("FR", "🇫🇷"),
    "Germany": ("DE", "🇩🇪"), "Hong Kong": ("HK", "🇭🇰"), "India": ("IN", "🇮🇳"),
    "Indonesia": ("ID", "🇮🇩"), "Iran": ("IR", "🇮🇷"), "Iraq": ("IQ", "🇮🇶"),
    "Italy": ("IT", "🇮🇹"), "Japan": ("JP", "🇯🇵"), "Kazakhstan": ("KZ", "🇰🇿"),
    "Kenya": ("KE", "🇰🇪"), "Malaysia": ("MY", "🇲🇾"), "Mexico": ("MX", "🇲🇽"),
    "Morocco": ("MA", "🇲🇦"), "Nepal": ("NP", "🇳🇵"), "Netherlands": ("NL", "🇳🇱"),
    "Nigeria": ("NG", "🇳🇬"), "Pakistan": ("PK", "🇵🇰"), "Peru": ("PE", "🇵🇪"),
    "Philippines": ("PH", "🇵🇭"), "Poland": ("PL", "🇵🇱"), "Portugal": ("PT", "🇵🇹"),
    "Romania": ("RO", "🇷🇴"), "Russia": ("RU", "🇷🇺"), "Saudi Arabia": ("SA", "🇸🇦"),
    "Singapore": ("SG", "🇸🇬"), "South Africa": ("ZA", "🇿🇦"), "South Korea": ("KR", "🇰🇷"),
    "Spain": ("ES", "🇪🇸"), "Sri Lanka": ("LK", "🇱🇰"), "Thailand": ("TH", "🇹🇭"),
    "Turkey": ("TR", "🇹🇷"), "Ukraine": ("UA", "🇺🇦"), "United Arab Emirates": ("AE", "🇦🇪"),
    "United Kingdom": ("GB", "🇬🇧"), "United States": ("US", "🇺🇸"), "Uzbekistan": ("UZ", "🇺🇿"),
    "Vietnam": ("VN", "🇻🇳"),
}

CALLING_CODES = {
    "Argentina": "54", "Australia": "61", "Austria": "43", "Bangladesh": "880", "Belgium": "32",
    "Brazil": "55", "Canada": "1", "Chile": "56", "China": "86", "Colombia": "57", "Egypt": "20",
    "France": "33", "Germany": "49", "Hong Kong": "852", "India": "91", "Indonesia": "62",
    "Iran": "98", "Iraq": "964", "Italy": "39", "Japan": "81", "Kazakhstan": "7", "Kenya": "254",
    "Malaysia": "60", "Mexico": "52", "Morocco": "212", "Nepal": "977", "Netherlands": "31",
    "Nigeria": "234", "Pakistan": "92", "Peru": "51", "Philippines": "63", "Poland": "48",
    "Portugal": "351", "Romania": "40", "Russia": "7", "Saudi Arabia": "966", "Singapore": "65",
    "South Africa": "27", "South Korea": "82", "Spain": "34", "Sri Lanka": "94", "Thailand": "66",
    "Turkey": "90", "Ukraine": "380", "United Arab Emirates": "971", "United Kingdom": "44",
    "United States": "1", "Uzbekistan": "998", "Vietnam": "84",
}

ADDITIONAL_COUNTRY_DATA = {
    "Afghanistan": ("AF", "🇦🇫", "93"), "Albania": ("AL", "🇦🇱", "355"),
    "Algeria": ("DZ", "🇩🇿", "213"), "Angola": ("AO", "🇦🇴", "244"),
    "Armenia": ("AM", "🇦🇲", "374"), "Azerbaijan": ("AZ", "🇦🇿", "994"),
    "Bahamas": ("BS", "🇧🇸", "1"), "Bahrain": ("BH", "🇧🇭", "973"),
    "Belize": ("BZ", "🇧🇿", "501"), "Botswana": ("BW", "🇧🇼", "267"),
    "Cape Verde": ("CV", "🇨🇻", "238"), "Central African Republic": ("CF", "🇨🇫", "236"),
    "Chad": ("TD", "🇹🇩", "235"), "Comoros": ("KM", "🇰🇲", "269"),
    "Congo": ("CG", "🇨🇬", "242"), "Costa Rica": ("CR", "🇨🇷", "506"),
    "Cuba": ("CU", "🇨🇺", "53"), "Czech Republic": ("CZ", "🇨🇿", "420"),
    "Denmark": ("DK", "🇩🇰", "45"), "Djibouti": ("DJ", "🇩🇯", "253"),
    "Dominica": ("DM", "🇩🇲", "1"), "Dominican Republic": ("DO", "🇩🇴", "1"),
    "Ecuador": ("EC", "🇪🇨", "593"), "El Salvador": ("SV", "🇸🇻", "503"),
    "Estonia": ("EE", "🇪🇪", "372"), "Fiji": ("FJ", "🇫🇯", "679"),
    "Finland": ("FI", "🇫🇮", "358"), "Gabon": ("GA", "🇬🇦", "241"),
    "Georgia": ("GE", "🇬🇪", "995"), "Ghana": ("GH", "🇬🇭", "233"),
    "Greece": ("GR", "🇬🇷", "30"), "Greenland": ("GL", "🇬🇱", "299"),
    "Grenada": ("GD", "🇬🇩", "1"), "Guadeloupe": ("GP", "🇬🇵", "590"),
    "Guam": ("GU", "🇬🇺", "1"), "Guatemala": ("GT", "🇬🇹", "502"),
    "Guyana": ("GY", "🇬🇾", "592"), "Haiti": ("HT", "🇭🇹", "509"),
    "Honduras": ("HN", "🇭🇳", "504"), "Hungary": ("HU", "🇭🇺", "36"),
    "Iceland": ("IS", "🇮🇸", "354"), "Ireland": ("IE", "🇮🇪", "353"),
    "Israel": ("IL", "🇮🇱", "972"), "Ivory Coast": ("CI", "🇨🇮", "225"),
    "Jamaica": ("JM", "🇯🇲", "1"), "Jordan": ("JO", "🇯🇴", "962"),
    "Kiribati": ("KI", "🇰🇮", "686"), "Kuwait": ("KW", "🇰🇼", "965"),
    "Kyrgyzstan": ("KG", "🇰🇬", "996"), "Laos": ("LA", "🇱🇦", "856"),
    "Latvia": ("LV", "🇱🇻", "371"), "Lebanon": ("LB", "🇱🇧", "961"),
    "Lesotho": ("LS", "🇱🇸", "266"), "Libya": ("LY", "🇱🇾", "218"),
    "Lithuania": ("LT", "🇱🇹", "370"), "Luxembourg": ("LU", "🇱🇺", "352"),
    "Macau": ("MO", "🇲🇴", "853"), "Madagascar": ("MG", "🇲🇬", "261"),
    "Malawi": ("MW", "🇲🇼", "265"), "Maldives": ("MV", "🇲🇻", "960"),
    "Malta": ("MT", "🇲🇹", "356"), "Mauritania": ("MR", "🇲🇷", "222"),
    "Mauritius": ("MU", "🇲🇺", "230"), "Moldova": ("MD", "🇲🇩", "373"),
    "Mozambique": ("MZ", "🇲🇿", "258"), "Myanmar": ("MM", "🇲🇲", "95"),
    "New Zealand": ("NZ", "🇳🇿", "64"), "Nicaragua": ("NI", "🇳🇮", "505"),
    "Niger": ("NE", "🇳🇪", "227"), "Norway": ("NO", "🇳🇴", "47"),
    "Oman": ("OM", "🇴🇲", "968"), "Palau": ("PW", "🇵🇼", "680"),
    "Palestine": ("PS", "🇵🇸", "970"), "Panama": ("PA", "🇵🇦", "507"),
    "Papua New Guinea": ("PG", "🇵🇬", "675"), "Paraguay": ("PY", "🇵🇾", "595"),
    "Puerto Rico": ("PR", "🇵🇷", "1787"), "Qatar": ("QA", "🇶🇦", "974"),
    "Samoa": ("WS", "🇼🇸", "685"), "Senegal": ("SN", "🇸🇳", "221"),
    "Serbia": ("RS", "🇷🇸", "381"), "Seychelles": ("SC", "🇸🇨", "248"),
    "Sierra Leone": ("SL", "🇸🇱", "232"), "Slovenia": ("SI", "🇸🇮", "386"),
    "Solomon Islands": ("SB", "🇸🇧", "677"), "Somalia": ("SO", "🇸🇴", "252"),
    "South Sudan": ("SS", "🇸🇸", "211"), "Sudan": ("SD", "🇸🇩", "249"),
    "Suriname": ("SR", "🇸🇷", "597"), "Swaziland": ("SZ", "🇸🇿", "268"),
    "Sweden": ("SE", "🇸🇪", "46"), "Switzerland": ("CH", "🇨🇭", "41"),
    "Syria": ("SY", "🇸🇾", "963"), "Taiwan": ("TW", "🇹🇼", "886"),
    "Tajikistan": ("TJ", "🇹🇯", "992"), "Timor-Leste": ("TL", "🇹🇱", "670"),
    "Togo": ("TG", "🇹🇬", "228"), "Tonga": ("TO", "🇹🇴", "676"),
    "Trinidad and Tobago": ("TT", "🇹🇹", "1"), "Tunisia": ("TN", "🇹🇳", "216"),
    "Turkmenistan": ("TM", "🇹🇲", "993"), "Uganda": ("UG", "🇺🇬", "256"),
    "Uruguay": ("UY", "🇺🇾", "598"), "Vanuatu": ("VU", "🇻🇺", "678"),
    "Yemen": ("YE", "🇾🇪", "967"), "Zambia": ("ZM", "🇿🇲", "260"),
}
for _country_name, (_iso, _flag, _calling) in ADDITIONAL_COUNTRY_DATA.items():
    LZT_COUNTRIES.setdefault(_country_name, (_iso, _flag))
    CALLING_CODES.setdefault(_country_name, _calling)

# Extra Server 1 country catalog entries. The third value is a stable button/API
# code used by callbacks; if the market rejects it, lookups fall back to the
# country name automatically.
MORE_SERVER1_COUNTRIES = """
Åland Islands|ALA|🇦🇽|358
American Samoa|ASM|🇦🇸|1
Andorra|AND|🇦🇩|376
Anguilla|AIA|🇦🇮|1
Antarctica|ATA|🇦🇶|672
Antigua and Barbuda|ATG|🇦🇬|1
Aruba|ABW|🇦🇼|297
Bahamas|BHS|🇧🇸|1
Barbados|BRB|🇧🇧|1
Belarus|BLR|🇧🇾|375
Benin|BEN|🇧🇯|229
Bermuda|BMU|🇧🇲|1
Bhutan|BTN|🇧🇹|975
Bolivia|BOL|🇧🇴|591
Bosnia and Herzegovina|BIH|🇧🇦|387
Bouvet Island|BVT|🇧🇻|47
British Indian Ocean Territory|IOT|🇮🇴|246
British Virgin Islands|VGB|🇻🇬|1
Brunei|BRN|🇧🇳|673
Bulgaria|BGR|🇧🇬|359
Burkina Faso|BFA|🇧🇫|226
Burundi|BDI|🇧🇮|257
Cambodia|KHM|🇰🇭|855
Cameroon|CMR|🇨🇲|237
Canary Islands|CNR|🇮🇨|34
Caribbean Netherlands|BES|🇧🇶|599
Cayman Islands|CYM|🇰🇾|1
Congo (DRC)|COD|🇨🇩|243
Cook Islands|COK|🇨🇰|682
Côte d’Ivoire|CIV|🇨🇮|225
Croatia|HRV|🇭🇷|385
Curaçao|CUW|🇨🇼|599
Cyprus|CYP|🇨🇾|357
Czechia|CZE|🇨🇿|420
Equatorial Guinea|GNQ|🇬🇶|240
Eritrea|ERI|🇪🇷|291
Eswatini|SWZ|🇸🇿|268
Ethiopia|ETH|🇪🇹|251
Falkland Islands|FLK|🇫🇰|500
Faroe Islands|FRO|🇫🇴|298
French Guiana|GUF|🇬🇫|594
French Polynesia|PYF|🇵🇫|689
French Southern Territories|ATF|🇹🇫|262
Gambia|GMB|🇬🇲|220
Gibraltar|GIB|🇬🇮|350
Guernsey|GGY|🇬🇬|44
Guinea|GIN|🇬🇳|224
Guinea-Bissau|GNB|🇬🇼|245
Heard Island and McDonald Islands|HMD|🇭🇲|672
Isle of Man|IMN|🇮🇲|44
Jersey|JEY|🇯🇪|44
Kosovo|XKX|🇽🇰|383
Liberia|LBR|🇱🇷|231
Liechtenstein|LIE|🇱🇮|423
Mali|MLI|🇲🇱|223
Marshall Islands|MHL|🇲🇭|692
Martinique|MTQ|🇲🇶|596
Mayotte|MYT|🇾🇹|262
Micronesia|FSM|🇫🇲|691
Monaco|MCO|🇲🇨|377
Mongolia|MNG|🇲🇳|976
Montenegro|MNE|🇲🇪|382
Montserrat|MSR|🇲🇸|1
Namibia|NAM|🇳🇦|264
Nauru|NRU|🇳🇷|674
New Caledonia|NCL|🇳🇨|687
Niue|NIU|🇳🇺|683
Norfolk Island|NFK|🇳🇫|672
North Korea|PRK|🇰🇵|850
North Macedonia|MKD|🇲🇰|389
Northern Mariana Islands|MNP|🇲🇵|1
Pitcairn Islands|PCN|🇵🇳|64
Réunion|REU|🇷🇪|262
Rwanda|RWA|🇷🇼|250
Saint Barthélemy|BLM|🇧🇱|590
Saint Helena|SHN|🇸🇭|290
Saint Kitts and Nevis|KNA|🇰🇳|1
Saint Lucia|LCA|🇱🇨|1
Saint Martin|MAF|🇲🇫|590
Saint Pierre and Miquelon|SPM|🇵🇲|508
Saint Vincent and the Grenadines|VCT|🇻🇨|1
San Marino|SMR|🇸🇲|378
São Tomé and Príncipe|STP|🇸🇹|239
Sint Maarten|SXM|🇸🇽|1
Slovakia|SVK|🇸🇰|421
South Georgia and South Sandwich Islands|SGS|🇬🇸|500
Svalbard and Jan Mayen|SJM|🇸🇯|47
Tanzania|TZA|🇹🇿|255
Tokelau|TKL|🇹🇰|690
Turks and Caicos Islands|TCA|🇹🇨|1
Tuvalu|TUV|🇹🇻|688
Vatican City|VAT|🇻🇦|379
Venezuela|VEN|🇻🇪|58
U.S. Virgin Islands|VIR|🇻🇮|1
Wallis and Futuna|WLF|🇼🇫|681
Western Sahara|ESH|🇪🇭|212
Zimbabwe|ZWE|🇿🇼|263
"""
for _line in MORE_SERVER1_COUNTRIES.strip().splitlines():
    _name, _code, _flag, _calling = _line.split("|")
    LZT_COUNTRIES.setdefault(_name, (_code, _flag))
    CALLING_CODES.setdefault(_name, _calling)

def p_btn(text, data=None, url=None, style=None, icon_custom_emoji_id=None):
    kwargs = {}
    if style:
        kwargs["style"] = style
    if icon_custom_emoji_id:
        kwargs["icon_custom_emoji_id"] = icon_custom_emoji_id
    if url:
        try:
            return Button.url(text, url, **kwargs)
        except TypeError:
            return Button.url(text, url)
    try:
        return Button.inline(text, data, **kwargs)
    except TypeError:
        return Button.inline(text, data)

def lzt_price_currency(item):
    if isinstance(item, dict):
        for key in ("currency", "price_currency", "priceCurrency", "currency_code", "currencyCode"):
            value = item.get(key)
            if value:
                return str(value).strip().lower()
        price_data = item.get("price_data") or item.get("priceData")
        if isinstance(price_data, dict):
            for key in ("currency", "currency_code", "currencyCode"):
                value = price_data.get(key)
                if value:
                    return str(value).strip().lower()
    return LZT_PRICE_CURRENCY

def lzt_currency_to_inr_rate(currency):
    currency = str(currency or LZT_PRICE_CURRENCY).strip().lower()
    if currency == "usd":
        return get_usdt_rate()
    rate_defaults = {
        "rub": 1.05,
        "eur": 100.0,
        "gbp": 118.0,
        "cny": 13.0,
        "uah": 2.3,
        "kzt": 0.2,
        "byn": 29.0,
        "try": 2.9,
        "jpy": 0.62,
        "brl": 17.0,
    }
    return get_rate(f"{currency}_inr_rate", rate_defaults.get(currency, 1.05))

def lzt_currency_params(extra=None):
    params = dict(extra or {})
    params.setdefault("currency", LZT_PRICE_CURRENCY)
    return params

def lzt_price_breakdown(item, markup_percent):
    raw_price = item.get("price_with_fee") or item.get("priceWithSellerFee") or item.get("price") or 0
    try:
        market_price = float(raw_price)
    except (TypeError, ValueError):
        market_price = 0.0
    currency = lzt_price_currency(item)
    inr_base = market_price * lzt_currency_to_inr_rate(currency)
    try:
        markup_percent = int(float(markup_percent))
    except (TypeError, ValueError):
        markup_percent = 20
    markup_amount = max(0, int(round(inr_base * (markup_percent / 100))))
    base_price = max(0, int(round(inr_base)))
    final_price = max(1, base_price + markup_amount)
    return {
        "market_price": market_price,
        "currency": currency.upper(),
        "base_inr": base_price,
        "markup_percent": markup_percent,
        "markup_inr": markup_amount,
        "final_inr": final_price,
    }

def lzt_final_inr_price(item, markup_percent):
    return lzt_price_breakdown(item, markup_percent)["final_inr"]

def get_lzt_markup(country_name):
    candidates = [country_name]
    if country_name in LZT_COUNTRIES:
        iso = LZT_COUNTRIES[country_name][0]
        candidates.extend([iso, iso.upper(), get_country_button_code(country_name)])
    row = None
    for candidate in dict.fromkeys(candidates):
        row = cur.execute("SELECT markup_percent FROM lzt_settings WHERE LOWER(country)=LOWER(?)", (candidate,)).fetchone()
        if row:
            break
    if not row:
        row = cur.execute("SELECT value FROM settings WHERE key='lzt_global_markup'").fetchone()
    try:
        return int(float(row[0])) if row else 20
    except (TypeError, ValueError):
        return 20

def clear_lzt_cache():
    cached_lzt_stock.clear()

def build_country_markup_buttons(page=1, per_page=20):
    countries = sorted(LZT_COUNTRIES.keys())
    total_pages = max(1, (len(countries) + per_page - 1) // per_page)
    page = min(max(1, int(page)), total_pages)
    start = (page - 1) * per_page
    buttons, row = [], []
    for name in countries[start:start + per_page]:
        markup = get_lzt_markup(name)
        row.append(p_btn(f"{country_button_label(name, include_phone=False)} {markup}%", f"adm_cmark|{LZT_COUNTRIES[name][0]}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    nav = []
    if page > 1:
        nav.append(p_btn("⬅ Prev", f"adm_cmarkpg|{page-1}"))
    if page < total_pages:
        nav.append(p_btn("Next ➡", f"adm_cmarkpg|{page+1}"))
    if nav:
        buttons.append(nav)
    buttons.append([p_btn("Back", "adm_lztset")])
    return buttons, page, total_pages

def lzt_candidate_timestamp(container):
    if not isinstance(container, dict):
        return 0
    for key in ("date", "time", "created_at", "createdDate", "timestamp"):
        value = container.get(key)
        try:
            return int(float(value))
        except (TypeError, ValueError):
            continue
    return 0

def collect_lzt_otp_candidates(value, parent_key="", candidates=None, depth=0):
    """Collect OTP candidates from LZT response without matching phones/dates.

    LZT can return codes as top-level fields, nested data/result dictionaries, or
    as a `codes` list like: {"codes": [{"code": "48492", "date": ...}]}.
    This walker only scans trusted OTP/message fields, so large item payloads do
    not accidentally turn phone numbers, Telegram IDs, or dates into OTPs.
    """
    if candidates is None:
        candidates = []
    if value is None or depth > 8:
        return candidates

    trusted_keys = {"code", "otp", "login_code", "telegram_login_code", "telegramLoginCode"}
    text_keys = {"message", "text", "sms", "telegram_message"}
    container_keys = {"data", "item", "telegram", "response", "result", "codes"}
    key_name = str(parent_key or "")

    if isinstance(value, dict):
        ts = lzt_candidate_timestamp(value)
        for key, nested in value.items():
            key_str = str(key)
            if key_str in trusted_keys or key_str in text_keys:
                before = len(candidates)
                collect_lzt_otp_candidates(nested, key_str, candidates, depth + 1)
                if ts:
                    for pos in range(before, len(candidates)):
                        code_ts, priority, code = candidates[pos]
                        if code_ts == 0:
                            candidates[pos] = (ts, priority, code)
            elif key_str in container_keys:
                collect_lzt_otp_candidates(nested, key_str, candidates, depth + 1)
        return candidates

    if isinstance(value, (list, tuple)):
        if key_name in container_keys or key_name in trusted_keys or key_name in text_keys:
            for index, item in enumerate(value):
                before = len(candidates)
                collect_lzt_otp_candidates(item, key_name, candidates, depth + 1)
                # Preserve API order as a weak freshness signal if no date exists.
                for pos in range(before, len(candidates)):
                    ts, priority, code = candidates[pos]
                    if ts == 0:
                        candidates[pos] = (index + 1, priority, code)
        return candidates

    if key_name not in trusted_keys and key_name not in text_keys and key_name != "codes":
        return candidates

    text_val = str(value)
    if "login detected" in text_val.lower():
        return candidates
    match = re.search(OTP_REGEX, text_val)
    if match:
        priority = 100 if key_name in trusted_keys else 50
        candidates.append((0, priority, match.group(0)))
    return candidates

def extract_lzt_otp(res):
    candidates = collect_lzt_otp_candidates(res)
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]

async def get_verified_lzt_otp(item_id, attempts=3, delay=1.5):
    """Fetch Server 1 OTP more than once and always return a found code.

    A code seen twice is marked verified. If the market only returns it once
    before a transient error/rate-limit, the bot still returns that latest code
    instead of hiding it from the buyer.
    """
    seen = []
    last_response = None
    for _ in range(max(1, attempts)):
        res = await lzt_request('GET', f"/{item_id}/telegram-login-code", notify_errors=False, return_error=True)
        last_response = res
        code = extract_lzt_otp(res)
        if code:
            seen.append(code)
            if seen.count(code) >= 2 or attempts == 1:
                return code, True, res
        await asyncio.sleep(delay)
    return (seen[-1], False, last_response) if seen else (None, False, last_response)

def lzt_purchase_has_error(res):
    if not res:
        return True
    if not isinstance(res, dict):
        return False
    for key in ("error", "errors", "error_description"):
        value = res.get(key)
        if value:
            return True
    return False

def lzt_purchase_item_id(res, fallback_item_id):
    if isinstance(res, dict):
        item = res.get("item") or res.get("account") or res.get("telegram")
        if isinstance(item, dict):
            return str(item.get("item_id") or item.get("id") or fallback_item_id)
        for key in ("item_id", "id"):
            if res.get(key):
                return str(res.get(key))
    return str(fallback_item_id)

def normalize_lzt_phone(raw_phone, fallback_item_id):
    phone = str(raw_phone or "").strip()
    if not phone or phone.startswith("LZT_"):
        return f"Hidden-{fallback_item_id}"
    compact = phone.replace(" ", "")
    return f"+{compact.lstrip('+')}" if compact.lstrip("+").isdigit() else phone

async def try_lzt_reset_authorizations(item_id):
    # Auto-reset disabled per admin configuration
    return False

def lzt_market_price(item):
    if not isinstance(item, dict):
        return None
    raw_price = item.get("price_with_fee") or item.get("priceWithSellerFee") or item.get("price")
    try:
        price = float(raw_price)
    except (TypeError, ValueError):
        return None
    return price if price > 0 else None

def lzt_item_requires_password(item):
    if not isinstance(item, dict):
        return False
    password_keys = (
        "password", "login_password", "telegram_password", "telegram_login_password",
        "has_password", "hasPassword", "twofa", "two_fa", "2fa"
    )
    for key in password_keys:
        value = item.get(key)
        if value in (None, "", 0, "0", False, "None", "none", "no", "NO"):
            continue
        return True
    return False

def lzt_item_country_name(item, fallback=None):
    if isinstance(item, dict):
        for key in ("country", "telegram_country", "country_name", "countryName"):
            value = item.get(key)
            if value:
                value = str(value).strip()
                for name, (iso, _flag) in LZT_COUNTRIES.items():
                    if value.lower() in (name.lower(), iso.lower()):
                        return name
                matches = find_country_matches(value)
                if matches:
                    return matches[0]
        phone = item.get("phone") or item.get("telegram_phone") or item.get("login")
        if phone:
            return get_country_info(str(phone))[0]
    return fallback or "Unknown"

def lzt_updated_market_price_from_error(res):
    text = lzt_error_text(res)
    match = re.search(r"costs now\s+([0-9]+(?:\.[0-9]+)?)", text, re.IGNORECASE)
    if match:
        try:
            return float(match.group(1))
        except (TypeError, ValueError):
            return None
    return None

def lzt_error_text(res):
    if not isinstance(res, dict):
        return str(res or "")
    parts = []
    for key in ("error", "errors", "error_description", "message", "detail"):
        value = res.get(key)
        if value:
            parts.append(str(value))
    return " | ".join(parts)

def lzt_should_retry_purchase(res):
    text = lzt_error_text(res).lower()
    return "retry_request" in text or "retry request" in text

async def lzt_fast_buy_item(item_id, market_price):
    current_price = market_price
    last_res = None
    for attempt in range(1, max(1, LZT_FAST_BUY_RETRIES) + 1):
        body = {"price": current_price} if current_price is not None else None
        last_res = await lzt_request('POST', f"/{item_id}/fast-buy", params=lzt_currency_params(), data=body, return_error=True, notify_errors=False)
        if last_res and not lzt_purchase_has_error(last_res):
            return last_res

        updated_price = lzt_updated_market_price_from_error(last_res)
        if updated_price and updated_price > 0:
            current_price = updated_price
            await asyncio.sleep(0.5)
            continue

        if not lzt_should_retry_purchase(last_res):
            return last_res
        await asyncio.sleep(min(3, 0.5 + (attempt * 0.1)))
    return last_res

def country_slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

def find_country_by_slug(slug):
    normalized = slug.strip().lower().replace("_", "-")
    for name in LZT_COUNTRIES:
        if country_slug(name) == normalized:
            return name
    matches = find_country_matches(normalized.replace("-", " "))
    return matches[0] if matches else None

def get_country_button_code(name):
    special = {"India": "IND"}
    if name in special:
        return special[name]
    return LZT_COUNTRIES.get(name, ("", ""))[0] or name[:3].upper()

def country_button_label(name, price_text=None, include_phone=True):
    iso_code, flag = LZT_COUNTRIES.get(name, ("", "🌍"))
    short_name = get_country_button_code(name)
    calling = CALLING_CODES.get(name, "")
    parts = [flag, short_name]
    if include_phone and calling:
        parts.append(f"+{calling}")
    label = " ".join(parts)
    if price_text is not None:
        label = f"{label} | {price_text}"
    return label

def find_country_matches(query):
    q = query.strip().lower().replace("+", "")
    if not q:
        return []
    exact, partial = [], []
    for name, (iso, flag) in LZT_COUNTRIES.items():
        calling = CALLING_CODES.get(name, "")
        tokens = {name.lower(), iso.lower(), calling.lower()}
        if q in tokens or (q.isdigit() and calling.startswith(q)):
            exact.append(name)
        elif q in name.lower() or iso.lower().startswith(q) or (q.isdigit() and q in calling):
            partial.append(name)
    return sorted(dict.fromkeys(exact + partial))

async def render_server1_country_page(e, uid, page):
    if not resolve_lzt_token():
        if is_admin(uid):
            await bot.send_message(uid, f"{P_WARN} <b>Server 1 token missing.</b>\nPlease set token first.", buttons=[[p_btn("Set Token", "adm_setlzttoken")]])
        return await safe_answer_cb(e, "Server 1 credentials missing. Please notify admin.", alert=True)
    if not is_server1_online():
        return await safe_answer_cb(e, "Server 1 is under maintenance!", alert=True)

    limit = 20
    flt = get_user_filters(uid)
    fkey = get_filter_key(flt)
    touch_filter_key(fkey)
    stock_dict = cached_lzt_stock.get(fkey, cached_lzt_stock.get(DEFAULT_FKEY, {}))

    sorted_countries = sorted(LZT_COUNTRIES.keys())
    sort_mode = flt.get("sort", "az")
    if sort_mode == "stock_high":
        sorted_countries.sort(key=lambda n: (stock_dict.get(n, (0, 0))[0], n), reverse=True)
    elif sort_mode == "stock_low":
        sorted_countries.sort(key=lambda n: (stock_dict.get(n, (0, 0))[0], n))
    elif sort_mode == "price_low":
        sorted_countries.sort(key=lambda n: (stock_dict.get(n, (0, 0))[1] or 10**9, n))
    elif sort_mode == "price_high":
        sorted_countries.sort(key=lambda n: (stock_dict.get(n, (0, 0))[1], n), reverse=True)

    total = len(sorted_countries)
    total_pages = max(1, (total + limit - 1) // limit)
    page = min(max(1, page), total_pages)
    offset = (page - 1) * limit
    page_countries = sorted_countries[offset:offset + limit]
    total_bal = cur.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()[0]

    me = await bot.get_me()
    all_link = f"https://t.me/{me.username}?start=AllServer1"
    msg = (f"<b>Click country to view price and stock:</b>\n"
           f"––––––––––––————––•\n"
           f"✅ Total balance: {format_price(uid, total_bal)} \n"
           f"✅ Server: Server (1)\n"
           f"✅ Page {page} of {total_pages}\n"
           f'✅ View all <a href="{all_link}">countries</a>\n'
           f"➖➖➖➖➖➖➖➖➖➖")

    sort_labels = {"az": "A-Z", "stock_high": "Stock High-Low", "stock_low": "Stock Low-High", "price_low": "Price Low-High", "price_high": "Price High-Low"}
    btns, row = [[p_btn("⚙️ Filters", "lzt_toggle_filters", style="primary"), p_btn(f"↕️ {sort_labels.get(sort_mode, 'A-Z')}", "lzt_sort_menu", style="primary")]], []
    for name in page_countries:
        iso_code, flag = LZT_COUNTRIES[name]
        ccode = CALLING_CODES.get(name, "")
        count, min_p = stock_dict.get(name, (0, 0.0))
        price_part = format_price(uid, min_p) if count else "0"
        label = country_button_label(name, price_part)
        row.append(p_btn(label, f"lzt_chk|{iso_code}|1"))
        if len(row) == 2:
            btns.append(row)
            row = []
    if row:
        btns.append(row)

    page_row = []
    window_start = max(1, min(page - 2, total_pages - 4))
    window_end = min(total_pages, window_start + 4)
    for pg in range(window_start, window_end + 1):
        text = f"[{pg}]" if pg != page else f"·{pg}·"
        page_row.append(p_btn(text, f"srv_1_pg|{pg}"))
    if page_row:
        btns.append(page_row)

    btns.append([p_btn("⛶ Show All", "lzt_all_countries", style="danger"), p_btn("ᯤ Search", "lzt_search_country", style="danger")])
    btns.append([p_btn("Back", "menu_buy")])
    await safe_show_message(e, msg, buttons=btns)

def is_server1_online():
    row = cur.execute("SELECT value FROM settings WHERE key='server1_status'").fetchone()
    return row[0] == 'on' if row else True

def get_rate(key, default):
    try:
        row = cur.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return float(row[0]) if row and row[0] else float(default)
    except:
        return float(default)

def get_currency_pref(uid):
    row = cur.execute("SELECT pref_curr FROM users WHERE user_id=?", (uid,)).fetchone()
    pref = (row[0] if row and row[0] else "INR").upper()
    if pref == "USD":
        pref = "USDT"
    return pref if pref in ("INR", "USDT") else "INR"

def format_inr_amount(inr_amt):
    try:
        amount = float(inr_amt)
    except (TypeError, ValueError):
        amount = 0.0
    return f"₹{amount:.0f}" if amount.is_integer() else f"₹{amount:.2f}"

def format_usdt_amount(inr_amt, suffix=" USDT"):
    try:
        rate = get_usdt_rate()
        usdt = float(inr_amt) / rate if rate > 0 else 0.0
    except (TypeError, ValueError, ZeroDivisionError):
        usdt = 0.0
    return f"{usdt:.2f}{suffix}"

def format_compact_usdt(inr_amt):
    try:
        rate = get_usdt_rate()
        usdt = float(inr_amt) / rate if rate > 0 else 0.0
    except (TypeError, ValueError, ZeroDivisionError):
        usdt = 0.0
    formatted = f"{usdt:.2f}".rstrip("0").rstrip(".")
    if not formatted:
        formatted = "0"
    return f"{formatted} USDT"

def format_price(uid, inr_amt):
    pref = get_currency_pref(uid)
    if pref == "USDT":
        return format_compact_usdt(inr_amt)
    return format_inr_amount(inr_amt)

async def send_admin_error(error_msg: str, trace: str = ""):
    global error_cooldowns
    try:
        sig = f"{error_msg}_{trace[:100]}"
        now = time.time()
        if sig in error_cooldowns:
            if now - error_cooldowns[sig] < 600:
                return
        error_cooldowns[sig] = now

        clean_trace = trace[:1500]
        alert = (f"🚨 <b>SYSTEM EXCEPTION ENCOUNTERED</b>\n\n"
                 f"<b>Error:</b> {html.escape(error_msg)}\n"
                 f"<b>Trace:</b>\n<pre>{html.escape(clean_trace)}</pre>")
        await bot.send_message(ADMIN_ID, alert)
    except Exception as ex:
        logger.error(f"Error logging admin message: {ex}")

async def safe_answer_cb(e, text=None, alert=False):
    try:
        await e.answer(text, alert=alert)
    except QueryIdInvalidError:
        pass
    except Exception as ex:
        logger.debug(f"Redundant cb exception: {ex}")

def is_callback_event(e):
    return getattr(e, "data", None) is not None

async def safe_show_message(e, text, buttons=None, link_preview=False):
    """Edit callback messages, but respond to normal /start messages.

    Telethon new-message events also expose an edit() method for the user's
    command message; editing that incoming message raises EditMessageRequest
    errors. This helper keeps /start flows on respond() and callback flows on
    edit().
    """
    if is_callback_event(e) and hasattr(e, "edit"):
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

async def wait_lzt_rate_limit():
    """Throttle all LZT requests so one VPS/IP never exceeds market limits."""
    global _lzt_last_request_at
    wait_for = 0.0
    async with _lzt_rate_lock:
        now = time.monotonic()
        scheduled_time = max(now, _lzt_blocked_until, _lzt_last_request_at + LZT_MIN_REQUEST_INTERVAL)
        wait_for = scheduled_time - now
        _lzt_last_request_at = scheduled_time
    if wait_for > 0:
        await asyncio.sleep(wait_for)

def parse_lzt_retry_after(headers):
    if not headers:
        return None
    raw_value = None
    try:
        raw_value = headers.get("Retry-After")
    except Exception:
        raw_value = None
    if not raw_value:
        return None
    try:
        return max(0.0, float(raw_value))
    except (TypeError, ValueError):
        pass
    try:
        retry_at = datetime.strptime(str(raw_value), "%a, %d %b %Y %H:%M:%S GMT").replace(tzinfo=timezone.utc)
        return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
    except Exception:
        return None

async def apply_lzt_rate_limit_cooldown(retry_after=None):
    global _lzt_blocked_until
    wait_for = max(float(retry_after or 0), LZT_RATE_LIMIT_COOLDOWN)
    _lzt_blocked_until = max(_lzt_blocked_until, time.monotonic() + wait_for)
    logger.warning("LZT API rate limited; pausing market requests for %.1fs", wait_for)
    return wait_for

async def get_lzt_session():
    global _lzt_session
    current_loop = asyncio.get_running_loop()
    session_loop = getattr(_lzt_session, "_loop", None) if _lzt_session is not None else None
    if _lzt_session is None or _lzt_session.closed or session_loop is not current_loop:
        if _lzt_session is not None and not _lzt_session.closed:
            await close_lzt_session()
        connector_kwargs = {
            "limit": 5,
            "ttl_dns_cache": 300,
            "keepalive_timeout": 30,
            "enable_cleanup_closed": True,
        }
        if LZT_FORCE_IPV4:
            connector_kwargs["family"] = socket.AF_INET
        connector = aiohttp.TCPConnector(**connector_kwargs)
        _lzt_session = aiohttp.ClientSession(connector=connector, trust_env=True)
    return _lzt_session

async def close_lzt_session():
    global _lzt_session
    if _lzt_session is not None and not _lzt_session.closed:
        await _lzt_session.close()
    _lzt_session = None

def clean_lzt_params(params):
    if not params:
        return None
    clean_params = {}
    for key, value in params.items():
        if key is None or value is None:
            continue
        if isinstance(value, (list, tuple)):
            clean_list = [str(item) for item in value if item is not None]
            if clean_list:
                clean_params[str(key)] = clean_list
        else:
            clean_params[str(key)] = str(value)
    return clean_params or None

def lzt_masked_url(endpoint, params=None):
    query = urllib.parse.urlencode(params or {}, doseq=True)
    return f"{endpoint}?{query}" if query else endpoint

def lzt_response_summary(res):
    if not isinstance(res, dict):
        return type(res).__name__
    parts = []
    if "items" in res and isinstance(res.get("items"), list):
        parts.append(f"items={len(res.get('items') or [])}")
    for key in ("totalItems", "total", "count", "item_id", "id", "http_status"):
        if key in res:
            parts.append(f"{key}={res.get(key)}")
    if not parts and "item" in res:
        parts.append("item=yes")
    if not parts and any(k in res for k in ("error", "errors", "message")):
        parts.append("error=yes")
    return ", ".join(parts) if parts else "ok"

def lzt_sync_request(method, url, headers, params=None, data=None, timeout_total=None, return_error=False, proxy=None):
    method = str(method or "GET").upper()
    timeout_total = float(timeout_total or LZT_REQUEST_TIMEOUT)
    request_url = url
    if params:
        request_url = f"{url}?{urllib.parse.urlencode(params, doseq=True)}"
    body = None
    if method != "GET" and data is not None:
        body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(request_url, data=body, headers=headers, method=method)
    opener = None
    if proxy:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    try:
        open_call = opener.open if opener else urllib.request.urlopen
        with open_call(req, timeout=timeout_total) as response:
            text = response.read().decode("utf-8", errors="replace")
            return json.loads(text) if text else {}
    except urllib.error.HTTPError as ex:
        text = ex.read().decode("utf-8", errors="replace")
        if return_error:
            try:
                err = json.loads(text) if text else {}
            except Exception:
                err = {"error": text}
            if not isinstance(err, dict):
                err = {"error": str(err)}
            err["http_status"] = ex.code
            return err
        raise

async def lzt_fallback_request(method, url, headers, params=None, data=None, timeout_total=None, return_error=False):
    await wait_lzt_rate_limit()
    try:
        return await asyncio.to_thread(
            lzt_sync_request, method, url, headers, params, data, timeout_total, return_error, LZT_PROXY or None
        )
    except urllib.error.HTTPError as ex:
        if ex.code == 429:
            wait_for = await apply_lzt_rate_limit_cooldown(parse_lzt_retry_after(ex.headers))
            if return_error:
                return {"error": "rate limited", "http_status": 429, "retry_after": wait_for}
            return None
        raise

async def lzt_request(method, endpoint, params=None, data=None, return_error=False, timeout_total=None, max_retries=None, notify_errors=True):
    global _lzt_missing_logged
    token_resolved = resolve_lzt_token()
    if not token_resolved:
        if not _lzt_missing_logged:
            _lzt_missing_logged = True
            logger.error("LZT API request blocked: token is missing for %s %s", method, endpoint)
            try:
                await send_admin_error("LZT token missing", f"Server 1 cannot submit {method} {endpoint} because no token is configured.")
            except Exception:
                pass
        return None
    token = token_resolved.replace("Bearer ", "").strip()
    method = str(method or "GET").upper()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "TgsellBot/1.0 (+https://t.me)"
    }
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    url = f"{LZT_BASE_URL}{endpoint}"

    params = clean_lzt_params(params)

    is_stock_request = method == 'GET' and endpoint == '/telegram'
    timeout_total = timeout_total if timeout_total is not None else (LZT_STOCK_TIMEOUT if is_stock_request else LZT_REQUEST_TIMEOUT)
    max_retries = max(1, int(max_retries if max_retries is not None else (LZT_STOCK_RETRIES if is_stock_request else LZT_MAX_RETRIES)))
    timeout = aiohttp.ClientTimeout(total=float(timeout_total), connect=min(2.0, float(timeout_total)), sock_connect=min(2.0, float(timeout_total)), sock_read=float(timeout_total))
    last_detail = ""
    masked_url = lzt_masked_url(endpoint, params)
    if LZT_REQUEST_DEBUG:
        logger.info("LZT API submit: %s %s via aiohttp timeout=%ss retries=%s", method, masked_url, timeout_total, max_retries)

    try:
        session = await get_lzt_session()
        for attempt in range(1, max_retries + 1):
            try:
                request_kwargs = {"headers": headers, "params": params, "timeout": timeout}
                if LZT_PROXY:
                    request_kwargs["proxy"] = LZT_PROXY
                if method == 'POST':
                    request_kwargs["json"] = data
                    request_ctx = session.post(url, **request_kwargs)
                elif method == 'GET':
                    request_ctx = session.get(url, **request_kwargs)
                else:
                    return None

                await wait_lzt_rate_limit()
                async with request_ctx as r:
                    try:
                        text = await r.text()
                    except (aiohttp.ClientPayloadError, asyncio.TimeoutError) as ex:
                        last_detail = f"{type(ex).__name__}: {ex!r}"
                        if attempt < max_retries:
                            await asyncio.sleep(0.15 * attempt)
                            continue
                        break
                    if r.status >= 500 and attempt < max_retries:
                        await asyncio.sleep(0.25 * attempt)
                        continue
                    if r.status == 429:
                        retry_after = parse_lzt_retry_after(r.headers)
                        wait_for = await apply_lzt_rate_limit_cooldown(retry_after)
                        if LZT_REQUEST_DEBUG:
                            logger.warning("LZT API HTTP 429: %s %s retry_after=%s body=%s", method, masked_url, wait_for, text[:500])
                        if attempt < max_retries:
                            await asyncio.sleep(wait_for)
                            continue
                        if return_error:
                            try:
                                err = await r.json(content_type=None)
                            except Exception:
                                err = {"error": text or "rate limited"}
                            if not isinstance(err, dict):
                                err = {"error": str(err)}
                            err["http_status"] = r.status
                            err["retry_after"] = wait_for
                            return err
                        return None
                    if r.status >= 400:
                        if LZT_REQUEST_DEBUG:
                            logger.warning("LZT API HTTP error: %s %s status=%s body=%s", method, masked_url, r.status, text[:500])
                        if notify_errors:
                            await send_admin_error(f"Market HTTP {r.status} {method} {endpoint}", text[:2000])
                        if return_error:
                            try:
                                err = await r.json(content_type=None)
                            except Exception:
                                err = {"error": text}
                            if not isinstance(err, dict):
                                err = {"error": str(err)}
                            err["http_status"] = r.status
                            return err
                        return None
                    try:
                        parsed = await r.json(content_type=None)
                        if LZT_REQUEST_DEBUG:
                            logger.info("LZT API success: %s %s status=%s %s", method, masked_url, r.status, lzt_response_summary(parsed))
                        return parsed
                    except Exception as ex:
                        last_detail = f"{type(ex).__name__}: {ex!r}"
                        if notify_errors:
                            await send_admin_error(f"Market {method} {endpoint} JSON Parse Fail", f"{last_detail}\n\n{text[:2000]}")
                        return None
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_detail = f"{type(e).__name__}: {e!r}"
                if isinstance(e, (aiohttp.ClientConnectorError, aiohttp.ServerDisconnectedError, aiohttp.ClientOSError)):
                    await close_lzt_session()
                    session = await get_lzt_session()
                if attempt < max_retries:
                    await asyncio.sleep(0.15 * attempt)
                    continue
        detail = last_detail or f"Timeout after {timeout_total}s"
        if LZT_HTTP_FALLBACK:
            try:
                if LZT_REQUEST_DEBUG:
                    logger.info("LZT API fallback submit: %s %s via urllib timeout=%ss", method, masked_url, timeout_total)
                fallback_res = await lzt_fallback_request(method, url, headers, params=params, data=data, timeout_total=timeout_total, return_error=return_error)
                if isinstance(fallback_res, dict) and fallback_res.get("http_status") == 429:
                    await apply_lzt_rate_limit_cooldown(fallback_res.get("retry_after"))
                if LZT_REQUEST_DEBUG:
                    logger.info("LZT API fallback success: %s %s %s", method, masked_url, lzt_response_summary(fallback_res))
                return fallback_res
            except Exception as fallback_ex:
                detail = f"{detail} | fallback {type(fallback_ex).__name__}: {fallback_ex!r}"
        if LZT_REQUEST_DEBUG:
            logger.warning("LZT API failed: %s %s %s", method, masked_url, detail)
        if notify_errors:
            await send_admin_error(f"Market Client/Timeout Error: {method} {endpoint}", detail)
        if return_error:
            return {"error": detail, "exception": detail.split(':', 1)[0]}
        return None
    except Exception as e:
        detail = f"{type(e).__name__}: {e!r}"
        if LZT_HTTP_FALLBACK:
            try:
                if LZT_REQUEST_DEBUG:
                    logger.info("LZT API fallback submit after general fail: %s %s via urllib timeout=%ss", method, masked_url, timeout_total)
                fallback_res = await lzt_fallback_request(method, url, headers, params=params, data=data, timeout_total=timeout_total, return_error=return_error)
                if isinstance(fallback_res, dict) and fallback_res.get("http_status") == 429:
                    await apply_lzt_rate_limit_cooldown(fallback_res.get("retry_after"))
                if LZT_REQUEST_DEBUG:
                    logger.info("LZT API fallback success: %s %s %s", method, masked_url, lzt_response_summary(fallback_res))
                return fallback_res
            except Exception as fallback_ex:
                detail = f"{detail} | fallback {type(fallback_ex).__name__}: {fallback_ex!r}"
        if LZT_REQUEST_DEBUG:
            logger.warning("LZT API failed: %s %s %s", method, masked_url, detail)
        if notify_errors:
            await send_admin_error(f"Market Request General Fail: {method} {endpoint}", detail)
        if return_error:
            return {"error": detail, "exception": type(e).__name__}
        return None

def resolve_lzt_token():
    env_token = (LZT_TOKEN or "").strip()
    if env_token:
        return env_token
    try:
        row = cur.execute("SELECT value FROM settings WHERE key='lzt_token'").fetchone()
        if row and str(row[0]).strip():
            return str(row[0]).strip()
    except Exception:
        pass
    return ""

async def send_all_countries_list(uid):
    fkey = get_filter_key(get_user_filters(uid))
    stock_dict = cached_lzt_stock.get(fkey, cached_lzt_stock.get(DEFAULT_FKEY, {}))
    me = await bot.get_me()
    bot_username = me.username or ""

    rows = []
    for name, (iso, flag) in LZT_COUNTRIES.items():
        ccode = CALLING_CODES.get(name, "")
        if not ccode:
            continue
        count, min_p = stock_dict.get(name, (0, 0.0))
        slug = country_slug(name)
        rows.append((count, name, iso, flag, ccode, min_p, slug))

    rows.sort(key=lambda item: (-item[0], item[1]))
    lines = ["All Server 1 countries [tap a country link to open]"]
    for count, name, iso, flag, ccode, min_p, slug in rows:
        label = f"{flag} +{ccode} {get_country_button_code(name)} ({iso}) {format_price(uid, min_p)} → {count}"
        if bot_username:
            lines.append(f'<a href="https://t.me/{bot_username}?start=server1-{slug}">{html.escape(label)}</a>')
        else:
            lines.append(html.escape(label))

    chunks, current = [], []
    for line in lines:
        projected = "\n".join(current + [line])
        if len(projected) > 3500 and current:
            chunks.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        chunks.append("\n".join(current))

    for idx, chunk in enumerate(chunks, start=1):
        title = f"<b>Server 1 countries P{idx}/{len(chunks)}</b>"
        text = f"{title}\n<blockquote expandable>{chunk}</blockquote>"
        await bot.send_message(uid, text, link_preview=False)

async def render_lzt_product(e, uid, item_id, country=None):
    res = await lzt_request('GET', f"/{item_id}", params=lzt_currency_params())
    if not res or 'item' not in res:
        return await safe_show_message(e, "❌ Unable to load Server 1 product. It may be sold or unavailable.", buttons=[[p_btn("Server 1", "srv_1_pg|1")]])
    item = res['item']
    country = country or lzt_item_country_name(item, "Unknown")
    price_info = lzt_price_breakdown(item, get_lzt_markup(country))
    final_price = price_info["final_inr"]
    spam = item.get("telegram_spam_block", -1)
    premium = item.get("telegram_premium", 0)
    contacts = item.get("telegram_contacts_count", 0)
    chats = item.get("telegram_chats_count", 0)
    channels = item.get("telegram_channels_count", 0)
    conv = item.get("telegram_conversations_count", 0)
    bal = cur.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()[0]
    diff = final_price - bal
    password_required = lzt_item_requires_password(item)
    msg = (f"{P_STORE} <b>Confirm Server 1 Purchase</b>\n\n"
           f"{P_CASH} <b>Price:</b> {format_price(uid, final_price)}\n"
           f"{P_CARD} <b>Your Balance:</b> {format_price(uid, bal)}\n"
           f"<tg-emoji emoji-id='5778613750688911681'>🪙</tg-emoji> <b>Country:</b> {html.escape(country)}\n"
           f"<tg-emoji emoji-id='6035191085452497972'>👤</tg-emoji> <b>ID:</b> <code>{item_id}</code>\n\n"
           f" <tg-emoji emoji-id='6037175527846975726'>🎁</tg-emoji> Premium: <b>{'YES' if premium else 'NO'}</b>\n"
           f"<tg-emoji emoji-id='6037254263187443802'>💬</tg-emoji> SpamBlock: <b>{'NO' if spam == -1 else 'YES'}</b>\n"
           f" <tg-emoji emoji-id='5767388406984216738'>💬</tg-emoji> Chats: <b>{chats}</b>\n"
           f"<tg-emoji emoji-id='6039422865189638057'>📣</tg-emoji> Channels: <b>{channels}</b>\n"
           f"<tg-emoji emoji-id='6032594876506312598'>👥</tg-emoji> Contacts: <b>{contacts}</b>\n"
           f" <tg-emoji emoji-id='5776233299424843260'>🌐</tg-emoji> Conversations: <b>{conv}</b>\n\n"
           f"<tg-emoji emoji-id='5920332557466997677'>🏪</tg-emoji> <b>Mass Buy:</b> tries this ID first, then same-price IDs until one succeeds or all fail.")
    btns = []
    iso_code = LZT_COUNTRIES.get(country, ("US", "🇺🇸"))[0]
    if password_required:
        btns.append([p_btn("🔐 Password Account - Cannot Buy", "noop")])
    elif diff > 0:
        btns.append([p_btn("Need Recharge", "menu_deposit")])
    else:
        btns.append([p_btn("✅ Purchase", f"lzt_buy|{item_id}|{final_price}|{country}")])
        btns.append([p_btn("🛒 Mass Buy Same Price", f"lzt_mass_buy|{item_id}|{final_price}|{country}")])
    btns.extend([
        [p_btn("⬅ Back to Stocks", f"lzt_chk|{iso_code}|1")],
        [p_btn("Back to Menu", "menu_main")]
    ])
    return await safe_show_message(e, msg, buttons=btns)

async def get_lzt_candidate_items(country, target_final_price, preferred_item_id=None, max_pages=2):
    # Use safe default market filters and exact displayed INR price for mass-buy candidates.
    iso_code = LZT_COUNTRIES.get(country, ("US", "🇺🇸"))[0]
    seen = set()
    candidates = []

    async def add_candidate(item):
        if not isinstance(item, dict):
            return
        item_id = str(item.get('item_id') or item.get('id') or '')
        if not item_id or item_id in seen:
            return
        seen.add(item_id)
        candidates.append(item)

    if preferred_item_id:
        res = await lzt_request('GET', f"/{preferred_item_id}", params=lzt_currency_params())
        if isinstance(res, dict) and isinstance(res.get('item'), dict):
            await add_candidate(res['item'])

    params_base = {
        "country[]": iso_code,
        "nsb": 1,
        "pmin": 0.01,
        "pmax": 1000,
        "per_page": 40,
        "password": "no",
        "currency": LZT_PRICE_CURRENCY,
    }
    for page in range(1, max_pages + 1):
        params = dict(params_base, page=page)
        res = await lzt_request('GET', '/telegram', params=params, timeout_total=LZT_STOCK_TIMEOUT, max_retries=LZT_STOCK_RETRIES, notify_errors=False)
        if isinstance(res, dict) and 'items' in res and not res.get('items') and params["country[]"] != country:
            params["country[]"] = country
            res = await lzt_request('GET', '/telegram', params=params, timeout_total=LZT_STOCK_TIMEOUT, max_retries=1, notify_errors=False)
        for item in (res or {}).get('items', [])[:40]:
            if lzt_final_inr_price(item, get_lzt_markup(country)) == int(target_final_price):
                await add_candidate(item)
    return candidates

async def finish_lzt_purchase_success(uid, item_id, country, final_price):
    res = await lzt_request('GET', f"/{item_id}", params=lzt_currency_params())
    phone_num = f"LZT_{item_id}"
    if res and 'item' in res:
        item = res['item']
        phone_num = item.get('phone') or item.get('telegram_phone') or item.get('login') or f"LZT_{item_id}"
    display_phone = normalize_lzt_phone(phone_num, item_id)
    phone = f"LZT_{item_id}"
    cur.execute(
        "INSERT INTO orders (user_id, country, year, price, phone, otp, server, item_ref) VALUES (?,?,?,?,?,?,?,?)",
        (uid, country, 2024, final_price, display_phone, None, "Server 1", str(item_id))
    )
    db.commit()
    await lzt_log_purchase(uid, country, final_price, display_phone)
    await try_lzt_reset_authorizations(item_id)
    return phone, display_phone


# ======================================================================
# PHASE 3: SERVER 1 (LZT MARKET) + MARKET PANEL FILTERS
# ======================================================================
LZT_FILTER_ORDER = ["spam", "twofa", "premium", "origin", "offline", "login_mail", "dc", "gifts", "admin"]
LZT_FILTER_DEFAULTS = {"spam": "no", "twofa": "any", "premium": "any", "origin": "any", "offline": "any",
                       "login_mail": "any", "dc": "any", "gifts": "any", "admin": "any",
                       "order": "cheap", "sort": "az"}
LZT_FILTER_CYCLES = {
    "spam": ["no", "yes", "any"],
    "twofa": ["any", "no", "yes"],
    "premium": ["any", "yes", "no"],
    "origin": ["any", "self_registration", "personal", "resale", "autoreg", "stealer", "phishing"],
    "offline": ["any", "1", "7", "14", "30", "90"],
    "login_mail": ["any", "yes", "no"],
    "dc": ["any", "1", "2", "3", "4", "5"],
    "gifts": ["any", "gifts", "stars", "none"],
    "admin": ["any", "has", "clean"],
    "order": ["cheap", "expensive", "newest"],
}
LZT_ORDER_PARAM = {"cheap": "price_to_up", "expensive": "price_to_down", "newest": "pdate_to_down"}
LZT_FILTER_TITLES = {
    "spam": "🚫 Spam Block", "twofa": "🔐 2FA Password", "premium": "💎 Premium", "origin": "🌱 Origin",
    "offline": "⏳ Time Breakout", "login_mail": "📧 Mail", "dc": "🛰 Data Center", "gifts": "🎁 Gifts & Stars",
    "admin": "👑 Admin & Channels", "order": "↕️ Sort Order",
}
LZT_VALUE_LABELS = {
    "spam": {"no": "Clean only", "yes": "Spam only", "any": "Any (All)"},
    "twofa": {"any": "Any", "no": "No 2FA", "yes": "Has 2FA"},
    "premium": {"any": "Any", "yes": "Premium", "no": "Non-Premium"},
    "origin": {"any": "Any Origin", "self_registration": "Self-registered", "personal": "Personal", "resale": "Resale",
               "autoreg": "Autoreg", "stealer": "Stealer", "phishing": "Phishing"},
    "login_mail": {"any": "Any Mail", "yes": "Has Mail", "no": "No Mail"},
    "gifts": {"any": "Any", "gifts": "Has Gifts", "stars": "Has Stars", "none": "None"},
    "admin": {"any": "Any", "has": "Has Channels/Admin", "clean": "Clean"},
    "order": {"cheap": "Cheapest First", "expensive": "Price High-to-Low", "newest": "Newest"},
}
MAX_ACTIVE_FKEYS = 6
_fkey_order = []


def lzt_filter_label(key, val):
    if key == "offline":
        return "Any" if val == "any" else f"≥ {val} days"
    if key == "dc":
        return "Any DC" if val == "any" else f"DC {val}"
    return LZT_VALUE_LABELS.get(key, {}).get(val, str(val))


def lzt_filter_key(flt):
    return "|".join(str(flt.get(k, "any")) for k in LZT_FILTER_ORDER)


DEFAULT_FKEY = lzt_filter_key(LZT_FILTER_DEFAULTS)
active_filter_keys.add(DEFAULT_FKEY)


def get_filter_key(flt):
    return lzt_filter_key(flt)


def touch_filter_key(fkey):
    """Remember recently used filter combinations (bounded so the cache loop stays cheap)."""
    if fkey in _fkey_order:
        _fkey_order.remove(fkey)
    _fkey_order.append(fkey)
    active_filter_keys.add(fkey)
    while len(_fkey_order) > MAX_ACTIVE_FKEYS:
        old = _fkey_order.pop(0)
        if old != DEFAULT_FKEY:
            active_filter_keys.discard(old)
            cached_lzt_stock.pop(old, None)


def get_user_filters(uid):
    if uid not in user_filters:
        d = dict(LZT_FILTER_DEFAULTS)
        d["profile"] = "default"
        row = cur.execute("SELECT profile, filters_json FROM user_filters WHERE user_id=?", (uid,)).fetchone()
        if row and row[0] == "custom":
            try:
                d.update(json.loads(row[1] or "{}"))
                d["profile"] = "custom"
            except Exception:
                pass
        user_filters[uid] = d
    for k, v in LZT_FILTER_DEFAULTS.items():
        user_filters[uid].setdefault(k, v)
    return user_filters[uid]


def save_user_filters(uid):
    flt = get_user_filters(uid)
    if flt.get("profile") == "custom":
        payload = {k: flt[k] for k in LZT_FILTER_DEFAULTS}
        cur.execute("INSERT OR REPLACE INTO user_filters (user_id, profile, filters_json) VALUES (?,?,?)",
                    (uid, "custom", json.dumps(payload)))
    else:
        cur.execute("INSERT OR IGNORE INTO user_filters (user_id, profile, filters_json) VALUES (?, 'default', '{}')", (uid,))
        cur.execute("UPDATE user_filters SET profile='default' WHERE user_id=?", (uid,))
    db.commit()


def switch_filter_profile(uid):
    """Toggle between the Default profile and the user's saved Custom settings."""
    flt = get_user_filters(uid)
    if flt.get("profile") == "custom":
        save_user_filters(uid)  # make sure the custom set is stored before switching away
        keep = {k: flt[k] for k in LZT_FILTER_DEFAULTS}
        for k, v in LZT_FILTER_DEFAULTS.items():
            flt[k] = v
        flt["profile"] = "default"
        cur.execute("INSERT OR REPLACE INTO user_filters (user_id, profile, filters_json) VALUES (?,?,?)",
                    (uid, "default", json.dumps(keep)))
        db.commit()
        touch_filter_key(get_filter_key(flt))
        return
    else:
        row = cur.execute("SELECT filters_json FROM user_filters WHERE user_id=?", (uid,)).fetchone()
        if row and row[0] and row[0] != "{}":
            try:
                flt.update(json.loads(row[0] or "{}"))
            except Exception:
                pass
        flt["profile"] = "custom"
    save_user_filters(uid)
    touch_filter_key(get_filter_key(flt))


def as_boolish(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value not in (0, -1)
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def _pick(item, *keys):
    for k in keys:
        if k in item and item[k] is not None:
            return item[k]
    return None


def _positive(value):
    """True for a truthy flag or a number > 0."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value > 0
    return as_boolish(value)


def lzt_item_matches_filters(item, flt):
    """Client-side checks. Fields the market does not expose can't confirm a positive filter,
    so positive filters (has/yes/DC n) hide unknown listings while negative ones keep them."""
    spam_pref = flt.get("spam", "any")
    if spam_pref != "any":
        spam_value = item.get("telegram_spam_block", item.get("spam", -1))
        has_spam = str(spam_value) not in ("-1", "0", "False", "false", "None", "")
        if (spam_pref == "no" and has_spam) or (spam_pref == "yes" and not has_spam):
            return False

    prem_pref = flt.get("premium", "any")
    if prem_pref != "any":
        has_prem = as_boolish(item.get("telegram_premium", item.get("premium")))
        if (prem_pref == "yes" and not has_prem) or (prem_pref == "no" and has_prem):
            return False

    mail_pref = flt.get("login_mail", "any")
    if mail_pref != "any":
        has_mail = as_boolish(_pick(item, "login_mail", "email", "has_email", "telegram_email"))
        if (mail_pref == "yes" and not has_mail) or (mail_pref == "no" and has_mail):
            return False

    tf_pref = flt.get("twofa", "any")
    if tf_pref != "any":
        raw = _pick(item, "telegram_2fa", "twofa", "two_fa", "has_2fa", "telegram_password")
        if raw is None:
            if tf_pref == "yes":
                return False
        elif (tf_pref == "yes") != as_boolish(raw):
            return False

    dc_pref = flt.get("dc", "any")
    if dc_pref != "any":
        raw = _pick(item, "telegram_dc", "dc_id", "dc", "telegram_dc_id")
        if raw is None or str(raw) != str(dc_pref):
            return False

    g_pref = flt.get("gifts", "any")
    if g_pref != "any":
        gifts = _pick(item, "telegram_gifts", "telegram_gifts_count", "gifts")
        stars = _pick(item, "telegram_stars", "telegram_stars_balance", "stars")
        has_g, has_s = _positive(gifts), _positive(stars)
        if g_pref == "gifts" and not has_g:
            return False
        if g_pref == "stars" and not has_s:
            return False
        if g_pref == "none" and (has_g or has_s):
            return False

    a_pref = flt.get("admin", "any")
    if a_pref != "any":
        raw = _pick(item, "telegram_admin", "telegram_admin_count", "telegram_channels_admin", "admin_channels")
        if raw is None:
            if a_pref == "has":
                return False
        elif (a_pref == "has") != _positive(raw):
            return False
    return True


def filter_lzt_items(items, flt):
    return [it for it in items if lzt_item_matches_filters(it, flt)]


def lzt_search_params(flt, iso_code, page=1, per_page=40):
    params = {
        "country[]": iso_code,
        "spam": flt.get("spam") if flt.get("spam", "any") != "any" else None,
        "nsb": 1, "pmin": 0.01, "pmax": 1000,
        "page": page, "per_page": per_page,
        "password": "no",
        "currency": LZT_PRICE_CURRENCY,
        "order_by": LZT_ORDER_PARAM.get(flt.get("order", "cheap"), "price_to_up"),
    }
    if flt.get("offline", "any") != "any":
        params["daybreak"] = int(flt["offline"])
    if flt.get("premium", "any") != "any":
        params["premium"] = flt["premium"]
    if flt.get("origin", "any") != "any":
        params["origin[]"] = flt["origin"]
    return params


def lzt_item_price_key(x):
    return float(x.get('price_with_fee') or x.get('priceWithSellerFee') or x.get('price') or 99999)


async def fetch_lzt_country_data_with_filters(country_name, flt):
    """Returns (country, count, cheapest final INR price) or None on API failure."""
    iso_code = LZT_COUNTRIES.get(country_name, ("US", "🇺🇸"))[0]
    params = lzt_search_params(flt, iso_code, 1)
    res = await lzt_request('GET', '/telegram', params=params, timeout_total=LZT_STOCK_TIMEOUT,
                            max_retries=LZT_STOCK_RETRIES, notify_errors=False)
    if isinstance(res, dict) and 'items' in res and not res.get('items') and iso_code:
        params["country[]"] = country_name
        res = await lzt_request('GET', '/telegram', params=params, timeout_total=LZT_STOCK_TIMEOUT, max_retries=1, notify_errors=False)
    if not res or 'items' not in res:
        return None
    if not res.get('items'):
        return (country_name, 0, 0.0)
    matched = filter_lzt_items(res['items'], flt)
    if not matched:
        return (country_name, 0, 0.0)
    count = res.get('totalItems', len(matched)) if len(matched) == len(res['items']) else len(matched)
    cheapest = sorted(matched, key=lzt_item_price_key)[0]
    return (country_name, count, lzt_final_inr_price(cheapest, get_lzt_markup(country_name)))


async def _cache_one(sem, country_name, fkey):
    async with sem:
        try:
            flt = dict(LZT_FILTER_DEFAULTS)
            flt.update(dict(zip(LZT_FILTER_ORDER, fkey.split("|"))))
            data = await fetch_lzt_country_data_with_filters(country_name, flt)
            cached_lzt_stock.setdefault(fkey, {})
            if data is not None:
                cached_lzt_stock[fkey][country_name] = (data[1], data[2])
        except Exception:
            cached_lzt_stock.setdefault(fkey, {})


async def cache_lzt_stock_loop():
    """Background loop: refresh per-country stock/min-price for every active filter combination."""
    sem = asyncio.Semaphore(max(1, LZT_CACHE_CONCURRENCY))
    while True:
        try:
            if resolve_lzt_token() and is_server1_online():
                tasks = [_cache_one(sem, c, fk) for fk in list(active_filter_keys) for c in LZT_COUNTRIES.keys()]
                await asyncio.gather(*tasks)
        except Exception as ex:
            logger.error("Background LZT cache failed: %s", ex)
        await asyncio.sleep(max(30, LZT_CACHE_REFRESH_SECONDS))


async def lzt_log_purchase(uid, country, price, phone):
    try:
        await log_primary_purchase(uid, country, price, price, 2024, 1)
    except Exception as ex:
        logger.warning("lzt purchase log failed: %s", ex)


async def render_filter_panel(e, uid):
    flt = get_user_filters(uid)
    lines = ["⚙️ <b>Market Panel – Server 1 Filters</b>", ""]
    btns = []
    for key in ("spam", "twofa", "premium", "origin", "offline", "login_mail", "dc", "gifts", "admin", "order"):
        lab = lzt_filter_label(key, flt.get(key, "any"))
        lines.append(f"{LZT_FILTER_TITLES[key]}: <b>{lab}</b>")
        btns.append([p_btn(f"{LZT_FILTER_TITLES[key]}: {lab}", f"flt_chg|{key}")])
    prof = "Custom (Your Settings)" if flt.get("profile") == "custom" else "Default"
    lines += [f"👤 Active Profile: <b>{prof}</b>", "",
              "<i>DC, Gifts/Stars, Admin and 2FA depend on fields the market lists; unknown listings are hidden when you require them.</i>"]
    btns.append([p_btn(f"👤 Active Profile: {prof}", "flt_chg|profile")])
    btns.append([p_btn("♻️ Reset to Default", "flt_reset"), p_btn("🔄 Refresh Stock", "lzt_refresh_cache")])
    btns.append([p_btn("✅ Apply", "srv_1_pg|1"), p_btn("⬅️ Back to Countries", "srv_1_pg|1")])
    await safe_show_message(e, "\n".join(lines), buttons=btns)


async def show_buy_servers(e, uid=None):
    uid = uid or e.sender_id
    bal = cur.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
    bal = bal[0] if bal else 0
    msg = ("● <b>Buy Best Telegram Accounts:</b>\n––––––—————––––——–––•\n"
           "• Choose a server based on your need\n"
           "• Server 1 – automated global market (cheap)\n"
           "• Server 2 – our own stock (high quality, WhatsApp, other apps)\n"
           f"• Total balance = <code>{format_price(uid, bal)}</code>")
    btns = [[p_btn("🌐 Server (1)", "srv_1_pg|1", style="primary")],
            [p_btn("🏪 Server (2)", "catmenu|single", style="primary")],
            [p_btn("🔁 Number Change", "nc_menu")],
            [p_btn("📜 My Purchases", "page_purchases_1")]]
    await safe_show_message(e, msg, buttons=btns)


async def handle_lzt_search_text(e, uid, text):
    if uid not in lzt_search_state:
        return False
    lzt_search_state.pop(uid, None)
    matches = find_country_matches(text)
    if not matches:
        await e.reply(f"{P_NO} No Server 1 country found for <code>{html.escape(text[:30])}</code>.",
                      buttons=[[p_btn("Back", "srv_1_pg|1")]])
        return True
    btns = [[p_btn(country_button_label(n), f"lzt_chk|{LZT_COUNTRIES[n][0]}|1")] for n in matches[:12]]
    btns.append([p_btn("Back", "srv_1_pg|1")])
    await e.reply("🔎 <b>Matching countries:</b>", buttons=btns)
    return True


async def lzt_empty_msg(e, country, flag, iso_code, filtered):
    why = "No listings matched your active filters" if filtered else "There are currently no active listings"
    btns = ([[p_btn("⚙️ Change Filters", "lzt_toggle_filters")]] if filtered else []) + [
        [p_btn("🔄 Refresh Catalog", f"lzt_chk|{iso_code}|1")], [p_btn("Change Country", "srv_1_pg|1")]]
    await e.edit(f"❌ <b>Stock Empty!</b>\n\n{why} for <b>{country} {flag}</b> on Server 1.", buttons=btns)


async def lzt_purchase_flow(e, uid, item_id, price_hint, country, mass=False):
    """Reserve balance -> try candidates (fast-buy w/ retries) -> deliver, or refund everything."""
    if uid in active_lzt_purchases:
        return await safe_answer_cb(e, "⏳ Your previous Server 1 purchase is still processing.", alert=True)
    active_lzt_purchases[uid] = time.time()
    iso_code = LZT_COUNTRIES.get(country, ("US", "🇺🇸"))[0]
    markup = get_lzt_markup(country)
    reserved = 0
    try:
        # 1) Re-fetch the latest listing: price may have changed since the user opened it
        latest = await lzt_request('GET', f"/{item_id}", params=lzt_currency_params())
        l_item = latest.get('item') if isinstance(latest, dict) else None
        if not l_item or lzt_market_price(l_item) is None:
            return await e.edit(f"{P_WARN} <b>Unable to load the latest Server 1 price.</b>\nPlease refresh and try again.",
                                buttons=[[p_btn("Back", f"lzt_chk|{iso_code}|1")]])
        if lzt_item_requires_password(l_item):
            return await e.edit(f"{P_WARN} <b>Cannot buy this account.</b>\nIt needs a seller login password, so it was skipped before charging you.",
                                buttons=[[p_btn("Back", f"lzt_chk|{iso_code}|1")]])
        target = lzt_final_inr_price(l_item, markup)
        if not mass and target != int(float(price_hint)):
            await safe_answer_cb(e, f"Price changed to {format_price(uid, target)}. Please confirm again.", alert=True)
            return await render_lzt_product(e, uid, item_id, country)

        # 2) Reserve balance atomically
        async with get_user_lock(uid):
            cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=? AND balance >= ?", (target, uid, target))
            if cur.rowcount == 0:
                db.commit()
                return await safe_answer_cb(e, f"❌ Insufficient Balance! Need {P_INR}{target}", alert=True)
            db.commit()
            reserved = target

        await e.edit(f"{P_TIME} <b>{'Mass Buy' if mass else 'Purchasing'} from Server 1...</b>\n\nPlease wait; balance is reserved and refunded if it fails.")
        candidates = [l_item] + ([c for c in await get_lzt_candidate_items(country, target, preferred_item_id=item_id, max_pages=3)
                                  if str(c.get('item_id') or c.get('id')) != str(item_id)] if mass else [])
        tried = skipped = 0
        last_error = "No matching accounts found."
        for item in candidates:
            cid = str(item.get('item_id') or item.get('id') or '')
            if not cid:
                skipped += 1
                continue
            fresh = await lzt_request('GET', f"/{cid}", params=lzt_currency_params())
            f_item = fresh.get('item') if isinstance(fresh, dict) else item
            if not f_item or lzt_item_requires_password(f_item):
                skipped += 1
                last_error = "Skipped password-required account."
                continue
            if lzt_final_inr_price(f_item, markup) != target:
                skipped += 1
                last_error = "Skipped: price changed."
                continue
            mprice = lzt_market_price(f_item)
            if mprice is None:
                skipped += 1
                continue
            tried += 1
            buy_res = await lzt_fast_buy_item(cid, mprice)
            if buy_res and not lzt_purchase_has_error(buy_res):
                bought_id = lzt_purchase_item_id(buy_res, cid)
                phone, display_phone = await finish_lzt_purchase_success(uid, bought_id, country, target)
                reserved = 0
                msg = (f"{P_YES} <b>Account Purchased (Server 1)!</b>\n\n{P_PHONE} <b>Phone:</b> <code>{display_phone}</code>\n"
                       f"🏳️ <b>Country:</b> {country}\n🆔 <b>ID:</b> <code>{bought_id}</code>\n"
                       f"🔁 Attempts: {tried} tried, {skipped} skipped\n\n<i>Tap Get OTP whenever you need the latest login code.</i>")
                return await e.edit(msg, buttons=[
                    [p_btn("🔄 Get OTP", f"lzt_get_otp|{bought_id}", style="success"),
                     p_btn("🚪 Logout & Finish", f"lzt_done|{bought_id}", style="danger")],
                    [p_btn("⬅️ Back", f"lzt_chk|{iso_code}|1")]])
            last_error = lzt_error_text(buy_res) or "Purchase failed for this ID."
            low = str(last_error).lower()
            if "balance" in low or "средств" in low or "not enough" in low:
                break  # market wallet empty: retrying other IDs is pointless
        # 3) Everything failed -> refund
        async with get_user_lock(uid):
            cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (reserved, uid))
            db.commit()
        reserved = 0
        low = str(last_error).lower()
        if "balance" in low or "средств" in low or "not enough" in low:
            note = "Server 1 is under maintenance (market wallet low). Your balance was refunded; try Server 2."
            await send_admin_error("Server 1 market balance low", str(last_error))
        else:
            note = f"Reason: <code>{html.escape(str(last_error)[:300])}</code>\nYour balance was refunded."
        return await e.edit(f"{P_NO} <b>Purchase Failed</b>\n\nTried: {tried} | Skipped: {skipped}\n{note}",
                            buttons=[[p_btn("Try Again", f"lzt_chk|{iso_code}|1")], [p_btn("Change Country", "srv_1_pg|1")]])
    except Exception as ex:
        logger.exception("Server 1 purchase error")
        if reserved:
            async with get_user_lock(uid):
                cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (reserved, uid))
                db.commit()
        await send_admin_error("Server 1 Buy Exception", str(ex))
        try:
            await e.edit(f"{P_NO} <b>Purchase failed.</b> Balance refunded.", buttons=[[p_btn("Back", f"lzt_chk|{iso_code}|1")]])
        except Exception:
            pass
    finally:
        active_lzt_purchases.pop(uid, None)


async def phase3_callbacks(e, uid, data):
    """Server 1 + filter callbacks. Returns True when handled."""
    if data == "menu_buy":
        await show_buy_servers(e, uid)
        return True
    if data.startswith("srv_1_pg|"):
        await render_server1_country_page(e, uid, int(data.split("|")[1]))
        return True
    if data == "lzt_all_countries":
        await e.answer("Sending Server 1 country list...", alert=False)
        await send_all_countries_list(uid)
        return True
    if data == "lzt_search_country":
        lzt_search_state[uid] = True
        await e.edit("🔎 <b>Search Server 1 Country</b>\n\nSend a country now. Examples: <code>+91</code>, <code>Ind</code>, <code>US</code>",
                     buttons=[[p_btn("Back", "srv_1_pg|1")]])
        return True
    if data == "lzt_toggle_filters":
        await render_filter_panel(e, uid)
        return True
    if data == "flt_reset":
        flt = get_user_filters(uid)
        for k, v in LZT_FILTER_DEFAULTS.items():
            flt[k] = v
        flt["profile"] = "default"
        save_user_filters(uid)
        touch_filter_key(get_filter_key(flt))
        await safe_answer_cb(e, "Filters reset to default.")
        await render_filter_panel(e, uid)
        return True
    if data.startswith("flt_chg|"):
        key = data.split("|")[1]
        if key == "profile":
            switch_filter_profile(uid)
        elif key in LZT_FILTER_CYCLES:
            flt = get_user_filters(uid)
            cyc = LZT_FILTER_CYCLES[key]
            cur_v = flt.get(key, cyc[0])
            flt[key] = cyc[(cyc.index(cur_v) + 1) % len(cyc)] if cur_v in cyc else cyc[0]
            flt["profile"] = "custom"
            save_user_filters(uid)
            touch_filter_key(get_filter_key(flt))
        await render_filter_panel(e, uid)
        return True
    if data == "lzt_refresh_cache":
        await e.answer("Refreshing stock for your filters... please wait.", alert=True)
        flt = get_user_filters(uid)
        fkey = get_filter_key(flt)
        touch_filter_key(fkey)
        sem = asyncio.Semaphore(max(1, LZT_CACHE_CONCURRENCY))
        await asyncio.gather(*[_cache_one(sem, c, fkey) for c in LZT_COUNTRIES.keys()])
        await render_server1_country_page(e, uid, 1)
        return True
    if data == "lzt_sort_menu":
        cur_mode = get_user_filters(uid).get("sort", "az")
        labels = [("az", "A-Z"), ("price_low", "Price Low To High"), ("price_high", "Price High To Low"),
                  ("stock_low", "Stock Low To High"), ("stock_high", "Stock High To Low")]
        btns = [[p_btn(("✅ " if cur_mode == m else "") + l, f"lzt_sort|{m}")] for m, l in labels] + [[p_btn("Back", "srv_1_pg|1")]]
        await e.edit("↕️ <b>Choose Server 1 country sorting</b>\n\nThis only changes the country list order.", buttons=btns)
        return True
    if data.startswith("lzt_sort|"):
        mode = data.split("|", 1)[1]
        if mode not in ("az", "price_low", "price_high", "stock_low", "stock_high"):
            await safe_answer_cb(e, "Invalid sorting option.", alert=True)
            return True
        get_user_filters(uid)["sort"] = mode
        await render_server1_country_page(e, uid, 1)
        return True

    if data.startswith("lzt_chk|"):
        parts = data.split("|")
        iso_code = parts[1]
        page = int(parts[2]) if len(parts) > 2 else 1
        await e.answer("Loading catalog...", alert=False)
        country = next((k for k, v in LZT_COUNTRIES.items() if v[0] == iso_code), "United States")
        flag = LZT_COUNTRIES.get(country, ("US", "🇺🇸"))[1]
        flt = get_user_filters(uid)
        params = lzt_search_params(flt, iso_code, page)
        res = await lzt_request('GET', '/telegram', params=params, timeout_total=LZT_STOCK_TIMEOUT,
                                max_retries=LZT_STOCK_RETRIES, notify_errors=False)
        if isinstance(res, dict) and 'items' in res and not res['items'] and params["country[]"] != country:
            params["country[]"] = country
            res = await lzt_request('GET', '/telegram', params=params, timeout_total=LZT_STOCK_TIMEOUT, max_retries=1, notify_errors=False)
        if not res or 'items' not in res or not res['items']:
            await lzt_empty_msg(e, country, flag, iso_code, False)
            return True
        matched = filter_lzt_items(res['items'], flt)
        if not matched:
            await lzt_empty_msg(e, country, flag, iso_code, True)
            return True
        if flt.get("order") == "cheap":
            matched.sort(key=lzt_item_price_key)
        elif flt.get("order") == "expensive":
            matched.sort(key=lzt_item_price_key, reverse=True)
        items = matched[:40]
        total_items = res.get('totalItems', len(items)) if len(matched) == len(res['items']) else len(matched)
        total_pages = max(1, (total_items + 39) // 40)
        markup = get_lzt_markup(country)
        start_price = min(lzt_final_inr_price(i, markup) for i in items)
        summary = " | ".join(f"{LZT_FILTER_TITLES[k].split(' ', 1)[1]}: {lzt_filter_label(k, flt[k])}" for k in LZT_FILTER_ORDER if flt.get(k, "any") != "any")
        msg = (f"📦 Found: {total_items} | Page {page}/{total_pages}\n💰 Starting Price: {format_price(uid, start_price)}\n"
               f"🔽 {country} {flag} | {lzt_filter_label('order', flt.get('order', 'cheap'))}\n"
               f"{('🎯 ' + summary) if summary else ''}\n\nTap an account to view details & buy:")
        grid, row = [[p_btn("⚙️ Change Filters", "lzt_toggle_filters")]], []
        for idx, item in enumerate(items, start=1):
            fp = lzt_final_inr_price(item, markup)
            gi = (page - 1) * 40 + idx
            row.append(p_btn(f"[{country_button_label(country, include_phone=False)} #{gi}] - {format_price(uid, fp)}",
                             f"lzt_view|{int(item.get('item_id'))}|{country}|{fp}"))
            if len(row) == 2:
                grid.append(row)
                row = []
        if row:
            grid.append(row)
        nav = []
        if page > 1:
            nav.append(p_btn("⬅️ Prev Page", f"lzt_chk|{iso_code}|{page - 1}"))
        if total_items > page * 40:
            nav.append(p_btn("Next Page ➡️", f"lzt_chk|{iso_code}|{page + 1}"))
        if nav:
            grid.append(nav)
        grid.append([p_btn("Change Country", "srv_1_pg|1")])
        await e.edit(msg, buttons=grid)
        return True

    if data.startswith("lzt_view|"):
        _, item_id, country, _hint = data.split("|")
        await render_lzt_product(e, uid, item_id, country)
        return True
    if data.startswith("lzt_buy|"):
        _, item_id, price_str, country = data.split("|")
        await lzt_purchase_flow(e, uid, item_id, price_str, country, mass=False)
        return True
    if data.startswith("lzt_mass_buy|"):
        _, item_id, price_str, country = data.split("|", 3)
        await lzt_purchase_flow(e, uid, item_id, price_str, country, mass=True)
        return True

    if data.startswith("lzt_get_otp|") or data.startswith("lzt_done|"):
        item_id = data.split("|")[1]
        row = cur.execute("SELECT country, phone FROM orders WHERE user_id=? AND server='Server 1' AND item_ref=? ORDER BY id DESC LIMIT 1",
                          (uid, item_id)).fetchone()
        if not row and is_admin(uid):
            row = cur.execute("SELECT country, phone FROM orders WHERE server='Server 1' AND item_ref=? ORDER BY id DESC LIMIT 1", (item_id,)).fetchone()
        if not row:
            await safe_answer_cb(e, "❌ Order not found or not yours.", alert=True)
            return True
        country, display_phone = row
        if data.startswith("lzt_done|"):
            await try_lzt_reset_authorizations(item_id)
            await e.edit(f"✅ <b>Order Finished</b>\n\n{P_PHONE} <code>{display_phone}</code>\n"
                         "💡 <i>For maximum security: Telegram → Settings → Devices → Terminate all other sessions.</i>")
            return True
        await e.answer("Fetching OTP from Server 1...", alert=False)
        code, verified, _res = await get_verified_lzt_otp(item_id, attempts=3, delay=1.5)
        if not code:
            await e.answer("⏳ OTP not available yet. Wait and retry.", alert=True)
            return True
        cur.execute("UPDATE orders SET otp=? WHERE user_id=? AND server='Server 1' AND item_ref=?", (code, uid, item_id))
        db.commit()
        msg = (f"{P_YES} <b>Latest OTP Fetched!</b>\n\n{P_PHONE} <b>Phone:</b> <code>{display_phone}</code>\n🏳️ <b>Country:</b> {country}\n"
               f"{P_TIME} <b>OTP:</b> <code>{code}</code>\n\n{P_SHIELD} Double-check: {'Verified' if verified else 'Best latest code'}")
        try:
            await e.edit(msg, buttons=[[p_btn("🔄 Read Again / Get OTP", f"lzt_get_otp|{item_id}", style="success"),
                                        p_btn("🚪 Logout & Finish", f"lzt_done|{item_id}", style="danger")]])
        except MessageNotModifiedError:
            pass
        return True
    return False


async def phase3_admin(event, action_data, uid, chat):
    """Admin: Server 1 token / markups / toggle / rates. Returns True if handled."""
    if not (action_data.startswith(("lzt", "cmark")) and has_perm(uid, "p_settings")):
        return False
    if action_data == "lztset":
        on = is_server1_online()
        tok = "✅ set" if resolve_lzt_token() else "❌ missing"
        gm = cur.execute("SELECT value FROM settings WHERE key='lzt_global_markup'").fetchone()
        btns = [[Button.inline(f"🔑 LZT Token ({tok})", "adm_lzt_token")],
                [Button.inline(f"📈 Global Markup ({gm[0] if gm else 20}%)", "adm_lzt_gmarkup"), Button.inline("🌍 Country Markups", "adm_cmarkpg|1")],
                [Button.inline(f"Server 1: {'🟢 ON' if on else '🔴 OFF'}", "adm_lzt_toggle"), Button.inline("💱 RUB→INR Rate", "adm_lzt_rate")],
                [Button.inline("🧹 Clear Stock Cache", "adm_lzt_clear")],
                [Button.inline("Back", "adm_adminmain")]]
        await event.edit(f"{PE_CROWN} <b>Server 1 (LZT) Settings</b>", buttons=btns)
        return True
    if action_data == "lzt_toggle":
        cur.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('server1_status', ?)", ("off" if is_server1_online() else "on",))
        db.commit()
        return await phase3_admin(event, "lztset", uid, chat)
    if action_data == "lzt_clear":
        cached_lzt_stock.clear()
        await event.answer("Cache cleared. It refills within a few minutes.", alert=True)
        return True
    if action_data.startswith("cmarkpg|"):
        buttons, pg, tp = build_country_markup_buttons(int(action_data.split("|")[1]))
        await event.edit(f"🌍 <b>Per-country markup</b> (page {pg}/{tp})\nTap a country to change its %.", buttons=buttons)
        return True
    if action_data in ("lzt_token", "lzt_gmarkup", "lzt_rate") or action_data.startswith("cmark|"):
        async with bot.conversation(chat, timeout=300) as conv:
            async def ask(t):
                await conv.send_message(t + "\n\n<i>(/cancel to abort)</i>")
                r = await conv.get_response()
                if r.raw_text == "/cancel":
                    raise AdminCancelled()
                return r.raw_text.strip()
            try:
                if action_data == "lzt_token":
                    tok = await ask("🔑 Send the LZT Market API token:")
                    cur.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('lzt_token',?)", (tok,))
                    db.commit()
                    await conv.send_message(f"{P_YES} Token saved. (A LZT_TOKEN in .env overrides this.)")
                elif action_data == "lzt_gmarkup":
                    pct = int(await ask("📈 Global markup % for Server 1 (e.g. 20)"))
                    cur.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('lzt_global_markup',?)", (str(pct),))
                    db.commit()
                    await conv.send_message(f"{P_YES} Global markup = {pct}%.")
                elif action_data == "lzt_rate":
                    r = float(await ask("💱 How many ₹ is 1 RUB? (e.g. 1.05)"))
                    cur.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('rub_inr_rate',?)", (str(r),))
                    db.commit()
                    await conv.send_message(f"{P_YES} RUB→INR = {r}.")
                else:
                    iso = action_data.split("|")[1]
                    pct = int(await ask(f"📈 Markup % for <b>{iso}</b> (send -1 to remove override)"))
                    if pct < 0:
                        cur.execute("DELETE FROM lzt_settings WHERE LOWER(country)=LOWER(?)", (iso,))
                    else:
                        cur.execute("INSERT OR REPLACE INTO lzt_settings (country, markup_percent) VALUES (?,?)", (iso, pct))
                    db.commit()
                    cached_lzt_stock.clear()
                    await conv.send_message(f"{P_YES} Saved.")
            except AdminCancelled:
                await conv.send_message(f"{P_NO} Cancelled.")
            except (ValueError, TypeError):
                await conv.send_message(f"{P_NO} Invalid number. Cancelled.")
        return True
    return False



# ======================================================================
# PHASE 4: SERVER 2 IMPORTS (string / hex / .session), WHATSAPP + ALL APP ACC,
#          WHATSAPP SELL REVIEW, NUMBER CHANGE
# ======================================================================
nc_state = {}        # uid -> number-change conversation
wa_sell_state = {}   # uid -> WhatsApp sell submission conversation
DC_IPS = {1: "149.154.175.53", 2: "149.154.167.51", 3: "149.154.175.100", 4: "149.154.167.91", 5: "91.108.56.130"}


def hex_to_string_session(auth_hex, dc_id=2):
    """Build a Telethon StringSession from a raw 256-byte auth key (hex) + DC id."""
    dc_id = int(dc_id or 2)
    key_bytes = bytes.fromhex(str(auth_hex or "").strip()[:512])
    if len(key_bytes) != 256:
        raise ValueError("Auth key must be exactly 512 hex characters (256 bytes).")
    data = struct.pack(">B4sH256s", dc_id, socket.inet_aton(DC_IPS.get(dc_id, DC_IPS[2])), 443, key_bytes)
    return StringSession("1" + base64.urlsafe_b64encode(data).decode("ascii"))


def persist_string_session(sess, phone):
    """Write a StringSession's auth key into sessions/<phone>.session, the format the rest of the bot uses."""
    os.makedirs("sessions", exist_ok=True)
    delete_session_files(f"sessions/{phone}")
    fc = TelegramClient(f"sessions/{phone}", API_ID, API_HASH)
    fc.session.set_dc(sess.dc_id, sess.server_address, sess.port)
    fc.session.auth_key = sess.auth_key
    fc.session.save()
    fc.session.close()


class ConvCancelled(Exception):
    pass


async def conv_ask(conv, text, want_msg=False):
    await conv.send_message(text + "\n\n<i>(/cancel to abort)</i>")
    r = await conv.get_response()
    if (r.raw_text or "").strip() == "/cancel":
        raise ConvCancelled()
    return r if want_msg else (r.raw_text or "").strip()


async def resolve_stock_price(conv, c_name, category, year):
    row = cur.execute("SELECT price FROM auto_prices WHERE country=? AND year=? AND category=?", (c_name, str(year), category)).fetchone()
    if not row:
        row = cur.execute("SELECT price FROM auto_prices WHERE country=? AND year='Common' AND category=?", (c_name, category)).fetchone()
    if row:
        await conv.send_message(f"⚡ Auto-price applied: {P_INR}{row[0]}")
        return int(row[0])
    existing = find_existing_price(c_name, category, year)
    if existing is not None:
        await conv.send_message(f"⚡ Auto-detected price: {P_INR}{existing}")
        return int(existing)
    return int(await conv_ask(conv, f"{P_MONEY} Price (₹):"))


async def import_session_to_stock(conv, session_obj, category):
    """Shared pipeline for string / hex imports: validate -> detect country/year -> 2FA -> price -> stock."""
    api_id, api_hash = get_random_api_credentials()
    client = TelegramClient(session_obj, int(api_id), api_hash)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            return await conv.send_message(f"{P_NO} Session is not authorized (logged out or invalid).")
        me = await client.get_me()
        phone = re.sub(r"\D", "", str(getattr(me, "phone", "") or ""))
        if not phone:
            return await conv.send_message(f"{P_NO} Could not read the phone number from this session.")
        if cur.execute("SELECT 1 FROM stock WHERE phone=?", (phone,)).fetchone():
            return await conv.send_message(f"{P_NO} +{phone} is already in stock.")
        c_name, c_icon = get_country_info(phone)
        if c_name == "Unknown":
            c_icon = await conv_ask(conv, f"{P_FLAG} Country not recognised. Send flag emoji:")
            c_name = await conv_ask(conv, f"{P_GLOBE} Country name:")
        year = await detect_account_year(client)
        pwd = await client(GetPasswordRequest())
        twofa = "None"
        if getattr(pwd, "has_password", False):
            raw = await conv_ask(conv, f"{P_2FA} This account has 2FA. Send the current password:")
            twofa = raw
            ok, err = await force_2fa_2007(client, raw)
            if ok:
                twofa = NEW_2FA
                await conv.send_message(f"{P_2FA} 2FA changed to {NEW_2FA}.")
            else:
                await conv.send_message(f"{P_WARN} Could not change 2FA ({html.escape(str(err))}); storing the old password.")
        year = int(await conv_ask(conv, f"{P_CAL} Detected year: <b>{year}</b>. Reply with the year to confirm/change:"))
        price = await resolve_stock_price(conv, c_name, category, year)
        persist_string_session(client.session, phone)
        cur.execute("INSERT OR REPLACE INTO stock (phone, session_file, country_name, country_icon, account_year, category, price, available, twofa) VALUES (?,?,?,?,?,?,?,?,?)",
                    (phone, f"sessions/{phone}.session", c_name, c_icon, year, category, price, 1, twofa))
        db.commit()
        await conv.send_message(f"{P_YES} <b>Added!</b> +{phone} | {c_icon} {c_name} | {year} | {P_INR}{price} | {cat_label(category)}")
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


async def admin_add_session_file(e, uid):
    """Admin sends a .session file in chat -> validate and add to Server 2 stock (category Spam Free)."""
    os.makedirs("sessions", exist_ok=True)
    tmp = await bot.download_media(e.message, f"upload_{uid}_{int(time.time())}_{random.randint(1000, 9999)}.session")
    if not tmp:
        return await e.reply(f"{P_NO} Could not download the file.")
    base = tmp[:-8] if tmp.endswith(".session") else tmp
    client = None
    try:
        api_id, api_hash = get_random_api_credentials()
        client = TelegramClient(base, int(api_id), api_hash)
        await client.connect()
        if not await client.is_user_authorized():
            return await e.reply(f"{P_NO} Session is not authorized, not added.")
        me = await client.get_me()
        phone = re.sub(r"\D", "", str(getattr(me, "phone", "") or ""))
        if not phone:
            return await e.reply(f"{P_NO} Could not detect the phone number.")
        if cur.execute("SELECT 1 FROM stock WHERE phone=?", (phone,)).fetchone():
            return await e.reply(f"{P_NO} +{phone} is already in stock.")
        c_name, c_icon = get_country_info(phone)
        year = await detect_account_year(client)
        pwd = await client(GetPasswordRequest())
        twofa = "Unknown" if getattr(pwd, "has_password", False) else "None"
        row = cur.execute("SELECT price FROM auto_prices WHERE country=? AND year=? AND category='spam_free'", (c_name, str(year))).fetchone() \
            or cur.execute("SELECT price FROM auto_prices WHERE country=? AND year='Common' AND category='spam_free'", (c_name,)).fetchone()
        price = int(row[0]) if row else (find_existing_price(c_name, "spam_free", year) or 0)
        if price <= 0:
            return await e.reply(f"{P_WARN} No auto/existing price for {c_name} {year}. Set an auto price first or use Add Single Acc.")
        await client.disconnect()
        client = None
        perm = f"sessions/{phone}"
        for ext in (".session", ".session-wal", ".session-shm", ".session-journal"):
            if os.path.exists(base + ext):
                shutil.move(base + ext, perm + ext)
        cur.execute("INSERT OR REPLACE INTO stock (phone, session_file, country_name, country_icon, account_year, category, price, available, twofa) VALUES (?,?,?,?,?,?,?,?,?)",
                    (phone, perm + ".session", c_name, c_icon, year, "spam_free", price, 1, twofa))
        db.commit()
        await e.reply(f"{P_YES} <b>Session added!</b>\n+{phone} | {c_icon} {c_name} | {year} | {P_INR}{price}\n<i>Use Manage Stock to move it to another category.</i>")
    except Exception as ex:
        await send_admin_error("Session file upload failed", str(ex))
        await e.reply(f"{P_NO} Session check failed; file not added.")
    finally:
        try:
            if client:
                await client.disconnect()
        except Exception:
            pass
        delete_session_files(base)


# ---------------- MANUAL DELIVERY STOCK (WhatsApp / All App Acc) ----------------
def new_item_key(prefix="APP"):
    return f"{prefix}{int(time.time() * 1000)}{random.randint(100, 999)}"


async def admin_add_manual_items(conv, category, bulk):
    wa = category == "whatsapp"
    if not bulk:
        if wa:
            ident = re.sub(r"\D", "", await conv_ask(conv, f"{P_PHONE} WhatsApp number (with country code):"))
            c_name, c_icon = get_country_info(ident)
            if c_name == "Unknown":
                c_icon = await conv_ask(conv, f"{P_FLAG} Flag emoji:")
                c_name = await conv_ask(conv, f"{P_GLOBE} Country name:")
        else:
            c_name = await conv_ask(conv, "📱 App / service name (e.g. Instagram):")
            c_icon = await conv_ask(conv, "🎨 Icon emoji for this app:")
            ident = await conv_ask(conv, "🆔 Unique ID/username/email (send <code>-</code> to auto-generate):")
            if ident == "-":
                ident = new_item_key()
        year = int(await conv_ask(conv, f"{P_CAL} Account year (e.g. 2023):"))
        details = await conv_ask(conv, "🔐 Delivery details the buyer will receive (login, password, notes):")
        price = await resolve_stock_price(conv, c_name, category, year)
        if cur.execute("SELECT 1 FROM stock WHERE phone=?", (ident,)).fetchone():
            return await conv.send_message(f"{P_NO} This ID is already in stock.")
        cur.execute("INSERT INTO stock (phone, session_file, country_name, country_icon, account_year, category, price, available, twofa, app_name, delivery_data) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (ident, "", c_name, c_icon, year, category, price, 1, "None", "" if wa else c_name, details))
        db.commit()
        return await conv.send_message(f"{P_YES} Added to {cat_label(category)}: {c_icon} {c_name} | {year} | {P_INR}{price}")

    # bulk: shared settings once, then one account per line "identifier | details"
    if not wa:
        c_name = await conv_ask(conv, "📱 App / service name for ALL lines:")
        c_icon = await conv_ask(conv, "🎨 Icon emoji:")
    year = int(await conv_ask(conv, f"{P_CAL} Year for ALL lines:"))
    price = int(await conv_ask(conv, f"{P_MONEY} Price (₹) for ALL lines:"))
    r = await conv_ask(conv, "📄 Send lines as <code>identifier | details</code> (one account per line) — as a message or a .txt file.\nFor All App Acc, identifier can be <code>-</code> to auto-generate.", want_msg=True)
    if r.file:
        raw = (await r.download_media(bytes)).decode("utf-8", "ignore")
    else:
        raw = r.raw_text or ""
    added = skipped = 0
    for line in raw.splitlines():
        if "|" not in line:
            continue
        ident, details = [x.strip() for x in line.split("|", 1)]
        if wa:
            ident = re.sub(r"\D", "", ident)
            if len(ident) < 7:
                skipped += 1
                continue
            cn, ci = get_country_info(ident)
            if cn == "Unknown":
                skipped += 1
                continue
        else:
            cn, ci = c_name, c_icon
            if ident in ("-", ""):
                ident = new_item_key()
        if cur.execute("SELECT 1 FROM stock WHERE phone=?", (ident,)).fetchone():
            skipped += 1
            continue
        cur.execute("INSERT INTO stock (phone, session_file, country_name, country_icon, account_year, category, price, available, twofa, app_name, delivery_data) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (ident, "", cn, ci, year, category, price, 1, "None", "" if wa else cn, details))
        added += 1
    db.commit()
    await conv.send_message(f"{P_YES} Bulk add done: {added} added, {skipped} skipped (duplicates / bad lines / unknown country).")


async def process_manual_purchase(event, category, h, year_str, price_str):
    """Instant text delivery for WhatsApp / All App Acc stock (no Telegram session involved)."""
    country = resolve_country(category, h)
    if not country:
        return await event.answer("❌ Stock changed, please go back and reselect.", alert=True)
    uid, base = event.sender_id, int(price_str)
    final = user_final_price(uid, base)
    async with get_user_lock(uid):
        row = cur.execute("SELECT phone, country_icon, account_year, delivery_data FROM stock WHERE available=1 AND category=? AND country_name=? AND account_year=? AND price=? LIMIT 1",
                          (category, country, year_str, base)).fetchone()
        if not row:
            return await event.answer("❌ Sold out! Another user just bought this.", alert=True)
        ident, icon, year, details = row
        cur.execute("UPDATE stock SET available=0 WHERE phone=? AND available=1", (ident,))
        if cur.rowcount == 0:
            db.commit()
            return await event.answer("❌ Sold out! Another user just bought this.", alert=True)
        cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=? AND balance >= ?", (final, uid, final))
        if cur.rowcount == 0:
            cur.execute("UPDATE stock SET available=1 WHERE phone=?", (ident,))
            db.commit()
            return await event.answer(f"❌ Insufficient Balance! Need ₹{final}", alert=True)
        label = "WhatsApp" if category == "whatsapp" else "All App Acc"
        cur.execute("INSERT INTO orders (user_id, country, year, price, phone, otp, server) VALUES (?,?,?,?,?,?,?)",
                    (uid, country, year, final, ident, None, label))
        db.commit()
    msg = (f"{P_YES} <b>{label} Purchased!</b>\n\n"
           f"{icon} <b>{'Country' if category == 'whatsapp' else 'App'}:</b> {html.escape(country)}\n"
           f"🆔 <b>ID:</b> <code>{html.escape(str(ident))}</code>\n{P_CAL} <b>Year:</b> {year}\n\n"
           f"🔐 <b>Delivery details:</b>\n<code>{html.escape(details or 'Contact support for details.')}</code>\n\n"
           f"<i>Order saved in 📜 Order History. Contact support if anything is wrong.</i>")
    await event.edit(msg, buttons=[[Button.inline("📜 Order History", "page_purchases_1")]])
    try:
        await log_primary_purchase(uid, country, final, final, year, 1)
    except Exception as ex:
        logger.warning("manual purchase log failed: %s", ex)


# ---------------- WHATSAPP SELL (admin review) ----------------
async def wa_sell_start(e, uid):
    if not is_sell_on():
        return await safe_answer_cb(e, "Selling is disabled by admin.", alert=True)
    wa_sell_state[uid] = {"step": "phone"}
    await bot.send_message(uid, "🟩 <b>Sell WhatsApp Account</b>\n\nSend the WhatsApp number (with country code, digits only):",
                           buttons=[[Button.inline("❌ Cancel", "cancel_action")]])
    await safe_answer_cb(e)


async def handle_wa_sell_text(e, uid, text):
    st = wa_sell_state.get(uid)
    if not st:
        return False
    if st["step"] == "phone":
        phone = re.sub(r"\D", "", text)
        if len(phone) < 7:
            await e.reply(f"{P_NO} Invalid number. Send digits with country code.")
            return True
        if cur.execute("SELECT 1 FROM blacklisted_phones WHERE phone=?", (phone,)).fetchone() or \
           cur.execute("SELECT 1 FROM stock WHERE phone=?", (phone,)).fetchone() or \
           cur.execute("SELECT 1 FROM manual_sell_requests WHERE phone=? AND status='pending'", (phone,)).fetchone():
            wa_sell_state.pop(uid, None)
            await e.reply(f"{P_NO} This number is blacklisted, already listed, or already under review.")
            return True
        st.update(step="details", phone=phone)
        await e.reply("📝 Send the account details/proof for the admin (login method, how to receive the code, year, any notes):")
        return True
    if st["step"] == "details":
        wa_sell_state.pop(uid, None)
        cur.execute("INSERT INTO manual_sell_requests (user_id, kind, phone, details) VALUES (?,?,?,?)", (uid, "whatsapp", st["phone"], text[:1500]))
        rid = cur.lastrowid
        db.commit()
        await e.reply(f"{P_YES} <b>Submitted!</b> An admin will review request #{rid} and you'll be notified.")
        adm = (f"🟩 <b>WHATSAPP SELL REQUEST #{rid}</b>\n\n👤 User: <code>{uid}</code>\n📞 Number: <code>{st['phone']}</code>\n"
               f"📝 Details:\n<code>{html.escape(text[:1500])}</code>")
        btns = [[Button.inline("✅ Approve", f"msr_act|app|{rid}"), Button.inline("❌ Reject", f"msr_act|rej|{rid}")]]
        for ch in {ADMIN_ID, LOG_CHANNEL_ID}:
            if ch:
                try:
                    await bot.send_message(ch, adm, buttons=btns)
                except Exception as ex:
                    logger.warning("msr notify %s failed: %s", ch, ex)
        return True
    return False


async def msr_decide(e, uid, action, rid):
    row = cur.execute("SELECT user_id, phone, details, status FROM manual_sell_requests WHERE id=?", (rid,)).fetchone()
    if not row or row[3] != "pending":
        return await safe_answer_cb(e, "⚠️ Already processed.", alert=True)
    t_uid, phone, details, _ = row
    if action == "rej":
        cur.execute("UPDATE manual_sell_requests SET status='rejected' WHERE id=? AND status='pending'", (rid,))
        if cur.rowcount:
            db.commit()
            try:
                await bot.send_message(t_uid, f"❌ Your WhatsApp sell request #{rid} (+{phone}) was rejected.")
            except Exception:
                pass
        return await e.edit(f"❌ Rejected WhatsApp sell request #{rid}.")
    async with bot.conversation(e.chat_id, timeout=300) as conv:
        try:
            pay = int(await conv_ask(conv, f"💰 Amount (₹) to pay the seller for +{phone} (they receive {100 - SELL_ADMIN_FEE_PCT}%):"))
            list_price = int(await conv_ask(conv, "🏷 Listing price (₹) for buyers:"))
            year = int(await conv_ask(conv, f"{P_CAL} Account year:"))
        except (ConvCancelled, ValueError, asyncio.TimeoutError):
            return await conv.send_message(f"{P_NO} Cancelled. Request is still pending.")
        c_name, c_icon = get_country_info(phone)
        if c_name == "Unknown":
            c_icon, c_name = "🌍", "Unknown"
        payout = pay - int(pay * SELL_ADMIN_FEE_PCT / 100)
        async with get_user_lock(t_uid):
            cur.execute("UPDATE manual_sell_requests SET status='approved' WHERE id=? AND status='pending'", (rid,))
            if cur.rowcount == 0:
                db.commit()
                return await conv.send_message("⚠️ Already processed.")
            cur.execute("INSERT OR REPLACE INTO stock (phone, session_file, country_name, country_icon, account_year, category, price, available, twofa, seller_id, delivery_data) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (phone, "", c_name, c_icon, year, "whatsapp", list_price, 1, "None", t_uid, details))
            cur.execute("UPDATE users SET sales_balance = COALESCE(sales_balance,0) + ? WHERE user_id=?", (payout, t_uid))
            db.commit()
        await conv.send_message(f"{P_YES} Approved #{rid}. Listed at {P_INR}{list_price}; seller credited {P_INR}{payout}.")
        try:
            await bot.send_message(t_uid, f"{P_YES} Your WhatsApp account +{phone} was accepted! {P_INR}{payout} added to your Sales Balance.")
        except Exception:
            pass


# ---------------- NUMBER CHANGE ----------------
def nc_enabled():
    r = cur.execute("SELECT value FROM settings WHERE key='nc_status'").fetchone()
    return (r[0] if r and r[0] else "on") == "on"


def nc_fee():
    r = cur.execute("SELECT value FROM settings WHERE key='nc_fee'").fetchone()
    try:
        return int(float(r[0])) if r and r[0] else 50
    except (TypeError, ValueError):
        return 50


async def nc_log(text):
    for ch in {LOG_CHANNEL_ID, LOOG_CHANNEL_ID}:
        if ch:
            try:
                await bot.send_message(ch, text)
            except Exception:
                pass


async def nc_refund(uid, req_id, status):
    """Refund the held fee once and mark the request."""
    async with get_user_lock(uid):
        cur.execute("UPDATE number_change_requests SET status=? WHERE id=? AND status IN ('processing','pending')", (status, req_id))
        if cur.rowcount:
            fee = cur.execute("SELECT fee FROM number_change_requests WHERE id=?", (req_id,)).fetchone()[0]
            cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (fee, uid))
        db.commit()


async def nc_cleanup(uid):
    st = nc_state.pop(uid, None)
    if not st:
        return
    if st.get("own_client") and st.get("client"):
        try:
            await st["client"].disconnect()
        except Exception:
            pass
    if st.get("req_id") and st.get("step") in ("code",):
        await nc_refund(uid, st["req_id"], "cancelled")


async def show_number_change_menu(e, uid):
    on = nc_enabled()
    msg = (f"🔁 <b>Number Change Service</b>\n\nMove an account to a new phone number.\n"
           f"💰 Fee: <b>{P_INR}{nc_fee()}</b> (refunded automatically if it fails)\n"
           f"Status: {'🟢 Available' if on else '🔴 Disabled'}\n\n"
           "• Accounts you bought here and still hold in the bot are changed <b>automatically</b>.\n"
           "• Any other account is handled by an <b>admin</b> (you'll be notified).")
    await safe_show_message(e, msg, buttons=[[p_btn("➕ Request Number Change", "nc_start")], [p_btn("📋 My Requests", "nc_list")],
                                              [p_btn("Back", "menu_buy")]])


async def phase4_callbacks(e, uid, data):
    if data == "cancel_action":
        await nc_cleanup(uid)
        wa_sell_state.pop(uid, None)
        return False
    if data == "wa_sell":
        await wa_sell_start(e, uid)
        return True
    if data.startswith("msr_act|") and has_perm(uid, "p_bal"):
        _, action, rid = data.split("|")
        await msr_decide(e, uid, action, int(rid))
        return True
    if data == "nc_menu":
        await show_number_change_menu(e, uid)
        return True
    if data == "nc_list":
        rows = cur.execute("SELECT id, old_phone, new_phone, fee, status, date FROM number_change_requests WHERE user_id=? ORDER BY id DESC LIMIT 10", (uid,)).fetchall()
        txt = "📋 <b>Your Number Change Requests</b>\n\n" + ("\n".join(f"#{i} | {o} → {n} | {P_INR}{f} | <b>{s}</b>" for i, o, n, f, s, d in rows) or "No requests yet.")
        await safe_show_message(e, txt, buttons=[[p_btn("Back", "nc_menu")]])
        return True
    if data == "nc_start":
        if not nc_enabled():
            await safe_answer_cb(e, "Number Change is currently disabled.", alert=True)
            return True
        bal = cur.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()[0]
        if bal < nc_fee():
            await safe_answer_cb(e, f"❌ Insufficient balance. Fee is {P_INR}{nc_fee()}.", alert=True)
            return True
        rows = cur.execute("SELECT DISTINCT phone FROM orders WHERE user_id=? AND (server IS NULL OR server='Server 2') ORDER BY id DESC LIMIT 10", (uid,)).fetchall()
        live = [r[0] for r in rows if os.path.exists(f"sessions/{r[0]}.session")]
        btns = [[p_btn(f"📞 +{ph}", f"nc_pick|{ph}")] for ph in live]
        btns.append([p_btn("🧑‍💼 Another account (admin handles)", "nc_manual")])
        btns.append([p_btn("Back", "nc_menu")])
        await safe_show_message(e, "Choose the account whose number you want to change:", buttons=btns)
        return True
    if data.startswith("nc_pick|"):
        phone = data.split("|")[1]
        if not cur.execute("SELECT 1 FROM orders WHERE user_id=? AND phone=?", (uid, phone)).fetchone() or not os.path.exists(f"sessions/{phone}.session"):
            await safe_answer_cb(e, "❌ This account is not available for automatic change.", alert=True)
            return True
        nc_state[uid] = {"step": "new", "old": phone}
        await safe_show_message(e, f"📞 Account: <code>+{phone}</code>\n\nSend the <b>NEW</b> phone number (digits with country code). "
                                   "You must be able to receive an SMS/call on it.", buttons=[[p_btn("❌ Cancel", "cancel_action")]])
        return True
    if data == "nc_manual":
        nc_state[uid] = {"step": "m_old"}
        await safe_show_message(e, "Send the <b>CURRENT</b> number of the account (digits with country code):", buttons=[[p_btn("❌ Cancel", "cancel_action")]])
        return True
    if data.startswith("nc_act|") and has_perm(uid, "p_manage_stock"):
        _, action, rid = data.split("|")
        rid = int(rid)
        row = cur.execute("SELECT user_id, old_phone, new_phone, status FROM number_change_requests WHERE id=?", (rid,)).fetchone()
        if not row or row[3] != "pending":
            await safe_answer_cb(e, "⚠️ Already processed.", alert=True)
            return True
        t_uid, old, new, _ = row
        if action == "app":
            cur.execute("UPDATE number_change_requests SET status='done' WHERE id=? AND status='pending'", (rid,))
            db.commit()
            await e.edit(f"✅ Number change #{rid} marked DONE ({old} → {new}).")
            try:
                await bot.send_message(t_uid, f"{P_YES} Your number change #{rid} ({old} → {new}) is complete.")
            except Exception:
                pass
            await nc_log(f"🔁 <b>Number change #{rid} DONE</b> (admin) user <code>{t_uid}</code> {old} → {new}")
        else:
            await nc_refund(t_uid, rid, "rejected")
            await e.edit(f"❌ Number change #{rid} rejected; fee refunded.")
            try:
                await bot.send_message(t_uid, f"❌ Your number change #{rid} was rejected. The fee was refunded.")
            except Exception:
                pass
        return True
    return False


async def handle_phase4_text(e, uid, text):
    if await handle_wa_sell_text(e, uid, text):
        return True
    st = nc_state.get(uid)
    if not st:
        return False
    step = st["step"]
    if step in ("m_old", "new", "m_new"):
        num = re.sub(r"\D", "", text)
        if not 7 <= len(num) <= 15:
            await e.reply(f"{P_NO} Invalid number. Send 7–15 digits with country code.")
            return True
        if step == "m_old":
            st.update(step="m_new", old=num)
            await e.reply("Now send the <b>NEW</b> number:")
            return True
        if num == st["old"]:
            await e.reply(f"{P_NO} New number must differ from the current one.")
            return True
        fee = nc_fee()
        async with get_user_lock(uid):
            cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=? AND balance >= ?", (fee, uid, fee))
            if cur.rowcount == 0:
                db.commit()
                nc_state.pop(uid, None)
                await e.reply(f"{P_NO} Insufficient balance. Fee is {P_INR}{fee}.")
                return True
            cur.execute("INSERT INTO number_change_requests (user_id, old_phone, new_phone, fee, status) VALUES (?,?,?,?,?)",
                        (uid, st["old"], num, fee, "pending" if step == "m_new" else "processing"))
            req_id = cur.lastrowid
            db.commit()
        if step == "m_new":  # admin-handled
            nc_state.pop(uid, None)
            await e.reply(f"{P_YES} Request #{req_id} submitted. Fee {P_INR}{fee} is held; you'll be notified.")
            adm = f"🔁 <b>NUMBER CHANGE REQUEST #{req_id}</b>\n\n👤 User: <code>{uid}</code>\n📞 {st['old']} → {num}\n💰 Fee held: {P_INR}{fee}"
            btns = [[Button.inline("✅ Done", f"nc_act|app|{req_id}"), Button.inline("❌ Reject & Refund", f"nc_act|rej|{req_id}")]]
            for ch in {ADMIN_ID, LOG_CHANNEL_ID}:
                if ch:
                    try:
                        await bot.send_message(ch, adm, buttons=btns)
                    except Exception as ex:
                        logger.warning("nc notify %s failed: %s", ch, ex)
            return True
        # automatic path
        old = st["old"]
        own = False
        try:
            client = (active_orders.get(old) or {}).get("client")
            if not client or not client.is_connected():
                client = TelegramClient(f"sessions/{old}", API_ID, API_HASH)
                await client.connect()
                own = True
            if not await client.is_user_authorized():
                raise RuntimeError("session no longer authorized")
            sent = await client(SendChangePhoneCodeRequest(phone_number=num, settings=CodeSettings()))
        except Exception as ex:
            await nc_refund(uid, req_id, "failed")
            nc_state.pop(uid, None)
            try:
                if own:
                    await client.disconnect()
            except Exception:
                pass
            await e.reply(f"{P_NO} Could not request the code: {html.escape(str(ex)[:150])}\nYour fee was refunded.")
            return True
        st.update(step="code", new=num, req_id=req_id, client=client, own_client=own, hash=sent.phone_code_hash, tries=0)
        await e.reply(f"📩 A code was sent to <b>+{num}</b>. Send it here (you can type it with spaces):",
                      buttons=[[Button.inline("❌ Cancel (refund)", "cancel_action")]])
        return True
    if step == "code":
        code = re.sub(r"\D", "", text)
        try:
            await st["client"](ChangePhoneRequest(phone_number=st["new"], phone_code_hash=st["hash"], phone_code=code))
        except (PhoneCodeInvalidError, PhoneCodeExpiredError):
            st["tries"] += 1
            if st["tries"] < 3:
                await e.reply(f"{P_NO} Wrong/expired code. Try again ({3 - st['tries']} left).")
                return True
            await nc_refund(uid, st["req_id"], "failed")
            await nc_cleanup_client(st)
            nc_state.pop(uid, None)
            await e.reply(f"{P_NO} Too many wrong codes. Request cancelled and fee refunded.")
            return True
        except Exception as ex:
            await nc_refund(uid, st["req_id"], "failed")
            await nc_cleanup_client(st)
            nc_state.pop(uid, None)
            await e.reply(f"{P_NO} Number change failed: {html.escape(str(ex)[:150])}\nFee refunded.")
            return True
        cur.execute("UPDATE number_change_requests SET status='done' WHERE id=?", (st["req_id"],))
        cur.execute("UPDATE orders SET phone=? WHERE user_id=? AND phone=?", (st["new"], uid, st["old"]))
        db.commit()
        await nc_cleanup_client(st)
        nc_state.pop(uid, None)
        await e.reply(f"{P_YES} <b>Number changed!</b>\n+{st['old']} → <b>+{st['new']}</b>\nLog in with the new number from now on.")
        await nc_log(f"🔁 <b>Number change #{st['req_id']} DONE</b> (auto) user <code>{uid}</code> {st['old']} → {st['new']}")
        return True
    return False


async def nc_cleanup_client(st):
    if st.get("own_client") and st.get("client"):
        try:
            await st["client"].disconnect()
        except Exception:
            pass


# ---------------- ADMIN ----------------
async def phase4_admin(event, action_data, uid, chat):
    if action_data.startswith("catpick|") and has_perm(uid, "p_add_stock"):
        cat = action_data.split("|")[1]
        if cat in MANUAL_DELIVERY_CATS:
            btns = [[Button.inline("➕ Add Item", f"adm_addmanual|{cat}"), Button.inline("📄 Bulk Add", f"adm_bulkmanual|{cat}")],
                    [Button.inline("Back", "adm_catmenu")]]
            txt = f"📦 <b>Category:</b> {cat_label(cat)}\n\nThis category is delivered as text (no Telegram session). Choose how to add stock:"
        else:
            btns = [[Button.inline("Add Single Acc", f"adm_addstock|{cat}"), Button.inline("Add ZIP", f"adm_addzip|{cat}")],
                    [Button.inline("🔑 Session String", f"adm_addstring|{cat}"), Button.inline("🧬 Hex Auth Key", f"adm_addhex|{cat}")],
                    [Button.inline("Back", "adm_catmenu")]]
            txt = (f"📦 <b>Category:</b> {cat_label(cat)}\n\nChoose how to add stock:\n"
                   "<i>Tip: you can also just send a .session file in this chat.</i>")
        await event.edit(txt, buttons=btns)
        return True

    if action_data == "ncmenu" and has_perm(uid, "p_settings"):
        pend = cur.execute("SELECT COUNT(*) FROM number_change_requests WHERE status='pending'").fetchone()[0]
        btns = [[Button.inline(f"Number Change: {'🟢 ON' if nc_enabled() else '🔴 OFF'}", "adm_nc_toggle")],
                [Button.inline(f"💰 Fee ({P_INR}{nc_fee()})", "adm_nc_fee"), Button.inline(f"⏳ Pending ({pend})", "adm_nc_pending")],
                [Button.inline("Back", "adm_adminmain")]]
        await event.edit("🔁 <b>Number Change Settings</b>", buttons=btns)
        return True
    if action_data == "nc_toggle" and has_perm(uid, "p_settings"):
        cur.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('nc_status', ?)", ("off" if nc_enabled() else "on",))
        db.commit()
        return await phase4_admin(event, "ncmenu", uid, chat)
    if action_data == "nc_pending" and has_perm(uid, "p_manage_stock"):
        rows = cur.execute("SELECT id, user_id, old_phone, new_phone, fee FROM number_change_requests WHERE status='pending' ORDER BY id LIMIT 10").fetchall()
        if not rows:
            await event.answer("No pending requests.", alert=True)
            return True
        for rid, t_uid, old, new, fee in rows:
            await bot.send_message(chat, f"🔁 <b>#{rid}</b> user <code>{t_uid}</code>\n{old} → {new} | fee {P_INR}{fee}",
                                   buttons=[[Button.inline("✅ Done", f"nc_act|app|{rid}"), Button.inline("❌ Reject & Refund", f"nc_act|rej|{rid}")]])
        await event.answer()
        return True

    flows = {"addmanual", "bulkmanual", "addstring", "addhex", "nc_fee"}
    base, _, arg = action_data.partition("|")
    if base in flows and has_perm(uid, "p_add_stock" if base != "nc_fee" else "p_settings"):
        async with bot.conversation(chat, timeout=600) as conv:
            try:
                if base == "nc_fee":
                    fee = int(await conv_ask(conv, "💰 New Number Change fee (₹):"))
                    cur.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('nc_fee',?)", (str(fee),))
                    db.commit()
                    await conv.send_message(f"{P_YES} Fee set to {P_INR}{fee}.")
                elif base in ("addmanual", "bulkmanual"):
                    await admin_add_manual_items(conv, arg, base == "bulkmanual")
                elif base == "addstring":
                    r = await conv_ask(conv, "🔑 Send the Telethon <b>StringSession</b> string:", want_msg=True)
                    try:
                        await r.delete()  # don't leave the secret in chat
                    except Exception:
                        pass
                    await import_session_to_stock(conv, StringSession((r.raw_text or "").strip()), arg)
                elif base == "addhex":
                    r = await conv_ask(conv, "🧬 Send the 512-character hex <b>auth key</b>:", want_msg=True)
                    try:
                        await r.delete()
                    except Exception:
                        pass
                    dc = int(await conv_ask(conv, "🛰 DC id (1-5):"))
                    await import_session_to_stock(conv, hex_to_string_session((r.raw_text or "").strip(), dc), arg)
            except ConvCancelled:
                await conv.send_message(f"{P_NO} Cancelled.")
            except (ValueError, TypeError) as ex:
                await conv.send_message(f"{P_NO} Invalid input: {html.escape(str(ex)[:100])}")
            except asyncio.TimeoutError:
                await conv.send_message(f"{P_WARN} Timed out. Start again.")
        return True
    return False


def parse_db_datetime(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(str(value), fmt)
        except (TypeError, ValueError):
            continue
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None

def format_purchase_datetime(value):
    parsed = parse_db_datetime(value)
    if not parsed:
        return str(value)
    if parsed.date() == datetime.now(timezone.utc).date():
        return f"Today {parsed.strftime('%H:%M:%S')} UTC"
    return parsed.strftime("%a %b %d %H:%M:%S %Y")

async def get_user_display_name(uid):
    """Returns formatted string with User ID and Username, e.g. 5719136023 (@SeedUchiha)."""
    if not uid: return "Unknown"
    row = cur.execute("SELECT username, first_name FROM users WHERE user_id=?", (uid,)).fetchone()
    username = row[0] if row and row[0] else ""
    first_name = row[1] if row and row[1] else ""
    if not username:
        try:
            entity = await bot.get_entity(int(uid))
            username = getattr(entity, "username", "") or ""
            first_name = getattr(entity, "first_name", "") or ""
            if username or first_name:
                cur.execute("UPDATE users SET username=?, first_name=? WHERE user_id=?", (str(username).lstrip("@"), str(first_name), uid))
                db.commit()
        except Exception:
            pass
    
    user_link = f"@{username}" if username else "N/A"
    return f"<code>{uid}</code> ({user_link})"

async def resolve_user_360(query):
    """Smart multi-field user resolver matching ID, @username, phone, order ID, or UTR."""
    query_str = str(query).strip()
    if not query_str:
        return None, "Empty search query"

    # 1. Direct numeric User ID lookup
    if query_str.isdigit():
        uid = int(query_str)
        u = cur.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
        if u:
            cols = [col[0] for col in cur.description]
            return dict(zip(cols, u)), None

    # 2. Username lookup (with or without @)
    clean_user = query_str.lstrip("@").strip()
    if clean_user:
        u = cur.execute("SELECT * FROM users WHERE LOWER(username)=LOWER(?)", (clean_user,)).fetchone()
        if u:
            cols = [col[0] for col in cur.description]
            return dict(zip(cols, u)), None

    # 3. Order phone number search
    phone_clean = re.sub(r"[^\d]", "", query_str)
    if phone_clean and len(phone_clean) >= 7:
        ord_row = cur.execute("SELECT user_id FROM orders WHERE phone LIKE ? LIMIT 1", (f"%{phone_clean}%",)).fetchone()
        if ord_row and ord_row[0]:
            u = cur.execute("SELECT * FROM users WHERE user_id=?", (ord_row[0],)).fetchone()
            if u:
                cols = [col[0] for col in cur.description]
                return dict(zip(cols, u)), None

    # 4. Deposit Order ID or UTR search
    dep_row = cur.execute("SELECT user_id FROM upi_orders WHERE order_id=? LIMIT 1", (query_str,)).fetchone()
    if dep_row and dep_row[0]:
        u = cur.execute("SELECT * FROM users WHERE user_id=?", (dep_row[0],)).fetchone()
        if u:
            cols = [col[0] for col in cur.description]
            return dict(zip(cols, u)), None

    # 5. First name substring search
    u = cur.execute("SELECT * FROM users WHERE LOWER(first_name) LIKE LOWER(?) LIMIT 1", (f"%{clean_user}%",)).fetchone()
    if u:
        cols = [col[0] for col in cur.description]
        return dict(zip(cols, u)), None

    return None, f"No user or record found matching '<code>{html.escape(query_str)}</code>'."

async def render_user_profile(e, uid):
    """Renders user profile card with complete financial metrics, referral statistics, and color-coded action buttons."""
    ensure_user(uid)
    row = cur.execute("SELECT balance, sales_balance, total_deposited, joined_date, referred_by, username, first_name FROM users WHERE user_id=?", (uid,)).fetchone()
    if not row:
        bal, s_bal, dep, date_str, ref_by, uname, f_name = 0, 0, 0, "N/A", None, "", ""
    else:
        bal, s_bal, dep, date_str, ref_by, uname, f_name = row
    
    if not uname:
        try:
            sender = getattr(e, "sender", None)
            if sender:
                uname = getattr(sender, "username", "") or ""
                f_name = getattr(sender, "first_name", "") or ""
            if not uname:
                entity = await bot.get_entity(int(uid))
                uname = getattr(entity, "username", "") or ""
                f_name = getattr(entity, "first_name", "") or ""
            if uname or f_name:
                cur.execute("UPDATE users SET username=?, first_name=? WHERE user_id=?", (str(uname).lstrip("@"), str(f_name), uid))
                db.commit()
        except Exception:
            pass

    user_link = f"@{uname}" if uname else "N/A"
    me = await bot.get_me()
    bot_username = me.username if me else "Acccheckbot"
    
    ord_summary = cur.execute("SELECT COUNT(*), SUM(price) FROM orders WHERE user_id=?", (uid,)).fetchone()
    total_accs = ord_summary[0] if ord_summary else 0
    total_spent = ord_summary[1] if ord_summary and ord_summary[1] else 0
    
    ref_count = cur.execute("SELECT COUNT(*) FROM users WHERE referred_by=?", (uid,)).fetchone()[0]
    ref_by_disp = await get_user_display_name(ref_by) if ref_by else "None"
    
    is_master = uid == ADMIN_ID or uid in get_admin_ids()
    is_subadmin = bool(cur.execute("SELECT user_id FROM admins WHERE user_id=?", (uid,)).fetchone())
    role_badge = "👑 Master Admin" if is_master else ("🛠 Sub-Admin" if is_subadmin else "👤 Verified Member")
    
    usdt_rate = get_usdt_rate()
    bal_usdt = bal / usdt_rate if usdt_rate > 0 else 0.0
    
    ref_pct = cur.execute("SELECT value FROM settings WHERE key='ref_percent'").fetchone()
    ref_bonus_rate = ref_pct[0] if ref_pct else "3"
    
    msg = (f"👤 <b>USER PROFILE & ACCOUNT CONTROL</b>\n"
           f"━━━━━━━━━━━━━━━━━━━━\n"
           f"🆔 <b>User ID:</b> <code>{uid}</code>\n"
           f"👤 <b>Name:</b> <b>{html.escape(f_name or 'Member')}</b> ({user_link})\n"
           f"🔰 <b>Role:</b> {role_badge}\n"
           f"📅 <b>Joined:</b> {str(date_str)[:10] if date_str else 'N/A'}\n"
           f"━━━━━━━━━━━━━━━━━━━━\n\n"
           f"💰 <b>FINANCIAL METRICS</b>\n"
           f"━━━━━━━━━━━━━━━━━━━━\n"
           f"💳 <b>Main Balance:</b> <b>{format_price(uid, bal)}</b> (~${bal_usdt:.2f} USDT)\n"
           f"🤝 <b>Sales Balance:</b> <b>{format_price(uid, s_bal)}</b>\n"
           f"📥 <b>Total Deposited:</b> <b>{format_price(uid, dep)}</b>\n"
           f"🛒 <b>Total Spent:</b> <b>{format_price(uid, total_spent)}</b> ({total_accs} Accounts)\n"
           f"━━━━━━━━━━━━━━━━━━━━\n\n"
           f"👥 <b>REFERRAL PROGRAM ({ref_bonus_rate}% Commission)</b>\n"
           f"━━━━━━━━━━━━━━━━━━━━\n"
           f"🔗 <b>Referred By:</b> {ref_by_disp}\n"
           f"👥 <b>Your Referrals:</b> <b>{ref_count}</b> Users\n"
           f"🔗 <b>Referral Link:</b>\n"
           f"<code>https://t.me/{bot_username}?start=ref_{uid}</code>\n"
           f"━━━━━━━━━━━━━━━━━━━━")
    
    c_pref = get_currency_pref(uid)
    c_btn_text = "💱 Switch to USDT ($)" if c_pref == "INR" else "💱 Switch to INR (₹)"
    
    btns = [
        [p_btn("💳 Deposit Balance", "menu_deposit", style="success"), p_btn("🤝 Withdraw Sales", "wd_sales", style="primary")],
        [p_btn(c_btn_text, "tgl_curr", style="primary"), p_btn("🎁 Claim Promo Code", "claim_promo", style="success")],
        [p_btn("📦 My Uploads", "menu_uploads", style="primary"), p_btn("📜 Order History", "menu_history", style="primary")],
        [p_btn("⬅️ Main Menu", "menu_main", style="danger")]
    ]
    await safe_show_message(e, msg, buttons=btns)

async def perform_360_user_lookup(e, admin_uid, target_query):
    """Renders 360-degree user profile card with complete diagnostics and action controls."""
    user_row, err_msg = await resolve_user_360(target_query)
    if not user_row:
        return await safe_show_message(e, f"❌ {err_msg}", buttons=[[p_btn("Try Again", "adm_lookup", style="primary"), p_btn("Admin Dashboard", "adm_adminmain", style="danger")]])
    
    t_uid = user_row["user_id"]
    username = user_row.get("username") or ""
    first_name = user_row.get("first_name") or ""
    if not username:
        try:
            entity = await bot.get_entity(int(t_uid))
            username = getattr(entity, "username", "") or ""
            first_name = getattr(entity, "first_name", "") or ""
            if username or first_name:
                cur.execute("UPDATE users SET username=?, first_name=? WHERE user_id=?", (str(username).lstrip("@"), str(first_name), t_uid))
                db.commit()
        except Exception:
            pass

    user_link = f"@{username}" if username else "N/A"
    
    bal = user_row.get("balance", 0)
    usdt_rate = get_usdt_rate()
    bal_usd = bal / usdt_rate if usdt_rate > 0 else 0.0
    
    is_master = t_uid == ADMIN_ID or t_uid in get_admin_ids()
    is_subadmin = bool(cur.execute("SELECT user_id FROM admins WHERE user_id=?", (t_uid,)).fetchone())
    role_badge = "👑 Master Admin" if is_master else ("🛠 Sub-Admin" if is_subadmin else "👤 Regular User")
    
    is_banned = is_user_banned(t_uid)
    status_str = "🔴 BANNED" if is_banned else "🟢 ACTIVE"
    
    # Financial aggregate queries
    dep_row = cur.execute("SELECT SUM(amount), COUNT(*) FROM deposits WHERE user_id=? AND status='success'", (t_uid,)).fetchone()
    upi_dep = cur.execute("SELECT SUM(amount), COUNT(*) FROM upi_orders WHERE user_id=? AND status='success'", (t_uid,)).fetchone()
    total_dep = (dep_row[0] or 0) + (upi_dep[0] or 0)
    total_dep_cnt = (dep_row[1] or 0) + (upi_dep[1] or 0)
    
    ord_row = cur.execute("SELECT COUNT(*), SUM(price) FROM orders WHERE user_id=?", (t_uid,)).fetchone()
    total_orders_cnt = ord_row[0] or 0
    total_spent = ord_row[1] or 0
    
    ref_row = cur.execute("SELECT COUNT(*) FROM users WHERE referred_by=?", (t_uid,)).fetchone()
    total_refs = ref_row[0] if ref_row else 0
    
    ref_by = user_row.get("referred_by")
    ref_by_str = await get_user_display_name(ref_by) if ref_by else "None"
    
    # Recent 5 Orders
    recent_orders = cur.execute("SELECT country, year, price, phone, date FROM orders WHERE user_id=? ORDER BY date DESC LIMIT 5", (t_uid,)).fetchall()
    ord_txt = ""
    for c, y, p, ph, dt in recent_orders:
        ord_txt += f"• 📦 <code>{str(dt)[:16] if dt else '?'}</code> | {c} ({y}) | ₹{p}\n   📱 <code>{ph}</code>\n"
    if not ord_txt: ord_txt = "No orders found.\n"
    
    # Recent 5 Recharges
    recent_deps = cur.execute("SELECT amount, method_name, status, date FROM deposits WHERE user_id=? ORDER BY date DESC LIMIT 5", (t_uid,)).fetchall()
    dep_txt = ""
    for a, m, s, dt in recent_deps:
        st_icon = "🟢" if s == 'success' else ("🔴" if s == 'rejected' else "🟡")
        dep_txt += f"• {st_icon} <code>{str(dt)[:16] if dt else '?'}</code> | {m} ₹{a} | {str(s).upper()}\n"
    if not dep_txt: dep_txt = "No deposits found.\n"
    
    msg = (f"👤 <b>USER 360° PROFILE & DIAGNOSTICS</b>\n"
           f"━━━━━━━━━━━━━━━━━━━━\n"
           f"🆔 <b>User ID:</b> <code>{t_uid}</code>\n"
           f"👤 <b>Name:</b> <b>{html.escape(first_name or 'Unknown')}</b> ({user_link})\n"
           f"🔰 <b>Role:</b> {role_badge}\n"
           f"📅 <b>Joined:</b> {user_row.get('joined_date', 'N/A')}\n"
           f"🚫 <b>Status:</b> {status_str}\n"
           f"━━━━━━━━━━━━━━━━━━━━\n\n"
           f"💰 <b>FINANCIAL SUMMARY</b>\n"
           f"━━━━━━━━━━━━━━━━━━━━\n"
           f"💳 <b>Active Balance:</b> <b>₹{bal}</b> (~${bal_usd:.2f} USDT)\n"
           f"📥 <b>Total Deposited:</b> <b>₹{total_dep}</b> ({total_dep_cnt} deposits)\n"
           f"📤 <b>Total Spent:</b> <b>₹{total_spent}</b> ({total_orders_cnt} orders)\n"
           f"━━━━━━━━━━━━━━━━━━━━\n\n"
           f"👥 <b>REFERRAL NETWORK</b>\n"
           f"━━━━━━━━━━━━━━━━━━━━\n"
           f"🔗 <b>Referred By:</b> {ref_by_str}\n"
           f"👥 <b>Direct Referrals:</b> <b>{total_refs}</b> users\n"
           f"━━━━━━━━━━━━━━━━━━━━\n\n"
           f"📦 <b>RECENT ORDERS (Last 5)</b>\n{ord_txt.strip()}\n\n"
           f"💳 <b>RECENT RECHARGES (Last 5)</b>\n{dep_txt.strip()}")
    
    btns = [
        [p_btn("🔴 Ban User" if not is_banned else "🟢 Unban User", f"lka_ban|{t_uid}", style="danger" if not is_banned else "success"),
         p_btn("💸 Add Balance", f"lka_bal|add|{t_uid}", style="success")],
        [p_btn("💳 Deduct Balance", f"lka_bal|ded|{t_uid}", style="danger"),
         p_btn("💬 Send Message", f"lka_msg|{t_uid}", style="primary")],
        [p_btn("📦 View All Orders", f"lka_ords|{t_uid}|1", style="primary"),
         p_btn("💳 Recharges Log", f"lka_deps|{t_uid}|1", style="primary")],
        [p_btn("👥 Referrals List", f"lka_refs|{t_uid}|1", style="primary"),
         p_btn("🔄 Refresh Profile", f"lka_ref|{t_uid}", style="primary")],
        [p_btn("⬅️ Back to Admin", "adm_adminmain", style="danger")]
    ]
    await safe_show_message(e, msg, buttons=btns)

# ======================================================================
# PHASE 5: GIVEAWAY, FIGHT, /lookup (360), /live, /logout, REFERRAL MODES, PAYMENT TOGGLES,
#          BULK WARN, API CREDENTIAL POOL, DB/JSON BACKUP & RESTORE, UPI EXPIRY, PRIVATE-ONLY
# ======================================================================
giveaway_ticket_state = {}
lookup_search_state = {}
logout_search_state = {}
restore_state = {}
session_cache_map = {}
FIGHT_EXPIRY_SECONDS = 600
UPI_QR_EXPIRY_SECONDS = 900
# Callbacks that admins may press from the log channel / group (everything else is private-only)
GROUP_ADMIN_CB_PREFIXES = ("dep_act|", "kp_adm|", "wd_act|", "nc_act|", "msr_act|", "adm_")


def get_admin_ids():
    ids = {ADMIN_ID}
    ids.update(r[0] for r in cur.execute("SELECT user_id FROM admins").fetchall())
    return ids


def is_method_on(key, default="on"):
    r = cur.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return (r[0] if r and r[0] else default) == "on"


def track_user_identity(sender):
    """Remember @username / first name so /lookup can search by them."""
    try:
        if sender and getattr(sender, "id", None):
            cur.execute("UPDATE users SET username=?, first_name=? WHERE user_id=?",
                        (getattr(sender, "username", None) or "", getattr(sender, "first_name", None) or "", sender.id))
            db.commit()
    except Exception:
        pass


# ---------------- REFERRAL MODES ----------------
def get_ref_mode():
    r = cur.execute("SELECT value FROM settings WHERE key='ref_mode'").fetchone()
    return r[0] if r and r[0] in ("flat", "percent") else "flat"


def get_ref_trigger():
    r = cur.execute("SELECT value FROM settings WHERE key='ref_trigger'").fetchone()
    return r[0] if r and r[0] in ("join", "deposit") else "join"


async def reward_referrer_on_join(uid):
    """Trigger = join: flat ₹ bonus when the referred user joins (percent has no base on join, so flat is used)."""
    if not is_ref_enabled() or get_ref_trigger() != "join":
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
            await bot.send_message(ref, f"{PE_GIFT} <b>Referral Bonus Unlocked!</b>\n{PE_HEART} Your referral <code>{uid}</code> joined.\n{PE_CHECK} You earned <b>{P_INR}{bonus}</b>!")
        except Exception:
            pass


async def process_referral_bonus(uid, amount):
    """Trigger = deposit: bonus on the referred user's FIRST approved deposit (flat ₹ or % of it)."""
    if not is_ref_enabled() or get_ref_trigger() != "deposit":
        return
    row = cur.execute("SELECT referred_by, ref_rewarded FROM users WHERE user_id=?", (uid,)).fetchone()
    if not row or not row[0] or row[1]:
        return
    cur.execute("UPDATE users SET ref_rewarded=1 WHERE user_id=? AND ref_rewarded=0", (uid,))
    if cur.rowcount == 0:
        return
    db.commit()
    val = get_ref_bonus()
    bonus = int(amount * val / 100) if get_ref_mode() == "percent" else val
    if bonus > 0:
        update_balance(row[0], bonus)
        try:
            await bot.send_message(row[0], f"{PE_GIFT} <b>Referral Bonus!</b>\nYour referral <code>{uid}</code> made their first deposit.\nYou earned <b>{P_INR}{bonus}</b>!")
        except Exception:
            pass


# ---------------- GIVEAWAY (ticket based) ----------------
async def render_giveaway(event, gid):
    row = cur.execute("SELECT prize_name, ticket_price, min_participants, winners_count, status FROM giveaways WHERE id=?", (gid,)).fetchone()
    if not row:
        return await safe_show_message(event, "❌ Giveaway not found.", buttons=[[p_btn("Back", "menu_buy")]])
    prize, price, min_p, winners, status = row
    users_count, tickets = cur.execute("SELECT COUNT(*), COALESCE(SUM(tickets),0) FROM giveaway_tickets WHERE giveaway_id=? AND tickets>0", (gid,)).fetchone()
    text = (f"🎁 <b>Giveaway: {html.escape(prize)}</b>\n\n🎟 Ticket price: <b>{P_INR}{price}</b>\n"
            f"👥 Participants: <b>{users_count}/{min_p}</b>\n🎫 Total tickets: <b>{tickets}</b>\n🏆 Winners: <b>{winners}</b>\n"
            f"📌 Status: <b>{status.upper()}</b>\n\nMore tickets = better winning chance.")
    btns = []
    if status == "open":
        btns.append([p_btn("🎟 Buy 1", f"g_buy|{gid}|1"), p_btn("🎟 Buy 5", f"g_buy|{gid}|5")])
        btns.append([p_btn("🎟 Buy 10", f"g_buy|{gid}|10"), p_btn("✍️ Custom", f"g_custom|{gid}")])
    await safe_show_message(event, text, buttons=btns or None)


async def buy_giveaway_tickets(uid, gid, qty):
    """Atomic ticket purchase. Returns (ok, message)."""
    async with get_user_lock(uid):
        row = cur.execute("SELECT ticket_price, status FROM giveaways WHERE id=?", (gid,)).fetchone()
        if not row or row[1] != "open":
            return False, "❌ Giveaway is closed or missing."
        total = row[0] * qty
        cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=? AND balance >= ?", (total, uid, total))
        if cur.rowcount == 0:
            db.commit()
            return False, f"❌ Need {P_INR}{total}. Add balance first."
        cur.execute("INSERT INTO giveaway_tickets (giveaway_id, user_id, tickets) VALUES (?,?,?) ON CONFLICT(giveaway_id, user_id) DO UPDATE SET tickets = tickets + excluded.tickets",
                    (gid, uid, qty))
        db.commit()
    return True, f"✅ Bought {qty} ticket(s) for {P_INR}{total}."


async def maybe_finish_giveaway(gid):
    row = cur.execute("SELECT prize_name, min_participants, winners_count, created_by FROM giveaways WHERE id=? AND status='open'", (gid,)).fetchone()
    if not row:
        return
    prize, min_p, winners_count, created_by = row
    parts = cur.execute("SELECT user_id, tickets FROM giveaway_tickets WHERE giveaway_id=? AND tickets>0", (gid,)).fetchall()
    if len(parts) < min_p:
        return
    cur.execute("UPDATE giveaways SET status='closed' WHERE id=? AND status='open'", (gid,))  # claim: only one finisher runs
    if cur.rowcount == 0:
        db.commit()
        return
    db.commit()
    pool = [u for u, t in parts for _ in range(max(1, int(t)))]
    winners = []
    while pool and len(winners) < min(winners_count, len(parts)):
        w = random.choice(pool)
        winners.append(w)
        pool = [x for x in pool if x != w]
    lines = []
    for wid in winners:
        try:
            ent = await bot.get_entity(wid)
            lines.append(f"🏆 <code>{wid}</code> {html.escape(ent.first_name or str(wid))} {('@' + ent.username) if getattr(ent, 'username', None) else ''}")
        except Exception:
            lines.append(f"🏆 <code>{wid}</code>")
    announce = (f"🎉 <b>Giveaway Ended!</b>\n\nPrize: <b>{html.escape(prize)}</b>\nParticipants: <b>{len(parts)}</b>\n\n<b>Winner(s):</b>\n" + "\n".join(lines))
    for u, _ in parts:
        try:
            await bot.send_message(u, announce)
        except Exception:
            pass
    try:
        await bot.send_message(created_by or ADMIN_ID, announce + "\n\n<i>Deliver the prize manually.</i>")
    except Exception:
        pass


def create_giveaway(prize, price, min_p, winners, admin_id):
    gid = f"Giv_{random.randint(1000, 9999)}"
    while cur.execute("SELECT 1 FROM giveaways WHERE id=?", (gid,)).fetchone():
        gid = f"Giv_{random.randint(1000, 9999)}"
    cur.execute("INSERT INTO giveaways (id, prize_name, ticket_price, min_participants, winners_count, status, created_by) VALUES (?,?,?,?,?,'open',?)",
                (gid, prize, price, min_p, winners, admin_id))
    db.commit()
    return gid


@bot.on(events.NewMessage(pattern=r"(?i)^/giveaway(?:\s+(\d+))?(?:\s+(\d+))?"))
async def handle_giveaway_command(e):
    if not e.is_private:
        return
    uid = e.sender_id
    if not is_admin(uid):
        return await e.reply("Admins only.")
    m = e.pattern_match
    if not m or not m.group(1) or not m.group(2) or int(m.group(1)) <= 0 or int(m.group(2)) <= 0:
        return await e.reply("Usage: <code>/giveaway &lt;ticket_price&gt; &lt;min_participants&gt;</code>")
    gid = create_giveaway("Giveaway Prize", int(m.group(1)), int(m.group(2)), 1, uid)
    me = await bot.get_me()
    await e.reply(f"🎁 <b>Giveaway Created</b>\n\nTicket: {P_INR}{m.group(1)}\nParticipants needed: {m.group(2)}\nLink: <code>https://t.me/{me.username}?start={gid}</code>",
                  buttons=[[Button.inline("Open Giveaway", f"g_open|{gid}")]])


# ---------------- FIGHT (persistent stakes) ----------------
@bot.on(events.NewMessage(pattern=r"(?i)^/fight(?:\s+(\d+))?"))
async def handle_fight_command(e):
    if not e.is_private:
        return
    uid = e.sender_id
    if not is_method_on("fight_game_status"):
        return await e.reply("❌ Fight game is disabled.")
    if not e.pattern_match or not e.pattern_match.group(1) or int(e.pattern_match.group(1)) <= 0:
        return await e.reply("Usage: <code>/fight 10</code>")
    amount = int(e.pattern_match.group(1))
    ensure_user(uid)
    async with get_user_lock(uid):
        cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=? AND balance >= ?", (amount, uid, amount))
        if cur.rowcount == 0:
            db.commit()
            return await e.reply(f"❌ Insufficient balance. You need {P_INR}{amount}.")
        fid = f"FGT{uid}{int(time.time())}"
        cur.execute("INSERT INTO fight_games (id, creator_id, amount, status, created) VALUES (?,?,?,?,?)", (fid, uid, amount, "open", time.time()))
        db.commit()
    name = html.escape(await get_user_display_name(uid))
    await e.reply(f"⚔️ <b>Fight Started!</b>\n\n{name} staked {P_INR}{amount}.\nWinner takes {P_INR}{amount * 2}.\nAnother player can join below (expires in {FIGHT_EXPIRY_SECONDS // 60} min).",
                  buttons=[[Button.inline(f"⚔️ Join Fight {P_INR}{amount}", f"join_fight|{fid}")]])


async def join_fight(e, uid, fid):
    ensure_user(uid)
    row = cur.execute("SELECT creator_id, amount, status FROM fight_games WHERE id=?", (fid,)).fetchone()
    if not row or row[2] != "open":
        return await safe_answer_cb(e, "❌ This battle has expired or already finished.", alert=True)
    creator, amount, _ = row
    if uid == creator:
        return await safe_answer_cb(e, "❌ You cannot join your own fight!", alert=True)
    async with get_user_lock(uid):
        cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=? AND balance >= ?", (amount, uid, amount))
        if cur.rowcount == 0:
            db.commit()
            return await safe_answer_cb(e, f"❌ Insufficient balance! Need {P_INR}{amount}.", alert=True)
        cur.execute("UPDATE fight_games SET status='done' WHERE id=? AND status='open'", (fid,))  # claim the fight exactly once
        if cur.rowcount == 0:
            cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, uid))
            db.commit()
            return await safe_answer_cb(e, "❌ Someone else just joined this fight.", alert=True)
        db.commit()
    winner = random.choice([creator, uid])
    update_balance(winner, amount * 2)
    n1, n2 = html.escape(await get_user_display_name(creator)), html.escape(await get_user_display_name(uid))
    await e.edit(f"{P_TADA} <b>BATTLE COMPLETED!</b>\n\n🤺 Initiator: {n1}\n🛡 Challenger: {n2}\n💰 Pool: <b>{P_INR}{amount * 2}</b>\n\n🏆 <b>Winner:</b> {n1 if winner == creator else n2}")


async def fight_expiry_loop():
    while True:
        try:
            old = cur.execute("SELECT id, creator_id, amount FROM fight_games WHERE status='open' AND created < ?", (time.time() - FIGHT_EXPIRY_SECONDS,)).fetchall()
            for fid, creator, amount in old:
                async with get_user_lock(creator):
                    cur.execute("UPDATE fight_games SET status='expired' WHERE id=? AND status='open'", (fid,))
                    if cur.rowcount:
                        cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, creator))
                    db.commit()
                try:
                    await bot.send_message(creator, f"⌛ Your fight expired with no challenger. {P_INR}{amount} was refunded.")
                except Exception:
                    pass
        except Exception as ex:
            logger.error("fight expiry loop: %s", ex)
        await asyncio.sleep(60)


async def upi_expiry_loop():
    """Mark stale UPI QR orders as expired and tell the user (late payers can still submit their UTR)."""
    while True:
        try:
            rows = cur.execute("SELECT order_id, user_id, qr_msg_id FROM upi_orders WHERE status='pending' AND created_ts < ?", (time.time() - UPI_QR_EXPIRY_SECONDS,)).fetchall()
            for oid, u, mid in rows:
                cur.execute("UPDATE upi_orders SET status='expired' WHERE order_id=? AND status='pending'", (oid,))
                db.commit()
                if mid:
                    try:
                        await bot.edit_message(u, mid, f"⌛ <b>This payment QR expired</b> (order <code>{oid}</code>).\nIf you already paid, tap Submit UTR; otherwise start a new deposit.",
                                               buttons=[[Button.inline("✅ Submit UTR (12 Digit)", f"submit_utr_{oid}")]])
                    except Exception:
                        pass
        except Exception as ex:
            logger.error("upi expiry loop: %s", ex)
        await asyncio.sleep(60)


# ---------------- SESSION MANAGER (/logout) ----------------
def parse_hex_or_string(text):
    t = (text or "").strip()
    dc = 2
    if ":" in t and len(t.rsplit(":", 1)[1]) <= 2:
        head, tail = t.rsplit(":", 1)
        try:
            dc = int(tail)
        except ValueError:
            dc = 2
        t = head
    hx = re.sub(r"[^0-9a-fA-F]", "", t)
    if len(hx) >= 512:
        return hex_to_string_session(hx[:512], dc)
    if len(t) >= 50 and not t.startswith("/"):
        return StringSession(t)
    return None


async def process_hex_or_string_logout_input(e, uid, text):
    sess = parse_hex_or_string(text)
    if sess is None:
        return await e.reply("❌ <b>Invalid key.</b> Send a 512-char Hex key (optionally <code>hex:DC</code>) or a Telethon String Session.")
    await e.reply("⌛ <i>Connecting to Telegram & fetching active devices...</i>")
    client = None
    try:
        api_id, api_hash = get_random_api_credentials()
        client = TelegramClient(sess, int(api_id), api_hash)
        await client.connect()
        if not await client.is_user_authorized():
            return await e.reply("❌ <b>Session expired or revoked.</b>")
        me = await client.get_me()
        phone = f"+{me.phone}" if me and me.phone else "Hidden"
        auths = (await client(GetAuthorizationsRequest())).authorizations
        sm_id = f"sm_{uid}_{int(time.time())}"
        session_cache_map[sm_id] = {"uid": uid, "sess": sess.save(), "time": time.time(), "auths": {str(a.hash): a for a in auths}}
        lines = [f"📱 <b>TELEGRAM SESSION MANAGER</b>", "━━━━━━━━━━━━━━━━━━━━",
                 f"👤 <b>Account:</b> <code>{phone}</code>", f"📲 <b>Active sessions:</b> {len(auths)}", ""]
        btns = []
        for i, a in enumerate(auths, 1):
            cur_tag = "✨ Current (Bot)" if getattr(a, "current", False) else "⚠️ Other device"
            lines.append(f"<b>{i}.</b> {html.escape(a.device_model or 'Device')} | {html.escape(a.platform or '')}\n   └ {html.escape(a.app_name or '')} · {html.escape(a.country or '')} ({a.ip})\n   └ {cur_tag}")
            if getattr(a, "current", False):
                btns.append([Button.inline(f"🔴 Logout bot session (#{i})", f"sm_kill|{sm_id}|current")])
            else:
                btns.append([Button.inline(f"🚫 Terminate #{i} ({(a.device_model or 'Device')[:16]})", f"sm_kill|{sm_id}|{a.hash}")])
        if len(auths) > 1:
            btns.append([Button.inline(f"🔴 Terminate ALL other devices ({len(auths) - 1})", f"sm_kill_all|{sm_id}")])
        lines.append("\n⚠️ <i>Never terminate the device you are using right now.</i>")
        await e.reply("\n".join(lines), buttons=btns)
    except Exception as ex:
        logger.error("logout manager error: %s", ex)
        await e.reply(f"❌ <b>Connection error:</b> {html.escape(str(ex)[:150])}")
    finally:
        if client:
            try:
                await client.disconnect()
            except Exception:
                pass


async def session_manager_action(e, uid, data):
    parts = data.split("|")
    sm_id = parts[1]
    cache = session_cache_map.get(sm_id)
    if not cache or time.time() - cache["time"] > 900:
        session_cache_map.pop(sm_id, None)
        return await safe_answer_cb(e, "❌ Expired. Send your key again with /logout.", alert=True)
    if cache["uid"] != uid and not is_admin(uid):
        return await safe_answer_cb(e, "❌ Unauthorized.", alert=True)
    client = None
    try:
        api_id, api_hash = get_random_api_credentials()
        client = TelegramClient(StringSession(cache["sess"]), int(api_id), api_hash)
        await client.connect()
        if not await client.is_user_authorized():
            return await safe_answer_cb(e, "❌ Session already logged out.", alert=True)
        if parts[0] == "sm_kill_all":
            n = 0
            for a in (await client(GetAuthorizationsRequest())).authorizations:
                if not getattr(a, "current", False):
                    try:
                        await client(ResetAuthorizationRequest(hash=a.hash))
                        n += 1
                    except Exception:
                        pass
            return await e.edit(f"✅ <b>{n} other device(s) terminated.</b>")
        if parts[2] == "current":
            await client.log_out()
            session_cache_map.pop(sm_id, None)
            return await e.edit("✅ <b>Bot session logged out.</b>")
        await client(ResetAuthorizationRequest(hash=int(parts[2])))
        await e.edit("✅ <b>Device terminated.</b> Send /logout again to refresh the list.")
    except Exception as ex:
        await safe_answer_cb(e, f"❌ Failed: {str(ex)[:100]}", alert=True)
    finally:
        if client:
            try:
                await client.disconnect()
            except Exception:
                pass


@bot.on(events.NewMessage(pattern=r"(?i)^/logout$"))
async def handle_logout_command(e):
    if not e.is_private:
        return
    logout_search_state[e.sender_id] = True
    await e.respond("🔐 <b>Session Manager</b>\n━━━━━━━━━━━━━━━━━━━━\nSend your <b>Hex:DC key</b> or <b>String Session</b> to list and terminate sessions.\n\n"
                    "• <code>590064df...:5</code> (Hex:DC)\n• <code>1BVts...</code> (String Session)\n\n⚠️ Terminate the bot session + other devices only — never your own phone.")


# ---------------- /lookup /live ----------------
@bot.on(events.NewMessage(pattern=r"(?i)^/lookup(?:\s+(.+))?"))
async def handle_lookup_command(e):
    if not e.is_private or not is_admin(e.sender_id):
        return
    q = e.pattern_match.group(1)
    if not q:
        lookup_search_state[e.sender_id] = True
        return await e.respond("🔍 <b>User 360° Lookup</b>\n\nSend a User ID, @username, phone number, order ID or UTR.")
    await perform_360_user_lookup(e, e.sender_id, q.strip())


async def handle_live_command(e):
    uid = e.sender_id
    if not is_admin(uid):
        return
    q1 = lambda sql: (cur.execute(sql).fetchone() or [0])[0] or 0
    total_users, banned = q1("SELECT COUNT(*) FROM users"), q1("SELECT COUNT(*) FROM users WHERE banned=1")
    stock = q1("SELECT COUNT(*) FROM stock WHERE available=1")
    sold_cnt, sold_amt = cur.execute("SELECT COUNT(*), COALESCE(SUM(price),0) FROM orders").fetchone()
    bal, sbal, dep = cur.execute("SELECT COALESCE(SUM(balance),0), COALESCE(SUM(sales_balance),0), COALESCE(SUM(total_deposited),0) FROM users").fetchone()
    upi_rev = (cur.execute("SELECT value FROM settings WHERE key='upi_revenue'").fetchone() or ["0"])[0]
    pend_wd = q1("SELECT COUNT(*) FROM withdrawals WHERE status='pending'")
    promos = q1("SELECT COUNT(*) FROM promo_codes WHERE used_count < max_uses")
    gws = q1("SELECT COUNT(*) FROM giveaways WHERE status='open'")
    holds = q1("SELECT COUNT(*) FROM sell_submissions WHERE status='holding'")
    apis = q1("SELECT COUNT(*) FROM api_credentials")
    s1 = "ON 🟢" if is_server1_online() else "OFF 🔴"
    lzt_line = "no token"
    if resolve_lzt_token():
        try:
            me_res = await lzt_request('GET', '/me', notify_errors=False)
            lzt_line = f"{me_res['user'].get('balance', '?')} RUB" if me_res and 'user' in me_res else "unreachable 🔴"
        except Exception:
            lzt_line = "unreachable 🔴"
    msg = (f"🟢 <b>360° LIVE SYSTEM DIAGNOSTICS</b>\n━━━━━━━━━━━━━━━━━━━━\n"
           f"👥 Users: <b>{total_users}</b> ({banned} banned)\n📦 Server 2 stock: <b>{stock}</b>\n⚡ Active order sessions: <b>{len(active_orders)}</b>\n"
           f"⏳ Sell holds: <b>{holds}</b>\n━━━━━━━━━━━━━━━━━━━━\n"
           f"🌐 Server 1: {s1} · Market balance: <b>{lzt_line}</b>\n🔑 API pool: <b>{apis}</b> (+ .env primary)\n━━━━━━━━━━━━━━━━━━━━\n"
           f"💳 Users balance: <b>{P_INR}{bal}</b>\n🤝 Sales balance: <b>{P_INR}{sbal}</b>\n📥 Total deposited: <b>{P_INR}{dep}</b>\n💰 UPI revenue: <b>{P_INR}{upi_rev}</b>\n"
           f"💳 Pending withdrawals: <b>{pend_wd}</b>\n🛒 Sold: <b>{sold_cnt}</b> ({P_INR}{sold_amt})\n━━━━━━━━━━━━━━━━━━━━\n"
           f"🎟 Active promos: <b>{promos}</b>\n🎉 Open giveaways: <b>{gws}</b>")
    await safe_show_message(e, msg, buttons=[[p_btn("🔄 Refresh", "adm_live_ref")], [p_btn("💻 Admin Dashboard", "adm_adminmain")]])


@bot.on(events.NewMessage(pattern=r"(?i)^/live$"))
async def live_command(e):
    if e.is_private:
        await handle_live_command(e)


# ---------------- BACKUP / RESTORE ----------------
def export_json_backup(path):
    data = {}
    for (t,) in cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
        c = db.execute(f"SELECT * FROM {t}")
        data[t] = {"columns": [d[0] for d in c.description], "rows": [list(r) for r in c.fetchall()]}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, default=str)


def restore_json_backup(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    existing = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    restored = 0
    try:
        cur.execute("BEGIN")
        for t, blob in data.items():
            if t not in existing or not re.fullmatch(r"\w+", t):
                continue
            cols = [c for c in blob["columns"] if re.fullmatch(r"\w+", c)]
            if len(cols) != len(blob["columns"]):
                continue
            cur.execute(f"DELETE FROM {t}")
            q = f"INSERT OR REPLACE INTO {t} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})"
            for row in blob["rows"]:
                cur.execute(q, row)
                restored += 1
        db.commit()
    except Exception:
        db.rollback()
        raise
    return restored


def restore_db_backup(path):
    src = sqlite3.connect(path)
    try:
        if src.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Backup failed the integrity check.")
        tables = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if not {"users", "settings", "stock"} <= tables:
            raise ValueError("This file does not look like a bot database.")
        src.backup(db)
    finally:
        src.close()


async def handle_restore_file(e, uid):
    restore_state.pop(uid, None)
    name = (e.file.name or "").lower()
    tmp = await bot.download_media(e.message, f"restore_{uid}_{int(time.time())}")
    try:
        if name.endswith(".json"):
            n = restore_json_backup(tmp)
            await e.reply(f"{P_YES} JSON restore complete: {n} rows restored.")
        elif name.endswith(".db"):
            restore_db_backup(tmp)
            await e.reply(f"{P_YES} Database restored. Restart the bot to be safe.")
        else:
            await e.reply(f"{P_NO} Send a .db or .json backup file.")
    except Exception as ex:
        await e.reply(f"{P_NO} Restore failed: {html.escape(str(ex)[:200])}")
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass


# ---------------- CALLBACKS ----------------
async def phase5_callbacks(e, uid, data):
    if data == "cancel_action":
        giveaway_ticket_state.pop(uid, None)
        lookup_search_state.pop(uid, None)
        logout_search_state.pop(uid, None)
        restore_state.pop(uid, None)
        return False
    if data in ("dep_upi", "depm_cw"):
        key = "upi_status" if data == "dep_upi" else "cwallet_status"
        if not is_method_on(key):
            await safe_answer_cb(e, "❌ This payment method is currently disabled.", alert=True)
            return True
        return False
    if data.startswith("join_fight|"):
        await join_fight(e, uid, data.split("|")[1])
        return True
    if data.startswith("g_open|"):
        await render_giveaway(e, data.split("|", 1)[1])
        return True
    if data.startswith("g_buy|"):
        _, gid, qty = data.split("|")
        ok, msg = await buy_giveaway_tickets(uid, gid, int(qty))
        await safe_answer_cb(e, re.sub(r"<[^>]+>", "", msg), alert=True)
        await render_giveaway(e, gid)
        if ok:
            await maybe_finish_giveaway(gid)
        return True
    if data.startswith("g_custom|"):
        gid = data.split("|", 1)[1]
        row = cur.execute("SELECT ticket_price, status FROM giveaways WHERE id=?", (gid,)).fetchone()
        if not row or row[1] != "open":
            await safe_answer_cb(e, "❌ Giveaway closed.", alert=True)
            return True
        giveaway_ticket_state[uid] = gid
        await safe_show_message(e, f"Send how many tickets to buy ({P_INR}{row[0]} each):", buttons=[[p_btn("Back", f"g_open|{gid}")]])
        return True
    if data.startswith("sm_kill|") or data.startswith("sm_kill_all|"):
        await session_manager_action(e, uid, data)
        return True
    return False


async def handle_phase5_text(e, uid, text):
    if uid in giveaway_ticket_state:
        gid = giveaway_ticket_state.pop(uid)
        if not text.strip().isdigit() or not 0 < int(text.strip()) <= 1000:
            await e.reply("❌ Send a valid ticket count (1–1000).", buttons=[[p_btn("Back", f"g_open|{gid}")]])
            return True
        ok, msg = await buy_giveaway_tickets(uid, gid, int(text.strip()))
        await e.reply(msg, buttons=[[p_btn("Open Giveaway", f"g_open|{gid}")]])
        if ok:
            await maybe_finish_giveaway(gid)
        return True
    if uid in lookup_search_state and is_admin(uid):
        lookup_search_state.pop(uid, None)
        await perform_360_user_lookup(e, uid, text.strip())
        return True
    if uid in logout_search_state:
        logout_search_state.pop(uid, None)
        await process_hex_or_string_logout_input(e, uid, text)
        return True
    return False


# ---------------- ADMIN: TOOLS ----------------
async def phase5_admin(event, action_data, uid, chat):
    if action_data == "tools" and has_perm(uid, "p_settings"):
        btns = [[Button.inline("🎁 Create Giveaway", "adm_creategiveaway"), Button.inline("⚠️ Bulk Warn", "adm_bulkwarn")],
                [Button.inline("🔑 API Credentials", "adm_apimenu"), Button.inline("🗄 Backup / Restore", "adm_bkmenu")],
                [Button.inline("👥 Referral Settings", "adm_refmenu"), Button.inline("📡 Live Stats", "adm_live_ref")],
                [Button.inline("🤝 Edit Sales Balance", "adm_salesbal")],
                [Button.inline("Back", "adm_adminmain")]]
        await event.edit(f"{PE_CROWN} <b>Admin Tools</b>", buttons=btns)
        return True
    if action_data == "live_ref" and is_admin(uid):
        await event.answer("Refreshing...", alert=False)
        await handle_live_command(event)
        return True
    if action_data == "payments" and has_perm(uid, "p_settings"):
        btns = [[Button.inline(f"UPI: {'🟢 ON' if is_method_on('upi_status') else '🔴 OFF'}", "adm_tgl_upi"),
                 Button.inline(f"Cwallet: {'🟢 ON' if is_method_on('cwallet_status') else '🔴 OFF'}", "adm_tgl_cw")],
                [Button.inline(f"Fight Game: {'🟢 ON' if is_method_on('fight_game_status') else '🔴 OFF'}", "adm_tgl_fight")],
                [Button.inline("Set $ Rate", "adm_usdtrate")],
                [Button.inline("Add Payment Method", "adm_addpay"), Button.inline("Remove Payment Method", "adm_delpay")],
                [Button.inline("Back", "adm_adminmain")]]
        await event.edit(f"{P_CARD} <b>Payment Methods & Toggles</b>", buttons=btns)
        return True
    if action_data in ("tgl_upi", "tgl_cw", "tgl_fight") and has_perm(uid, "p_settings"):
        key = {"tgl_upi": "upi_status", "tgl_cw": "cwallet_status", "tgl_fight": "fight_game_status"}[action_data]
        ns = "off" if is_method_on(key) else "on"
        cur.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (key, ns))
        db.commit()
        await event.answer(f"{key} → {ns.upper()}", alert=True)
        return await phase5_admin(event, "payments", uid, chat)

    if action_data == "refmenu" and has_perm(uid, "p_settings"):
        mode, trig, val = get_ref_mode(), get_ref_trigger(), get_ref_bonus()
        btns = [[Button.inline(f"Type: {'Flat ₹' if mode == 'flat' else 'Percent %'}", "adm_ref_mode")],
                [Button.inline(f"Trigger: {'On Join' if trig == 'join' else 'On First Deposit'}", "adm_ref_trig")],
                [Button.inline(f"Value: {val}{'%' if mode == 'percent' else ' ₹'}", "adm_refpct")],
                [Button.inline("Back", "adm_tools")]]
        await event.edit("👥 <b>Referral Settings</b>\n\n<i>Percent applies only when the trigger is First Deposit; on Join the flat ₹ value is used.</i>", buttons=btns)
        return True
    if action_data in ("ref_mode", "ref_trig") and has_perm(uid, "p_settings"):
        if action_data == "ref_mode":
            cur.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('ref_mode',?)", ("percent" if get_ref_mode() == "flat" else "flat",))
        else:
            cur.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('ref_trigger',?)", ("deposit" if get_ref_trigger() == "join" else "join",))
        db.commit()
        return await phase5_admin(event, "refmenu", uid, chat)

    if action_data == "apimenu" and has_perm(uid, "p_settings"):
        rows = cur.execute("SELECT id, api_id FROM api_credentials ORDER BY id").fetchall()
        txt = "🔑 <b>API Credential Pool</b>\n<i>Sell/import/session tools pick one at random; .env is the fallback.</i>\n\n" + ("\n".join(f"#{i}: <code>{a}</code>" for i, a in rows) or "Pool empty (using .env credentials).")
        btns = [[Button.inline("➕ Add", "adm_api_add"), Button.inline("➖ Remove", "adm_api_del")], [Button.inline("Back", "adm_tools")]]
        await event.edit(txt, buttons=btns)
        return True
    if action_data == "bkmenu" and has_perm(uid, "p_settings"):
        btns = [[Button.inline("💾 DB Backup (.db)", "adm_bk_db"), Button.inline("🧾 JSON Backup", "adm_bk_json")],
                [Button.inline("♻️ Restore (.db / .json)", "adm_bk_restore")], [Button.inline("Back", "adm_tools")]]
        await event.edit("🗄 <b>Backup / Restore</b>", buttons=btns)
        return True
    if action_data in ("bk_db", "bk_json") and has_perm(uid, "p_settings"):
        path = f"bot_backup_{int(time.time())}.{'db' if action_data == 'bk_db' else 'json'}"
        try:
            if action_data == "bk_db":
                dst = sqlite3.connect(path)
                db.backup(dst)
                dst.close()
            else:
                export_json_backup(path)
            await bot.send_file(chat, path, caption="✅ Backup (contains user data — keep it private)")
        except Exception as ex:
            await send_admin_error("Backup failed", str(ex))
            await event.answer("Backup failed", alert=True)
        finally:
            if os.path.exists(path):
                os.remove(path)
        return True
    if action_data == "bk_restore" and has_perm(uid, "p_settings"):
        restore_state[uid] = True
        await event.edit("♻️ <b>Restore</b>\n\nSend the <b>.db</b> or <b>.json</b> backup file now.\n<b>This replaces current data.</b>", buttons=[[Button.inline("❌ Cancel", "cancel_action")]])
        return True

    flows = {"creategiveaway", "bulkwarn", "api_add", "api_del", "salesbal"}
    if action_data in flows and has_perm(uid, "p_settings"):
        async with bot.conversation(chat, timeout=300) as conv:
            try:
                if action_data == "creategiveaway":
                    prize = await conv_ask(conv, "🎁 Prize name:")
                    price = int(await conv_ask(conv, "🎟 Ticket price (₹):"))
                    min_p = int(await conv_ask(conv, "👥 Participants needed to draw:"))
                    wins = int(await conv_ask(conv, "🏆 Number of winners:"))
                    if min(price, min_p, wins) <= 0:
                        raise ValueError("values must be > 0")
                    gid = create_giveaway(prize, price, min_p, wins, uid)
                    me = await bot.get_me()
                    await conv.send_message(f"{P_YES} Giveaway created.\nLink: <code>https://t.me/{me.username}?start={gid}</code>", buttons=[[Button.inline("Open", f"g_open|{gid}")]])
                elif action_data == "bulkwarn":
                    txt = await conv_ask(conv, "⚠️ Warning text to send to ALL users (HTML ok):")
                    users = cur.execute("SELECT user_id FROM users WHERE banned=0").fetchall()
                    ok = bad = 0
                    for (u,) in users:
                        try:
                            await bot.send_message(int(u), f"⚠️ <b>Notice</b>\n\n{txt}")
                            ok += 1
                        except Exception:
                            bad += 1
                        await asyncio.sleep(0.07)
                    await conv.send_message(f"{P_YES} Warning sent: {ok} delivered, {bad} failed.")
                elif action_data == "api_add":
                    aid = int(await conv_ask(conv, "🔑 API ID:"))
                    ah = await conv_ask(conv, "🔑 API HASH:")
                    if len(ah) < 20:
                        raise ValueError("api hash looks too short")
                    cur.execute("INSERT INTO api_credentials (api_id, api_hash) VALUES (?,?)", (aid, ah))
                    db.commit()
                    await conv.send_message(f"{P_YES} Credential added to the pool.")
                elif action_data == "api_del":
                    cid = int(await conv_ask(conv, "Send the credential # to remove:"))
                    cur.execute("DELETE FROM api_credentials WHERE id=?", (cid,))
                    db.commit()
                    await conv.send_message(f"{P_YES} Removed (if it existed).")
                elif action_data == "salesbal":
                    t = int(await conv_ask(conv, "👤 User ID:"))
                    amt = int(await conv_ask(conv, "💰 Amount to ADD to sales balance (negative to deduct):"))
                    async with get_user_lock(t):
                        cur.execute("UPDATE users SET sales_balance = COALESCE(sales_balance,0) + ? WHERE user_id=? AND COALESCE(sales_balance,0) + ? >= 0", (amt, t, amt))
                        ok = cur.rowcount
                        db.commit()
                    await conv.send_message(f"{P_YES} Updated." if ok else f"{P_NO} User not found or balance would go negative.")
            except ConvCancelled:
                await conv.send_message(f"{P_NO} Cancelled.")
            except (ValueError, TypeError) as ex:
                await conv.send_message(f"{P_NO} Invalid input: {html.escape(str(ex)[:80])}")
            except asyncio.TimeoutError:
                await conv.send_message(f"{P_WARN} Timed out.")
        return True
    return False


@bot.on(events.NewMessage(pattern=r"(?i)^/start"))
async def handle_start(e):
    try:
        uid = e.sender_id
        if not uid or not e.is_private:
            return

        ensure_user(uid)
        if is_user_banned(uid):
            return

        if not is_bot_online() and not is_admin(uid):
            return await e.respond(f"{P_OFF} <b>Bot is currently under maintenance.</b> Please try again later.")

        session_buy_state.pop(uid, None)
        deposit_input.pop(uid, None)

        text = e.raw_text or ''
        deep_link = None
        if len(text.split()) > 1:
            start_param = text.split()[1]
            if start_param.startswith("server1-") or start_param == "AllServer1" or start_param.startswith("Giv_"):
                deep_link = start_param
            if start_param.startswith("ref_"):
                ref = start_param.replace("ref_", "")
                if ref.isdigit() and int(ref) != uid:
                    cur.execute("UPDATE users SET referred_by=? WHERE user_id=? AND referred_by IS NULL", (int(ref), uid))
                    db.commit()

        is_joined = await check_channel_joined(uid)
        if not is_joined:
            return await e.respond(JOIN_MSG, buttons=get_join_buttons())
        _join_cache[uid] = time.time()

        await reward_referrer_on_join(uid)

        if not terms_accepted(uid):
            return await e.respond(TERMS_MSG, buttons=get_terms_buttons())

        await send_main_menu(e, uid)
        if deep_link:
            if deep_link.startswith("Giv_"):
                await render_giveaway(e, deep_link)
            elif deep_link == "AllServer1":
                await send_all_countries_list(uid)
            else:
                cname = find_country_by_slug(deep_link[len("server1-"):])
                if cname:
                    await e.respond(f"{LZT_COUNTRIES[cname][1]} <b>{cname}</b> – Server 1", buttons=[[p_btn("📦 Open Catalog", f"lzt_chk|{LZT_COUNTRIES[cname][0]}|1")]])
    except Exception as ex:
        logger.error(f"Start Error: {ex}")


@bot.on(events.NewMessage())
async def handle_all_messages(e):
    try:
        uid = e.sender_id
        if not uid or not e.is_private:
            return
        if getattr(e, 'raw_text', None) and e.raw_text.startswith('/'):
            return
        if not is_bot_online() and not is_admin(uid):
            return await e.respond(f"{P_OFF} <b>Bot is currently under maintenance.</b> Please try again later.")

        ensure_user(uid)
        if is_user_banned(uid):
            return
        try:
            track_user_identity(await e.get_sender())
        except Exception:
            pass

        # Join + Terms gate (type karke bypass nahi ho sakta)
        if not is_admin(uid):
            if not await is_joined_cached(uid):
                return await e.respond(JOIN_MSG, buttons=get_join_buttons())
            if not terms_accepted(uid):
                return await e.respond(TERMS_MSG, buttons=get_terms_buttons())

        if uid in restore_state and is_admin(uid) and e.file:
            return await handle_restore_file(e, uid)

        if e.file and (e.file.name or "").endswith(".session") and is_admin(uid) and has_perm(uid, "p_add_stock"):
            return await admin_add_session_file(e, uid)

        if uid in waiting_proof and (e.photo or (e.raw_text and "http" in e.raw_text)):
            info = waiting_proof.pop(uid)
            final_amt = info['amount']
            if info['method'] == "Cwallet":
                final_amt = int(final_amt * 1.05)

            cur.execute("INSERT INTO deposits (user_id, amount, method_name, status) VALUES (?,?,?,?)", (uid, final_amt, info['method'], "pending"))
            db.commit()
            dep_id = cur.lastrowid
            await e.reply(f"{PE_GIFT} Deposit request submitted! Please wait for admin approval.")
            cap = (f"{PE_LIGHTNING} <b>NEW DEPOSIT REQUEST</b>\n{P_ACC} User: <code>{uid}</code>\n"
                   f"{P_MONEY} Request: <b>{P_INR}{info['amount']}</b>\n{P_CARD} Method: {html.escape(info['method'])}\n"
                   f"{P_ID} Ref: <code>{dep_id}</code>")
            btns = deposit_request_buttons(dep_id, uid, final_amt, with_custom=True)

            try:
                if e.photo:
                    await bot.send_message(LOG_CHANNEL_ID, cap, file=e.media, buttons=btns)
                else:
                    await bot.send_message(LOG_CHANNEL_ID, cap + f"\n🔗 Hash: {html.escape(e.raw_text)}", buttons=btns)
            except Exception as log_err:
                logger.error(f"Failed to log deposit: {log_err}")
            return

        text = e.raw_text or ""
        if not text:
            return
        t = text.strip()

        # Sirf EXACT menu button dabane par purani states clear hoti hain
        is_menu = t in MENU_LABELS
        if is_menu:
            session_buy_state.pop(uid, None)
            deposit_input.pop(uid, None)
            waiting_proof.pop(uid, None)
            admin_dep_state.pop(uid, None)
            promo_state.pop(uid, None)
            wd_state.pop(uid, None)
            lzt_search_state.pop(uid, None)
            wa_sell_state.pop(uid, None)
            giveaway_ticket_state.pop(uid, None)
            lookup_search_state.pop(uid, None)
            logout_search_state.pop(uid, None)
            restore_state.pop(uid, None)
            await nc_cleanup(uid)
            await sell_cleanup_state(uid)

        if is_admin(uid) and uid in admin_dep_state:
            st = admin_dep_state[uid]
            if st['step'] == 'wait_reason':
                t_uid, dep_id, msg_id = st['target_uid'], st['dep_id'], st['msg_id']
                cur.execute("UPDATE deposits SET status='rejected' WHERE id=? AND status='pending'", (dep_id,))
                changed = cur.rowcount
                db.commit()
                admin_dep_state.pop(uid, None)
                if not changed:
                    return await e.reply(f"{P_WARN} Ye deposit pehle hi process ho chuka hai.")

                try:
                    await bot.edit_message(LOG_CHANNEL_ID, msg_id, f"{P_NO} <b>REJECTED USER {t_uid}</b>\nReason: {html.escape(text)}")
                except Exception:
                    pass

                try:
                    await bot.send_message(int(t_uid), f"{P_NO} <b>Deposit Rejected!</b>\n📋 Reason: {html.escape(text)}")
                except Exception:
                    pass
                await e.reply(f"{P_YES} Rejection reason sent.")
                return

        if not is_menu:
            if await handle_sell_text(e, uid, t):
                return
            if await handle_promo_text(e, uid, t):
                return
            if await handle_wd_text(e, uid, t):
                return
            if await handle_lzt_search_text(e, uid, t):
                return
            if await handle_phase4_text(e, uid, t):
                return
            if await handle_phase5_text(e, uid, t):
                return

        if uid in session_buy_state:
            state = session_buy_state[uid]
            try:
                qty = int(re.sub(r'[^\d]', '', text))
                if qty < 1:
                    raise ValueError
            except ValueError:
                return await e.respond(f"{P_NO} Please enter a valid number.")

            if qty > state['stock']:
                return await e.respond(f"{P_WARN} <b>Not enough stock!</b> Max is {state['stock']}.")

            disc_row = cur.execute("SELECT discount FROM users WHERE user_id=?", (uid,)).fetchone()
            discount = disc_row[0] if disc_row else 0
            total_cost = qty * state['price']
            if discount > 0:
                total_cost = int(total_cost * (100 - discount) / 100)

            bal_row = cur.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
            user_bal = bal_row[0] if bal_row else 0
            if user_bal < total_cost:
                return await e.respond(f"{P_NO} <b>Insufficient Balance!</b>\nYou need {P_INR}{total_cost} to buy {qty} sessions.")

            session_buy_state.pop(uid, None)
            await process_bulk_sessions(e, uid, qty, state, total_cost)
            return

        if uid in deposit_input and deposit_input[uid]['step'] == 'wait_amt':
            try:
                amt = int(re.sub(r'[^\d]', '', text))
            except ValueError:
                return await e.respond(f"{P_NO} Please enter a valid number in {P_INR} (INR).")
            if amt < 10:
                return await e.reply(f"{P_WARN} Minimum Deposit is ₹10.")
            method = deposit_input[uid]['method']
            waiting_proof[uid] = {'amount': amt, 'method': method}
            deposit_input.pop(uid)

            rate = get_usdt_rate()
            usdt_amt = round(amt / rate, 2)
            rate_text = f"\n\n{P_MONEY} <b>Amount to Pay:</b> {P_INR}{amt} (~{P_USDT}{usdt_amt} USDT)\n💱 <i>Exchange Rate: {P_INR}{rate} = $1</i>"
            cancel_btn = [[Button.inline("❌ Cancel", "cancel_action")]]

            if method == "Cwallet":
                msg = (f"{P_CARD} <b>Method:</b> {method}\n\n🚀 <b>Address / ID:</b>\n<code>{CWALLET_ID}</code>"
                       f"{rate_text}\n\n👉 <b>Send Proof:</b>\nPlease send the Transaction Hash (Link) or a Screenshot of the payment now.")
                try:
                    await bot.send_file(uid, CWALLET_QR, caption=msg, buttons=cancel_btn)
                except Exception:
                    await bot.send_message(uid, msg + f"\n\n🔗 QR Link: {CWALLET_QR}", buttons=cancel_btn)
            else:
                row = cur.execute("SELECT caption, qr_file_id FROM custom_payments WHERE name=?", (method,)).fetchone()
                if row:
                    cap = row[0] + f"{rate_text}\n\n👇 <b>After paying, send a clear Screenshot here:</b>"
                    if row[1] and os.path.exists(row[1]):
                        try:
                            await bot.send_file(e.chat_id, row[1], caption=cap, buttons=cancel_btn)
                        except Exception:
                            await e.reply(cap, buttons=cancel_btn)
                    else:
                        await e.reply(cap, buttons=cancel_btn)
                else:
                    await e.reply(f"{P_CARD} <b>{html.escape(method)} Deposit</b>{rate_text}\n\n👇 Send Screenshot here:", buttons=cancel_btn)
            return

        # Menu dispatch: EXACT match (pehle "Support" in text jaisa loose check tha)
        if t == BTN_BUY:
            await show_buy_servers(e, uid)
        elif t == BTN_SESSIONS:
            await show_categories(e, 'bulk')
        elif t == BTN_SELL:
            await show_sell_menu(e)
        elif t == BTN_SELL_SESSIONS:
            await show_sell_sessions(e, uid)
        elif t == BTN_PROMO:
            await start_promo(e)
        elif t == BTN_DEPOSIT:
            await deposit_menu(e)
        elif t == BTN_PROFILE:
            await profile_handler(e)
        elif t == BTN_STATS:
            await stats_handler(e)
        elif t == BTN_REFER:
            await refer_handler(e)
        elif t == BTN_SUPPORT:
            await e.reply(f"{PE_ANGEL} <b>Vinnu Store Support & Relevant Information</b>\n\n{P_WARN} For support contact admin or use the buttons below.", buttons=get_support_buttons())
        elif t == BTN_ADMIN:
            if is_admin(uid):
                await admin_panel_handler(e)

    except Exception as ex:
        logger.error(f"Message Error: {ex}")


@bot.on(events.CallbackQuery)
async def handle_callback_query(e):
    try:
        uid = e.sender_id
        if not is_bot_online() and not is_admin(uid):
            return await e.answer("⚙️ Bot is under maintenance.", alert=True)

        ensure_user(uid)
        now = time.time()
        if uid in user_spam_cooldown and now - user_spam_cooldown[uid] < 0.5:
            return await e.answer("⚠️ Please slow down! Don't spam buttons.", alert=True)
        user_spam_cooldown[uid] = now

        if is_user_banned(uid):
            return await e.answer("🚫 BANNED", alert=True)
        data = e.data.decode()

        # Private-chat only (admins may still act on approval buttons inside the log channel/group)
        if not e.is_private and not (is_admin(uid) and data.startswith(GROUP_ADMIN_CB_PREFIXES)):
            return await e.answer("Please use this bot in private chat.", alert=True)

        # Join + Terms gate (purane buttons se bypass roko)
        if data not in ("verify_join", "tc_accept", "tc_reject") and not is_admin(uid):
            if not await is_joined_cached(uid):
                return await e.answer("⚠️ Pehle channels join karo. /start dabao.", alert=True)
            if not terms_accepted(uid):
                return await e.answer("⚠️ Pehle Terms accept karo. /start dabao.", alert=True)

        if await phase2_callbacks(e, uid, data):
            return
        if await phase3_callbacks(e, uid, data):
            return
        if await phase4_callbacks(e, uid, data):
            return
        if await phase5_callbacks(e, uid, data):
            return

        if data == "verify_join":
            if not await check_channel_joined(uid):
                return await e.answer("⚠️ You must join the channels first!", alert=True)
            _join_cache[uid] = time.time()
            await reward_referrer_on_join(uid)
            if not terms_accepted(uid):
                try:
                    await e.edit(TERMS_MSG, buttons=get_terms_buttons())
                except MessageNotModifiedError:
                    pass
                return
            await send_main_menu(e, uid)

        elif data == "tc_accept":
            if not await is_joined_cached(uid):
                return await e.answer("⚠️ Pehle channels join karo. /start dabao.", alert=True)
            cur.execute("UPDATE users SET terms_accepted=1 WHERE user_id=?", (uid,))
            db.commit()
            await e.answer("✅ Terms Accepted!", alert=True)
            await send_main_menu(e, uid)

        elif data == "tc_reject":
            try:
                await e.edit(f"{P_NO} You cannot use the bot without accepting the terms.")
            except MessageNotModifiedError:
                pass

        elif data == "cancel_action":
            deposit_input.pop(uid, None)
            waiting_proof.pop(uid, None)
            session_buy_state.pop(uid, None)
            try:
                await e.edit(f"{P_NO} <b>Cancelled.</b>")
            except MessageNotModifiedError:
                pass

        elif data.startswith("catmenu|"):
            p = data.split("|")
            await show_categories(e, p[1])

        elif data.startswith("cat|"):
            p = data.split("|")
            await show_countries(e, p[1], p[2], 1)

        elif data.startswith("pg_c|"):
            p = data.split("|")
            await show_countries(e, p[1], p[2], int(p[3]))

        elif data.startswith("bc|"):
            p = data.split("|")
            await show_years(e, p[1], p[2], p[3])

        elif data.startswith("by|"):
            p = data.split("|")
            if p[1] == 'single':
                await show_account_info(e, p[2], p[3], p[4], p[5])
            else:
                country = resolve_country(p[2], p[3])
                if not country:
                    return await e.answer("❌ Stock changed, please go back and reselect.", alert=True)
                await init_session_purchase(e, p[2], country, p[4], p[5])

        elif data.startswith("pc|"):
            p = data.split("|")
            await confirm_purchase(e, p[1], p[2], p[3], p[4])

        elif data.startswith("buy_cf|"):
            p = data.split("|")
            await process_purchase(e, p[1], p[2], p[3], p[4])

        elif data.startswith("get_otp_again|"):
            phone = data.split("|")[1]
            if phone not in active_orders:
                return await e.answer("⚠️ Session already logged out or expired.", alert=True)

            order = active_orders[phone]
            if order['uid'] != uid:
                return await e.answer("❌ Ye order aapka nahi hai.", alert=True)
            client = order['client']
            start_time = order['start_time']

            await e.answer("🔄 Fetching latest OTP...", alert=False)
            try:
                msgs = await client.get_messages(777000, limit=5)
                latest_code = extract_login_code(msgs, start_time)

                if latest_code:
                    msg = otp_message(order, phone, latest_code, f"{P_YES} <b>Latest OTP Fetched!</b>")
                    try:
                        await e.edit(msg, buttons=otp_buttons(phone))
                    except MessageNotModifiedError:
                        pass
                else:
                    await e.answer("⏳ No new OTP found yet. Try again in a few seconds.", alert=True)
            except Exception as ex:
                logger.warning(f"get_otp_again error {phone}: {ex}")
                await e.answer("❌ Error fetching OTP.", alert=True)

        elif data.startswith("logout_bot|"):
            phone = data.split("|")[1]
            order = active_orders.get(phone)
            if not order:
                return await e.answer("⚠️ No active order found or already logged out.", alert=True)
            if order['uid'] != uid:
                return await e.answer("❌ Ye order aapka nahi hai.", alert=True)
            try:
                await render_sessions(e, phone)
            except Exception as ex:
                logger.error(f"Sessions list error: {ex}")
                await e.answer("❌ Session list fetch nahi ho payi. Thodi der baad try karo.", alert=True)

        elif data.startswith("lo_dev|") or data.startswith("lo_all|"):
            p = data.split("|")
            phone = p[1]
            order = active_orders.get(phone)
            if not order:
                return await e.answer("⚠️ No active order found or already logged out.", alert=True)
            if order['uid'] != uid:
                return await e.answer("❌ Ye order aapka nahi hai.", alert=True)
            try:
                if p[0] == "lo_dev":
                    h = int(p[2])
                    res = await order['client'](GetAuthorizationsRequest())
                    target = next((a for a in res.authorizations if a.hash == h and not a.current), None)
                    if not target:
                        return await render_sessions(e, phone, f"{P_WARN} Ye device pehle hi logout ho chuka hai.")
                    await order['client'](ResetAuthorizationRequest(hash=h))
                    note = f"{P_YES} <b>Device logout ho gaya:</b> {html.escape(target.device_model or 'Unknown')}"
                else:
                    await order['client'](ResetAuthorizationsRequest())
                    note = f"{P_YES} <b>Saare dusre devices logout ho gaye.</b>"
                await render_sessions(e, phone, note)
            except Exception as ex:
                logger.error(f"Device logout error: {ex}")
                if "FRESH_RESET" in str(ex).upper():
                    await e.answer("⚠️ Telegram rule: dusre devices tabhi hat sakte hain jab bot ka session 24 ghante se purana ho. Baad me try karo.", alert=True)
                else:
                    await e.answer("❌ Device logout nahi ho paya. Thodi der baad try karo.", alert=True)

        elif data.startswith("logout_no|"):
            phone = data.split("|")[1]
            order = active_orders.get(phone)
            if not order or order['uid'] != uid:
                return await e.answer("⚠️ No active order found.", alert=True)
            await e.edit(f"↩️ <b>Logout cancelled.</b>\n{P_PHONE} <code>{phone}</code>\nOTP dobara chahiye to neeche button dabao.", buttons=otp_buttons(phone))

        elif data.startswith("logout_cf|"):
            phone = data.split("|")[1]
            order = active_orders.get(phone)
            if not order:
                return await e.answer("⚠️ No active order found or already logged out.", alert=True)
            if order['uid'] != uid:
                return await e.answer("❌ Ye order aapka nahi hai.", alert=True)
            order = active_orders.pop(phone)
            try:
                await order['client'].log_out()
            except Exception:
                pass
            try:
                await order['client'].disconnect()
            except Exception:
                pass
            delete_session_files(order['sess'])
            await e.edit(f"{P_YES} <b>Session Finished & Logged out successfully.</b>")

        elif data.startswith("page_purchases_"):
            await send_purchase_page(e, uid, int(data.split("_")[2]))
        elif data == "back_to_stats":
            await stats_handler(e, is_callback=True)
        elif data == "view_referrals":
            await view_referrals(e)

        elif data.startswith("depm_"):
            await manual_deposit_init(e, data.replace("depm_", ""))
        elif data == "dep_upi":
            await init_upi_keypad(e)
        elif data.startswith("kp_"):
            await keypad_logic(e)
        elif data.startswith("submit_utr_"):
            await verify_upi_payment(e, data.replace("submit_utr_", ""))

        elif data.startswith("adm_") and is_admin(uid):
            await admin_actions(e)

        elif data.startswith("dkp|") and has_perm(uid, 'p_bal'):
            _, dep_id, action = data.split("|")
            dep_id = int(dep_id)
            row = cur.execute("SELECT user_id, method_name, status, amount FROM deposits WHERE id=?", (dep_id,)).fetchone()
            if not row or row[2] != 'pending':
                return await e.edit(f"{P_WARN} Already processed.")
            t_uid, method, orig_amt = row[0], row[1], row[3]

            curr = custom_dep_amt.get(dep_id, "0")

            if action.isdigit():
                if curr == "0":
                    curr = action
                else:
                    curr += action
                if len(curr) > 7:
                    curr = curr[:7]
            elif action == "del":
                curr = curr[:-1] or "0"
            elif action == "cancel":
                custom_dep_amt.pop(dep_id, None)
                return await e.edit(f"{PE_LIGHTNING} <b>NEW DEPOSIT REQUEST</b>\n{P_ACC} User: <code>{t_uid}</code>\n{P_MONEY} Request: <b>{P_INR}{orig_amt}</b>\n{P_CARD} Method: {html.escape(method)}\n{P_ID} Ref: <code>{dep_id}</code>",
                                    buttons=deposit_request_buttons(dep_id, t_uid, orig_amt, with_custom=True))
            elif action == "conf":
                amt = int(curr)
                if amt <= 0:
                    return await e.answer("Amount must be > 0", alert=True)

                res = await approve_deposit(dep_id, amt)
                if not res:
                    return await e.edit(f"{P_WARN} Already processed.")
                t_uid, method, prev_bal = res
                custom_dep_amt.pop(dep_id, None)

                await process_referral_bonus(t_uid, amt)
                await e.edit(f"{PE_CHECK} <b>APPROVED {P_INR}{amt} TO {t_uid} (Custom Amount)</b>")
                try:
                    await bot.send_message(int(t_uid), f"{PE_CHECK} <b>Deposit Approved!</b>\n{P_MONEY} Amount Added: {P_INR}{amt}\n📉 Old: {P_INR}{prev_bal} | 📈 New: {P_INR}{prev_bal+amt}")
                except Exception:
                    pass
                await log_primary_deposit(t_uid, amt, method)
                return

            custom_dep_amt[dep_id] = curr
            try:
                await e.edit(f"{P_KEY} <b>Enter Custom Amount for User {t_uid}:</b>\n\n{P_MONEY} {curr}", buttons=get_admin_custom_keypad(dep_id))
            except MessageNotModifiedError:
                pass

        elif data.startswith("dep_acc|") and has_perm(uid, 'p_bal'):
            # Format: dep_acc|dep_id|user_id|exact/custom|amount
            p = data.split("|")
            dep_id, t_uid, a_type = int(p[1]), int(p[2]), p[3]
            row = cur.execute("SELECT status FROM deposits WHERE id=?", (dep_id,)).fetchone()
            if not row or row[0] != 'pending':
                return await e.edit(f"{P_WARN} Already processed.")

            if a_type == "exact":
                amt = int(p[4])
                res = await approve_deposit(dep_id, amt)
                if not res:
                    return await e.edit(f"{P_WARN} Already processed.")
                t_uid, method, prev_bal = res

                await process_referral_bonus(t_uid, amt)

                user_msg = (f"{PE_CHECK} <b>Deposit Approved!</b>\n\n{P_MONEY} <b>Amount Added:</b> ${to_usd(amt):.2f} ({P_INR}{amt})\n"
                            f"📉 <b>Previous Balance:</b> ${to_usd(prev_bal):.2f} ({P_INR}{prev_bal})\n📈 <b>New Balance:</b> ${to_usd(prev_bal+amt):.2f} ({P_INR}{prev_bal+amt})")
                try:
                    await bot.send_message(int(t_uid), user_msg)
                except Exception:
                    pass
                try:
                    await e.edit(f"{PE_CHECK} <b>INSTANT CREDITED {P_INR}{amt} TO {t_uid}</b>")
                except MessageNotModifiedError:
                    pass
                await log_primary_deposit(t_uid, amt, method)

            elif a_type == "custom":
                custom_dep_amt[dep_id] = "0"
                await e.edit(f"{P_KEY} <b>Enter Custom Amount for User {t_uid}:</b>\n\n{P_MONEY} 0", buttons=get_admin_custom_keypad(dep_id))

        elif data.startswith("dep_rej|") and has_perm(uid, 'p_bal'):
            p = data.split("|")
            dep_id, t_uid = int(p[1]), int(p[2])
            row = cur.execute("SELECT status FROM deposits WHERE id=?", (dep_id,)).fetchone()
            if not row or row[0] != 'pending':
                return await e.edit(f"{P_WARN} Already processed.")
            admin_dep_state[uid] = {'target_uid': t_uid, 'dep_id': dep_id, 'step': 'wait_reason', 'msg_id': e.message_id}
            await bot.send_message(uid, f"{P_WARN} Reply to this message with the REASON for rejecting user <code>{t_uid}</code>:")
            try:
                await e.answer("Check your bot PMs to enter the reason.", alert=True)
            except Exception:
                pass

    except Exception as ex:
        logger.error(f"Callback Error: {ex}")


async def main():
    await recover_pending_orders()
    await recover_sell_holds()
    asyncio.create_task(cache_lzt_stock_loop())
    asyncio.create_task(fight_expiry_loop())
    asyncio.create_task(upi_expiry_loop())
    print("✅ ULTIMATE ADVANCED HTML BOT STARTED SUCCESSFULLY")
    await bot.run_until_disconnected()


if __name__ == '__main__':
    bot.start(bot_token=BOT_TOKEN)
    bot.loop.run_until_complete(main())
