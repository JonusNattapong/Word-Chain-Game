import os  # ใช้อ่าน env และไฟล์
import json  # เก็บ/อ่านคะแนน
import asyncio  # ใช้ task / lock / to_thread
import time  # ใช้ cooldown timing
from dataclasses import dataclass, field  # โครงสร้าง state
from typing import Dict, List, Set, Optional, Tuple  # type hints

import discord  # discord api
from discord.ext import commands  # command framework
from dotenv import load_dotenv  # โหลด .env
import aiohttp  # http client แบบ async
from openai import OpenAI  # ใช้ OpenRouter (ผ่าน OpenAI SDK)
import discord.utils  # สำหรับ escape markdown

from config import config  # โหลดการตั้งค่า (ต้องมีในโปรเจกต์ของน้อง)


# ---------------------------
# Config / Setup
# ---------------------------

load_dotenv()  # โหลดค่าใน .env
TOKEN = os.getenv("DISCORD_TOKEN")  # token ของบอท
if not TOKEN:
    raise ValueError("DISCORD_TOKEN is not set in .env file. Please provide a valid Discord bot token.")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")  # key สำหรับ OpenRouter
if not OPENROUTER_API_KEY:
    raise ValueError("OPENROUTER_API_KEY is not set in .env file. Please provide a valid OpenRouter API key.")

OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"  # base url ของ OpenRouter

intents = discord.Intents.default()  # intents พื้นฐาน
intents.message_content = True  # ต้องเปิดเพื่ออ่าน message.content
intents.members = False  # ไม่ขอ privileged members intent

allowed_mentions_none = discord.AllowedMentions.none()  # กันบอท @everyone / @here / mention คนโดยไม่ตั้งใจ


def dynamic_prefix(bot: commands.Bot, message: discord.Message):  # ฟังก์ชันคืน prefix แบบ dynamic
    return config.command_prefix  # ใช้ prefix ปัจจุบันจาก config


bot = commands.Bot(command_prefix=dynamic_prefix, intents=intents)  # สร้างบอทแบบ prefix เปลี่ยนได้


openai_client = OpenAI(  # สร้าง client OpenRouter ผ่าน OpenAI SDK
    api_key=OPENROUTER_API_KEY,  # ใส่ key
    base_url=OPENROUTER_API_BASE,  # ใส่ base url
    default_headers={  # header แนะนำของ OpenRouter
        "HTTP-Referer": "https://github.com/JonusNattapong/Word-Chain-Game",  # referer
        "X-Title": "Word Chain Discord Bot",  # ชื่อแอป
    },
)

SCORES_FILE: str  # ไฟล์คะแนนรวม (จะกำหนดใน on_ready และ reload_config)
scores_data: Dict[str, int] = {}  # {"user_id": score} และ {"ai_name": score}
scores_lock = asyncio.Lock()  # กันการเขียนไฟล์ชนกัน

ai_display_names: Dict[str, str] = {}  # {"ai_key": "display_name"} สำหรับ leaderboard
not_your_turn_cooldowns: Dict[int, float] = {}  # quiet cooldown สำหรับ "not your turn" messages
user_display_names: Dict[int, str] = {}  # {user_id: display_name} สำหรับ leaderboard

VALID_WORDS: Set[str] = set()  # ชุดคำอังกฤษที่ถูกต้อง (โหลดจากไฟล์)
valid_words_lock = asyncio.Lock()  # กัน reload words พร้อมกัน

http_session: Optional[aiohttp.ClientSession] = None  # session รวมทั้งบอท

# Additional locks for thread safety
games_lock = asyncio.Lock()  # กันการเข้าถึง games dict ชนกัน
cooldowns_lock = asyncio.Lock()  # กันการเข้าถึง cooldowns dict ชนกัน
display_names_lock = asyncio.Lock()  # กันการเข้าถึง display names dict ชนกัน


# ---------------------------
# Game State (แยกต่อห้อง)
# ---------------------------

@dataclass
class GameState:  # state ของเกมใน 1 ห้อง
    active: bool = False  # เกมกำลังเล่นอยู่ไหม

    players: List[int] = field(default_factory=list)  # ลิสต์ user_id (human)
    ai_players: List[str] = field(default_factory=list)  # ลิสต์ชื่อ AI
    player_names: Dict[int, str] = field(default_factory=dict)  # {user_id: display_name}

    current_idx: int = 0  # index ของคนที่ถึงตา (รวม human + AI)
    word_chain: List[str] = field(default_factory=list)  # ลำดับคำ
    used_words: Set[str] = field(default_factory=set)  # กันคำซ้ำ

    turn_seconds: int = field(default_factory=lambda: config.turn_seconds)  # เวลาต่อเทิร์น (ต่อห้อง)
    turn_task: Optional[asyncio.Task] = None  # task นับถอยหลังต่อเทิร์น
    turn_message: Optional[discord.Message] = None  # message เทิร์น (แก้ progress bar)

    player_streaks: Dict[int, int] = field(default_factory=dict)  # streak ต่อคน
    combo_count: int = 0  # combo ต่อห้อง

    cooldowns: Dict[int, float] = field(default_factory=dict)  # cooldown ต่อคน (ใช้เฉพาะตอน "ไม่ใช่ตา")
    joining_users: Set[int] = field(default_factory=set)  # กัน join ซ้อน
    adding_ais: Set[str] = field(default_factory=set)  # กัน add_ai ซ้อน

    turn_token: int = 0  # token เพิ่มทุกเทิร์น กัน AI/Timer ยิงซ้อน (race condition)

    # Lock for thread-safe state modifications
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)


games: Dict[int, GameState] = {}  # {channel_id: GameState}


# --------------------------- Helper functions for safe state access ---------------------------

async def update_state_activity(state: GameState):
    """Update the last activity timestamp for a game state"""
    state._last_activity = time.time()


async def with_state_lock(state: GameState, func):
    """Execute a function with state lock held"""
    async with state._lock:
        await update_state_activity(state)
        return await func()


def with_state_lock_sync(state: GameState, func):
    """Execute a synchronous function with state lock held (use with caution)"""
    # Note: This is not truly thread-safe for sync functions, but provides basic protection
    # For full thread safety, all state modifications should be async
    state._last_activity = time.time()
    return func()


# ---------------------------
# Persistence (scores)
# ---------------------------

def load_scores_sync():  # โหลดคะแนนแบบ sync ตอนเริ่ม
    global scores_data  # ใช้ dict กลาง
    try:  # กันไฟล์ไม่มี/พัง
        with open(SCORES_FILE, "r", encoding="utf-8") as f:  # เปิดไฟล์
            data = json.load(f)  # อ่าน json
            scores_data = data if isinstance(data, dict) else {}  # กัน format แปลก
    except FileNotFoundError:  # ครั้งแรกยังไม่มี
        scores_data = {}  # เริ่มใหม่
    except json.JSONDecodeError:  # ไฟล์เสีย
        scores_data = {}  # รีเซ็ต


async def save_scores_async():  # เซฟคะแนนแบบ async + lock + atomic
    async with scores_lock:  # กันชนกัน
        tmp_file = SCORES_FILE + ".tmp"  # เขียนไปไฟล์ชั่วคราวก่อน
        with open(tmp_file, "w", encoding="utf-8") as f:  # เขียน tmp
            json.dump(scores_data, f, indent=4, ensure_ascii=False)  # เซฟ json
        os.replace(tmp_file, SCORES_FILE)  # atomic replace


# ---------------------------
# Word list
# ---------------------------

async def load_valid_words_async():  # โหลดคำอังกฤษจากไฟล์แบบ async-safe
    global VALID_WORDS  # ใช้ global
    async with valid_words_lock:  # กันโหลดซ้อน
        try:  # กันไฟล์ไม่มี
            with open(config.words_file, "r", encoding="utf-8") as f:  # อ่านไฟล์
                words = [line.strip().lower() for line in f if line.strip()]  # normalize
            VALID_WORDS = set(words)  # set lookup เร็ว
            print(f"Loaded {len(VALID_WORDS)} valid words")  # log
        except FileNotFoundError:  # ถ้าไม่มีไฟล์
            VALID_WORDS = set()  # ว่างไว้ แล้ว fallback ไป spellchecker
            print("Warning: words file not found, using spellchecker fallback")  # แจ้งเตือน


# ---------------------------
# Helpers
# ---------------------------

def get_game(channel_id: int) -> GameState:  # ดึง state ตามห้อง
    # Use lock to prevent race conditions when accessing games dict
    # Note: This is a synchronous function, so we can't use async lock here
    # We'll rely on the fact that dict access is atomic in CPython for simple operations
    if channel_id not in games:  # ถ้ายังไม่มีให้สร้าง
        games[channel_id] = GameState()  # init
    return games[channel_id]  # คืน state


async def cleanup_inactive_games():  # เคลียร์เกมที่ไม่ได้ใช้มานาน
    """Periodically clean up inactive games to prevent memory leaks"""
    while True:
        try:
            await asyncio.sleep(3600)  # ตรวจทุก 1 ชั่วโมง
            current_time = time.time()

            async with games_lock:
                channels_to_remove = []
                for channel_id, state in games.items():
                    # ถ้าเกมไม่ active และไม่ได้ใช้งานมานาน (>24 ชั่วโมง)
                    if not state.active and hasattr(state, '_last_activity'):
                        if current_time - state._last_activity > 86400:  # 24 ชั่วโมง
                            channels_to_remove.append(channel_id)

                for channel_id in channels_to_remove:
                    del games[channel_id]
                    print(f"Cleaned up inactive game for channel {channel_id}")

        except Exception as e:
            print(f"Error in cleanup task: {e}")
            await asyncio.sleep(60)  # รอแล้วลองใหม่


def total_players(state: GameState) -> int:  # จำนวนผู้เล่นทั้งหมด
    return len(state.players) + len(state.ai_players)  # human + AI


def current_player_info(state: GameState) -> Tuple[Optional[int], Optional[str]]:  # (user_id, ai_name)
    tp = total_players(state)  # จำนวนทั้งหมด
    if tp == 0:  # ไม่มีผู้เล่น
        return None, None  # ไม่มีใคร
    idx = state.current_idx % tp  # normalize index
    if idx < len(state.players):  # อยู่ในช่วง human
        return state.players[idx], None  # คืน user_id
    ai_idx = idx - len(state.players)  # index ในลิสต์ AI
    return None, state.ai_players[ai_idx]  # คืนชื่อ AI


def peek_current_name(state: GameState) -> str:  # ชื่อคนที่ถึงตาตอนนี้
    uid, ai_name = current_player_info(state)  # ดึงคน/AI ปัจจุบัน
    if uid is not None:  # เป็น human
        return state.player_names.get(uid, f"User {uid}")  # ชื่อ
    return ai_name or "Unknown"  # ชื่อ AI


def advance_turn(state: GameState):  # เลื่อนเทิร์นไปคนถัดไป
    tp = total_players(state)  # จำนวนทั้งหมด
    if tp <= 0:  # กันหารศูนย์
        state.current_idx = 0  # รีเซ็ต
        return  # จบ
    state.current_idx = (state.current_idx + 1) % tp  # เลื่อน index


def normalize_word(word: str) -> str:  # normalize คำ
    return word.strip().lower()  # strip + lower


def is_valid_word_basic(word: str) -> bool:  # ตรวจรูปแบบคำ
    return word.isalpha() and 3 <= len(word) <= 15  # ตัวอักษรล้วน และยาว 3-15 ตรงกับ AI


async def is_valid_english_word(word: str) -> bool:  # ตรวจคำอังกฤษ
    if VALID_WORDS and word in VALID_WORDS:  # ถ้ามี wordlist และพบ
        return True  # ผ่าน
    return False  # ไม่ใช้ spell fallback เพื่อความเข้ม


def create_progress_bar(current: int, total: int, length: int = 10) -> str:  # สร้าง progress bar
    if total <= 0:  # กันหารศูนย์
        return "▰" * length  # เต็ม
    filled = int((current / total) * length)  # จำนวนช่องเต็ม
    empty = max(0, length - filled)  # จำนวนช่องว่าง
    return "▰" * filled + "▱" * empty  # คืน bar


def build_turn_text(state: GameState, name: str, remaining: int) -> str:  # สร้างข้อความเทิร์นแบบ deterministic
    bar = create_progress_bar(remaining, state.turn_seconds, 10)  # progress bar
    if not state.word_chain:  # ยังไม่มีคำเริ่ม
        return f"🎮 It's {name}'s turn! Start with any English word.\n{bar} ({remaining}s)"  # ข้อความเริ่ม
    last_letter = state.word_chain[-1][-1]  # ตัวท้ายคำล่าสุด
    return f"🎮 It's {name}'s turn! Word must start with '{last_letter}'.\n{bar} ({remaining}s)"  # ข้อความต่อคำ


def sanitize_ai_key(ai_name: str) -> str:  # ทำชื่อ AI ให้ปลอดภัยเป็น key
    safe = (ai_name or "AI").strip().lower()  # trim + lower
    safe = safe.replace(" ", "_")  # แทน space กัน key แปลก
    return f"ai_{safe}"  # ใส่ prefix


def cleanup_cooldowns():  # เคลียร์ cooldowns เก่า ๆ
    """Remove cooldowns older than 1 hour to prevent memory leak"""
    now = time.monotonic()
    cutoff = now - 3600  # 1 hour ago
    global not_your_turn_cooldowns
    # Note: This function is called synchronously, so we can't use async lock
    # In practice, this should be fine as cleanup is infrequent
    not_your_turn_cooldowns = {k: v for k, v in not_your_turn_cooldowns.items() if v > cutoff}


async def cleanup_cooldowns_async():  # async version สำหรับ cleanup ที่ปลอดภัย
    """Async version of cleanup_cooldowns with proper locking"""
    now = time.monotonic()
    cutoff = now - 3600  # 1 hour ago
    async with cooldowns_lock:
        global not_your_turn_cooldowns
        not_your_turn_cooldowns = {k: v for k, v in not_your_turn_cooldowns.items() if v > cutoff}


# ---------------------------
# Turn timer (safe cancel + token)
# ---------------------------

async def cancel_turn_timer_async(state: GameState):  # ยกเลิก timer แบบปลอดภัย
    current = asyncio.current_task()  # task ที่กำลังรัน
    t = state.turn_task  # task เดิม
    if t and not t.done() and t is not current:  # cancel ได้เมื่อไม่ใช่ตัวเอง
        t.cancel()  # cancel
        try:
            await t  # รอให้จบจริง (กัน ghost task)
        except asyncio.CancelledError:
            pass  # cancel สำเร็จ
        except Exception:
            pass  # กัน error อื่น
    state.turn_task = None  # เคลียร์ตัวชี้


async def send_turn_prompt(channel: discord.abc.Messageable, state: GameState):  # ส่ง prompt เทิร์น
    state.turn_message = None  # เคลียร์ก่อนส่งใหม่ กัน edit ข้อความผิด
    uid, ai_name = current_player_info(state)  # ดึงคนที่ถึงตา
    if uid is None and ai_name is None:  # ไม่มีผู้เล่น
        await channel.send("No players joined yet! Use !join or !add_ai", allowed_mentions=allowed_mentions_none)  # แจ้ง
        return None  # จบ

    name = state.player_names.get(uid, f"User {uid}") if uid is not None else (ai_name or "Unknown")  # ชื่อผู้เล่น
    name = discord.utils.escape_markdown(name)  # escape markdown/mentions
    text = build_turn_text(state, name, state.turn_seconds)  # ข้อความเริ่มต้น
    msg = await channel.send(text, allowed_mentions=allowed_mentions_none)  # ส่งข้อความ
    state.turn_message = msg  # เก็บไว้แก้ progress
    return msg  # คืน message


async def start_turn_timer(channel: discord.abc.Messageable, state: GameState):  # เริ่ม timer เทิร์น
    await cancel_turn_timer_async(state)  # ยกเลิกของเก่าก่อน

    # token เพิ่มทุกครั้งที่เริ่มเทิร์น เพื่อกัน task/AI เก่าทำงานทับ
    state.turn_token += 1  # bump token
    my_token = state.turn_token  # token ของ task นี้

    async def timer():  # task นับถอยหลัง
        try:
            tp = total_players(state)  # จำนวนผู้เล่น
            if not state.active or tp == 0:  # เกมปิดหรือไม่มีคน
                return  # จบ

            uid, ai_name = current_player_info(state)  # คนที่ถึงตาตอนเริ่ม timer

            # --- AI turn ---
            if ai_name is not None:  # ถ้าเป็นตา AI
                await asyncio.sleep(getattr(config, "ai_think_delay", 1.0))  # หน่วงให้ prompt แสดงก่อน

                # ถ้า token ไม่ตรง แปลว่าเทิร์นเปลี่ยนแล้ว -> หยุดทันที
                if my_token != state.turn_token or not state.active:  # ตรวจ token
                    return  # จบ

                word = await generate_ai_word_async(state, ai_name)  # ขอคำจาก AI แบบไม่ค้างบอท

                # token ตรวจซ้ำกัน race condition
                if my_token != state.turn_token or not state.active:  # ตรวจ token
                    return  # จบ

                if word:  # ถ้าได้คำ
                    await process_word_submission(channel, word, state, player_id=None, ai_player=ai_name)  # ส่งเข้าระบบ
                    return  # จบ (process_word_submission จะเปิดเทิร์นใหม่)
                # AI คิดไม่ออก -> ข้าม
                advance_turn(state)  # ข้ามไปคนถัดไป
                await channel.send(f"🤖 {ai_name} couldn't think of a word! Skipping...", allowed_mentions=allowed_mentions_none)  # แจ้ง
                await send_turn_prompt(channel, state)  # prompt เทิร์นใหม่
                await start_turn_timer(channel, state)  # เริ่ม timer ใหม่
                return  # จบ

            # --- Human turn countdown ---
            remaining = state.turn_seconds  # เวลาที่เหลือ
            update_interval = 2  # อัปเดตทุก 2 วินาที (ลดโอกาสโดน rate-limit)

            while remaining > 0:  # นับถอยหลัง
                # ถ้า token ไม่ตรง แปลว่าเทิร์นถูกเปลี่ยนแล้ว -> หยุด
                if my_token != state.turn_token or not state.active:  # ตรวจ token
                    return  # จบ

                tp2 = total_players(state)  # จำนวนผู้เล่นปัจจุบัน (อาจเปลี่ยนได้)
                if tp2 == 0:  # ไม่มีคนแล้ว
                    return  # จบ

                # อัปเดตข้อความ progress
                if state.turn_message and remaining < state.turn_seconds:  # ไม่ใช่รอบแรก
                    name = peek_current_name(state)  # ชื่อคนที่ถึงตา ณ ตอนนี้
                    try:
                        await state.turn_message.edit(content=build_turn_text(state, name, remaining))  # แก้ไขข้อความ
                    except discord.errors.HTTPException:
                        pass  # ถ้าแก้ไม่ได้ก็ข้าม

                sleep_time = min(update_interval, remaining)  # กันเหลือ < interval
                await asyncio.sleep(sleep_time)  # รอ
                remaining -= sleep_time  # ลดเวลาที่เหลือ

            # --- Time's up -> skip human ---
            # ถ้า token ไม่ตรง แปลว่าเทิร์นเปลี่ยนแล้ว -> ไม่ต้อง skip
            if my_token != state.turn_token or not state.active:  # ตรวจ token
                return  # จบ

            tp3 = total_players(state)  # จำนวนผู้เล่นอีกครั้ง
            if tp3 == 0:  # ไม่มีคน
                return  # จบ

            # รีเซ็ต streak/combo เมื่อโดนข้าม
            if uid is not None:  # เป็นคน
                state.player_streaks[uid] = 0  # รีเซ็ต streak คนนี้
            state.combo_count = 0  # รีเซ็ต combo ห้อง

            name = state.player_names.get(uid, f"User {uid}") if uid is not None else "Unknown"  # ชื่อคนที่โดนข้าม
            advance_turn(state)  # เลื่อนไปคนถัดไป
            await channel.send(f"⏰ Time's up! Skipping {name}.", allowed_mentions=allowed_mentions_none)  # แจ้ง
            await send_turn_prompt(channel, state)  # ส่ง prompt ใหม่
            await start_turn_timer(channel, state)  # เริ่ม timer ใหม่

        except asyncio.CancelledError:
            return  # ถูก cancel ก็จบ
        except Exception as e:
            print(f"Timer error: {e}")  # log error
            return  # จบ

    state.turn_task = asyncio.create_task(timer())  # สร้าง task ใหม่


# ---------------------------
# AI (OpenRouter via OpenAI SDK) - sync + to_thread
# ---------------------------

def generate_ai_word(state: GameState, ai_name: str) -> Optional[str]:  # สร้างคำ AI (sync) กับ retry
    max_retries = 3  # ลองใหม่ได้ 3 ครั้ง
    for attempt in range(max_retries):  # ลูป retry
        try:
            if not OPENROUTER_API_KEY:  # ถ้าไม่มี key
                print("AI error: OPENROUTER_API_KEY is not set")  # log
                return None  # จบ

            last_letter = state.word_chain[-1][-1] if state.word_chain else None  # ตัวท้ายคำล่าสุด
            used_words_preview = state.word_chain[-20:] if state.word_chain else []  # เอาท้าย ๆ 20 คำ (ตามลำดับเวลา)
            used_words_str = ", ".join(used_words_preview)  # ทำเป็นสตริง

            prompt = "You are playing a Word Chain game.\n"  # ตั้งบทบาท
            if last_letter:  # ถ้ามีเงื่อนไขตัวอักษร
                prompt += f"Your word must start with '{last_letter}'.\n"  # บอกกติกา
            else:
                prompt += "You can start with any word.\n"  # เริ่มได้ทุกคำ
            prompt += f"Used words: {used_words_str}\n"  # บอกคำที่ใช้แล้ว
            prompt += "Return ONE valid English word (3-15 letters), letters only, not used yet. Reply with only the word."  # ข้อกำหนด

            resp = openai_client.chat.completions.create(  # เรียกโมเดล
                model=config.ai_model,  # โมเดลจาก config
                messages=[{"role": "user", "content": prompt}],  # ข้อความ user
                max_tokens=config.ai_max_tokens,  # จำกัด token
                temperature=config.ai_temperature,  # ความสุ่ม
            )

            word = (resp.choices[0].message.content or "").strip().lower()  # ดึงคำตอบ
            if not word:  # กันคำตอบว่าง
                continue  # ลองใหม่

            # ทำความสะอาดคำตอบเผื่อมีเครื่องหมาย / ข้อความอื่น
            word = "".join(ch for ch in word if ch.isalpha())  # เอาเฉพาะตัวอักษร

            if not is_valid_word_basic(word):  # ตรวจรูปแบบ
                continue  # ลองใหม่

            if word in state.used_words:  # กันซ้ำ
                continue  # ลองใหม่

            if last_letter and not word.startswith(last_letter):  # ต้องเริ่มด้วยตัวท้ายเดิม
                continue  # ลองใหม่

            return word  # ผ่านทั้งหมด
        except Exception as e:
            print(f"AI word generation error (attempt {attempt + 1}): {e}")  # log
            if attempt < max_retries - 1:  # ถ้ายังไม่ครบ retry
                continue  # ลองใหม่
    return None  # ยอมแพ้หลัง retry หมด


async def generate_ai_word_async(state: GameState, ai_name: str) -> Optional[str]:  # async wrapper
    return await asyncio.to_thread(generate_ai_word, state, ai_name)  # ย้ายงาน sync ไป thread


# ---------------------------
# Core submission logic
# ---------------------------

async def process_word_submission(
    channel: discord.abc.Messageable,  # ช่องที่จะส่งข้อความ
    word: str,  # คำที่ส่งมา
    state: GameState,  # state ห้อง
    player_id: Optional[int] = None,  # user_id (ถ้าเป็นคน)
    ai_player: Optional[str] = None,  # ai_name (ถ้าเป็น AI)
):
    word = normalize_word(word)  # normalize

    # --- Validate basic ---
    if not is_valid_word_basic(word):  # ตรวจรูปแบบคำ
        if ai_player:
            await channel.send(f"🤖 {ai_player} submitted invalid word format.", allowed_mentions=allowed_mentions_none)  # แจ้ง
        else:
            await channel.send("Please enter a valid word (letters only, at least 2).", allowed_mentions=allowed_mentions_none)  # แจ้ง
        return  # จบ

    # --- Validate English ---
    if not await is_valid_english_word(word):  # ตรวจคำอังกฤษ
        if ai_player:
            await channel.send(f"🤖 {ai_player} submitted invalid English word.", allowed_mentions=allowed_mentions_none)  # แจ้ง
        else:
            await channel.send("Not a valid English word (dictionary check failed).", allowed_mentions=allowed_mentions_none)  # แจ้ง
        return  # จบ

    # --- Duplicate ---
    if word in state.used_words:  # คำซ้ำ
        if ai_player:
            await channel.send(f"🤖 {ai_player} submitted already used word.", allowed_mentions=allowed_mentions_none)  # แจ้ง
        else:
            await channel.send("Word already used!", allowed_mentions=allowed_mentions_none)  # แจ้ง
        return  # จบ

    # --- Chain rule ---
    if state.word_chain:  # ถ้ามีคำก่อนหน้า
        last_word = state.word_chain[-1]  # คำล่าสุด
        if word[0] != last_word[-1]:  # ตัวแรกไม่ตรงตัวท้าย
            if ai_player:
                await channel.send(f"🤖 {ai_player} submitted word that doesn't chain properly.", allowed_mentions=allowed_mentions_none)  # แจ้ง
            else:
                await channel.send(f"Word must start with '{last_word[-1]}'.", allowed_mentions=allowed_mentions_none)  # แจ้ง
            return  # จบ

    # --- Stop timer for this turn (safe) ---
    await cancel_turn_timer_async(state)  # ยกเลิก timer รอบนี้ (ปลอดภัย)

    # --- Apply word (with state lock) ---
    async with state._lock:  # lock เพื่อแก้ไข state อย่างปลอดภัย
        await update_state_activity(state)  # track activity

        state.word_chain.append(word)  # เพิ่มใน chain
        state.used_words.add(word)  # mark used

        # --- Scoring ---
        base_points = 1  # คะแนนพื้นฐาน
        bonus_points = 0  # คะแนนโบนัส

        if len(word) >= config.long_word_len:  # โบนัสคำยาว
            bonus_points += config.long_word_bonus  # บวกโบนัส

        if ai_player:  # ถ้าเป็น AI
            key = sanitize_ai_key(ai_player)  # key ปลอดภัย
            async with display_names_lock:
                ai_display_names[key] = ai_player  # เก็บ display name
            total_points = base_points + bonus_points  # รวมคะแนน
            async with scores_lock:  # lock เพื่อกัน lost update
                scores_data[key] = scores_data.get(key, 0) + total_points  # เพิ่มคะแนน AI
                await save_scores_async()  # เซฟ

            advance_turn(state)  # เลื่อนไปคนถัดไป

        else:  # ถ้าเป็น human
            if player_id is None:  # กันกรณีข้อมูลไม่ครบ
                return  # จบ

            streak = state.player_streaks.get(player_id, 0) + 1  # เพิ่ม streak
            state.player_streaks[player_id] = streak  # เก็บ streak
            if streak >= config.streak_min:  # ถึงเกณฑ์ streak
                bonus_points += config.streak_bonus  # บวกโบนัส

            state.combo_count += 1  # เพิ่ม combo
            if config.combo_step > 0 and (state.combo_count % config.combo_step == 0):  # ทุก ๆ step
                bonus_points += config.combo_bonus  # บวกโบนัส

            total_points = base_points + bonus_points  # รวมคะแนน
            key = str(player_id)  # key ของ human
            async with scores_lock:  # lock เพื่อกัน lost update
                scores_data[key] = scores_data.get(key, 0) + total_points  # เพิ่มคะแนน human
                await save_scores_async()  # เซฟ

            advance_turn(state)  # เลื่อนไปคนถัดไป

    # --- Send results (outside lock to avoid blocking) ---
    next_name = peek_current_name(state)  # ชื่อคนถัดไปจริง
    next_name = discord.utils.escape_markdown(next_name)  # escape

    if ai_player:
        await channel.send(  # ส่งผลลัพธ์
            f"🤖 {discord.utils.escape_markdown(ai_player)} played '{word}' (+{total_points} pts). "
            f"Next starts with '{word[-1]}'. Next: {next_name}",
            allowed_mentions=allowed_mentions_none,
        )
    else:
        bonus_text = f" (+{bonus_points} bonus)" if bonus_points > 0 else ""  # ข้อความโบนัส
        await channel.send(  # ส่งผลลัพธ์
            f"✅ Added '{word}' (+{total_points} pts{bonus_text}). Next starts with '{word[-1]}'. "
            f"Your total score: {scores_data[key]}. Next: {next_name}",
            allowed_mentions=allowed_mentions_none,
        )
    await start_turn_timer(channel, state)  # เริ่ม timer เทิร์นใหม่


# ---------------------------
# Events
# ---------------------------

@bot.event
async def on_ready():  # บอทพร้อม
    global SCORES_FILE, http_session  # ใช้ scores_file และ http_session global
    SCORES_FILE = config.scores_file  # กำหนดไฟล์คะแนนจาก config ปัจจุบัน
    load_scores_sync()  # โหลดคะแนน
    http_session = aiohttp.ClientSession()  # สร้าง session ครั้งเดียว
    await load_valid_words_async()  # โหลด wordlist

    # Start cleanup task for inactive games
    asyncio.create_task(cleanup_inactive_games())

    print("Bot is ready")  # log


@bot.event
async def on_message(message: discord.Message):  # รับข้อความ
    if message.author == bot.user:  # กัน loop
        return  # จบ

    # ให้ command ทำงานก่อน (รองรับ mention prefix + prefix ปัจจุบัน)
    await bot.process_commands(message)  # สำคัญ

    # ถ้าเป็น command (prefix หรือ mention) ให้หยุด ไม่เอาเข้าเกม
    try:
        prefixes = await bot.get_prefix(message)  # ได้ list ของ prefix (รวม mention)
        if isinstance(prefixes, str):  # กันกรณีเป็นสตริง
            prefixes = [prefixes]  # ทำเป็น list
        if any(message.content.startswith(p) for p in prefixes):  # เช็คทุก prefix
            return  # จบ
    except Exception:
        # fallback ถ้ามีอะไรแปลก
        if message.content.startswith(config.command_prefix):  # เช็ค prefix ปกติ
            return  # จบ

    state = get_game(message.channel.id)  # state ห้อง
    if not state.active:  # เกมไม่ active
        return  # จบ

    if total_players(state) == 0:  # ไม่มีผู้เล่น
        await message.channel.send("No players joined yet! Use !join or !add_ai", allowed_mentions=allowed_mentions_none)  # แจ้ง
        return  # จบ

    # เช็คว่าเป็นตาของคนนี้หรือไม่ก่อน (สำคัญ: cooldown ห้าม block คนที่ถึงตา)
    uid, ai_name = current_player_info(state)  # ดึงคนที่ถึงตา
    if uid != message.author.id:  # ไม่ใช่ตาเขา
        # Cleanup old cooldowns periodically (async version)
        async with cooldowns_lock:
            if len(not_your_turn_cooldowns) > 100:  # ถ้ามีมากกว่า 100 entries
                await cleanup_cooldowns_async()  # เคลียร์เก่าแบบ async

            # quiet cooldown สำหรับ "not your turn" messages (กัน spam)
            now = time.monotonic()  # เวลาปัจจุบัน
            last_quiet = not_your_turn_cooldowns.get(message.author.id, 0.0)  # เวลาครั้งล่าสุดที่ส่งข้อความนี้
            if now - last_quiet < 5.0:  # cooldown 5 วินาทีสำหรับข้อความนี้
                return  # เงียบ ๆ ไม่ส่งข้อความซ้ำ
            not_your_turn_cooldowns[message.author.id] = now  # อัปเดตเวลา

        name = state.player_names.get(uid, f"User {uid}") if uid is not None else (ai_name or "Unknown")  # ชื่อคนที่ถึงตา
        name = discord.utils.escape_markdown(name)  # escape
        await message.channel.send(f"🚫 Not your turn. It's {name}'s turn!", allowed_mentions=allowed_mentions_none)  # แจ้ง
        return  # จบ

    # ถึงตาแล้ว ไม่ใช้ cooldown เพื่อไม่ block การเล่น
    await process_word_submission(message.channel, message.content, state, player_id=message.author.id, ai_player=None)  # ประมวลผลคำ


@bot.event
async def on_disconnect():  # หลุดการเชื่อมต่อ
    # ไม่ต้องปิด session เพราะ discord อาจ reconnect เอง
    pass  # เว้นไว้


@bot.event
async def on_error(event, *args, **kwargs):  # log error ระดับ event
    print(f"Error in event: {event}")  # log ชื่อ event


# ---------------------------
# Commands
# ---------------------------

@bot.command()
async def start_game(ctx):  # เริ่มเกม
    state = get_game(ctx.channel.id)  # state ห้อง

    async with state._lock:  # lock เพื่อแก้ไข state อย่างปลอดภัย
        await update_state_activity(state)  # track activity

        state.active = True  # เปิดเกม

        # reset เกมในห้อง
        state.word_chain = []  # รีเซ็ตคำ
        state.used_words = set()  # รีเซ็ต used
        state.player_streaks = {}  # รีเซ็ต streak
        state.combo_count = 0  # รีเซ็ต combo
        state.turn_seconds = config.turn_seconds  # ใช้ค่าจาก config ล่าสุด
        state.current_idx = 0  # เริ่มที่คนแรก
        state.turn_token += 1  # bump token เพื่อกัน task เก่าทับ

        await cancel_turn_timer_async(state)  # ยกเลิก timer เก่า

        tp = total_players(state)  # จำนวนผู้เล่นทั้งหมด
        if tp == 0:  # ไม่มีผู้เล่น
            await ctx.send("🎮 Game started, but no players yet. Use !join or !add_ai", allowed_mentions=allowed_mentions_none)  # แจ้ง
            return  # จบ

        await ctx.send("🎮 Word chain started in this channel! Use !join / !add_ai then play in turn.", allowed_mentions=allowed_mentions_none)  # แจ้งเริ่ม
        await send_turn_prompt(ctx.channel, state)  # ส่ง prompt
        await start_turn_timer(ctx.channel, state)  # เริ่ม timer


@bot.command()
@commands.has_permissions(manage_guild=True)
async def end_game(ctx):  # จบเกม (admin only)
    state = get_game(ctx.channel.id)  # state ห้อง
    state.active = False  # ปิดเกม
    state.turn_token += 1  # bump token เพื่อให้ task เก่าหยุดเอง
    await cancel_turn_timer_async(state)  # ยกเลิก timer
    state.turn_message = None  # เคลียร์ message อ้างอิง
    await ctx.send("🛑 Game ended in this channel.", allowed_mentions=allowed_mentions_none)  # แจ้งจบ


@bot.command()
async def join(ctx):  # เข้าร่วมเกม
    state = get_game(ctx.channel.id)  # state ห้อง
    uid = ctx.author.id  # id ผู้ใช้

    if uid in state.players:  # กัน join ซ้ำ
        await ctx.send("You're already in this channel's game!", allowed_mentions=allowed_mentions_none)  # แจ้ง
        return  # จบ

    if uid in state.joining_users:  # กัน join ซ้อน
        return  # จบ

    state.joining_users.add(uid)  # mark กำลัง join
    try:
        state.players.append(uid)  # เพิ่มผู้เล่น
        state.player_names[uid] = ctx.author.display_name  # เก็บชื่อใน state
        async with display_names_lock:
            user_display_names[uid] = ctx.author.display_name  # เก็บชื่อ global สำหรับ leaderboard
        await ctx.send(f"➕ {ctx.author.display_name} joined this channel's game!", allowed_mentions=allowed_mentions_none)  # แจ้ง
    finally:
        state.joining_users.discard(uid)  # unmark

    # ถ้าเกม active และผู้เล่นคนแรก -> เริ่ม prompt/timer
    if state.active and total_players(state) == 1:  # คนแรกในห้อง
        state.current_idx = 0  # ให้เริ่มที่คนแรก
        await send_turn_prompt(ctx.channel, state)  # prompt
        await start_turn_timer(ctx.channel, state)  # timer


@bot.command()
async def leave(ctx):  # ออกจากเกม
    state = get_game(ctx.channel.id)  # state ห้อง
    uid = ctx.author.id  # id ผู้ใช้

    if uid not in state.players:  # ไม่ได้อยู่ในเกม
        await ctx.send("You're not in this channel's game.", allowed_mentions=allowed_mentions_none)  # แจ้ง
        return  # จบ

    idx = state.players.index(uid)  # index ในลิสต์ human (ฐาน global ก็เท่ากันเพราะ human อยู่ต้น)
    removed_global_idx = idx  # global index ในลิสต์รวม (human อยู่ช่วงแรก)

    state.players.remove(uid)  # ลบออก
    state.player_names.pop(uid, None)  # ลบชื่อที่เก็บ
    state.player_streaks.pop(uid, None)  # ลบ streak

    tp = total_players(state)  # จำนวนผู้เล่นหลังลบ
    if tp > 0:  # ยังมีผู้เล่น
        # ถ้าคนที่ออกอยู่ก่อน current_idx -> ลด current_idx ลง
        if removed_global_idx < state.current_idx:  # เทียบฐานเดียวกันแล้ว
            state.current_idx -= 1  # เลื่อนกลับ
        state.current_idx %= tp  # mod ด้วยจำนวนรวม (รวม AI)
    else:
        state.current_idx = 0  # รีเซ็ต
        state.turn_token += 1  # bump token ให้ task เก่าหยุด
        await cancel_turn_timer_async(state)  # ไม่มีคนก็หยุด timer

    await ctx.send(f"➖ {ctx.author.display_name} left this channel's game!", allowed_mentions=allowed_mentions_none)  # แจ้ง

    # ถ้าเกม active และยังมีคน -> รีสตาร์ท prompt/timer (กันค้างเทิร์น)
    if state.active and tp > 0:  # ยังเล่นได้
        state.turn_token += 1  # bump token เพื่อกัน timer เดิมทับ
        await cancel_turn_timer_async(state)  # ยกเลิก timer เดิม (ถ้ามี)
        await send_turn_prompt(ctx.channel, state)  # prompt ใหม่
        await start_turn_timer(ctx.channel, state)  # timer ใหม่


@bot.command()
async def add_ai(ctx, ai_name: str = "AI"):  # เพิ่ม AI
    state = get_game(ctx.channel.id)  # state ห้อง
    # Validate AI name
    ai_name = ai_name.strip()  # trim spaces
    if not ai_name:  # empty name
        await ctx.send("🤖 AI name cannot be empty!", allowed_mentions=allowed_mentions_none)  # แจ้ง
        return  # จบ
    if len(ai_name) > 50:  # too long
        await ctx.send("🤖 AI name too long! Maximum 50 characters.", allowed_mentions=allowed_mentions_none)  # แจ้ง
        return  # จบ
    if not ai_name.replace(" ", "").replace("_", "").isalnum():  # invalid characters
        await ctx.send("🤖 AI name can only contain letters, numbers, spaces, and underscores!", allowed_mentions=allowed_mentions_none)  # แจ้ง
        return  # จบ
    if ai_name in state.ai_players:  # กันซ้ำ
        await ctx.send(f"🤖 {ai_name} is already in this channel's game!", allowed_mentions=allowed_mentions_none)  # แจ้ง
        return  # จบ

    if len(state.ai_players) >= config.max_ai_players:  # จำกัดจำนวน AI
        await ctx.send(f"🤖 Maximum {config.max_ai_players} AI players allowed!", allowed_mentions=allowed_mentions_none)  # แจ้ง
        return  # จบ

    if ai_name in state.adding_ais:  # กัน add_ai ซ้อน
        return  # จบ

    state.adding_ais.add(ai_name)  # mark
    try:
        state.ai_players.append(ai_name)  # เพิ่ม AI
        await ctx.send(f"🤖 {ai_name} joined this channel's game!", allowed_mentions=allowed_mentions_none)  # แจ้ง
    finally:
        state.adding_ais.discard(ai_name)  # unmark

    # ถ้าเกม active และเป็นผู้เล่นคนแรก -> เริ่ม prompt/timer
    if state.active and total_players(state) == 1:  # คนแรกในห้อง
        state.current_idx = 0  # เริ่มที่ index 0
        await send_turn_prompt(ctx.channel, state)  # prompt
        await start_turn_timer(ctx.channel, state)  # timer

    # ถ้าเกม active และเทิร์นกำลังเดินอยู่ ให้รีสตาร์ท prompt/timer เพื่อ sync รายชื่อ
    if state.active and total_players(state) > 1 and state.turn_task:  # มีเกมและมี timer อยู่
        state.turn_token += 1  # bump token กัน task เดิม
        await cancel_turn_timer_async(state)  # ยกเลิก task เดิม
        await send_turn_prompt(ctx.channel, state)  # prompt ใหม่
        await start_turn_timer(ctx.channel, state)  # timer ใหม่


@bot.command()
async def remove_ai(ctx, ai_name: str):  # ลบ AI
    state = get_game(ctx.channel.id)  # state ห้อง

    if ai_name not in state.ai_players:  # ไม่มี AI นี้
        await ctx.send(f"🤖 {ai_name} is not in this channel's game.", allowed_mentions=allowed_mentions_none)  # แจ้ง
        return  # จบ

    ai_idx = state.ai_players.index(ai_name)  # index ในลิสต์ AI
    removed_global_idx = len(state.players) + ai_idx  # global index ของ AI ในลิสต์รวม "ก่อนลบ"

    state.ai_players.remove(ai_name)  # ลบออก

    tp = total_players(state)  # จำนวนผู้เล่นหลังลบ
    if tp > 0:  # ยังมีผู้เล่น
        if removed_global_idx < state.current_idx:  # ถ้า AI ที่ออกอยู่ก่อนเทิร์นปัจจุบัน
            state.current_idx -= 1  # เลื่อนกลับ
        state.current_idx %= tp  # mod ด้วยทั้งหมด
    else:
        state.current_idx = 0  # รีเซ็ต
        state.turn_token += 1  # bump token ให้ task เก่าหยุด
        await cancel_turn_timer_async(state)  # ไม่มีคนก็หยุด timer

    await ctx.send(f"🤖 {ai_name} left this channel's game!", allowed_mentions=allowed_mentions_none)  # แจ้ง

    if state.active and tp > 0:  # ถ้ายังเล่นได้
        state.turn_token += 1  # bump token เพื่อกัน timer เดิมทับ
        await cancel_turn_timer_async(state)  # ยกเลิก timer เดิม
        await send_turn_prompt(ctx.channel, state)  # prompt ใหม่
        await start_turn_timer(ctx.channel, state)  # timer ใหม่


@bot.command()
@commands.has_permissions(manage_guild=True)
async def settime(ctx, seconds: int):  # ตั้งเวลาเทิร์นต่อห้อง (admin only)
    state = get_game(ctx.channel.id)  # state ห้อง
    seconds = max(config.min_turn_time, min(seconds, config.max_turn_time))  # จำกัดช่วง
    state.turn_seconds = seconds  # ตั้งค่า
    await ctx.send(f"⏳ Turn time set to {seconds}s for this channel.", allowed_mentions=allowed_mentions_none)  # แจ้ง


@bot.command()
async def status(ctx):  # ดูสถานะเกม
    state = get_game(ctx.channel.id)  # state ห้อง

    if not state.active:  # เกมไม่ active
        await ctx.send("ℹ️ No active game in this channel. Use !start_game", allowed_mentions=allowed_mentions_none)  # แจ้ง
        return  # จบ

    if total_players(state) == 0:  # ไม่มีผู้เล่น
        await ctx.send("ℹ️ Game is active but no players joined. Use !join or !add_ai", allowed_mentions=allowed_mentions_none)  # แจ้ง
        return  # จบ

    turn_name = peek_current_name(state)  # ชื่อคนที่ถึงตา
    last = state.word_chain[-1] if state.word_chain else "(none)"  # คำล่าสุด

    await ctx.send(  # สรุปสถานะ
        f"📣 Active: {state.active}\n"
        f"👥 Humans: {len(state.players)} | 🤖 AIs: {len(state.ai_players)}\n"
        f"🧠 Last word: {last}\n"
        f"🎯 Current turn: {turn_name}\n"
        f"⏳ Turn time: {state.turn_seconds}s\n"
        f"🔗 Chain length: {len(state.word_chain)}",
        allowed_mentions=allowed_mentions_none,
    )


@bot.command(name="scores")
async def leaderboard(ctx):  # top 10 คะแนนรวม (รองรับ AI)
    if not scores_data:  # ยังไม่มีคะแนน
        await ctx.send("No scores yet!", allowed_mentions=allowed_mentions_none)  # แจ้ง
        return  # จบ

    sorted_scores = sorted(scores_data.items(), key=lambda x: x[1], reverse=True)  # เรียงคะแนน
    text = "🏆 **Leaderboard (Global)** 🏆\n"  # หัวข้อ

    rank = 1  # ลำดับ
    async with display_names_lock:  # lock เพื่ออ่าน display names อย่างปลอดภัย
        for user_key, score in sorted_scores:  # วนทุกคน
            if rank > 10:  # top 10
                break  # จบ

            if str(user_key).startswith("ai_"):  # ถ้าเป็น AI
                display_name = ai_display_names.get(user_key, str(user_key).replace("ai_", ""))  # ใช้ display name ถ้ามี
                name = f"🤖 {display_name}"  # ชื่อ AI
            else:
                try:
                    user_id = int(user_key)
                    name = user_display_names.get(user_id, f"User {user_key}")  # ใช้ชื่อที่เก็บไว้ หรือ fallback
                except Exception:
                    name = f"User {user_key}"  # กันข้อมูลแปลก

            text += f"{rank}. {name}: {score}\n"  # ต่อบรรทัด
            rank += 1  # เพิ่มอันดับ

    await ctx.send(text, allowed_mentions=allowed_mentions_none)  # ส่ง


@bot.command()
async def myscore(ctx):  # ดูคะแนนตัวเอง
    key = str(ctx.author.id)  # key ของ user
    score = scores_data.get(key, 0)  # คะแนน
    await ctx.send(f"📌 {ctx.author.display_name}, your total score is {score}.", allowed_mentions=allowed_mentions_none)  # ส่ง


@bot.command()
@commands.has_permissions(manage_guild=True)
async def reload_config(ctx):  # โหลด config ใหม่ (admin only)
    try:
        from config import GameConfig  # import ตัวคลาส (ต้องมีในโปรเจกต์น้อง)
        global config, SCORES_FILE  # ใช้ config และ scores_file global
        config = GameConfig()  # โหลดใหม่จากไฟล์ของน้องเอง
        SCORES_FILE = config.scores_file  # อัปเดตไฟล์คะแนนตาม config ใหม่

        if config.validate():  # ตรวจความถูกต้อง
            await load_valid_words_async()  # reload words เผื่อเปลี่ยนไฟล์
            await ctx.send("✅ Configuration reloaded successfully!", allowed_mentions=allowed_mentions_none)  # แจ้งสำเร็จ
            await ctx.send(
                f"📋 Prefix: {config.command_prefix} | Turn: {config.turn_seconds}s | AI Model: {config.ai_model}",
                allowed_mentions=allowed_mentions_none,
            )  # สรุป
        else:
            await ctx.send("❌ Configuration validation failed! Check your config.json values.", allowed_mentions=allowed_mentions_none)  # แจ้ง
    except Exception as e:
        await ctx.send(f"❌ Error reloading configuration: {e}", allowed_mentions=allowed_mentions_none)  # แจ้ง error


@bot.command()
async def hint(ctx):  # ขอคำใบ้
    state = get_game(ctx.channel.id)  # state ห้อง
    if not state.active:  # เกมไม่เริ่ม
        await ctx.send("No active game in this channel.", allowed_mentions=allowed_mentions_none)  # แจ้ง
        return  # จบ

    if not state.word_chain:  # ยังไม่มีคำ
        await ctx.send("No words yet. Start with any word!", allowed_mentions=allowed_mentions_none)  # แจ้ง
        return  # จบ

    if http_session is None or http_session.closed:  # session ยังไม่พร้อม
        await ctx.send("HTTP session not ready.", allowed_mentions=allowed_mentions_none)  # แจ้ง
        return  # จบ

    last_letter = state.word_chain[-1][-1]  # ตัวท้ายคำล่าสุด
    url = f"https://api.datamuse.com/words?sp={last_letter}*&max=20"  # คำขึ้นต้นด้วย last_letter
    try:
        async with http_session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as r:  # ยิง request
            data = await r.json()  # อ่าน json
        suggestions = [w["word"] for w in data if w.get("word") and w["word"] not in state.used_words and len(w["word"]) > 2]  # กรอง
        if suggestions:
            await ctx.send(f"💡 Hints for '{last_letter}': {', '.join(suggestions[:5])}", allowed_mentions=allowed_mentions_none)  # ส่ง 5 คำ
        else:
            await ctx.send(f"💡 No hints left for '{last_letter}'.", allowed_mentions=allowed_mentions_none)  # แจ้ง
    except Exception:
        await ctx.send("Couldn't fetch hints right now.", allowed_mentions=allowed_mentions_none)  # แจ้ง


@bot.command()
@commands.has_permissions(manage_guild=True)
async def reset_scores(ctx):  # รีเซ็ตคะแนนทั้งหมด (admin only)
    global scores_data, ai_display_names  # เคลียร์ global
    scores_data = {}  # รีเซ็ต dict
    ai_display_names = {}  # เคลียร์ display names
    await save_scores_async()  # เซฟไฟล์ว่าง
    await ctx.send("🗑️ All scores have been reset!", allowed_mentions=allowed_mentions_none)  # แจ้ง


@bot.command()
@commands.has_permissions(manage_guild=True)
async def clear_channel(ctx):  # เคลียร์ state ของห้องนี้ (admin only)
    state = get_game(ctx.channel.id)  # state ห้อง
    state.active = False  # ปิดเกม
    state.players = []  # เคลียร์ผู้เล่น
    state.ai_players = []  # เคลียร์ AI
    state.player_names = {}  # เคลียร์ชื่อ
    state.word_chain = []  # เคลียร์คำ
    state.used_words = set()  # เคลียร์ used
    state.current_idx = 0  # รีเซ็ต index
    state.player_streaks = {}  # เคลียร์ streak
    state.combo_count = 0  # เคลียร์ combo
    state.cooldowns = {}  # เคลียร์ cooldowns
    state.turn_token += 1  # bump token
    await cancel_turn_timer_async(state)  # ยกเลิก timer
    state.turn_message = None  # เคลียร์ message
    await ctx.send("🧹 Channel state has been cleared!", allowed_mentions=allowed_mentions_none)  # แจ้ง


# ---------------------------
# Graceful shutdown (proper)
# ---------------------------

@bot.event
async def on_close():  # ปิดบอท -> ปิด session
    global http_session  # ใช้ global
    if http_session and not http_session.closed:  # ถ้า session ยังเปิด
        await http_session.close()  # ปิด
    http_session = None  # เคลียร์


# ---------------------------
# Run
# ---------------------------

bot.run(TOKEN)  # รันบอท