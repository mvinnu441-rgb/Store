"""
Vinnu Account Store — Unified Telegram Bot
Single-file production build. Copy-paste runnable.
"""
import os
import sqlite3
import re
import asyncio
import time
import logging
import csv
import zipfile
import shutil
import html
import hashlib
import string as _string
import json
import random
import socket
import ssl
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

from telethon import TelegramClient, events, Button
from telethon.errors import (
    SessionPasswordNeededError, MessageNotModifiedError, UserNotParticipantError,
    ChatAdminRequiredError, PhoneCodeInvalidError, PhoneCodeExpiredError,
    PhoneNumberInvalidError, PhoneNumberBannedError, FloodWaitError,
)
from telethon.sessions import StringSession
from telethon.tl.types import ReplyKeyboardMarkup, KeyboardButtonRow, KeyboardButton
from telethon.extensions import html as tl_html
from telethon.tl import types as tl_types
from telethon.tl.functions.channels import GetParticipantRequest
from telethon.tl.functions.account import (
    GetPasswordRequest, GetAuthorizationsRequest, ResetAuthorizationRequest,
)
from telethon.tl.functions.auth import ResetAuthorizationsRequest

import aiohttp

# ================= LOGGING =================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[logging.FileHandler("bot.log", encoding="utf-8"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


# ================= CONFIG =================
def load_env_file(path=".env"):
    if not os.path.exists(path):
        return
    try:
        with open(path, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except Exception as ex:
        print(f"Failed to load {path}: {ex}")


load_env_file()


def env_int(name, default=0):
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(str(raw).strip())
    except Exception:
        return default


def env_float(name, default=0.0):
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return float(str(raw).strip())
    except Exception:
        return default


def env_list(name, default_csv=""):
    raw = os.getenv(name, default_csv)
    return [x.strip() for x in raw.split(",") if x.strip()]


API_ID = env_int("API_ID", 31626369)
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = env_int("ADMIN_ID", 0)

LOG_CHANNEL_ID = env_int("LOG_CHANNEL_ID", 0)
LOOG_CHANNEL_ID = env_int("LOOG_CHANNEL_ID", 0)
CHECK_CHANNELS = env_list("CHECK_CHANNELS", "")
JOIN_URLS = env_list("JOIN_URLS", "")

TERMS_URL = os.getenv("TERMS_URL", "https://example.com/terms")
if not TERMS_URL.startswith("http"):
    TERMS_URL = "https://" + TERMS_URL
CWALLET_QR = os.getenv("CWALLET_QR", "https://example.com/qr.jpg")
CWALLET_ID = os.getenv("CWALLET_ID", "")

UPI_MID = os.getenv("UPI_MID", "")
UPI_ID = os.getenv("UPI_ID", "")

# LZT (Server 1)
LZT_TOKEN = os.getenv("LZT_TOKEN", "")
LZT_ENABLED = os.getenv("LZT_ENABLED", "0").strip() == "1"
LZT_MARKUP_PCT = env_float("LZT_MARKUP_PERCENT", 10.0)
LZT_PROXY = os.getenv("LZT_PROXY", "")

OTP_REGEX = r"\b\d{4,8}\b"
AUTO_CANCEL_SECONDS = 600
PAID_ORDER_TTL = 1800
NEW_2FA = "2007"

OTP_IGNORE_PHRASES = (
    "login detected", "new login", "new device", "two-step verification",
    "active sessions", "account from a new device", "account was used to",
    "settings changed", "password and/or email were changed",
    "if this wasn't you", "if somebody logged in", "if you think that somebody",
    "unusual activity", "someone tried to", "this device was logged in",
    "was deleted", "terminate that session",
)


def validate_config():
    missing = []
    if API_ID <= 0: missing.append("API_ID")
    if not API_HASH: missing.append("API_HASH")
    if not BOT_TOKEN or ":" not in BOT_TOKEN: missing.append("BOT_TOKEN")
    if ADMIN_ID <= 0: missing.append("ADMIN_ID")
    if missing:
        raise RuntimeError(f"Missing config: {', '.join(missing)}. Set in .env")
    if not CHECK_CHANNELS:
        logger.warning("CHECK_CHANNELS empty — join check disabled")
    if not JOIN_URLS:
        logger.warning("JOIN_URLS empty — join buttons hidden")
    if not UPI_ID:
        logger.warning("UPI_ID empty — UPI deposit will not work")


# ================= TEXT STYLE =================
_SMALL_CAPS = "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢ"
assert len(_SMALL_CAPS) == 26
STYLE_MAP = {}
for _i, _c in enumerate(_string.ascii_uppercase):
    STYLE_MAP[_c] = chr(0x1D400 + _i)
for _c, _sc in zip(_string.ascii_lowercase, _SMALL_CAPS):
    STYLE_MAP[_c] = _sc

STYLE_SKIP_RE = re.compile(r"@\w+|https?://\S+|t\.me/\S+|(?<!\S)/\w+")
_PROTECTED_NAMES = ("MessageEntityCode", "MessageEntityPre", "MessageEntityUrl",
                    "MessageEntityMention", "MessageEntityMentionName",
                    "InputMessageEntityMentionName", "MessageEntityBotCommand",
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


# ================= EMOJIS =================
USE_PREMIUM_EMOJIS = os.getenv("USE_PREMIUM_EMOJIS", "1").strip().lower() not in {"0", "false", "no", "off"}
PREMIUM_EMOJIS = {
    "heart_fire": "5042225965518816316", "lightning": "5042334757040423886",
    "location": "5039775669496579510", "flower": "6073117703965511893",
    "check": "6147460667281511517", "crown": "6235252066554484059",
    "kiss": "6116282026506065674", "skull": "6089128873893563936",
    "xmas": "6267071898702583835", "monkey": "6273627839862411998",
    "gift": "5893175870096414393", "angel": "5893411041030707544",
    "devil": "5893079628469246474",
}


def tg_emoji(name, fallback):
    eid = PREMIUM_EMOJIS.get(name)
    if USE_PREMIUM_EMOJIS and eid:
        return f'<tg-emoji emoji-id="{eid}">{fallback}</tg-emoji>'
    return fallback


PE_HEART = tg_emoji("heart_fire", "💖")
PE_LIGHTNING = tg_emoji("lightning", "⚡")
PE_LOCATION = tg_emoji("location", "🌍")
PE_FLOWER = tg_emoji("flower", "♻️")
PE_CHECK = tg_emoji("check", "✅")
PE_CROWN = tg_emoji("crown", "☠️")
PE_KISS = tg_emoji("kiss", "👤")
PE_GIFT = tg_emoji("gift", "🎁")
PE_ANGEL = tg_emoji("angel", "🎧")

P_YES = PE_CHECK; P_NO = '❌'; P_PKG = '📦'; P_MONEY = '💰'; P_USDT = '💲'
P_INR = '₹'; P_TG = '✈️'; P_GIFT = PE_GIFT; P_STATS = '📊'; P_CARD = '💳'
P_USERS = '👥'; P_CAL = '📅'; P_PC = '💻'; P_EYE = '👁️'; P_UPI = '🏦'
P_CW = '👛'; P_ON = '🟢'; P_OFF = '🔴'; P_ID = '🆔'; P_KEY = '⌨️'
P_GLOBE = PE_LOCATION; P_CART = '🛒'; P_STORE = '🏬'; P_OTP = '🔢'
P_2FA = '🔐'; P_FLAG = '🏳️'; P_PHONE = '📱'; P_WAIT = '⏳'; P_TIME = '⏰'
P_WARN = '⚠️'; P_DOC = '📃'; P_SOS = '🆘'; P_ASST = '🤖'; P_ACC = '👤'

# ================= MENU LABELS =================
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


# ================= INIT =================
os.makedirs("sessions", exist_ok=True)

validate_config()

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


# ================= DB SCHEMA =================
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
        category TEXT,
        country TEXT,
        year TEXT,
        price INTEGER,
        PRIMARY KEY (category, country, year)
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
    CREATE TABLE IF NOT EXISTS sell_prices (
        country_code TEXT PRIMARY KEY,
        country_name TEXT,
        flag TEXT DEFAULT '🌍',
        price_usd REAL
    );
    CREATE TABLE IF NOT EXISTS sell_submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        phone TEXT,
        country_name TEXT,
        price_usd REAL,
        price_inr INTEGER,
        session_path TEXT,
        status TEXT DEFAULT 'holding',
        reason TEXT,
        created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        decided_at TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS blacklisted_phones (
        phone TEXT PRIMARY KEY,
        reason TEXT
    );
    CREATE TABLE IF NOT EXISTS withdrawals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount INTEGER,
        method TEXT,
        upi_id TEXT,
        status TEXT DEFAULT 'pending',
        created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS promo_codes (
        code TEXT PRIMARY KEY,
        amount INTEGER,
        max_uses INTEGER DEFAULT 1,
        used INTEGER DEFAULT 0,
        expires TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS promo_claims (
        user_id INTEGER,
        code TEXT,
        claimed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (user_id, code)
    );
    CREATE TABLE IF NOT EXISTS giveaways (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        prize INTEGER,
        tickets_required INTEGER,
        ends TIMESTAMP,
        active INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS giveaway_tickets (
        user_id INTEGER,
        giveaway_id INTEGER,
        tickets INTEGER DEFAULT 0,
        PRIMARY KEY (user_id, giveaway_id)
    );
    CREATE TABLE IF NOT EXISTS fight_games (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        challenger INTEGER,
        opponent INTEGER,
        amount INTEGER,
        status TEXT DEFAULT 'open',
        winner INTEGER,
        created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS lzt_cache (
        item_id TEXT PRIMARY KEY,
        country TEXT,
        price_usd REAL,
        payload TEXT,
        spam INTEGER DEFAULT 0,
        twofa INTEGER DEFAULT 0,
        premium INTEGER DEFAULT 0,
        mail INTEGER DEFAULT 0,
        dc INTEGER DEFAULT 0,
        gifts INTEGER DEFAULT 0,
        stars INTEGER DEFAULT 0,
        has_admin INTEGER DEFAULT 0,
        origin TEXT,
        breakout TEXT,
        added TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS market_filters (
        user_id INTEGER PRIMARY KEY,
        spam TEXT DEFAULT 'any',
        twofa TEXT DEFAULT 'any',
        premium TEXT DEFAULT 'any',
        origin TEXT DEFAULT 'any',
        breakout TEXT DEFAULT 'any',
        mail TEXT DEFAULT 'any',
        dc TEXT DEFAULT 'any',
        gifts TEXT DEFAULT 'any',
        admin TEXT DEFAULT 'any',
        sort TEXT DEFAULT 'cheapest',
        profile TEXT DEFAULT 'default'
    );
    CREATE TABLE IF NOT EXISTS number_change_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        phone TEXT,
        old_number TEXT,
        new_number TEXT,
        fee INTEGER,
        status TEXT DEFAULT 'pending',
        created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS app_accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        app_name TEXT,
        country TEXT,
        email TEXT,
        password TEXT,
        price INTEGER,
        available INTEGER DEFAULT 1,
        details TEXT,
        added TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    db.commit()


setup_db()

# Migrations (safe)
for _m in [
    "ALTER TABLE users ADD COLUMN ref_rewarded INTEGER DEFAULT 0",
    "ALTER TABLE users ADD COLUMN sales_balance INTEGER DEFAULT 0",
    "ALTER TABLE stock ADD COLUMN spam INTEGER DEFAULT 0",
    "ALTER TABLE stock ADD COLUMN twofa_flag INTEGER DEFAULT 0",
    "ALTER TABLE stock ADD COLUMN premium INTEGER DEFAULT 0",
    "ALTER TABLE stock ADD COLUMN mail INTEGER DEFAULT 0",
    "ALTER TABLE stock ADD COLUMN dc INTEGER DEFAULT 0",
    "ALTER TABLE stock ADD COLUMN origin TEXT",
    "ALTER TABLE stock ADD COLUMN breakout TEXT",
    "ALTER TABLE stock ADD COLUMN gifts INTEGER DEFAULT 0",
    "ALTER TABLE stock ADD COLUMN stars INTEGER DEFAULT 0",
    "ALTER TABLE stock ADD COLUMN has_admin INTEGER DEFAULT 0",
]:
    try:
        cur.execute(_m); db.commit()
    except sqlite3.OperationalError:
        pass


# ================= HELPERS =================
def is_bot_online():
    r = cur.execute("SELECT value FROM settings WHERE key='bot_status'").fetchone()
    return (r[0] == 'on') if r else True


def setting_get(key, default=None):
    r = cur.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r[0] if r else default


def setting_set(key, val):
    cur.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (key, str(val)))
    db.commit()


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
    try:
        return float(setting_get("usdt_rate", "94") or 94)
    except Exception:
        return 94.0


def get_support_url():
    url = setting_get("support_url", "https://t.me/vinnu_exe")
    if not url.startswith("http"):
        url = "https://" + url.replace("@", "t.me/")
    return url


def to_usd(inr):
    return round(inr / get_usdt_rate(), 2)


def is_user_banned(uid):
    r = cur.execute("SELECT banned FROM users WHERE user_id=?", (uid,)).fetchone()
    return bool(r and r[0] == 1)


def update_balance(uid, amount):
    cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, uid))
    db.commit()


def add_upi_revenue(method, amt):
    if str(method).startswith("UPI"):
        cur.execute(
            "INSERT INTO settings(key,value) VALUES('upi_revenue','0') ON CONFLICT(key) DO NOTHING"
        )
        cur.execute(
            "UPDATE settings SET value=CAST(CAST(value AS INTEGER)+? AS TEXT) WHERE key='upi_revenue'",
            (int(amt),))


def delete_session_files(session_path):
    if not session_path:
        return
    base = session_path[:-8] if session_path.endswith('.session') else session_path
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
                ent = await bot.get_entity(ch_id)
                await bot(GetParticipantRequest(channel=ent, participant=uid))
        except UserNotParticipantError:
            return False
        except ChatAdminRequiredError:
            logger.error(f"Bot not admin in {ch}")
            return False
        except Exception as e:
            logger.error(f"Channel check {ch}: {e}")
            return False
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


def terms_accepted(uid):
    r = cur.execute("SELECT terms_accepted FROM users WHERE user_id=?", (uid,)).fetchone()
    return bool(r and r[0])


# ================= COUNTRIES =================
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
    '966': ('Saudi Arabia', '🇸🇦'), '971': ('UAE', '🇦🇪'), '998': ('Uzbekistan', '🇺🇿'),
}


def get_flag_by_country_name(name):
    for code, (cn, cf) in COUNTRY_CODES.items():
        if cn == name:
            return cf
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
        cs = cur.execute("SELECT code, name, flag FROM custom_countries").fetchall()
        cs.sort(key=lambda x: len(x[0]), reverse=True)
        for code, name, flag in cs:
            if phone.startswith(code):
                return name, flag
    except Exception:
        pass
    for length in (3, 2, 1):
        p = phone[:length]
        if p in COUNTRY_CODES:
            return COUNTRY_CODES[p]
    return "Unknown", "🌍"


def country_hash(name):
    return hashlib.md5(str(name).encode("utf-8")).hexdigest()[:10]


def resolve_country(category, h):
    for (n,) in cur.execute("SELECT DISTINCT country_name FROM stock WHERE category=?", (category,)).fetchall():
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
        r = cur.execute("SELECT price FROM stock WHERE country_name=? AND category=? AND account_year=? LIMIT 1",
                        (country, category, int(year))).fetchone()
        if r:
            return r[0]
    r = cur.execute("SELECT price FROM stock WHERE country_name=? AND category=? LIMIT 1", (country, category)).fetchone()
    return r[0] if r else None


def detect_account_year_fallback():
    return 2024


async def detect_account_year(client):
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
                    mt = re.search(r'(?:Created|Age|Registration)[^\d]*(\d{4})', m.text, re.I)
                    if mt:
                        return int(mt.group(1))
    except Exception:
        pass
    return 2024


async def force_2fa_2007(client, old_password=None):
    try:
        pwd = await client(GetPasswordRequest())
        if pwd.has_password:
            if not old_password or old_password == "None":
                return False, "old 2FA unknown"
            if old_password == NEW_2FA:
                return True, None
            await client.edit_2fa(current_password=old_password, new_password=NEW_2FA, hint="")
        else:
            await client.edit_2fa(new_password=NEW_2FA, hint="")
        return True, None
    except Exception as ex:
        return False, str(ex)[:120]


def extract_login_code(msgs, start_time):
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


# ================= REFERRAL =================
def is_ref_enabled():
    return (setting_get("ref_enabled", "on") == "on")


def get_ref_bonus():
    try:
        return int(setting_get("ref_bonus", "1") or 1)
    except Exception:
        return 1


async def reward_referrer_on_join(uid):
    if not is_ref_enabled():
        return
    row = cur.execute("SELECT referred_by, ref_rewarded FROM users WHERE user_id=?", (uid,)).fetchone()
    if not row or not row[0] or row[1]:
        return
    ref, bonus = row[0], get_ref_bonus()
    cur.execute("UPDATE users SET ref_rewarded=1 WHERE user_id=? AND ref_rewarded=0", (uid,))
    if cur.rowcount == 0:
        db.commit()
        return
    db.commit()
    if bonus > 0:
        update_balance(ref, bonus)
        try:
            await bot.send_message(ref,
                f"{PE_GIFT} <b>Referral Bonus Unlocked!</b>\n"
                f"{PE_HEART} Your referral <code>{uid}</code> joined.\n"
                f"{PE_CHECK} You earned <b>{P_INR}{bonus}</b>!")
        except Exception:
            pass


# ================= LOGGING =================
async def log_primary_deposit(uid, amt, method):
    try:
        try:
            u = await bot.get_entity(int(uid))
            uname = html.escape(u.username) if u.username else "NoUsername"
        except Exception:
            uname = "NoUsername"
        t = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        msg = (f"{PE_GIFT} <b>NEW DEPOSIT</b>\n\n"
               f"{P_ACC} User: <code>{uid}</code>\n@{uname}\n"
               f"{P_MONEY} Amount: {P_INR}{amt}\n"
               f"{P_CARD} Method: {html.escape(str(method))}\n{P_TIME} {t}")
        if LOG_CHANNEL_ID:
            await bot.send_message(LOG_CHANNEL_ID, msg)
    except Exception as e:
        logger.error(f"Dep log: {e}")


async def log_primary_purchase(uid, country, price, amount, year, qty):
    try:
        t = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        msg = (f"{PE_LIGHTNING} <b>NEW PURCHASE</b>\n\n"
               f"{P_ID} User: <code>******{str(uid)[-4:]}</code>\n"
               f"{P_GLOBE} {html.escape(str(country))}\n"
               f"{P_MONEY} Price: {P_INR}{price}\n"
               f"{P_CARD} Paid: {P_INR}{amount}\n"
               f"{P_CAL} Year: {year}\n{P_PKG} Qty: {qty}\n{P_TIME} {t}")
        if LOOG_CHANNEL_ID:
            await bot.send_message(LOOG_CHANNEL_ID, msg)
    except Exception as e:
        logger.error(f"Pur log: {e}")


# ================= MENU =================
def get_persistent_menu(uid):
    rows = [
        [KeyboardButton(BTN_BUY),      KeyboardButton(BTN_SELL)],
        [KeyboardButton(BTN_BUY_SESS), KeyboardButton(BTN_SELL_SESS)],
        [KeyboardButton(BTN_DEPOSIT),  KeyboardButton(BTN_PROFILE)],
        [KeyboardButton(BTN_REFER),    KeyboardButton(BTN_PROMO)],
        [KeyboardButton(BTN_STATS),    KeyboardButton(BTN_SUPPORT)],
    ]
    if is_admin(uid):
        rows.append([KeyboardButton(BTN_ADMIN)])
    return ReplyKeyboardMarkup([KeyboardButtonRow(r) for r in rows], resize=True)


def get_terms_buttons():
    return [
        [Button.url("📜 Read Terms & Conditions", TERMS_URL)],
        [Button.inline("✅ Accept", "tc_accept"), Button.inline("❌ Reject", "tc_reject")],
    ]


def get_support_buttons():
    btns = [[Button.url("📩 Support", get_support_url())],
            [Button.url("📜 Terms", TERMS_URL)]]
    if JOIN_URLS:
        btns.append([Button.url("📢 Channel", JOIN_URLS[0])])
    return btns


def get_join_buttons():
    btns = [[Button.url(f"📢 Join Channel {i+1}", l)] for i, l in enumerate(JOIN_URLS) if l]
    btns.append([Button.inline("✅ Verify Joined", "verify_join")])
    return btns


JOIN_MSG = (f"{PE_FLOWER} <b>Join our channels first!</b>\n"
            f"{PE_LOCATION} Join all and tap <b>Verify</b>.")
TERMS_MSG = (f"{PE_FLOWER} <b>TERMS & CONDITIONS</b>\n"
             f"Accept before using the bot.")


async def build_welcome(uid):
    if is_ref_enabled():
        me = await bot.get_me()
        link = (f"<code>https://t.me/{me.username}?start=ref_{uid}</code>"
                if me.username else "<i>Set a public bot username.</i>")
        ref_part = (f"{P_GIFT} <b>Refer & Earn:</b> Invite friends — earn ₹{get_ref_bonus()} each\n{link}")
    else:
        ref_part = f"{P_OFF} Referral temporarily off."
    return (f"{PE_HEART} <b>Welcome to Vinnu Account Store!</b>\n\n"
            f"{PE_GIFT} <b>Premium services</b> — Buy accounts, sessions, top-ups.\n"
            f"{ref_part}\n\n👨‍💻 <b>Developer:</b> @vinnu_exe")


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
        
        # ================= DEPOSIT SYSTEM (WORKING 3K PRESERVED) =================
def format_payment_buttons(buttons):
    n = len(buttons)
    res = []
    for i in range(0, n, 2):
        res.append(buttons[i:i+2])
    return res


async def deposit_menu(event):
    if setting_get("upi_enabled", "on") != "on":
        return await bot.send_message(event.chat_id, "⚠️ Deposits temporarily disabled.")
    msg = (f"{P_CARD} <b>Select Payment Method:</b>\n\n"
           f"{PE_LIGHTNING} Automatic = instant credit\n"
           f"{P_WAIT} Manual = UTR/proof needed")
    flat = [Button.inline("⚡ UPI Automatic", "dep_upi"),
            Button.inline("👛 Cwallet (+5%)", "depm_cw")]
    customs = cur.execute("SELECT id, name FROM custom_payments").fetchall()
    for cid, cname in customs:
        flat.append(Button.inline(f"💳 {cname}", f"depm_{cid}"))
    await bot.send_message(event.chat_id, msg, buttons=format_payment_buttons(flat))


def get_keypad():
    return [
        [Button.inline("1", "kp_1"), Button.inline("2", "kp_2"), Button.inline("3", "kp_3")],
        [Button.inline("4", "kp_4"), Button.inline("5", "kp_5"), Button.inline("6", "kp_6")],
        [Button.inline("7", "kp_7"), Button.inline("8", "kp_8"), Button.inline("9", "kp_9")],
        [Button.inline("🔙 Del", "kp_del"), Button.inline("0", "kp_0"), Button.inline("✅ Confirm", "kp_done")],
        [Button.inline("❌ Cancel", "cancel_action")],
    ]


def get_admin_custom_keypad(dep_id):
    return [
        [Button.inline("1", f"dkp|{dep_id}|1"), Button.inline("2", f"dkp|{dep_id}|2"), Button.inline("3", f"dkp|{dep_id}|3")],
        [Button.inline("4", f"dkp|{dep_id}|4"), Button.inline("5", f"dkp|{dep_id}|5"), Button.inline("6", f"dkp|{dep_id}|6")],
        [Button.inline("7", f"dkp|{dep_id}|7"), Button.inline("8", f"dkp|{dep_id}|8"), Button.inline("9", f"dkp|{dep_id}|9")],
        [Button.inline("🔙 Del", f"dkp|{dep_id}|del"), Button.inline("0", f"dkp|{dep_id}|0"), Button.inline("✅ Confirm", f"dkp|{dep_id}|conf")],
        [Button.inline("❌ Cancel", f"dkp|{dep_id}|cancel")],
    ]


def deposit_request_buttons(dep_id, uid, amt, with_custom=True):
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
            return await event.answer("❌ Method not available.", alert=True)
        method = row[0]
    deposit_input[uid] = {'step': 'wait_amt', 'method': method}
    await event.edit(
        f"{P_CARD} <b>{html.escape(method)} Deposit</b>\n\n"
        f"👇 Reply with <b>AMOUNT in ₹</b>.",
        buttons=[[Button.inline("❌ Cancel", "cancel_action")]])


async def init_upi_keypad(event):
    uid = event.sender_id
    deposit_input[uid] = {'step': 'upi_keypad', 'val': '0'}
    await event.edit(f"{P_KEY} <b>ENTER AMOUNT (Min ₹1)</b>\n\n{P_MONEY} <code>₹0</code>",
                     buttons=get_keypad())


async def keypad_logic(event):
    uid = event.sender_id
    action = event.data.decode().replace("kp_", "")
    curr = deposit_input.get(uid, {}).get('val', "0")
    if action.isdigit():
        curr = action if curr == "0" else curr + action
        if len(curr) > 5:
            curr = curr[:5]
    elif action == "del":
        curr = curr[:-1] or "0"
    elif action == "done":
        amt = int(curr)
        if amt < 1:
            return await event.answer("⚠️ Min ₹1", alert=True)
        return await show_upi_qr(event, amt)
    deposit_input[uid] = {'step': 'upi_keypad', 'val': curr}
    try:
        await event.edit(f"{P_KEY} <b>ENTER AMOUNT</b>\n\n{P_MONEY} <code>₹{curr}</code>",
                         buttons=get_keypad())
    except MessageNotModifiedError:
        pass


async def show_upi_qr(event, amount):
    uid = event.sender_id
    if not UPI_ID:
        return await event.edit("❌ UPI not configured. Contact admin.")
    order_id = f"ORDER_{uid}_{int(time.time())}"
    await event.edit(f"{P_WAIT} Generating QR...")
    upi_url = f"upi://pay?pa={UPI_ID}&pn=VinnuStore&am={amount}&cu=INR"
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=400x400&data={quote(upi_url)}"
    try:
        cur.execute("INSERT INTO upi_orders (order_id, user_id, amount, status) VALUES (?,?,?,?)",
                    (order_id, uid, amount, "pending"))
        db.commit()
        msg = (f"{PE_LIGHTNING} <b>AUTOMATIC UPI</b>\n\n"
               f"{P_MONEY} Amount: <code>₹{amount}</code>\n"
               f"{P_ID} Order: <code>{order_id}</code>\n\n"
               f"👇 Scan or pay to:\n<code>{UPI_ID}</code>\n\n"
               f"⚠️ <b>After paying</b>, submit 12-digit UTR.")
        await event.delete()
        await bot.send_file(uid, qr_url, caption=msg, buttons=[
            [Button.inline("✅ Submit UTR (12 digit)", f"submit_utr_{order_id}")],
            [Button.inline("❌ Cancel", "cancel_action")],
        ])
    except Exception as e:
        await bot.send_message(uid, f"{P_NO} Error: {html.escape(str(e))}")


async def verify_upi_payment(event, order_id):
    uid = event.sender_id
    row = cur.execute("SELECT amount, status, user_id FROM upi_orders WHERE order_id=?", (order_id,)).fetchone()
    if not row or row[2] != uid:
        return await event.answer("❌ Order not found.", alert=True)
    if row[1] != 'pending':
        return await event.answer("⚠️ Already submitted.", alert=True)
    chat = event.chat_id
    await event.delete()
    async with bot.conversation(chat, timeout=180) as conv:
        try:
            await conv.send_message("👇 Enter 12-digit UTR / Reference:\n<i>(/cancel to abort)</i>")
            resp = await conv.get_response()
            utr = resp.raw_text.strip()
            if utr == "/cancel":
                return await conv.send_message("❌ Cancelled.")
            if not re.fullmatch(r"\d{12}", utr):
                return await conv.send_message("❌ Must be exactly 12 digits.")
            if cur.execute("SELECT 1 FROM deposits WHERE method_name LIKE ?", (f"%UTR: {utr})%",)).fetchone():
                return await conv.send_message("❌ UTR already used.")
            cur.execute("UPDATE upi_orders SET status='submitted' WHERE order_id=? AND status='pending'", (order_id,))
            if cur.rowcount == 0:
                db.commit()
                return await conv.send_message("⚠️ Already submitted.")
            amt = int(row[0])
            cur.execute("INSERT INTO deposits (user_id, amount, method_name, status) VALUES (?,?,?,?)",
                        (uid, amt, f"UPI (UTR: {utr})", "pending"))
            db.commit()
            dep_id = cur.lastrowid
            cap = (f"{PE_LIGHTNING} <b>NEW UPI DEPOSIT</b>\n"
                   f"{P_ACC} User: <code>{uid}</code>\n"
                   f"{P_MONEY} Amount: <b>₹{amt}</b>\n"
                   f"🧾 UTR: <code>{html.escape(utr)}</code>\n"
                   f"Verify in payment app.")
            if LOG_CHANNEL_ID:
                await bot.send_message(LOG_CHANNEL_ID, cap,
                    buttons=deposit_request_buttons(dep_id, uid, amt, with_custom=False))
            await conv.send_message("✅ UTR submitted! Balance credited after admin verification.")
        except asyncio.TimeoutError:
            await conv.send_message("❌ Timeout. Try again.")
        except Exception as e:
            logger.error(f"UTR: {e}")
            await conv.send_message("❌ Error. Try again.")


async def approve_deposit(dep_id, amt):
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
        cur.execute("UPDATE users SET balance = balance + ?, total_deposited = total_deposited + ? WHERE user_id=?",
                    (amt, amt, t_uid))
        add_upi_revenue(method, amt)
        db.commit()
    return t_uid, method, prev_bal


# ================= BUY FLOW =================
CATEGORIES = [
    ("spam_free", "🟢", "Spam Free"),
    ("limit_spam", "🔴", "Limit / Spam"),
    ("premium",   "🔵", "Premium"),
    ("whatsapp",  "💬", "WhatsApp Account"),
    ("all_app",   "📱", "All App Acc"),
    ("server2",   "🖥️", "Server 2"),
]
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
    if flow == "single":
        btns.append([Button.inline("🌐 Server 1 (LZT Market)", "s1_market")])
    btns.append([Button.inline("Cancel", "cancel_action")])
    if not counts:
        msg += f"\n\n{P_NO} <b>Stock empty. Check back later!</b>"
    if isinstance(event, events.CallbackQuery.Event):
        await event.edit(msg, buttons=btns)
    else:
        await event.respond(msg, buttons=btns)


async def show_countries(event, flow, category, page=1):
    limit = 10
    offset = (page - 1) * limit
    total_row = cur.execute("SELECT COUNT(DISTINCT country_name) FROM stock WHERE available=1 AND category=?",
                            (category,)).fetchone()
    total = total_row[0] if total_row else 0
    rows = cur.execute(
        "SELECT MIN(country_icon), country_name, COUNT(*) FROM stock WHERE available=1 AND category=? "
        "GROUP BY country_name ORDER BY country_name ASC LIMIT ? OFFSET ?",
        (category, limit, offset)).fetchall()
    if not rows and page == 1:
        err_msg = f"{P_NO} <b>{cat_label(category)}: Empty.</b>"
        btns = [[Button.inline("⬅️ Back", f"catmenu|{flow}")]]
        if isinstance(event, events.CallbackQuery.Event):
            return await event.edit(err_msg, buttons=btns)
        return await event.respond(err_msg, buttons=btns)
    title = f"{PE_LIGHTNING} <b>Bulk Sessions</b>" if flow == 'bulk' else f"{PE_HEART} <b>Single Account</b>"
    msg = (f"{title}\n📦 Type: {cat_label(category)}\n\n"
           f"{P_GLOBE} <b>Select region (Page {page}):</b>\n"
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
        return await event.answer("❌ Stock changed, reselect.", alert=True)
    rows = cur.execute(
        "SELECT account_year, price, COUNT(*) FROM stock WHERE available=1 AND category=? AND country_name=? "
        "GROUP BY account_year, price ORDER BY account_year DESC, price ASC",
        (category, country)).fetchall()
    if not rows:
        return await event.answer("❌ Out of stock.", alert=True)
    uid = event.sender_id
    disc_row = cur.execute("SELECT discount FROM users WHERE user_id=?", (uid,)).fetchone()
    discount = disc_row[0] if disc_row else 0
    msg = f"{PE_FLOWER} <b>Select Year</b>\n📦 {cat_label(category)}\n{P_GLOBE} {html.escape(country)}\n\n"
    btns = []
    for (y, p, c) in rows:
        disp_p = p if discount == 0 else int(p * (100 - discount) / 100)
        dt = f" (-{discount}%)" if discount > 0 else ""
        btns.append([Button.inline(f"{y} | ₹{disp_p}{dt} | {c}", f"by|{flow}|{category}|{h}|{y}|{p}")])
    btns.append([Button.inline("Back", f"pg_c|{flow}|{category}|1")])
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
        return await event.answer("❌ Stock changed.", alert=True)
    uid, base = event.sender_id, int(price_str)
    row = cur.execute("SELECT MIN(country_icon), COUNT(*) FROM stock WHERE available=1 AND category=? AND "
                      "country_name=? AND account_year=? AND price=?",
                      (category, country, int(year), base)).fetchone()
    if not row or not row[1]:
        return await event.answer("❌ Out of stock.", alert=True)
    icon, cnt = row
    final = user_final_price(uid, base)
    msg = (f"⚡ <b>Telegram Account</b>\n\n"
           f"🌍 <b>Country:</b> {icon} {html.escape(country)}\n"
           f"📦 <b>Type:</b> {cat_label(category)}\n"
           f"💸 <b>Price:</b> {usd_inr(final)}\n"
           f"📦 <b>Available:</b> {cnt}\n"
           f"⚠️ Use Graph/Plus Messenger.\n"
           f"🚫 Not responsible for freezes/bans.")
    btns = [[Button.inline("🛒 Buy Now", f"pc|{category}|{h}|{year}|{base}")],
            [Button.inline("⬅️ Back", f"bc|single|{category}|{h}")]]
    await event.edit(msg, buttons=btns)


async def confirm_purchase(event, category, h, year, price_str):
    country = resolve_country(category, h)
    if not country:
        return await event.answer("❌ Stock changed.", alert=True)
    uid, base = event.sender_id, int(price_str)
    acc = cur.execute("SELECT phone, country_icon, account_year, twofa FROM stock WHERE available=1 AND "
                      "category=? AND country_name=? AND account_year=? AND price=? ORDER BY phone LIMIT 1",
                      (category, country, int(year), base)).fetchone()
    if not acc:
        return await event.answer("❌ Sold out.", alert=True)
    phone, icon, yr, twofa = acc
    bal_row = cur.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
    bal = bal_row[0] if bal_row else 0
    final = user_final_price(uid, base)
    age_y = max(datetime.now().year - int(yr), 0)
    has_2fa = "✅ Yes" if twofa and twofa != "None" else "❌ No"
    after = f"💸 After: {usd_inr(bal - final)}" if bal >= final else "💸 After: ⚠️ Insufficient"
    msg = (f"━━━━━━━━━━━━━━━━━━━━\n🛒 <b>PURCHASE CONFIRMATION</b>\n"
           f"━━━━━━━━━━━━━━━━━━━━\n\n"
           f"🏷️ {icon} {html.escape(country)}\n📦 {cat_label(category)}\n\n"
           f"📞 <code>{mask_phone(phone)}</code>\n"
           f"⏰ Age: {yr} ({age_y}Y)\n🔐 2FA: {has_2fa}\n\n"
           f"💰 {usd_inr(final)}\n💵 Balance: {usd_inr(bal)}\n{after}\n\n"
           f"✅ Use Plus Messenger.\n🚫 Not responsible for freezes.")
    btns = [[Button.inline("✅ Confirm Purchase", f"buy_cf|{category}|{h}|{year}|{base}")],
            [Button.inline("❌ Cancel", "cancel_action")]]
    await event.edit(msg, buttons=btns)


async def process_purchase(event, category, h, year_str, price_str):
    country = resolve_country(category, h)
    if not country:
        return await event.answer("❌ Stock changed.", alert=True)
    uid, base_price = event.sender_id, int(price_str)
    disc_row = cur.execute("SELECT discount FROM users WHERE user_id=?", (uid,)).fetchone()
    discount = disc_row[0] if disc_row else 0
    final_price = base_price if discount == 0 else int(base_price * (100 - discount) / 100)
    async with get_user_lock(uid):
        row = cur.execute(
            "SELECT phone, session_file, country_icon, account_year, twofa FROM stock WHERE "
            "category=? AND country_name=? AND account_year=? AND price=? AND available=1 ORDER BY phone LIMIT 1",
            (category, country, int(year_str), base_price)).fetchone()
        if not row:
            return await event.answer("❌ Sold out!", alert=True)
        phone, sess, c_icon, actual_year, twofa_pass = row
        cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=? AND balance >= ?",
                    (final_price, uid, final_price))
        if cur.rowcount == 0:
            return await event.answer(f"❌ Need ₹{final_price}", alert=True)
        cur.execute("UPDATE stock SET available=0 WHERE phone=?", (phone,))
        cur.execute("INSERT OR REPLACE INTO pending_orders (phone, user_id, price, created) VALUES (?,?,?,?)",
                    (phone, uid, final_price, time.time()))
        db.commit()
    await event.edit(f"{PE_LIGHTNING} <b>Fetching (+{phone})...</b>")
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
        return await event.edit(f"{P_NO} <b>Invalid account.</b> Refunded.")
    msg = (f"{PE_LIGHTNING} <b>Order Active!</b>\n\n"
           f"{P_PHONE} <b>Phone:</b> <code>{phone}</code>\n"
           f"{P_FLAG} {c_icon} {html.escape(country)}\n\n"
           f"🔻 <b>Instructions:</b>\n"
           f"1. Open Telegram → Add Account\n"
           f"2. Enter number above\n"
           f"3. {P_WAIT} Bot will deliver OTP automatically.\n\n"
           f"<i>Auto-cancel & refund in 10 min if no OTP.</i>")
    sent = await event.edit(msg)
    active_orders[phone] = {
        'uid': uid, 'client': client, 'sess': sess, 'start_time': time.time(),
        'paid': False, 'price': final_price, 'country': country, 'year': actual_year,
        'c_icon': c_icon, 'twofa': twofa_pass, 'msg_id': sent.id,
    }
    asyncio.create_task(auto_otp_task(phone))


def otp_buttons(phone):
    return [[Button.inline("🔄 Get OTP Again", f"get_otp_again|{phone}")],
            [Button.inline("🚪 Finish & Logout", f"logout_bot|{phone}")]]


def otp_message(order, phone, code, title):
    twofa_text = (f"{P_2FA} <b>2FA:</b> <code>{html.escape(str(order['twofa']))}</code>"
                  if order['twofa'] != "None"
                  else f"🔓 <b>2FA:</b> <code>Disabled</code>")
    return (f"{title}\n\n"
            f"{P_PHONE} <b>Phone:</b> <code>{phone}</code>\n"
            f"{P_FLAG} {order['c_icon']} {html.escape(order['country'])}\n"
            f"{P_OTP} <b>OTP:</b> <code>{code}</code>\n"
            f"{twofa_text}")


async def paid_order_cleanup(phone):
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
        await bot.send_message(order['uid'],
            f"{P_TIME} <b>Session auto-closed</b> for <code>{phone}</code> (30 min).")
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
    try:
        await client.get_dialogs(limit=20)
    except Exception as ex:
        logger.warning(f"Warmup {phone}: {ex}")
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
                        cur.execute("INSERT INTO orders (user_id, country, year, price, phone, otp) VALUES (?,?,?,?,?,?)",
                                    (uid, order['country'], order['year'], order['price'], phone, code))
                        cur.execute("DELETE FROM stock WHERE phone=?", (phone,))
                        cur.execute("DELETE FROM pending_orders WHERE phone=?", (phone,))
                        db.commit()
                    await log_primary_purchase(uid, order['country'], order['price'],
                                              order['price'], order['year'], 1)
                    asyncio.create_task(paid_order_cleanup(phone))
                msg_text = otp_message(order, phone, code, f"{PE_CHECK} <b>OTP Received!</b>")
                try:
                    await bot.edit_message(uid, msg_id, msg_text, buttons=otp_buttons(phone))
                except MessageNotModifiedError:
                    pass
                except Exception:
                    await bot.send_message(uid, msg_text, buttons=otp_buttons(phone))
                return
        except Exception as ex:
            logger.warning(f"OTP poll {phone}: {ex}")
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
            await bot.edit_message(uid, msg_id,
                f"{P_TIME} <b>Order Expired!</b>\n10-minute limit hit. ₹{order['price']} refunded.")
        except Exception:
            pass


async def recover_pending_orders():
    rows = cur.execute("SELECT phone, user_id, price FROM pending_orders").fetchall()
    for phone, uid, price in rows:
        async with get_user_lock(uid):
            cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (price, uid))
            cur.execute("UPDATE stock SET available=1 WHERE phone=?", (phone,))
            cur.execute("DELETE FROM pending_orders WHERE phone=?", (phone,))
            db.commit()
        logger.info(f"Recovered pending {phone} → {uid} (₹{price})")
        try:
            await bot.send_message(uid,
                f"{P_WARN} Restart → order cancelled. ₹{price} refunded.")
        except Exception:
            pass


async def init_session_purchase(event, category, country, year, price_str):
    uid, price = event.sender_id, int(price_str)
    stock_row = cur.execute("SELECT COUNT(*) FROM stock WHERE category=? AND country_name=? AND "
                            "account_year=? AND price=? AND available=1",
                            (category, country, int(year), price)).fetchone()
    stock = stock_row[0] if stock_row else 0
    if stock == 0:
        return await event.answer("❌ Out of stock.", alert=True)
    session_buy_state[uid] = {'category': category, 'country': country, 'year': year,
                              'price': price, 'stock': stock}
    disc_row = cur.execute("SELECT discount FROM users WHERE user_id=?", (uid,)).fetchone()
    discount = disc_row[0] if disc_row else 0
    p_disp = price if discount == 0 else int(price * (100 - discount) / 100)
    msg = (f"{PE_GIFT} <b>Buy {html.escape(country)} ({year}) Sessions</b>\n"
           f"📦 {cat_label(category)}\n\n"
           f"{P_MONEY} Price/session: {P_INR}{p_disp}\n"
           f"{P_PKG} Stock: {stock}\n\n"
           f"👇 Reply with <b>Quantity</b>.")
    await event.edit(msg, buttons=[[Button.inline("Cancel", "cancel_action")]])


async def process_bulk_sessions(event, uid, qty, state, final_cost):
    category, country = state['category'], state['country']
    year, price = int(state['year']), int(state['price'])
    await event.respond(f"{PE_LIGHTNING} <b>Processing...</b>")
    async with get_user_lock(uid):
        rows = cur.execute(
            "SELECT phone, session_file, twofa, account_year FROM stock WHERE "
            "category=? AND country_name=? AND account_year=? AND price=? AND available=1 LIMIT ?",
            (category, country, year, price, qty)).fetchall()
        if len(rows) < qty:
            return await event.respond(f"{P_NO} Stock changed. Cancelled.")
        cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=? AND balance >= ?",
                    (final_cost, uid, final_cost))
        if cur.rowcount == 0:
            return await event.respond(f"{P_NO} Insufficient balance.")
        phones = [r[0] for r in rows]
        ph = ",".join("?" for _ in phones)
        cur.execute(f"UPDATE stock SET available=0 WHERE phone IN ({ph})", phones)
        price_per = final_cost // qty
        for p in phones:
            cur.execute("INSERT INTO orders (user_id, country, year, price, phone, otp) VALUES (?,?,?,?,?,?)",
                        (uid, country, year, price_per, p, "SESSION_FILES"))
        db.commit()
    zip_name = f"sessions_{uid}_{int(time.time())}.zip"
    sent = False
    try:
        with zipfile.ZipFile(zip_name, 'w') as zf:
            nums = ""
            for phone, sess_file, twofa_pass, y in rows:
                base_s = sess_file if not sess_file.endswith(".session") else sess_file[:-8]
                for ext in ['.session', '.session-wal', '.session-shm', '.session-journal']:
                    src = base_s + ext
                    if os.path.exists(src):
                        zf.write(src, os.path.basename(src))
                p_txt = twofa_pass if twofa_pass != "None" else "No_Password"
                nums += f"+{phone} | pass:{p_txt}\n"
            nums += "\nPurchased from @Vinnutgsales\n"
            zf.writestr("numbers.txt", nums)
        caption = (f"{PE_GIFT} <b>Bulk Purchase OK!</b>\n\n"
                   f"{P_FLAG} {html.escape(country)}\n📦 {cat_label(category)}\n"
                   f"{P_PKG} Qty: {qty}\n{P_CARD} Paid: {P_INR}{final_cost}\n"
                   f"{P_2FA} 2FA: 2007")
        await bot.send_file(uid, zip_name, caption=caption)
        sent = True
    except Exception as e:
        logger.error(f"Bulk zip: {e}")
        if not sent:
            async with get_user_lock(uid):
                cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (final_cost, uid))
                cur.execute(f"UPDATE stock SET available=1 WHERE phone IN ({ph})", phones)
                cur.execute(f"DELETE FROM orders WHERE user_id=? AND otp='SESSION_FILES' AND phone IN ({ph})",
                            [uid] + phones)
                db.commit()
            await event.respond(f"{P_WARN} Error: {html.escape(str(e))}\nRefunded.")
    finally:
        if os.path.exists(zip_name):
            os.remove(zip_name)
    if sent:
        await log_primary_purchase(uid, country, price, final_cost, year, qty)


# ================= PROFILE / STATS =================
async def profile_handler(event):
    uid = event.sender_id
    row = cur.execute("SELECT balance, total_deposited, joined_date, discount, sales_balance "
                      "FROM users WHERE user_id=?", (uid,)).fetchone()
    if not row:
        return await bot.send_message(event.chat_id, "⚠️ Type /start first.")
    bal, dep, date, discount, sales = row
    ref_count = cur.execute("SELECT COUNT(*) FROM users WHERE referred_by=?", (uid,)).fetchone()[0]
    me = await bot.get_me()
    ref_link = f"https://t.me/{me.username}?start=ref_{uid}" if me.username else None
    disc_msg = f"\n{P_GIFT} Discount: <b>{discount}% OFF</b>" if discount > 0 else ""
    ref_block = (f"{P_USERS} <b>Referral Link:</b>\n<code>{ref_link}</code>\n\n"
                 if ref_link else "")
    msg = (f"{PE_KISS} <b>USER PROFILE</b>\n\n"
           f"{P_ID} ID: <code>{uid}</code>\n"
           f"{P_MONEY} Balance: <code>${to_usd(bal):.2f} (₹{bal})</code>\n"
           f"{P_CARD} Deposited: <code>₹{dep}</code>{disc_msg}\n"
           f"💸 Sales Balance: <code>₹{sales}</code>\n"
           f"{P_USERS} Referrals: <b>{ref_count}</b>\n"
           f"{P_CAL} Joined: {str(date)[:10]}\n\n{ref_block}")
    await bot.send_message(event.chat_id, msg)


async def stats_handler(event, is_callback=False):
    uid = event.sender_id
    row = cur.execute("SELECT total_deposited FROM users WHERE user_id=?", (uid,)).fetchone()
    if not row:
        return
    dep = row[0]
    o_row = cur.execute("SELECT COUNT(*), SUM(price) FROM orders WHERE user_id=?", (uid,)).fetchone()
    total_orders = o_row[0] if o_row else 0
    spent = o_row[1] if o_row and o_row[1] else 0
    ref_count = cur.execute("SELECT COUNT(*) FROM users WHERE referred_by=?", (uid,)).fetchone()[0]
    msg = (f"{PE_CROWN} <b>My Stats</b>\n\n"
           f"{P_CART} Accounts Bought: {total_orders}\n"
           f"{P_USERS} Referrals: {ref_count}\n"
           f"{P_MONEY} Total Spent: ${to_usd(spent):.2f}\n"
           f"{P_CARD} Total Deposited: ${to_usd(dep):.2f}")
    btns = [[Button.inline("View Purchase Logs", "page_purchases_1")],
            [Button.inline("Referral Logs", "view_referrals")]]
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
    rows = cur.execute("SELECT phone, date FROM orders WHERE user_id=? ORDER BY id DESC LIMIT ? OFFSET ?",
                       (uid, limit, offset)).fetchall()
    msg = f"{PE_FLOWER} <b>Purchase History</b>\nPage {page}\n\n"
    if not rows:
        msg += "No purchases."
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
    await event.answer(f"👥 You referred {len(refs)} user(s).", alert=True)


async def handle_get_otp_again(event, phone):
    if phone not in active_orders:
        return await event.answer("❌ Order expired or not found.", alert=True)
    order = active_orders[phone]
    try:
        msgs = await order['client'].get_messages(777000, limit=5)
        code = extract_login_code(msgs, order['start_time'])
        if code:
            msg_text = otp_message(order, phone, code, f"{PE_CHECK} <b>Latest OTP</b>")
            await event.edit(msg_text, buttons=otp_buttons(phone))
        else:
            await event.answer("⏳ OTP not yet received. Wait a bit.", alert=True)
    except Exception as e:
        await event.answer(f"❌ {str(e)[:80]}", alert=True)


async def handle_logout_bot(event, phone):
    order = active_orders.pop(phone, None)
    if not order:
        return await event.answer("❌ Already closed.", alert=True)
    try:
        await order['client'].log_out()
    except Exception:
        pass
    try:
        await order['client'].disconnect()
    except Exception:
        pass
    delete_session_files(order['sess'])
    await event.edit(f"{P_YES} <b>Session logged out.</b>\nAccount <code>{phone}</code> is now safe.")
    
    # ================= SELL SYSTEM =================
DEFAULT_SELL_PRICES = [
    ("998", "UZ", "🇺🇿", 0.45), ("7", "RU", "🇷🇺", 0.55),
    ("1", "US", "🇺🇸", 1.20), ("91", "IN", "🇮🇳", 0.40),
    ("880", "BD", "🇧🇩", 0.35), ("92", "PK", "🇵🇰", 0.30),
    ("62", "ID", "🇮🇩", 0.50), ("63", "PH", "🇵🇭", 0.45),
    ("84", "VN", "🇻🇳", 0.40), ("254", "KE", "🇰🇪", 0.30),
]


def seed_sell_prices():
    for code, name, flag, usd in DEFAULT_SELL_PRICES:
        cur.execute("INSERT OR IGNORE INTO sell_prices (country_code, country_name, flag, price_usd) "
                    "VALUES (?,?,?,?)", (code, name, flag, usd))
    db.commit()


seed_sell_prices()


def get_sell_price_for_phone(phone):
    phone = str(phone).replace("+", "")
    rows = cur.execute("SELECT country_code, country_name, flag, price_usd FROM sell_prices "
                       "ORDER BY LENGTH(country_code) DESC").fetchall()
    for code, name, flag, usd in rows:
        if phone.startswith(code):
            return name, flag, usd
    return None, "🌍", 0.0


async def sell_menu(event):
    rows = cur.execute("SELECT country_code, country_name, flag, price_usd "
                       "FROM sell_prices ORDER BY country_code").fetchall()
    chunks, block = [], "💸 <b>We buy from you →</b>\n\n"
    for code, name, flag, usd in rows:
        block += f"[{flag}] +{code}-{name}: {usd:.2f}$\n"
        if len(block) > 3500:
            chunks.append(block)
            block = "💸 <b>(continued)</b>\n\n"
    if block:
        chunks.append(block)
    for i, chunk in enumerate(chunks):
        btn = None
        if i == len(chunks) - 1:
            btn = [[Button.inline("📱 Submit Account", "sell_start")],
                   [Button.inline("📁 My Sold Sessions", "sell_my")]]
        await bot.send_message(event.chat_id,
            chunk + "\n\n<i>You receive 90% of listed price.</i>", buttons=btn)


async def sell_start_flow(event):
    uid = event.sender_id
    if setting_get("sell_enabled", "on") != "on":
        return await event.answer("⚠️ Selling disabled.", alert=True)
    chat = event.chat_id
    async with bot.conversation(chat, timeout=300) as conv:
        await conv.send_message("📱 <b>Enter phone number to sell</b> (with country code, e.g. +998...):\n"
                                "<i>Type /cancel to abort.</i>")
        resp = await conv.get_response()
        if resp.raw_text == "/cancel":
            return await conv.send_message("❌ Cancelled.")
        phone = resp.raw_text.replace(" ", "").replace("+", "")
        if not phone.isdigit() or len(phone) < 7:
            return await conv.send_message("❌ Invalid phone.")
        if cur.execute("SELECT 1 FROM blacklisted_phones WHERE phone=?", (phone,)).fetchone():
            return await conv.send_message("❌ Number blacklisted.")
        name, flag, usd = get_sell_price_for_phone(phone)
        if not name:
            return await conv.send_message("❌ Country not supported.")
        rate = get_usdt_rate()
        inr = int(usd * rate * 0.9)
        sp = f"sessions/sell_{phone}_{int(time.time())}"
        client = TelegramClient(sp, API_ID, API_HASH)
        try:
            await client.connect()
            sreq = await client.send_code_request(phone)
            await conv.send_message("🔢 OTP sent. Enter code:")
            otp = (await conv.get_response()).raw_text.strip()
            try:
                await client.sign_in(phone, otp, phone_code_hash=sreq.phone_code_hash)
            except SessionPasswordNeededError:
                await conv.send_message("🔐 2FA required. Enter password:")
                pwd = (await conv.get_response()).raw_text.strip()
                await client.sign_in(password=pwd)
            await conv.send_message(
                "⚠️ <b>IMPORTANT:</b>\nGo to Telegram → Settings → Devices → terminate ALL other sessions.\n"
                "Bot will verify in 10 minutes.")
            cur.execute("INSERT INTO sell_submissions (user_id, phone, country_name, price_usd, "
                        "price_inr, session_path, status) VALUES (?,?,?,?,?,?,'holding')",
                        (uid, phone, name, usd, inr, sp + ".session"))
            db.commit()
            sub_id = cur.lastrowid
            await conv.send_message(
                f"⏳ <b>Submission #{sub_id} under review.</b>\n"
                f"Price if accepted: ₹{inr} ({usd:.2f}$ × 90%)\n"
                f"Auto-verify in 10 minutes.")
            asyncio.create_task(sell_hold_task(sub_id))
        except Exception as e:
            await conv.send_message(f"❌ Error: {html.escape(str(e))[:200]}")
            delete_session_files(sp + ".session")
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass


async def sell_hold_task(sub_id):
    await asyncio.sleep(600)
    row = cur.execute("SELECT user_id, phone, price_inr, session_path FROM sell_submissions "
                      "WHERE id=? AND status='holding'", (sub_id,)).fetchone()
    if not row:
        return
    uid, phone, inr, sess = row
    accepted = False
    try:
        s = sess[:-8] if sess.endswith(".session") else sess
        client = TelegramClient(s, API_ID, API_HASH)
        await client.connect()
        if await client.is_user_authorized():
            auths = await client(GetAuthorizationsRequest())
            others = [a for a in auths.authorizations if not a.current]
            if not others:
                accepted = True
        await client.disconnect()
    except Exception:
        pass
    if accepted:
        async with get_user_lock(uid):
            cur.execute("UPDATE sell_submissions SET status='accepted', decided_at=CURRENT_TIMESTAMP "
                        "WHERE id=?", (sub_id,))
            cur.execute("UPDATE users SET sales_balance = sales_balance + ? WHERE user_id=?", (inr, uid))
            year = 2024
            name, flag = get_sell_price_for_phone(phone)[0], get_sell_price_for_phone(phone)[1]
            cur.execute("INSERT OR REPLACE INTO stock (phone, session_file, country_name, "
                        "country_icon, account_year, category, price, available, twofa) "
                        "VALUES (?,?,?,?,?,?,?,1,'None')",
                        (phone, sess, name or "Unknown", flag or "🌍", year, "spam_free", inr * 2))
            db.commit()
        try:
            await bot.send_message(uid,
                f"✅ <b>Account accepted!</b>\n₹{inr} added to Sales Balance.")
        except Exception:
            pass
    else:
        cur.execute("UPDATE sell_submissions SET status='rejected', "
                    "reason='Other sessions active or dead', decided_at=CURRENT_TIMESTAMP WHERE id=?",
                    (sub_id,))
        db.commit()
        delete_session_files(sess)
        try:
            await bot.send_message(uid,
                "❌ <b>Submission rejected.</b>\nReason: other sessions active or invalid.")
        except Exception:
            pass


async def sell_my(event):
    uid = event.sender_id
    rows = cur.execute("SELECT id, phone, country_name, price_inr, status, created "
                       "FROM sell_submissions WHERE user_id=? ORDER BY id DESC LIMIT 10",
                       (uid,)).fetchall()
    if not rows:
        return await event.respond("📭 No submissions yet.")
    msg = "📁 <b>My Sold Sessions</b>\n\n"
    for sid, phone, cname, inr, status, dt in rows:
        icon = {"holding": "⏳", "accepted": "✅", "rejected": "❌"}.get(status, "❔")
        msg += f"{icon} #{sid} +{phone} ({cname}) — ₹{inr} — {status}\n"
    await event.respond(msg, buttons=[[Button.inline("💳 Withdraw to Wallet", "sell_withdraw")]])


async def sell_withdraw_flow(event):
    uid = event.sender_id
    row = cur.execute("SELECT sales_balance FROM users WHERE user_id=?", (uid,)).fetchone()
    bal = row[0] if row else 0
    if bal <= 0:
        return await event.answer("❌ No sales balance.", alert=True)
    async with bot.conversation(event.chat_id, timeout=120) as conv:
        await conv.send_message(f"💳 Sales Balance: ₹{bal}\n\n"
                                "Type <b>wallet</b> (instant to main) or <b>upi</b> (admin approval):")
        resp = await conv.get_response()
        choice = resp.raw_text.strip().lower()
        if choice == "wallet":
            async with get_user_lock(uid):
                cur.execute("UPDATE users SET balance=balance+?, sales_balance=0 WHERE user_id=?",
                            (bal, uid))
                db.commit()
            return await conv.send_message(f"✅ ₹{bal} moved to main balance.")
        elif choice == "upi":
            await conv.send_message("Enter your UPI ID:")
            upi = (await conv.get_response()).raw_text.strip()
            cur.execute("INSERT INTO withdrawals (user_id, amount, method, upi_id) VALUES (?,?,?,?)",
                        (uid, bal, "upi", upi))
            db.commit()
            wid = cur.lastrowid
            if LOG_CHANNEL_ID:
                await bot.send_message(LOG_CHANNEL_ID,
                    f"💳 <b>Withdrawal #{wid}</b>\nUser: <code>{uid}</code>\n"
                    f"Amount: ₹{bal}\nUPI: <code>{html.escape(upi)}</code>",
                    buttons=[[Button.inline("✅ Approve", f"wd_ok|{wid}"),
                              Button.inline("❌ Reject", f"wd_no|{wid}")]])
            await conv.send_message("✅ Request sent to admin.")
        else:
            await conv.send_message("❌ Cancelled.")


async def handle_withdrawal_decision(event, data):
    if not is_admin(event.sender_id):
        return await event.answer("⛔", alert=True)
    kind, wid = data.split("|")
    wid = int(wid)
    row = cur.execute("SELECT user_id, amount FROM withdrawals WHERE id=? AND status='pending'",
                      (wid,)).fetchone()
    if not row:
        return await event.answer("Already processed.", alert=True)
    tuid, amt = row
    if kind == "wd_ok":
        cur.execute("UPDATE withdrawals SET status='approved' WHERE id=?", (wid,))
        cur.execute("UPDATE users SET sales_balance=sales_balance-? WHERE user_id=?", (amt, tuid))
        db.commit()
        await bot.send_message(tuid, f"✅ Withdrawal ₹{amt} approved! Will be sent shortly.")
        await event.edit(f"✅ #{wid} approved")
    else:
        cur.execute("UPDATE withdrawals SET status='rejected' WHERE id=?", (wid,))
        db.commit()
        await bot.send_message(tuid, f"❌ Withdrawal ₹{amt} rejected. Refunded to sales balance.")
        await event.edit(f"❌ #{wid} rejected")


# ================= PROMO / GIVEAWAY / FIGHT / LOOKUP =================
async def promo_flow(event):
    async with bot.conversation(event.chat_id, timeout=120) as conv:
        await conv.send_message("🎟️ Enter promo code:")
        code = (await conv.get_response()).raw_text.strip().upper()
        row = cur.execute("SELECT amount, max_uses, used FROM promo_codes WHERE code=?",
                          (code,)).fetchone()
        if not row:
            return await conv.send_message("❌ Invalid code.")
        amount, mx, used = row
        if used >= mx:
            return await conv.send_message("❌ Code expired/used up.")
        if cur.execute("SELECT 1 FROM promo_claims WHERE user_id=? AND code=?",
                       (event.sender_id, code)).fetchone():
            return await conv.send_message("❌ Already claimed.")
        async with get_user_lock(event.sender_id):
            cur.execute("UPDATE promo_codes SET used=used+1 WHERE code=?", (code,))
            cur.execute("INSERT INTO promo_claims (user_id, code) VALUES (?,?)",
                        (event.sender_id, code))
            cur.execute("UPDATE users SET balance=balance+? WHERE user_id=?",
                        (amount, event.sender_id))
            db.commit()
        await conv.send_message(f"✅ ₹{amount} credited!")


async def fight_handler(event, amount):
    if setting_get("fight_enabled", "off") != "on":
        return await event.respond("⚠️ Fight disabled.")
    if amount <= 0:
        return await event.respond("❌ Invalid amount.")
    game = cur.execute("SELECT id, challenger, amount FROM fight_games WHERE status='open' "
                       "AND amount=? AND challenger != ? LIMIT 1",
                       (amount, event.sender_id)).fetchone()
    if game:
        gid, challenger, amt = game
        async with get_user_lock(event.sender_id):
            r = cur.execute("SELECT balance FROM users WHERE user_id=?",
                            (event.sender_id,)).fetchone()
            if not r or r[0] < amt:
                return await event.respond("❌ Insufficient balance.")
            winner = random.choice([challenger, event.sender_id])
            cur.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (amt, challenger))
            cur.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (amt, event.sender_id))
            cur.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amt * 2, winner))
            cur.execute("UPDATE fight_games SET status='done', opponent=?, winner=? WHERE id=?",
                        (event.sender_id, winner, gid))
            db.commit()
        await event.respond(f"⚔️ Match!\nWinner: <code>{winner}</code>\n"
                            f"Prize: ₹{amt * 2}")
    else:
        async with get_user_lock(event.sender_id):
            r = cur.execute("SELECT balance FROM users WHERE user_id=?",
                            (event.sender_id,)).fetchone()
            if not r or r[0] < amount:
                return await event.respond("❌ Insufficient balance.")
            cur.execute("UPDATE users SET balance=balance-? WHERE user_id=?",
                        (amount, event.sender_id))
            cur.execute("INSERT INTO fight_games (challenger, amount) VALUES (?,?)",
                        (event.sender_id, amount))
            db.commit()
        await event.respond(f"⚔️ Fight listed at ₹{amount}. Waiting for opponent…")


async def lookup_handler(event, target_id):
    if not is_admin(event.sender_id):
        return
    row = cur.execute("SELECT user_id, balance, sales_balance, total_deposited, "
                      "joined_date, banned, discount FROM users WHERE user_id=?",
                      (target_id,)).fetchone()
    if not row:
        return await event.respond("❌ Not found.")
    uid, bal, sb, dep, jd, ban, disc = row
    orders = cur.execute("SELECT COUNT(*) FROM orders WHERE user_id=?", (uid,)).fetchone()[0]
    sells = cur.execute("SELECT COUNT(*) FROM sell_submissions WHERE user_id=?",
                        (uid,)).fetchone()[0]
    await event.respond(
        f"🔍 <b>360 Lookup: {uid}</b>\n\n"
        f"Balance: ₹{bal}\nSales: ₹{sb}\nDeposited: ₹{dep}\n"
        f"Orders: {orders}\nSells: {sells}\n"
        f"Joined: {jd}\nBanned: {ban}\nDiscount: {disc}%")


# ================= SERVER 1 — LZT MARKET =================
_lzt_cooldown_until = 0
_lzt_last_error = ""


def lzt_headers():
    return {"Authorization": f"Bearer {LZT_TOKEN}", "Accept": "application/json"}


def _forced_ipv4_connector():
    class _IPv4Connector(aiohttp.TCPConnector):
        async def _resolve_host(self, host, port, *a, **kw):
            infos = await aiohttp.helpers.getaddrinfo(host, port, family=socket.AF_INET)
            return infos
    return _IPv4Connector(ssl=ssl.create_default_context())


def lzt_client_kwargs():
    kw = {"headers": lzt_headers(),
          "connector": _forced_ipv4_connector(),
          "timeout": aiohttp.ClientTimeout(total=25)}
    if LZT_PROXY:
        kw["proxy"] = LZT_PROXY
    return kw


def lzt_inr_price(usd_price):
    rate = get_usdt_rate()
    inr = float(usd_price) * rate * (1 + LZT_MARKUP_PCT / 100)
    return int(round(inr))


async def lzt_fetch(path, params=None):
    global _lzt_cooldown_until, _lzt_last_error
    if time.time() < _lzt_cooldown_until:
        raise RuntimeError(f"Cooldown {int(_lzt_cooldown_until - time.time())}s")
    try:
        async with aiohttp.ClientSession(**lzt_client_kwargs()) as s:
            async with s.get(f"https://api.lzt.market{path}", params=params) as r:
                if r.status == 429:
                    retry = int(r.headers.get("Retry-After", "60"))
                    _lzt_cooldown_until = time.time() + retry
                    raise RuntimeError(f"Rate-limited {retry}s")
                if r.status >= 500:
                    raise RuntimeError(f"LZT {r.status}")
                data = await r.json()
                if data.get("errors"):
                    raise RuntimeError(f"LZT error: {data['errors']}")
                return data
    except Exception as e:
        _lzt_last_error = str(e)
        raise


async def cache_lzt_stock_loop_once():
    if not LZT_ENABLED or not LZT_TOKEN:
        return
    try:
        data = await lzt_fetch("/telegram", {"category_id": 1, "pmax": 100,
                                             "spam": "0", "geoblock": "0", "offline": "0"})
        items = data.get("items", {}) or {}
        cur.execute("DELETE FROM lzt_cache")
        n = 0
        for iid, it in items.items():
            origin = (it.get("origin") or {}).get("country", "Unknown")
            cur.execute(
                "INSERT OR REPLACE INTO lzt_cache "
                "(item_id, country, price_usd, payload, spam, twofa, premium, mail, "
                " dc, gifts, stars, has_admin, origin, breakout) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (str(iid), origin, float(it.get("price", 0)), json.dumps(it),
                 int(bool(it.get("spamBlock"))), int(bool(it.get("hasPassword"))),
                 int(bool(it.get("premium"))), int(bool(it.get("hasMail"))),
                 int(it.get("dc_id", 0) or 0), int(bool(it.get("gifts"))),
                 int(bool(it.get("stars"))), int(bool(it.get("hasAdmin"))),
                 origin, it.get("breakoutType", "")))
            n += 1
        db.commit()
        logger.info(f"LZT cache: {n} items")
    except Exception as e:
        logger.error(f"LZT loop: {e}")


async def cache_lzt_stock_loop():
    if not LZT_ENABLED or not LZT_TOKEN:
        logger.info("LZT disabled")
        return
    while True:
        await cache_lzt_stock_loop_once()
        await asyncio.sleep(300)


def _apply_market_filters(uid):
    row = cur.execute(
        "SELECT spam, twofa, premium, origin, breakout, mail, dc, gifts, admin, sort "
        "FROM market_filters WHERE user_id=?", (uid,)).fetchone()
    if not row:
        return "", [], "price_usd ASC"
    spam, twofa, premium, origin, breakout, mail, dc, gifts, admin, sort = row
    where, params = [], []
    if spam == "clean":
        where.append("spam=0")
    elif spam == "restricted":
        where.append("spam=1")
    if twofa == "no":
        where.append("twofa=0")
    elif twofa == "has":
        where.append("twofa=1")
    if premium == "yes":
        where.append("premium=1")
    elif premium == "no":
        where.append("premium=0")
    if origin != "any":
        where.append("origin=?")
        params.append(origin)
    if breakout == "recent":
        where.append("breakout!=''")
    elif breakout == "aged":
        where.append("breakout=''")
    if mail == "has":
        where.append("mail=1")
    elif mail == "no":
        where.append("mail=0")
    if dc != "any":
        try:
            where.append("dc=?")
            params.append(int(dc))
        except ValueError:
            pass
    if gifts == "has":
        where.append("(gifts=1 OR stars=1)")
    elif gifts == "none":
        where.append("gifts=0 AND stars=0")
    if admin == "has":
        where.append("has_admin=1")
    elif admin == "clean":
        where.append("has_admin=0")
    sort_map = {"cheapest": "price_usd ASC", "expensive": "price_usd DESC",
                "newest": "added DESC"}
    return ("WHERE " + " AND ".join(where) if where else ""), params, \
        sort_map.get(sort, "price_usd ASC")


async def show_lzt_market(event):
    uid = event.sender_id
    cur.execute("INSERT OR IGNORE INTO market_filters (user_id) VALUES (?)", (uid,))
    db.commit()
    row = cur.execute(
        "SELECT spam, twofa, premium, origin, breakout, mail, dc, gifts, admin, sort, profile "
        "FROM market_filters WHERE user_id=?", (uid,)).fetchone()
    if not row:
        return await event.answer("DB error", alert=True)
    labels = ["Spam", "2FA", "Premium", "Origin", "Breakout", "Mail",
              "DC", "Gifts/Stars", "Admin/Ch", "Sort", "Profile"]
    icons = {"any": "🔄", "clean": "🟢", "restricted": "🔴", "has": "✅",
             "no": "❌", "yes": "✅", "none": "❌", "recent": "🆕",
             "aged": "📅", "cheapest": "⬇️", "expensive": "⬆️",
             "newest": "🆕", "default": "⚙️", "custom": "🎨"}
    btns = []
    for i, (lbl, val) in enumerate(zip(labels, row)):
        ic = icons.get(str(val), "•")
        btns.append([Button.inline(f"{lbl}: {ic} {val}", f"mflt|{i}")])
    where, params, order = _apply_market_filters(uid)
    cnt = cur.execute(f"SELECT COUNT(*) FROM lzt_cache {where}", params).fetchone()[0]
    btns.append([Button.inline(f"🛒 Browse {cnt} Items", "s1_browse")])
    btns.append([Button.inline("🔄 Reset", "mflt_reset"),
                 Button.inline("⬅️ Back", "s1_buyback")])
    txt = (f"🌐 <b>Server 1 — LZT Market</b>\n\n"
           f"📦 Available: <b>{cnt}</b>\n"
           f"💰 Rate: 1 USDT = ₹{get_usdt_rate()} (+{LZT_MARKUP_PCT:.1f}% markup)\n\n"
           f"Tap filters to cycle values.")
    if _lzt_cooldown_until > time.time():
        txt += f"\n\n⚠️ Rate-limited: {int(_lzt_cooldown_until - time.time())}s"
    try:
        await event.edit(txt, buttons=btns)
    except MessageNotModifiedError:
        pass


async def buy_back_to_categories(event):
    await event.edit(f"{PE_HEART} <b>Buy Menu</b>\n\nChoose source:",
                     buttons=[
                         [Button.inline("📦 Server 2 (Own Stock)", "cat|single|spam_free")],
                         [Button.inline("🌐 Server 1 (LZT Market)", "s1_market")],
                         [Button.inline("Cancel", "cancel_action")],
                     ])


async def reset_market_filters(event):
    cur.execute(
        "UPDATE market_filters SET spam='any',twofa='any',premium='any',origin='any',"
        "breakout='any',mail='any',dc='any',gifts='any',admin='any',sort='cheapest',"
        "profile='default' WHERE user_id=?", (event.sender_id,))
    db.commit()
    return await show_lzt_market(event)


async def cycle_filter(event, idx):
    uid = event.sender_id
    cols = ["spam", "twofa", "premium", "origin", "breakout", "mail",
            "dc", "gifts", "admin", "sort", "profile"]
    options = {
        "spam": ["any", "clean", "restricted"],
        "twofa": ["any", "no", "has"],
        "premium": ["any", "yes", "no"],
        "origin": ["any"] + list({v[0] for v in COUNTRY_CODES.values()}),
        "breakout": ["any", "recent", "aged"],
        "mail": ["any", "has", "no"],
        "dc": ["any", "1", "2", "3", "4", "5"],
        "gifts": ["any", "has", "none"],
        "admin": ["any", "has", "clean"],
        "sort": ["cheapest", "expensive", "newest"],
        "profile": ["default", "custom"],
    }
    col = cols[int(idx)]
    row = cur.execute(f"SELECT {col} FROM market_filters WHERE user_id=?", (uid,)).fetchone()
    cur_val = row[0] if row else "any"
    opts = options[col]
    nxt = opts[(opts.index(cur_val) + 1) % len(opts)] if cur_val in opts else opts[0]
    cur.execute(f"UPDATE market_filters SET {col}=? WHERE user_id=?", (nxt, uid))
    db.commit()
    await show_lzt_market(event)


async def lzt_browse(event, page=1):
    uid = event.sender_id
    where, params, order = _apply_market_filters(uid)
    limit, offset = 5, (page - 1) * 5
    rows = cur.execute(f"SELECT item_id, country, price_usd FROM lzt_cache {where} "
                       f"ORDER BY {order} LIMIT ? OFFSET ?",
                       params + [limit, offset]).fetchall()
    total = cur.execute(f"SELECT COUNT(*) FROM lzt_cache {where}", params).fetchone()[0]
    if not rows:
        return await event.edit("No items match filters.",
                                buttons=[[Button.inline("⬅️ Back", "s1_market")]])
    msg = f"🌐 <b>Server 1 Listing</b> (page {page})\n\n"
    btns = []
    for iid, country, usd in rows:
        flag = get_flag_by_country_name(country)
        inr = lzt_inr_price(usd)
        msg += f"{flag} {html.escape(country)} — ${usd:.2f} → ₹{inr}\n"
        btns.append([Button.inline(f"🛒 Buy {flag} ₹{inr}", f"s1_buy|{iid}")])
    nav = []
    if page > 1:
        nav.append(Button.inline("Prev", f"s1_pg|{page-1}"))
    if offset + limit < total:
        nav.append(Button.inline("Next", f"s1_pg|{page+1}"))
    if nav:
        btns.append(nav)
    btns.append([Button.inline("⬅️ Back", "s1_market")])
    await event.edit(msg, buttons=btns)


async def lzt_fast_buy(event, item_id):
    uid = event.sender_id
    if not LZT_ENABLED:
        return await event.answer("❌ LZT disabled.", alert=True)
    row = cur.execute("SELECT price_usd FROM lzt_cache WHERE item_id=?", (item_id,)).fetchone()
    if not row:
        return await event.answer("❌ Item sold/expired. Refresh list.", alert=True)
    cached_usd = row[0]
    try:
        fresh = await lzt_fetch(f"/{item_id}")
        real_usd = float(fresh.get("item", {}).get("price", cached_usd))
    except Exception as e:
        return await event.answer(f"⚠️ Price check failed: {str(e)[:80]}", alert=True)
    if abs(real_usd - cached_usd) > 0.01:
        cur.execute("UPDATE lzt_cache SET price_usd=? WHERE item_id=?", (real_usd, item_id))
        db.commit()
        return await event.answer(
            f"⚠️ Price changed: ${cached_usd:.2f} → ${real_usd:.2f}. Confirm again.",
            alert=True)
    inr_price = lzt_inr_price(real_usd)
    async with get_user_lock(uid):
        bal_row = cur.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
        cur_bal = bal_row[0] if bal_row else 0
        if cur_bal < inr_price:
            return await event.answer(f"❌ Need ₹{inr_price}. You have ₹{cur_bal}.", alert=True)
        cur.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (inr_price, uid))
        db.commit()
    await event.edit(f"{PE_LIGHTNING} <b>Purchasing…</b>\nItem: {item_id}\nPrice: ₹{inr_price}")
    success, last_err = False, ""
    for attempt in range(3):
        try:
            bought = await lzt_fetch(f"/{item_id}/buy",
                                     params={"price": real_usd, "currency": "usd"})
            if bought.get("item"):
                success = True
                break
        except Exception as e:
            last_err = str(e)
            logger.warning(f"LZT buy {attempt+1}: {e}")
            await asyncio.sleep(2 ** attempt)
    if not success:
        async with get_user_lock(uid):
            cur.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (inr_price, uid))
            db.commit()
        return await event.edit(
            f"{P_NO} Purchase failed: {html.escape(last_err[:200])}\n₹{inr_price} refunded.")
    otp_code = None
    for _ in range(3):
        try:
            otp_resp = await lzt_fetch(f"/{item_id}/telegram-login-code")
            otp_code = otp_resp.get("code")
            if otp_code:
                break
        except Exception:
            pass
        await asyncio.sleep(5)
    cur.execute("INSERT INTO orders (user_id, country, year, price, phone, otp) "
                "VALUES (?,?,?,?,?,?)",
                (uid, "LZT-" + item_id, 2024, inr_price, item_id, otp_code or "PENDING"))
    cur.execute("DELETE FROM lzt_cache WHERE item_id=?", (item_id,))
    db.commit()
    await log_primary_purchase(uid, "LZT-" + item_id, inr_price, inr_price, 2024, 1)
    if otp_code:
        await event.edit(
            f"{PE_CHECK} <b>Server 1 Purchase OK!</b>\n\n"
            f"🆔 <code>{item_id}</code>\n💰 Paid: ₹{inr_price}\n"
            f"🔑 OTP: <code>{otp_code}</code>\n\n"
            f"<i>Login now.</i>")
    else:
        await event.edit(
            f"✅ <b>Purchased!</b> OTP not auto-retrieved.\n"
            f"🆔 <code>{item_id}</code>\n💰 ₹{inr_price}\n\n"
            f"Tap below to retry:",
            buttons=[[Button.inline("🔄 Fetch OTP", f"lzt_otp|{item_id}")]])


async def lzt_retry_otp(event, item_id):
    await event.answer("Fetching…")
    try:
        resp = await lzt_fetch(f"/{item_id}/telegram-login-code")
        code = resp.get("code")
        if code:
            await event.edit(f"🔑 <b>OTP:</b> <code>{code}</code>\n"
                             f"🆔 {item_id}",
                             buttons=[[Button.inline("Back to Market", "s1_market")]])
        else:
            await event.answer("⏳ Not ready yet.", alert=True)
    except Exception as e:
        await event.answer(f"❌ {str(e)[:80]}", alert=True)


# ================= NUMBER CHANGE =================
async def number_change_flow(event):
    if setting_get("number_change_enabled", "off") != "on":
        return await event.answer("⚠️ Disabled.", alert=True)
    async with bot.conversation(event.chat_id, timeout=180) as conv:
        await conv.send_message("🔁 <b>Number Change Service</b>\n\nEnter phone to change:")
        phone = (await conv.get_response()).raw_text.strip().replace("+", "")
        await conv.send_message("Enter NEW number:")
        new_num = (await conv.get_response()).raw_text.strip().replace("+", "")
        fee = 100
        async with get_user_lock(event.sender_id):
            r = cur.execute("SELECT balance FROM users WHERE user_id=?",
                            (event.sender_id,)).fetchone()
            if not r or r[0] < fee:
                return await conv.send_message(f"❌ Insufficient balance (₹{fee} required).")
            cur.execute("UPDATE users SET balance=balance-? WHERE user_id=?",
                        (fee, event.sender_id))
            cur.execute("INSERT INTO number_change_requests (user_id, phone, old_number, "
                        "new_number, fee) VALUES (?,?,?,?,?)",
                        (event.sender_id, phone, phone, new_num, fee))
            db.commit()
        rid = cur.lastrowid
        if LOG_CHANNEL_ID:
            await bot.send_message(LOG_CHANNEL_ID,
                f"🔁 <b>Number Change #{rid}</b>\nUser: {event.sender_id}\n"
                f"Old: +{phone}\nNew: +{new_num}\nFee: ₹{fee}",
                buttons=[[Button.inline("✅ Done", f"ncr_ok|{rid}"),
                          Button.inline("❌ Reject", f"ncr_no|{rid}")]])
        await conv.send_message("✅ Request submitted. Admin will process.")


async def handle_number_change_decision(event, data):
    if not is_admin(event.sender_id):
        return await event.answer("⛔", alert=True)
    kind, rid = data.split("|")
    rid = int(rid)
    row = cur.execute("SELECT user_id, fee FROM number_change_requests "
                      "WHERE id=? AND status='pending'", (rid,)).fetchone()
    if not row:
        return await event.answer("Already processed.", alert=True)
    tuid, fee = row
    if kind == "ncr_ok":
        cur.execute("UPDATE number_change_requests SET status='done' WHERE id=?", (rid,))
        db.commit()
        await bot.send_message(tuid, "✅ Your number change is complete!")
        await event.edit(f"✅ #{rid} done")
    else:
        cur.execute("UPDATE number_change_requests SET status='rejected' WHERE id=?", (rid,))
        cur.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (fee, tuid))
        db.commit()
        await bot.send_message(tuid, f"❌ Rejected — ₹{fee} refunded.")
        await event.edit(f"❌ #{rid} rejected")
        
        # ================= ADMIN PANEL =================
async def admin_panel_handler(event):
    uid = event.sender_id
    if not is_admin(uid):
        return
    status = "🟢 ON" if is_bot_online() else "🔴 OFF"
    total_users = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    total_stock = cur.execute("SELECT COUNT(*) FROM stock WHERE available=1").fetchone()[0]
    pending_deps = cur.execute("SELECT COUNT(*) FROM deposits WHERE status='pending'").fetchone()[0]
    btns = []
    if uid == ADMIN_ID or has_perm(uid, 'p_settings'):
        btns.append([Button.inline(f"Bot Status: {status}", "adm_togglebot")])
    if uid == ADMIN_ID or has_perm(uid, 'p_add_stock'):
        btns.append([Button.inline("📦 Add Stock", "adm_catmenu")])
    if uid == ADMIN_ID or has_perm(uid, 'p_manage_stock'):
        btns.append([Button.inline("📦 Manage Stock", "adm_managestock"),
                     Button.inline("📦 Auto Price", "adm_autoprice")])
    if uid == ADMIN_ID or has_perm(uid, 'p_stats'):
        btns.append([Button.inline("Stats", "adm_stats"),
                     Button.inline("Broadcast", "adm_bcast"),
                     Button.inline("User Info", "adm_userinfo")])
    if uid == ADMIN_ID or has_perm(uid, 'p_bal'):
        btns.append([Button.inline("Balance", "adm_bal"),
                     Button.inline("Ban User", "adm_ban")])
    if uid == ADMIN_ID or has_perm(uid, 'p_settings'):
        btns.append([Button.inline("Discount", "adm_discount"),
                     Button.inline("Ref ₹ Amount", "adm_refpct")])
        btns.append([Button.inline(f"Referral: {'🟢' if is_ref_enabled() else '🔴'}", "adm_reftoggle")])
        btns.append([Button.inline("Support URL", "adm_supporturl"),
                     Button.inline("Payments", "adm_payments")])
        btns.append([Button.inline("USDT Rate", "adm_usdtrate")])
        btns.append([Button.inline("💸 Sell Prices", "adm_sellprices"),
                     Button.inline("🚫 Blacklist", "adm_blacklist")])
        btns.append([Button.inline("💳 Withdrawals", "adm_withdrawals"),
                     Button.inline("🎟️ Promo Codes", "adm_promos")])
        btns.append([Button.inline("🌐 LZT Settings", "adm_lzt"),
                     Button.inline("🔁 NCR", "adm_ncr")])
        btns.append([Button.inline("⚙️ Toggles", "adm_toggles")])
        btns.append([Button.inline("Backup Users", "adm_backupusr"),
                     Button.inline("Restore Users", "adm_restoreusr")])
    if uid == ADMIN_ID:
        btns.append([Button.inline("Manage Admins", "adm_manageadmins")])
    header = (f"{PE_CROWN} <b>ADMIN DASHBOARD</b>\n\n"
              f"{P_USERS} Users: <b>{total_users}</b>\n"
              f"{P_PKG} Stock: <b>{total_stock}</b>\n"
              f"{P_WAIT} Pending Deps: <b>{pending_deps}</b>")
    await bot.send_message(event.chat_id, header, buttons=btns)


async def manage_admins_menu(event):
    rows = cur.execute("SELECT user_id FROM admins").fetchall()
    msg = f"{PE_CROWN} <b>Sub-Admins</b>\n\n"
    for r in rows:
        msg += f"{P_ACC} <code>{r[0]}</code>\n"
    btns = [[Button.inline("Add Admin", "adm_addadmin"),
             Button.inline("Edit Admin", "adm_editadminreq")],
            [Button.inline("Back", "adm_adminmain")]]
    await event.edit(msg, buttons=btns)


async def edit_admin_menu(event, target_id):
    row = cur.execute("SELECT p_add_stock, p_manage_stock, p_stats, p_bal, p_settings "
                      "FROM admins WHERE user_id=?", (target_id,)).fetchone()
    if not row:
        return await event.answer("Admin not found", alert=True)
    p = ["✅" if x == 1 else "❌" for x in row]
    btns = [
        [Button.inline(f"Add Stock: {p[0]}", f"adm_tglperm|{target_id}|p_add_stock")],
        [Button.inline(f"Manage Stock: {p[1]}", f"adm_tglperm|{target_id}|p_manage_stock")],
        [Button.inline(f"Stats/Bcast: {p[2]}", f"adm_tglperm|{target_id}|p_stats")],
        [Button.inline(f"Bal/Users: {p[3]}", f"adm_tglperm|{target_id}|p_bal")],
        [Button.inline(f"Settings: {p[4]}", f"adm_tglperm|{target_id}|p_settings")],
        [Button.inline("Remove Admin", f"adm_deladmin|{target_id}")],
        [Button.inline("Back", "adm_manageadmins")],
    ]
    await event.edit(f"✏️ <b>Editing:</b> <code>{target_id}</code>", buttons=btns)


async def send_managestock_catmenu(event):
    btns = [[Button.inline(f"{icon} {label}", f"adm_mscat|{key}")]
            for key, icon, label in CATEGORIES]
    btns.append([Button.inline("Back", "adm_adminmain")])
    await event.edit(f"{PE_LOCATION} <b>Manage Stock</b>\nCategory:", buttons=btns)


async def send_manage_stock_page(event, category, page):
    limit = 10
    offset = (page - 1) * limit
    rows = cur.execute("SELECT DISTINCT country_name FROM stock WHERE category=? "
                       "ORDER BY country_name", (category,)).fetchall()
    total = len(rows)
    countries = rows[offset:offset + limit]
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
        return await event.edit(f"{PE_LOCATION} <b>Manage Stock</b>\n📦 {cat_label(category)}\n\n"
                                f"{P_NO} Empty.", buttons=btns)
    await event.edit(f"{PE_LOCATION} <b>Manage Stock</b> (Page {page})\n"
                     f"📦 {cat_label(category)}\nSelect a country:", buttons=btns)


async def send_manage_stock_country(event, category, h):
    c_name = resolve_country(category, h)
    if not c_name:
        return await event.answer("❌ Not found (refresh).", alert=True)
    years = cur.execute("SELECT DISTINCT account_year FROM stock WHERE category=? "
                        "AND country_name=? ORDER BY account_year DESC",
                        (category, c_name)).fetchall()
    flag = get_flag_by_country_name(c_name)
    btns = [
        [Button.inline("Edit Name", f"adm_msedit|name|{category}|{h}"),
         Button.inline("Edit Flag", f"adm_msedit|flag|{category}|{h}")],
        [Button.inline("Edit Common Price", f"adm_msedit|cprice|{category}|{h}")],
        [Button.inline("🔀 Move Category", f"adm_msmove|{category}|{h}")],
    ]
    y_btns = [Button.inline(f"{y}", f"adm_msedit|yprice|{category}|{h}|{y}") for (y,) in years]
    for i in range(0, len(y_btns), 3):
        btns.append(y_btns[i:i + 3])
    btns.append([Button.inline("Back", f"adm_mspg|{category}|1")])
    await event.edit(f"{flag} <b>{html.escape(c_name)}</b>\n📦 {cat_label(category)}\n"
                     f"Edit option:", buttons=btns)


async def send_autoprice_catmenu(event):
    btns = [[Button.inline(f"{icon} {label}", f"adm_apcat|{key}")]
            for key, icon, label in CATEGORIES]
    btns.append([Button.inline("Back", "adm_adminmain")])
    await event.edit(f"{PE_LIGHTNING} <b>Auto Price</b>\nCategory:", buttons=btns)


async def send_autoprice_page(event, category, page):
    limit = 10
    offset = (page - 1) * limit
    c_list = sorted(all_country_names(category))
    total = len(c_list)
    countries = c_list[offset:offset + limit]
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
    await event.edit(f"{PE_LIGHTNING} <b>Auto Price</b> (Page {page})\n"
                     f"📦 {cat_label(category)}\nSelect country:", buttons=btns)


async def send_autoprice_country(event, category, h):
    c_name = resolve_any_country(category, h)
    if not c_name:
        return await event.answer("❌ Not found.", alert=True)
    flag = get_flag_by_country_name(c_name)
    btns = [[Button.inline("Set Common Price", f"adm_apset|{category}|{h}|Common")]]
    y_btns = [Button.inline(f"{y}", f"adm_apset|{category}|{h}|{y}")
              for y in range(datetime.now().year, 1999, -1)]
    for i in range(0, len(y_btns), 4):
        btns.append(y_btns[i:i + 4])
    btns.append([Button.inline("Back", f"adm_appg|{category}|1")])
    await event.edit(f"{flag} <b>Auto Price: {html.escape(c_name)}</b>\n"
                     f"📦 {cat_label(category)}\nPick Common or specific year:", buttons=btns)


# ================= ADMIN ACTIONS DISPATCHER =================
async def admin_actions(event):
    data_full = event.data.decode()
    if not data_full.startswith("adm_"):
        return
    uid = event.sender_id
    action_data = data_full[4:]
    chat = event.chat_id

    # Simple navigations
    if action_data == "adminmain":
        await event.delete()

        class _Fake:
            chat_id = chat
            sender_id = uid
        return await admin_panel_handler(_Fake())

    if action_data == "catmenu" and has_perm(uid, 'p_add_stock'):
        btns = [[Button.inline(f"{icon} {label}", f"adm_catpick|{key}")]
                for key, icon, label in CATEGORIES]
        btns.append([Button.inline("Back", "adm_adminmain")])
        return await event.edit("📦 <b>Category to add stock:</b>", buttons=btns)

    if action_data.startswith("catpick|") and has_perm(uid, 'p_add_stock'):
        cat = action_data.split("|")[1]
        btns = [[Button.inline("Add Single Acc", f"adm_addstock|{cat}"),
                 Button.inline("Add ZIP", f"adm_addzip|{cat}")],
                [Button.inline("Back", "adm_catmenu")]]
        return await event.edit(f"📦 <b>Category:</b> {cat_label(cat)}\n"
                                f"Choose add method:", buttons=btns)

    if action_data == "togglebot" and has_perm(uid, 'p_settings'):
        new = 'off' if is_bot_online() else 'on'
        setting_set("bot_status", new)
        await event.answer(f"Bot {new.upper()}", alert=True)

        class _Fake:
            chat_id = chat
            sender_id = uid
        await event.delete()
        return await admin_panel_handler(_Fake())

    if action_data == "reftoggle" and has_perm(uid, 'p_settings'):
        new = 'off' if is_ref_enabled() else 'on'
        setting_set("ref_enabled", new)
        await event.answer(f"Referral {new.upper()}", alert=True)

        class _Fake:
            chat_id = chat
            sender_id = uid
        await event.delete()
        return await admin_panel_handler(_Fake())

    if action_data == "stats" and has_perm(uid, 'p_stats'):
        u = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        s = cur.execute("SELECT COUNT(*) FROM stock WHERE available=1").fetchone()[0]
        r = setting_get("upi_revenue", "0")
        bal = cur.execute("SELECT SUM(balance) FROM users").fetchone()[0] or 0
        o = cur.execute("SELECT COUNT(*), SUM(price) FROM orders").fetchone()
        to = o[0] or 0
        sp = o[1] or 0
        msg = (f"{P_STATS} <b>ADVANCED STATS</b>\n\n"
               f"{P_USERS} Users: {u}\n"
               f"{P_PKG} Stock: {s}\n"
               f"{P_MONEY} UPI Revenue: ₹{r}\n\n"
               f"{P_CARD} Users Balance: ₹{bal}\n"
               f"{P_CART} Sold: {to}\n"
               f"{P_USDT} Total Sales: ₹{sp}")
        return await event.edit(msg, buttons=[[Button.inline("Back", "adm_adminmain")]])

    if action_data == "payments" and has_perm(uid, 'p_settings'):
        btns = [[Button.inline("Add Payment", "adm_addpay")],
                [Button.inline("Remove Payment", "adm_delpay")],
                [Button.inline("Back", "adm_adminmain")]]
        return await event.edit(f"{P_CARD} <b>Payment Methods</b>", buttons=btns)

    if action_data == "manageadmins" and uid == ADMIN_ID:
        return await manage_admins_menu(event)

    if action_data.startswith("tglperm|") and uid == ADMIN_ID:
        _, t_id, p_name = action_data.split("|")
        if p_name not in ("p_add_stock", "p_manage_stock", "p_stats", "p_bal", "p_settings"):
            return await event.answer("Invalid", alert=True)
        cur.execute(f"UPDATE admins SET {p_name} = CASE WHEN {p_name}=1 THEN 0 ELSE 1 END "
                    f"WHERE user_id=?", (t_id,))
        db.commit()
        return await edit_admin_menu(event, t_id)

    if action_data.startswith("deladmin|") and uid == ADMIN_ID:
        t_id = action_data.split("|")[1]
        cur.execute("DELETE FROM admins WHERE user_id=?", (t_id,))
        db.commit()
        await event.answer("✅ Removed", alert=True)
        return await manage_admins_menu(event)

    if action_data == "managestock" and has_perm(uid, 'p_manage_stock'):
        return await send_managestock_catmenu(event)
    if action_data.startswith("mscat|") and has_perm(uid, 'p_manage_stock'):
        return await send_manage_stock_page(event, action_data.split("|")[1], 1)
    if action_data.startswith("mspg|") and has_perm(uid, 'p_manage_stock'):
        p = action_data.split("|")
        return await send_manage_stock_page(event, p[1], int(p[2]))
    if action_data.startswith("msc|") and has_perm(uid, 'p_manage_stock'):
        p = action_data.split("|")
        return await send_manage_stock_country(event, p[1], p[2])

    if action_data.startswith("msmove|") and has_perm(uid, 'p_manage_stock'):
        p = action_data.split("|")
        category, h = p[1], p[2]
        c_name = resolve_country(category, h)
        if not c_name:
            return await event.answer("❌ Not found.", alert=True)
        n = cur.execute("SELECT COUNT(*) FROM stock WHERE category=? AND country_name=?",
                        (category, c_name)).fetchone()[0]
        btns = [[Button.inline(f"{icon} {label}", f"adm_msmv2|{category}|{h}|{key}")]
                for key, icon, label in CATEGORIES if key != category]
        btns.append([Button.inline("Back", f"adm_msc|{category}|{h}")])
        return await event.edit(
            f"🔀 <b>Move: {html.escape(c_name)}</b>\n"
            f"📦 From: {cat_label(category)}\n{P_PKG} Accounts: <b>{n}</b>\n\n"
            f"New category?", buttons=btns)

    if action_data.startswith("msmv2|") and has_perm(uid, 'p_manage_stock'):
        p = action_data.split("|")
        category, h, new_cat = p[1], p[2], p[3]
        if new_cat not in CATEGORY_MAP or new_cat == category:
            return await event.answer("❌ Invalid", alert=True)
        c_name = resolve_country(category, h)
        if not c_name:
            return await event.answer("❌ Not found.", alert=True)
        cur.execute("UPDATE stock SET category=? WHERE country_name=? AND category=?",
                    (new_cat, c_name, category))
        moved = cur.rowcount
        db.commit()
        await event.answer(f"✅ {moved} moved to {CATEGORY_MAP[new_cat][1]}", alert=True)
        return await send_manage_stock_country(event, new_cat, h)

    if action_data == "autoprice" and has_perm(uid, 'p_manage_stock'):
        return await send_autoprice_catmenu(event)
    if action_data.startswith("apcat|") and has_perm(uid, 'p_manage_stock'):
        return await send_autoprice_page(event, action_data.split("|")[1], 1)
    if action_data.startswith("appg|") and has_perm(uid, 'p_manage_stock'):
        p = action_data.split("|")
        return await send_autoprice_page(event, p[1], int(p[2]))
    if action_data.startswith("apc|") and has_perm(uid, 'p_manage_stock'):
        p = action_data.split("|")
        return await send_autoprice_country(event, p[1], p[2])

    # ===== LZT SETTINGS =====
    if action_data == "lzt" and has_perm(uid, 'p_settings'):
        global LZT_ENABLED
        btns = [
            [Button.inline(f"LZT Enabled: {'🟢 ON' if LZT_ENABLED else '🔴 OFF'}", "adm_lzt_toggle")],
            [Button.inline(f"Markup: {LZT_MARKUP_PCT:.1f}%", "adm_lzt_markup")],
            [Button.inline("Rotate Token", "adm_lzt_token")],
            [Button.inline(f"Cache: {cur.execute('SELECT COUNT(*) FROM lzt_cache').fetchone()[0]}",
                           "adm_lzt_refresh")],
            [Button.inline("Back", "adm_adminmain")],
        ]
        return await event.edit("🌐 <b>LZT Market Settings</b>", buttons=btns)

    if action_data == "lzt_toggle" and has_perm(uid, 'p_settings'):
        global LZT_ENABLED
        LZT_ENABLED = not LZT_ENABLED
        setting_set("lzt_enabled", "1" if LZT_ENABLED else "0")
        await event.answer(f"LZT {'ON' if LZT_ENABLED else 'OFF'}", alert=True)
        return await event.edit("✅ Toggled.",
                                buttons=[[Button.inline("Back", "adm_lzt")]])

    if action_data == "lzt_markup" and has_perm(uid, 'p_settings'):
        async with bot.conversation(chat, timeout=120) as conv:
            await conv.send_message(f"Current: {LZT_MARKUP_PCT:.1f}%\nNew % (e.g. 15):")
            v = (await conv.get_response()).raw_text.strip()
            try:
                global LZT_MARKUP_PCT
                LZT_MARKUP_PCT = float(v)
                setting_set("lzt_markup", str(LZT_MARKUP_PCT))
                await conv.send_message(f"✅ {LZT_MARKUP_PCT}%")
            except ValueError:
                await conv.send_message("❌ Invalid.")
        return

    if action_data == "lzt_token" and has_perm(uid, 'p_settings'):
        async with bot.conversation(chat, timeout=120) as conv:
            await conv.send_message("Send new LZT Bearer token (or /cancel):")
            r = await conv.get_response()
            if r.raw_text == "/cancel":
                return
            global LZT_TOKEN
            LZT_TOKEN = r.raw_text.strip()
            setting_set("lzt_token", LZT_TOKEN)
            await conv.send_message("✅ Token rotated.")
        return

    if action_data == "lzt_refresh" and has_perm(uid, 'p_settings'):
        await event.answer("Refreshing…")
        asyncio.create_task(cache_lzt_stock_loop_once())
        return await event.edit("🔄 Refresh started.",
                                buttons=[[Button.inline("Back", "adm_lzt")]])

    # ===== SELL PRICES =====
    if action_data == "sellprices" and has_perm(uid, 'p_settings'):
        rows = cur.execute("SELECT country_code, country_name, flag, price_usd "
                           "FROM sell_prices ORDER BY country_code").fetchall()
        msg = "💸 <b>Sell Price List</b>\n\n"
        for code, name, flag, usd in rows:
            msg += f"[{flag}] +{code}-{name}: {usd}$\n"
        btns = [[Button.inline("✏️ Edit Price", "adm_sellprices_edit")],
                [Button.inline("➕ Add Country", "adm_sellprices_add")],
                [Button.inline("Back", "adm_adminmain")]]
        return await event.edit(msg or "Empty.", buttons=btns)

    if action_data == "sellprices_edit" and has_perm(uid, 'p_settings'):
        async with bot.conversation(chat, timeout=180) as conv:
            await conv.send_message("Country Code (e.g. 998):")
            code = (await conv.get_response()).raw_text.strip()
            await conv.send_message("New USD price (e.g. 0.55):")
            try:
                usd = float((await conv.get_response()).raw_text.strip())
                cur.execute("UPDATE sell_prices SET price_usd=? WHERE country_code=?",
                            (usd, code))
                db.commit()
                await conv.send_message(f"✅ +{code} → {usd}$")
            except Exception:
                await conv.send_message("❌ Invalid.")
        return

    if action_data == "sellprices_add" and has_perm(uid, 'p_settings'):
        async with bot.conversation(chat, timeout=180) as conv:
            await conv.send_message("Country code (digits):")
            code = (await conv.get_response()).raw_text.strip()
            await conv.send_message("Country name:")
            name = (await conv.get_response()).raw_text.strip()
            await conv.send_message("Flag emoji:")
            flag = (await conv.get_response()).raw_text.strip()
            await conv.send_message("USD price:")
            try:
                usd = float((await conv.get_response()).raw_text.strip())
                cur.execute("INSERT OR REPLACE INTO sell_prices "
                            "(country_code, country_name, flag, price_usd) VALUES (?,?,?,?)",
                            (code, name, flag, usd))
                db.commit()
                await conv.send_message(f"✅ +{code}-{name} @ {usd}$")
            except Exception:
                await conv.send_message("❌ Invalid.")
        return

    # ===== BLACKLIST =====
    if action_data == "blacklist" and has_perm(uid, 'p_settings'):
        btns = [[Button.inline("➕ Add", "adm_bl_add"),
                 Button.inline("➖ Remove", "adm_bl_del")],
                [Button.inline("📋 List", "adm_bl_list")],
                [Button.inline("Back", "adm_adminmain")]]
        return await event.edit("🚫 <b>Blacklist</b>", buttons=btns)

    if action_data == "bl_add" and has_perm(uid, 'p_settings'):
        async with bot.conversation(chat, timeout=120) as conv:
            await conv.send_message("Phone to blacklist:")
            ph = (await conv.get_response()).raw_text.strip().replace("+", "")
            cur.execute("INSERT OR IGNORE INTO blacklisted_phones (phone, reason) "
                        "VALUES (?, '')", (ph,))
            db.commit()
            await conv.send_message(f"✅ +{ph} blacklisted.")
        return

    if action_data == "bl_del" and has_perm(uid, 'p_settings'):
        async with bot.conversation(chat, timeout=120) as conv:
            await conv.send_message("Phone to remove:")
            ph = (await conv.get_response()).raw_text.strip().replace("+", "")
            cur.execute("DELETE FROM blacklisted_phones WHERE phone=?", (ph,))
            db.commit()
            await conv.send_message(f"✅ +{ph} removed.")
        return

    if action_data == "bl_list" and has_perm(uid, 'p_settings'):
        rows = cur.execute("SELECT phone FROM blacklisted_phones LIMIT 50").fetchall()
        msg = "🚫 <b>Blacklist</b>\n\n" + ("\n".join(f"+{r[0]}" for r in rows)
                                          if rows else "Empty.")
        return await event.edit(msg, buttons=[[Button.inline("Back", "adm_blacklist")]])

    # ===== WITHDRAWALS =====
    if action_data == "withdrawals" and has_perm(uid, 'p_bal'):
        rows = cur.execute("SELECT id, user_id, amount, method, upi_id, status, created "
                           "FROM withdrawals ORDER BY id DESC LIMIT 20").fetchall()
        if not rows:
            return await event.edit("No withdrawals.",
                                    buttons=[[Button.inline("Back", "adm_adminmain")]])
        count = 0
        for wid, tuid, amt, method, upi, st, dt in rows:
            if st != "pending":
                continue
            count += 1
            cap = (f"💳 <b>Withdrawal #{wid}</b>\nUser: <code>{tuid}</code>\n"
                   f"Amount: ₹{amt}\nMethod: {method}\nUPI: {html.escape(upi or '—')}\n"
                   f"Date: {dt}")
            await bot.send_message(chat, cap,
                buttons=[[Button.inline("✅ Approve", f"wd_ok|{wid}"),
                          Button.inline("❌ Reject", f"wd_no|{wid}")]])
        await event.answer(f"{count} pending.", alert=True)
        return

    # ===== PROMO CODES =====
    if action_data == "promos" and has_perm(uid, 'p_settings'):
        rows = cur.execute("SELECT code, amount, max_uses, used FROM promo_codes "
                           "ORDER BY code").fetchall()
        msg = "🎟️ <b>Promo Codes</b>\n\n"
        for c, a, m, u in rows:
            msg += f"<code>{c}</code> — ₹{a} ({u}/{m})\n"
        btns = [[Button.inline("➕ Create", "adm_promo_add"),
                 Button.inline("🗑️ Delete", "adm_promo_del")],
                [Button.inline("Back", "adm_adminmain")]]
        return await event.edit(msg or "No codes.", buttons=btns)

    if action_data == "promo_add" and has_perm(uid, 'p_settings'):
        async with bot.conversation(chat, timeout=180) as conv:
            await conv.send_message("Code (uppercase):")
            code = (await conv.get_response()).raw_text.strip().upper()
            await conv.send_message("Amount ₹:")
            amt = int((await conv.get_response()).raw_text.strip())
            await conv.send_message("Max uses:")
            mx = int((await conv.get_response()).raw_text.strip())
            cur.execute("INSERT OR REPLACE INTO promo_codes "
                        "(code, amount, max_uses, used) VALUES (?,?,?,0)",
                        (code, amt, mx))
            db.commit()
            await conv.send_message(f"✅ `{code}` created: ₹{amt} × {mx}")
        return

    if action_data == "promo_del" and has_perm(uid, 'p_settings'):
        async with bot.conversation(chat, timeout=120) as conv:
            await conv.send_message("Enter code to delete:")
            code = (await conv.get_response()).raw_text.strip().upper()
            cur.execute("DELETE FROM promo_codes WHERE code=?", (code,))
            db.commit()
            await conv.send_message(f"🗑️ Deleted `{code}`")
        return

    # ===== TOGGLES =====
    if action_data == "toggles" and has_perm(uid, 'p_settings'):
        flags = ["sell_enabled", "number_change_enabled", "upi_enabled",
                 "cwallet_enabled", "fight_enabled"]
        btns = []
        for k in flags:
            v = setting_get(k, "off")
            btns.append([Button.inline(
                f"{k.replace('_', ' ').title()}: {'🟢' if v == 'on' else '🔴'}",
                f"adm_tg|{k}")])
        btns.append([Button.inline("Back", "adm_adminmain")])
        return await event.edit("⚙️ <b>Feature Toggles</b>", buttons=btns)

    if action_data.startswith("tg|") and has_perm(uid, 'p_settings'):
        key = action_data.split("|", 1)[1]
        cur_val = setting_get(key, "off")
        new = "off" if cur_val == "on" else "on"
        setting_set(key, new)
        await event.answer(f"{key}: {new.upper()}")
        flags = ["sell_enabled", "number_change_enabled", "upi_enabled",
                 "cwallet_enabled", "fight_enabled"]
        btns = []
        for k in flags:
            v = setting_get(k, "off")
            btns.append([Button.inline(
                f"{k.replace('_', ' ').title()}: {'🟢' if v == 'on' else '🔴'}",
                f"adm_tg|{k}")])
        btns.append([Button.inline("Back", "adm_adminmain")])
        return await event.edit("⚙️ <b>Feature Toggles</b>", buttons=btns)

    # ===== NUMBER CHANGE REQUESTS =====
    if action_data == "ncr" and has_perm(uid, 'p_bal'):
        rows = cur.execute("SELECT id, user_id, phone, old_number, new_number, fee "
                           "FROM number_change_requests WHERE status='pending'").fetchall()
        if not rows:
            return await event.edit("No pending NCRs.",
                                    buttons=[[Button.inline("Back", "adm_adminmain")]])
        for rid, tuid, phone, old_n, new_n, fee in rows:
            cap = (f"🔁 <b>Number Change #{rid}</b>\nUser: {tuid}\n"
                   f"Old: +{old_n}\nNew: +{new_n}\nFee: ₹{fee}")
            await bot.send_message(chat, cap,
                buttons=[[Button.inline("✅ Done", f"ncr_ok|{rid}"),
                          Button.inline("❌ Reject", f"ncr_no|{rid}")]])
        await event.answer("Sent.", alert=True)
        return

    # ===== BACKUP / RESTORE =====
    if action_data == "backupusr" and has_perm(uid, 'p_settings'):
        cur.execute("SELECT * FROM users")
        with open("users_backup.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([i[0] for i in cur.description])
            w.writerows(cur.fetchall())
        await bot.send_file(chat, "users_backup.csv",
                            caption=f"{P_USERS} <b>Users Backup</b>")
        os.remove("users_backup.csv")
        return await event.answer("✅ Backup generated!", alert=True)

    # ===== CONVERSATION-BASED ADMIN ACTIONS =====
    async with bot.conversation(chat, timeout=600) as conv:
        async def get_reply(txt):
            await conv.send_message(txt + "\n\n<i>(/cancel to abort)</i>")
            resp = await conv.get_response()
            if resp.raw_text == "/cancel":
                raise AdminCancelled()
            return resp

        try:
            if action_data.startswith("ap_add_country") and has_perm(uid, 'p_manage_stock'):
                code = (await get_reply(f"{P_PHONE} <b>Country Calling Code (no +):</b>\n"
                                        f"<i>e.g. 91</i>")).raw_text.replace("+", "").strip()
                flag = (await get_reply(f"{P_FLAG} <b>Flag emoji:</b>\n"
                                        f"<i>e.g. 🇮🇳</i>")).raw_text.strip()
                name = (await get_reply(f"{P_GLOBE} <b>Country Name:</b>\n"
                                        f"<i>e.g. India</i>")).raw_text.strip()
                cur.execute("INSERT OR REPLACE INTO custom_countries "
                            "(code, name, flag) VALUES (?,?,?)", (code, name, flag))
                db.commit()
                await conv.send_message(f"{P_YES} <b>Added!</b>\n{flag} {html.escape(name)} (+{code})")

            elif action_data == "userinfo" and has_perm(uid, 'p_stats'):
                t_uid = int((await get_reply(f"{P_ACC} <b>User ID:</b>")).raw_text)
                await conv.send_message("Fetching…")
                row = cur.execute("SELECT user_id, balance, sales_balance, total_deposited, "
                                  "joined_date, banned, discount FROM users WHERE user_id=?",
                                  (t_uid,)).fetchone()
                if not row:
                    return await conv.send_message(f"{P_NO} Not found.")
                _, bal, sb, dep, joined, banned, disc = row
                o = cur.execute("SELECT COUNT(*), SUM(price) FROM orders WHERE user_id=?",
                                (t_uid,)).fetchone()
                o_cnt = o[0] or 0
                o_spent = o[1] or 0
                upi_dep = cur.execute("SELECT SUM(amount) FROM upi_orders WHERE user_id=? "
                                      "AND status='success'", (t_uid,)).fetchone()[0] or 0
                msg = (f"{P_ACC} <b>USER:</b> <code>{t_uid}</code>\n\n"
                       f"{P_MONEY} Balance: ₹{bal}\n💸 Sales: ₹{sb}\n"
                       f"{P_CARD} Deposited: ₹{dep}\n{P_UPI} UPI: ₹{upi_dep}\n"
                       f"{P_CART} Orders: {o_cnt}\n{P_USDT} Spent: ₹{o_spent}\n"
                       f"{P_GIFT} Discount: {disc}%\n{P_CAL} Joined: {joined}\n"
                       f"{P_OFF} Banned: {'Yes' if banned else 'No'}")
                await conv.send_message(msg)

            elif action_data == "addadmin" and uid == ADMIN_ID:
                new_ad = int((await get_reply(f"{P_ACC} <b>New Admin User ID:</b>")).raw_text)
                cur.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (new_ad,))
                db.commit()
                await conv.send_message(f"{P_YES} Admin added!")

            elif action_data == "editadminreq" and uid == ADMIN_ID:
                t_id = int((await get_reply(f"{P_ACC} <b>Admin ID to edit:</b>")).raw_text)
                await conv.send_message(f"Editing {t_id}… (open panel)")
                # We'll let admin tap Manage Admins again

            elif action_data.startswith("msedit|") and has_perm(uid, 'p_manage_stock'):
                parts = action_data.split("|")
                action, category, h = parts[1], parts[2], parts[3]
                c_name = resolve_country(category, h)
                if not c_name:
                    return await conv.send_message(f"{P_NO} Country not found (refresh list).")
                e_name = html.escape(c_name)
                if action == "name":
                    new_name = (await get_reply(f"{P_DOC} <b>New Name for {e_name}:</b>")).raw_text.strip()
                    if not new_name:
                        return await conv.send_message(f"{P_NO} Empty name.")
                    cur.execute("UPDATE stock SET country_name=? WHERE country_name=? AND category=?",
                                (new_name, c_name, category))
                    cur.execute("UPDATE auto_prices SET country=? WHERE country=? AND category=?",
                                (new_name, c_name, category))
                    db.commit()
                    await conv.send_message(f"{P_YES} Renamed → '{html.escape(new_name)}'.")
                elif action == "flag":
                    new_flag = (await get_reply(f"{P_FLAG} <b>New Flag for {e_name}:</b>")).raw_text.strip()
                    cur.execute("UPDATE stock SET country_icon=? WHERE country_name=? AND category=?",
                                (new_flag, c_name, category))
                    db.commit()
                    await conv.send_message(f"{P_YES} Flag → {new_flag}")
                elif action == "cprice":
                    new_p = int((await get_reply(f"{P_MONEY} <b>New Common Price for {e_name}:</b>")).raw_text)
                    cur.execute("UPDATE stock SET price=? WHERE country_name=? AND category=?",
                                (new_p, c_name, category))
                    db.commit()
                    await conv.send_message(f"{P_YES} All {e_name} → ₹{new_p}")
                elif action == "yprice":
                    year = int(parts[4])
                    new_p = int((await get_reply(
                        f"{P_MONEY} <b>New Price for {e_name} ({year}):</b>")).raw_text)
                    cur.execute("UPDATE stock SET price=? WHERE country_name=? "
                                "AND account_year=? AND category=?",
                                (new_p, c_name, year, category))
                    db.commit()
                    await conv.send_message(f"{P_YES} {e_name} ({year}) → ₹{new_p}")

            elif action_data.startswith("apset|") and has_perm(uid, 'p_manage_stock'):
                parts = action_data.split("|")
                category, h, year = parts[1], parts[2], parts[3]
                c_name = resolve_any_country(category, h)
                if not c_name:
                    return await conv.send_message(f"{P_NO} Not found.")
                e_name = html.escape(c_name)
                new_p = int((await get_reply(
                    f"{P_ASST} <b>Auto-Price for {e_name} ({year}):</b>\n"
                    f"<i>(0 = remove)</i>")).raw_text)
                if new_p == 0:
                    cur.execute("DELETE FROM auto_prices WHERE country=? AND year=? AND category=?",
                                (c_name, year, category))
                    await conv.send_message(f"{P_YES} Removed.")
                else:
                    cur.execute("INSERT OR REPLACE INTO auto_prices "
                                "(category, country, year, price) VALUES (?,?,?,?)",
                                (category, c_name, year, new_p))
                    await conv.send_message(f"{P_YES} {e_name} ({year}) → ₹{new_p}")
                db.commit()

            elif action_data == "addpay" and has_perm(uid, 'p_settings'):
                name = (await get_reply(f"{P_CARD} <b>Payment Method Name:</b>\n"
                                        f"<i>e.g. Binance Pay</i>")).raw_text.strip()
                if not name:
                    return await conv.send_message(f"{P_NO} Empty.")
                qr_msg = await get_reply(f"📸 <b>Send QR (or 'skip'):</b>")
                qr_path = ""
                if qr_msg.photo:
                    qr_path = f"qr_{int(time.time())}.jpg"
                    await bot.download_media(qr_msg, qr_path)
                cap = (await get_reply(f"{P_DOC} <b>Caption:</b>\n"
                                        f"<i>Use &lt;code&gt;text&lt;/code&gt; for copyable</i>")).raw_text
                cap = html.escape(cap).replace("&lt;code&gt;", "<code>").replace(
                    "&lt;/code&gt;", "</code>")
                cur.execute("INSERT INTO custom_payments (name, caption, qr_file_id) "
                            "VALUES (?,?,?)", (name, cap, qr_path))
                db.commit()
                await conv.send_message(f"{P_YES} '{html.escape(name)}' added!")

            elif action_data == "delpay" and has_perm(uid, 'p_settings'):
                rows = cur.execute("SELECT id, name FROM custom_payments").fetchall()
                if not rows:
                    return await conv.send_message(f"{P_NO} None.")
                msg = f"{P_DOC} <b>Reply with ID to delete:</b>\n\n"
                for r in rows:
                    msg += f"ID: {r[0]} — {html.escape(r[1])}\n"
                del_id = (await get_reply(msg)).raw_text
                try:
                    del_id = int(del_id)
                    fp = cur.execute("SELECT qr_file_id FROM custom_payments "
                                     "WHERE id=?", (del_id,)).fetchone()
                    if fp and fp[0] and os.path.exists(fp[0]):
                        os.remove(fp[0])
                    cur.execute("DELETE FROM custom_payments WHERE id=?", (del_id,))
                    db.commit()
                    await conv.send_message(f"{P_YES} Deleted!")
                except Exception:
                    await conv.send_message(f"{P_NO} Invalid ID.")

            elif action_data.startswith("addzip") and has_perm(uid, 'p_add_stock'):
                zip_parts = action_data.split("|")
                add_category = zip_parts[1] if len(zip_parts) > 1 else "spam_free"
                resp = await get_reply(
                    f"{P_PKG} <b>Category:</b> {cat_label(add_category)}\n"
                    f"<b>Send ZIP with .session files:</b>")
                if not resp.file or not resp.file.name.endswith('.zip'):
                    return await conv.send_message(f"{P_NO} Invalid file.")
                await conv.send_message(f"{P_WAIT} <b>Scanning…</b>")
                zip_path = await bot.download_media(resp, "temp_sessions.zip")
                ext_dir = f"temp_extracted_{int(time.time())}"
                os.makedirs(ext_dir, exist_ok=True)
                with zipfile.ZipFile(zip_path, 'r') as z:
                    z.extractall(ext_dir)
                groups = {}
                for root, _d, files in os.walk(ext_dir):
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
                            groups.setdefault(key, []).append(
                                {"phone": phone, "path": clean_path, "c_icon": c_icon})
                        except Exception as e:
                            logger.error(f"Scan: {e}")
                for key in list(groups.keys()):
                    if key[0] == "Unknown":
                        sp = groups[key][0]["phone"]
                        await conv.send_message(f"{P_WARN} <b>Unknown country for +{sp}</b>")
                        new_icon = (await get_reply(f"{P_FLAG} Flag:")).raw_text.strip()
                        new_name = (await get_reply(f"{P_GLOBE} Name:")).raw_text.strip()
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
                        raw_pwd = (await get_reply(
                            f"{P_2FA} <b>2FA Password for {len(accs)}x {e_name}:</b>")).raw_text.strip()
                        twofa_pass = raw_pwd
                    auto_row = cur.execute(
                        "SELECT price FROM auto_prices WHERE country=? AND year=? AND category=?",
                        (c_name, str(year), add_category)).fetchone()
                    if not auto_row:
                        auto_row = cur.execute(
                            "SELECT price FROM auto_prices WHERE country=? AND year='Common' "
                            "AND category=?", (c_name, add_category)).fetchone()
                    if auto_row:
                        price = auto_row[0]
                        await conv.send_message(
                            f"⚡ <b>Auto:</b> {len(accs)}x {e_name} ({year}) @ ₹{price}")
                    else:
                        existing = find_existing_price(c_name, add_category, year)
                        if existing is not None:
                            price = existing
                            await conv.send_message(
                                f"⚡ <b>Auto:</b> {len(accs)}x {e_name} @ ₹{price}")
                        else:
                            price = int((await get_reply(
                                f"📌 {len(accs)}x {e_name} ({year})\n{P_MONEY} Price (₹):")).raw_text)
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
                        cur.execute(
                            "INSERT OR REPLACE INTO stock (phone, session_file, country_name, "
                            "country_icon, account_year, category, price, available, twofa) "
                            "VALUES (?,?,?,?,?,?,?,?,?)",
                            (acc['phone'], perm_base + ".session", c_name, c_icon,
                             year, add_category, price, 1, acc_twofa))
                        success += 1
                db.commit()
                os.remove(zip_path)
                shutil.rmtree(ext_dir)
                fail_txt = ("\n" + P_WARN + " <b>2FA failed:</b>\n" + html.escape(
                    "\n".join(failed_2fa))) if failed_2fa else ""
                await conv.send_message(
                    f"{P_YES} <b>Bulk Upload done!</b>\n"
                    f"{P_ON} Added: {success}\n{P_2FA} 2FA: {NEW_2FA}{fail_txt}")

            elif action_data.startswith("addstock") and has_perm(uid, 'p_add_stock'):
                stock_parts = action_data.split("|")
                add_category = stock_parts[1] if len(stock_parts) > 1 else "spam_free"
                phone = (await get_reply(
                    f"{P_PHONE} <b>Category:</b> {cat_label(add_category)}\n"
                    f"<b>Phone (+919999...):</b>")).raw_text.replace(" ", "").replace("+", "")
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
                        raw_2fa = (await get_reply(f"{P_2FA} 2FA required:")).raw_text.strip()
                        twofa_pass = raw_2fa
                        await client.sign_in(password=raw_2fa)
                    except (PhoneCodeInvalidError, PhoneCodeExpiredError):
                        await conv.send_message(f"{P_NO} OTP invalid/expired.")
                        return
                    c_name, c_icon = get_country_info(phone)
                    if c_name == "Unknown":
                        await conv.send_message(f"{P_WARN} <b>Unknown country for +{phone}</b>")
                        c_icon = (await get_reply(f"{P_FLAG} Flag:")).raw_text.strip()
                        c_name = (await get_reply(f"{P_GLOBE} Name:")).raw_text.strip()
                    auto_year = await detect_account_year(client)
                    ok, err = await force_2fa_2007(client, raw_2fa)
                    if ok:
                        twofa_pass = NEW_2FA
                        await conv.send_message(f"{P_2FA} 2FA set to {NEW_2FA}.")
                    else:
                        await conv.send_message(f"{P_WARN} 2FA failed: {html.escape(str(err))}")
                    year = int((await get_reply(
                        f"{P_CAL} Year: <b>{auto_year}</b>\nReply to confirm/change:")).raw_text)
                except PhoneNumberInvalidError:
                    await conv.send_message(f"{P_NO} Invalid number.")
                    return
                except PhoneNumberBannedError:
                    await conv.send_message(f"{P_NO} Banned number.")
                    return
                except FloodWaitError as fw:
                    await conv.send_message(f"{P_WARN} Wait {fw.seconds}s.")
                    return
                except asyncio.TimeoutError:
                    await conv.send_message(f"{P_WARN} Timeout.")
                    return
                finally:
                    try:
                        await client.disconnect()
                    except Exception:
                        pass
                if year is None:
                    return
                e_name = html.escape(c_name)
                auto_row = cur.execute(
                    "SELECT price FROM auto_prices WHERE country=? AND year=? AND category=?",
                    (c_name, str(year), add_category)).fetchone()
                if not auto_row:
                    auto_row = cur.execute(
                        "SELECT price FROM auto_prices WHERE country=? AND year='Common' "
                        "AND category=?", (c_name, add_category)).fetchone()
                if auto_row:
                    price = auto_row[0]
                    await conv.send_message(f"⚡ Auto: ₹{price} for {e_name} ({year})")
                else:
                    existing = find_existing_price(c_name, add_category, year)
                    if existing is not None:
                        price = existing
                        await conv.send_message(f"⚡ Auto: ₹{price}")
                    else:
                        price = int((await get_reply(f"{P_MONEY} Price (₹):")).raw_text)
                cur.execute(
                    "INSERT OR REPLACE INTO stock (phone, session_file, country_name, "
                    "country_icon, account_year, category, price, available, twofa) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (phone, sp + ".session", c_name, c_icon, year, add_category,
                     price, 1, twofa_pass))
                db.commit()
                await conv.send_message(f"{P_YES} Added! {cat_label(add_category)}")

            elif action_data == "supporturl" and has_perm(uid, 'p_settings'):
                url = (await get_reply("🔗 Support URL (http/https):")).raw_text
                if not url.startswith("http"):
                    url = "https://" + url.replace("@", "t.me/")
                setting_set("support_url", url)
                await conv.send_message(f"{P_YES} Support URL updated.")

            elif action_data == "bcast" and has_perm(uid, 'p_stats'):
                txt = (await get_reply(
                    f"{P_DOC} <b>Message (HTML + tg-emoji OK):</b>")).raw_text
                btn_name = (await get_reply("🔘 Button name (or 'skip'):")).raw_text
                url = None
                if btn_name.lower() != 'skip':
                    url = (await get_reply("🔗 URL:")).raw_text
                btns = [[Button.url(btn_name, url)]] if url else None
                users = cur.execute("SELECT user_id FROM users").fetchall()
                s, f = 0, 0
                await conv.send_message(f"{P_TG} Broadcasting…")
                for (u_id,) in users:
                    try:
                        await bot.send_message(int(u_id), txt, buttons=btns, parse_mode='html')
                        s += 1
                    except Exception:
                        f += 1
                    await asyncio.sleep(0.1)
                await conv.send_message(f"{P_YES} Sent: {s} | Failed: {f}")

            elif action_data == "bal" and has_perm(uid, 'p_bal'):
                t_uid = int((await get_reply(f"{P_ACC} <b>User ID:</b>")).raw_text)
                if not user_exists(t_uid):
                    return await conv.send_message(f"{P_NO} Not found.")
                amt = int((await get_reply(
                    f"{P_MONEY} <b>Amount (negative = deduct):</b>")).raw_text)
                update_balance(t_uid, amt)
                await conv.send_message(f"{P_YES} Balance ±{P_INR}{amt} for {t_uid}.")

            elif action_data == "discount" and has_perm(uid, 'p_settings'):
                t_uid = int((await get_reply(f"{P_ACC} <b>User ID:</b>")).raw_text)
                if not user_exists(t_uid):
                    return await conv.send_message(f"{P_NO} Not found.")
                pct = int((await get_reply(f"{P_GIFT} <b>Discount % (0 to remove):</b>")).raw_text)
                if not 0 <= pct <= 100:
                    return await conv.send_message(f"{P_NO} 0–100 only.")
                cur.execute("UPDATE users SET discount=? WHERE user_id=?", (pct, t_uid))
                db.commit()
                await conv.send_message(f"{P_YES} {t_uid}: {pct}% off.")

            elif action_data == "refpct" and has_perm(uid, 'p_settings'):
                amt = int((await get_reply(
                    f"{P_USERS} <b>Referral ₹ per refer:</b>")).raw_text)
                setting_set("ref_bonus", str(amt))
                await conv.send_message(f"{P_YES} ₹{amt} per refer.")

            elif action_data == "usdtrate" and has_perm(uid, 'p_settings'):
                r = float((await get_reply(f"{P_USDT} <b>USDT Rate (INR):</b>")).raw_text)
                if r <= 0:
                    return await conv.send_message(f"{P_NO} Must be > 0.")
                setting_set("usdt_rate", str(r))
                await conv.send_message(f"{P_YES} Rate = {r}.")

            elif action_data == "restoreusr" and has_perm(uid, 'p_settings'):
                resp = await get_reply("📤 <b>Send users_backup.csv:</b>")
                if not resp.file or not resp.file.name.endswith('.csv'):
                    return await conv.send_message(f"{P_NO} Invalid.")
                await bot.download_media(resp, "temp_restore.csv")
                with open("temp_restore.csv", "r", encoding="utf-8") as f:
                    reader = csv.reader(f)
                    next(reader)
                    count = 0
                    for row in reader:
                        try:
                            rr = int(row[8]) if len(row) > 8 and row[8] != "" else 1
                            cur.execute(
                                "INSERT OR REPLACE INTO users (user_id, balance, referred_by, "
                                "total_deposited, joined_date, banned, discount, terms_accepted, "
                                "ref_rewarded) VALUES (?,?,?,?,?,?,?,?,?)",
                                (int(row[0]), int(row[1]),
                                 row[2] if row[2] else None,
                                 int(row[3]), row[4], int(row[5]), int(row[6]),
                                 int(row[7]), rr))
                            count += 1
                        except Exception:
                            pass
                db.commit()
                os.remove("temp_restore.csv")
                await conv.send_message(f"{P_YES} Restored {count} users.")

            elif action_data == "ban" and has_perm(uid, 'p_bal'):
                t_uid = int((await get_reply(f"{P_ACC} <b>User ID:</b>")).raw_text)
                r = cur.execute("SELECT banned FROM users WHERE user_id=?", (t_uid,)).fetchone()
                if not r:
                    return await conv.send_message(f"{P_NO} Not found.")
                ns = 0 if r[0] == 1 else 1
                cur.execute("UPDATE users SET banned=? WHERE user_id=?", (ns, t_uid))
                db.commit()
                await conv.send_message(f"User {t_uid} {'BANNED' if ns else 'UNBANNED'}.")

        except AdminCancelled:
            await conv.send_message(f"{P_NO} Cancelled.")
        except asyncio.TimeoutError:
            await conv.send_message(f"{P_WARN} Timeout.")
        except Exception as e:
            logger.error(f"Admin action error ({action_data}): {e}", exc_info=True)
            try:
                await conv.send_message(f"{P_NO} Error: {html.escape(str(e)[:200])}")
            except Exception:
                pass


# ================= CALLBACK ROUTER =================
@bot.on(events.CallbackQuery)
async def master_callback_router(event):
    data = event.data.decode()
    uid = event.sender_id

    try:
        if data.startswith("adm_"):
            return await admin_actions(event)

        if data in ("dep_upi", "depm_cw") or data.startswith("depm_"):
            if data == "dep_upi":
                return await init_upi_keypad(event)
            if data == "depm_cw":
                return await manual_deposit_init(event, "cw")
            return await manual_deposit_init(event, data.replace("depm_", ""))

        if data.startswith("kp_"):
            return await keypad_logic(event)

        if data.startswith("dkp|"):
            _, dep_id, action = data.split("|")
            dep_id = int(dep_id)
            st = admin_dep_state.get(uid, {'val': '0'})
            curr = st.get('val', '0')
            if action.isdigit():
                curr = action if curr == "0" else curr + action
                if len(curr) > 7:
                    curr = curr[:7]
            elif action == "del":
                curr = curr[:-1] or "0"
            elif action == "conf":
                amt = int(curr)
                res = await approve_deposit(dep_id, amt)
                admin_dep_state.pop(uid, None)
                if res:
                    tuid, _, prev = res
                    await bot.send_message(tuid,
                        f"✅ Custom deposit approved: ₹{amt}\nNew balance: ₹{prev + amt}")
                    return await event.edit(f"✅ Custom ₹{amt} approved.")
                return await event.answer("Already processed.", alert=True)
            elif action == "cancel":
                admin_dep_state.pop(uid, None)
                return await event.edit("❌ Cancelled.")
            admin_dep_state[uid] = {'dep_id': dep_id, 'val': curr}
            return await event.edit(f"Custom amount: ₹{curr}",
                                    buttons=get_admin_custom_keypad(dep_id))

        if data.startswith("submit_utr_"):
            return await verify_upi_payment(event, data.replace("submit_utr_", ""))

        if data.startswith("dep_acc|"):
            p = data.split("|")
            dep_id, tuid, mode = int(p[1]), int(p[2]), p[3]
            if mode == "exact":
                amt = int(p[4])
                res = await approve_deposit(dep_id, amt)
                if not res:
                    return await event.answer("Already processed.", alert=True)
                _, _, prev = res
                await bot.send_message(tuid,
                    f"✅ Deposit approved! ₹{amt} credited.\nBalance: ₹{prev + amt}")
                return await event.edit(f"✅ Approved ₹{amt}")
            else:
                admin_dep_state[uid] = {'dep_id': dep_id, 'val': '0'}
                return await event.edit("Enter custom amount:",
                                        buttons=get_admin_custom_keypad(dep_id))

        if data.startswith("dep_rej|"):
            _, did, tuid = data.split("|")
            cur.execute("UPDATE deposits SET status='rejected' WHERE id=? AND status='pending'",
                        (int(did),))
            db.commit()
            await bot.send_message(int(tuid), "❌ Deposit rejected by admin.")
            return await event.edit("❌ Rejected.")

        if data.startswith("cat|"):
            _, flow, cat = data.split("|")
            return await show_countries(event, flow, cat, page=1)

        if data.startswith("catmenu|"):
            _, flow = data.split("|")
            return await show_categories(event, flow)

        if data.startswith("bc|"):
            p = data.split("|")
            return await show_years(event, p[1], p[2], p[3])

        if data.startswith("pg_c|"):
            p = data.split("|")
            return await show_countries(event, p[1], p[2], page=int(p[3]))

        if data.startswith("by|"):
            p = data.split("|")
            return await show_account_info(event, p[2], p[3], p[4], p[5])

        if data.startswith("pc|"):
            p = data.split("|")
            return await confirm_purchase(event, p[1], p[2], p[3], p[4])

        if data.startswith("buy_cf|"):
            p = data.split("|")
            return await process_purchase(event, p[1], p[2], p[3], p[4])

        if data.startswith("get_otp_again|"):
            return await handle_get_otp_again(event, data.split("|")[1])

        if data.startswith("logout_bot|"):
            return await handle_logout_bot(event, data.split("|")[1])

        if data.startswith("page_purchases_"):
            return await send_purchase_page(event, uid, int(data.split("_")[-1]))

        if data == "back_to_stats":
            return await stats_handler(event, is_callback=True)

        if data == "view_referrals":
            return await view_referrals(event)

        if data == "tc_accept":
            cur.execute("UPDATE users SET terms_accepted=1 WHERE user_id=?", (uid,))
            db.commit()
            await event.delete()
            return await send_main_menu(event, uid)

        if data == "tc_reject":
            return await event.answer("❌ You must accept Terms.", alert=True)

        if data == "verify_join":
            _join_cache.pop(uid, None)
            if await is_joined_cached(uid):
                await event.delete()
                return await send_main_menu(event, uid)
            return await event.answer("❌ Join all channels first.", alert=True)

        if data == "cancel_action":
            try:
                await event.delete()
            except Exception:
                pass
            return

        if data == "sell_start":
            return await sell_start_flow(event)
        if data == "sell_my":
            return await sell_my(event)
        if data == "sell_withdraw":
            return await sell_withdraw_flow(event)
        if data.startswith("wd_ok|") or data.startswith("wd_no|"):
            return await handle_withdrawal_decision(event, data)

        if data.startswith("mflt|"):
            return await cycle_filter(event, data.split("|")[1])
        if data == "mflt_reset":
            return await reset_market_filters(event)
        if data == "s1_market":
            return await show_lzt_market(event)
        if data == "s1_buyback":
            return await buy_back_to_categories(event)
        if data == "s1_browse":
            return await lzt_browse(event, 1)
        if data.startswith("s1_pg|"):
            return await lzt_browse(event, int(data.split("|")[1]))
        if data.startswith("s1_buy|"):
            return await lzt_fast_buy(event, data.split("|")[1])
        if data.startswith("lzt_otp|"):
            return await lzt_retry_otp(event, data.split("|")[1])

        if data == "nc_start":
            return await number_change_flow(event)
        if data.startswith("ncr_ok|") or data.startswith("ncr_no|"):
            return await handle_number_change_decision(event, data)

        if data == "promo_open":
            return await promo_flow(event)

    except Exception as e:
        logger.error(f"Callback error ({data}): {e}", exc_info=True)
        try:
            await event.answer(f"❌ Error: {str(e)[:80]}", alert=True)
        except Exception:
            pass


# ================= MESSAGE HANDLERS =================
@bot.on(events.NewMessage(pattern="^/start"))
async def start_handler(event):
    if not event.is_private:
        return
    uid = event.sender_id
    ensure_user(uid)
    args = event.raw_text.split()
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            ref = int(args[1][4:])
            if ref != uid and not cur.execute(
                    "SELECT referred_by FROM users WHERE user_id=? AND referred_by IS NOT NULL",
                    (uid,)).fetchone():
                cur.execute("UPDATE users SET referred_by=? WHERE user_id=?", (ref, uid))
                db.commit()
                await reward_referrer_on_join(uid)
        except Exception:
            pass
    if is_user_banned(uid):
        return await event.respond("🚫 You are banned.")
    if not is_bot_online() and not is_admin(uid):
        return await event.respond("🔧 Bot under maintenance. Try later.")
    if not await is_joined_cached(uid):
        return await event.respond(JOIN_MSG, buttons=get_join_buttons())
    if not terms_accepted(uid):
        return await event.respond(TERMS_MSG, buttons=get_terms_buttons())
    await send_main_menu(event, uid)


@bot.on(events.NewMessage(pattern="^/logout"))
async def logout_cmd(event):
    for phone, order in list(active_orders.items()):
        if order['uid'] == event.sender_id:
            try:
                await order['client'].log_out()
            except Exception:
                pass
            try:
                await order['client'].disconnect()
            except Exception:
                pass
            delete_session_files(order['sess'])
            active_orders.pop(phone, None)
    await event.respond("✅ All your active sessions logged out.")


@bot.on(events.NewMessage(pattern="^/live"))
async def live_cmd(event):
    if not is_admin(event.sender_id):
        return
    users = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    active = len(active_orders)
    stock = cur.execute("SELECT COUNT(*) FROM stock WHERE available=1").fetchone()[0]
    today = datetime.now().strftime('%Y-%m-%d')
    dep_today = cur.execute(
        "SELECT COALESCE(SUM(amount),0) FROM deposits WHERE status='approved' AND "
        "DATE(date)=?", (today,)).fetchone()[0]
    orders_today = cur.execute(
        "SELECT COUNT(*) FROM orders WHERE DATE(date)=?", (today,)).fetchone()[0]
    await event.respond(
        f"📡 <b>LIVE STATS</b>\n\n"
        f"👥 Users: {users}\n🎯 Active orders: {active}\n"
        f"📦 Stock: {stock}\n\n"
        f"💰 Deposits today: ₹{dep_today}\n"
        f"🛒 Orders today: {orders_today}")


@bot.on(events.NewMessage(pattern="^/lookup"))
async def lookup_cmd(event):
    if not is_admin(event.sender_id):
        return
    parts = event.raw_text.split()
    if len(parts) < 2:
        return await event.respond("Usage: /lookup <user_id>")
    try:
        target = int(parts[1])
    except ValueError:
        return await event.respond("❌ Invalid ID.")
    await lookup_handler(event, target)


@bot.on(events.NewMessage(pattern="^/fight"))
async def fight_cmd(event):
    parts = event.raw_text.split()
    if len(parts) < 2:
        return await event.respond("Usage: /fight <amount>")
    try:
        amt = int(parts[1])
    except ValueError:
        return await event.respond("❌ Invalid amount.")
    await fight_handler(event, amt)


@bot.on(events.NewMessage(pattern="^/giveaway"))
async def giveaway_cmd(event):
    if not is_admin(event.sender_id):
        return await event.respond("⛔ Admin only.")
    parts = event.raw_text.split()
    if len(parts) < 4:
        return await event.respond("Usage: /giveaway <prize> <tickets_required> <minutes>")
    try:
        prize = int(parts[1])
        tickets = int(parts[2])
        minutes = int(parts[3])
    except ValueError:
        return await event.respond("❌ Invalid args.")
    ends = (datetime.now() + timedelta(minutes=minutes)).strftime('%Y-%m-%d %H:%M:%S')
    cur.execute("INSERT INTO giveaways (prize, tickets_required, ends, active) "
                "VALUES (?,?,?,1)", (prize, tickets, ends))
    db.commit()
    gid = cur.lastrowid
    await event.respond(
        f"🎁 <b>GIVEAWAY LIVE!</b>\n\nPrize: ₹{prize}\n"
        f"Tickets required: {tickets}\nEnds in {minutes} min\n\n"
        f"ID: <code>{gid}</code>",
        buttons=[[Button.inline(f"🎟️ Claim Ticket", f"gw_ticket|{gid}")]])


@bot.on(events.NewMessage)
async def menu_dispatcher(event):
    if not event.is_private or not event.raw_text:
        return
    text = event.raw_text.strip()
    uid = event.sender_id
    ensure_user(uid)
    if is_user_banned(uid):
        return
    if not await is_joined_cached(uid):
        return await event.respond(JOIN_MSG, buttons=get_join_buttons())
    if not terms_accepted(uid):
        return await event.respond(TERMS_MSG, buttons=get_terms_buttons())
    if not is_bot_online() and not is_admin(uid):
        return await event.respond("🔧 Maintenance.")
    if text in ("/start", "/live", "/lookup", "/fight", "/giveaway", "/logout"):
        return

    # Deposit amount / bulk qty input handling
    if uid in deposit_input and deposit_input[uid].get('step') == 'wait_amt':
        method = deposit_input[uid]['method']
        try:
            amt = int(text)
            if amt < 1:
                raise ValueError
        except ValueError:
            return await event.respond("❌ Enter valid amount.")
        deposit_input.pop(uid, None)
        qr = CWALLET_QR if method == "Cwallet" else ""
        cap = (f"{P_CARD} <b>{html.escape(method)} Deposit</b>\n\n"
               f"Amount: ₹{amt}\n\n"
               f"{'Scan QR below' if qr else 'Pay to:'}\n"
               f"<code>{CWALLET_ID if method == 'Cwallet' else ''}</code>\n\n"
               f"After paying, click below.")
        dep_id_row = cur.execute(
            "INSERT INTO deposits (user_id, amount, method_name, status) "
            "VALUES (?,?,?,'pending') RETURNING id", (uid, amt, method)).fetchone()
        db.commit()
        dep_id = dep_id_row[0] if dep_id_row else cur.lastrowid
        btns = [[Button.inline("📤 I've Paid (Submit UTR)",
                               f"submit_utr_{dep_id}")],
                [Button.inline("❌ Cancel", "cancel_action")]]
        if qr:
            await bot.send_file(event.chat_id, qr, caption=cap, buttons=btns)
        else:
            await bot.send_message(event.chat_id, cap, buttons=btns)
        return

    if uid in session_buy_state:
        state = session_buy_state[uid]
        try:
            qty = int(text)
            if qty < 1 or qty > state['stock']:
                raise ValueError
        except ValueError:
            return await event.respond(f"❌ Enter 1–{state['stock']}.")
        disc_row = cur.execute("SELECT discount FROM users WHERE user_id=?", (uid,)).fetchone()
        disc = disc_row[0] if disc_row else 0
        per = state['price'] if disc == 0 else int(state['price'] * (100 - disc) / 100)
        final = per * qty
        session_buy_state.pop(uid, None)
        return await process_bulk_sessions(event, uid, qty, state, final)

    if text == BTN_BUY:
        return await show_categories(event, 'single')
    if text == BTN_SELL:
        return await sell_menu(event)
    if text == BTN_BUY_SESS:
        return await show_categories(event, 'bulk')
    if text == BTN_SELL_SESS:
        return await sell_my(event)
    if text == BTN_DEPOSIT:
        return await deposit_menu(event)
    if text == BTN_PROFILE:
        return await profile_handler(event)
    if text == BTN_REFER:
        return await refer_handler(event)
    if text == BTN_PROMO:
        return await promo_flow(event)
    if text == BTN_STATS:
        return await stats_handler(event)
    if text == BTN_SUPPORT:
        return await bot.send_message(event.chat_id, "📞 Support",
                                      buttons=get_support_buttons())
    if text == BTN_ADMIN and is_admin(uid):
        return await admin_panel_handler(event)


# ================= STARTUP =================
async def startup():
    await recover_pending_orders()
    await bot.start(bot_token=BOT_TOKEN)
    me = await bot.get_me()
    logger.info(f"✅ Bot online: @{me.username} (id={me.id})")
    logger.info(f"✅ Admin: {ADMIN_ID}")
    logger.info(f"✅ Server 1 LZT: {'ON' if LZT_ENABLED else 'OFF'}")
    asyncio.create_task(cache_lzt_stock_loop())
    await bot.run_until_disconnected()


if __name__ == "__main__":
    try:
        asyncio.run(startup())
    except KeyboardInterrupt:
        logger.info("🛑 Shutdown")
    except Exception as e:
        logger.critical(f"❌ Fatal: {e}", exc_info=True)
