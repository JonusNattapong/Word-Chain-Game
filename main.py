import os  # อธิบาย: ใช้อ่าน env และไฟล์
import json  # อธิบาย: เก็บ/อ่านคะแนน
import asyncio  # อธิบาย: ใช้ task / lock / to_thread
import time  # อธิบาย: ใช้ cooldown timing
from dataclasses import dataclass, field  # อธิบาย: โครงสร้าง state
from typing import Dict, List, Set, Optional, Tuple  # อธิบาย: type hints

import discord  # อธิบาย: discord api
from discord.ext import commands  # อธิบาย: command framework
from dotenv import load_dotenv  # อธิบาย: โหลด .env
from spellchecker import SpellChecker  # อธิบาย: ตรวจคำอังกฤษแบบ offline
import aiohttp  # อธิบาย: http client แบบ async
from openai import OpenAI  # อธิบาย: ใช้ OpenRouter (ผ่าน OpenAI SDK)
import discord.utils  # อธิบาย: สำหรับ escape markdown

from config import config  # อธิบาย: โหลดการตั้งค่า (ต้องมีในโปรเจกต์ของน้อง)


# ---------------------------
# Config / Setup
# ---------------------------

load_dotenv()  # อธิบาย: โหลดค่าใน .env
TOKEN = os.getenv("DISCORD_TOKEN")  # อธิบาย: token ของบอท
if not TOKEN:
    raise ValueError("DISCORD_TOKEN is not set in .env file. Please provide a valid Discord bot token.")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")  # อธิบาย: key สำหรับ OpenRouter
if not OPENROUTER_API_KEY:
    raise ValueError("OPENROUTER_API_KEY is not set in .env file. Please provide a valid OpenRouter API key.")

OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"  # อธิบาย: base url ของ OpenRouter

intents = discord.Intents.default()  # อธิบาย: intents พื้นฐาน
intents.message_content = True  # อธิบาย: ต้องเปิดเพื่ออ่าน message.content
intents.members = False  # อธิบาย: ไม่ขอ privileged members intent

spell = SpellChecker()  # อธิบาย: ตัวเช็คคำอังกฤษ (offline)

allowed_mentions_none = discord.AllowedMentions.none()  # อธิบาย: กันบอท @everyone / @here / mention คนโดยไม่ตั้งใจ


def dynamic_prefix(bot: commands.Bot, message: discord.Message):  # อธิบาย: ฟังก์ชันคืน prefix แบบ dynamic
    return config.command_prefix  # อธิบาย: ใช้ prefix ปัจจุบันจาก config


bot = commands.Bot(command_prefix=dynamic_prefix, intents=intents)  # อธิบาย: สร้างบอทแบบ prefix เปลี่ยนได้

@bot.setup_hook
async def setup_hook():  # อธิบาย: setup hook สำหรับ init session
    global http_session  # อธิบาย: ใช้ session global
    http_session = aiohttp.ClientSession()  # อธิบาย: สร้าง session ครั้งเดียว

async def close():  # อธิบาย: override close เพื่อปิด session
    if http_session and not http_session.closed:  # อธิบาย: ถ้าเปิดอยู่
        await http_session.close()  # อธิบาย: ปิด session
    await super().close()  # อธิบาย: ปิดบอทปกติ

bot.close = close  # อธิบาย: กำหนด close method


openai_client = OpenAI(  # อธิบาย: สร้าง client OpenRouter ผ่าน OpenAI SDK
    api_key=OPENROUTER_API_KEY,  # อธิบาย: ใส่ key
    base_url=OPENROUTER_API_BASE,  # อธิบาย: ใส่ base url
    default_headers={  # อธิบาย: header แนะนำของ OpenRouter
        "HTTP-Referer": "https://github.com/JonusNattapong/Word-Chain-Game",  # อธิบาย: referer
        "X-Title": "Word Chain Discord Bot",  # อธิบาย: ชื่อแอป
    },
)

SCORES_FILE: str  # อธิบาย: ไฟล์คะแนนรวม (จะกำหนดใน on_ready และ reload_config)
scores_data: Dict[str, int] = {}  # อธิบาย: {"user_id": score} และ {"ai_name": score}
scores_lock = asyncio.Lock()  # อธิบาย: กันการเขียนไฟล์ชนกัน

ai_display_names: Dict[str, str] = {}  # อธิบาย: {"ai_key": "display_name"} สำหรับ leaderboard
not_your_turn_cooldowns: Dict[int, float] = {}  # อธิบาย: quiet cooldown สำหรับ "not your turn" messages

VALID_WORDS: Set[str] = set()  # อธิบาย: ชุดคำอังกฤษที่ถูกต้อง (โหลดจากไฟล์)
valid_words_lock = asyncio.Lock()  # อธิบาย: กัน reload words พร้อมกัน

http_session: Optional[aiohttp.ClientSession] = None  # อธิบาย: session รวมทั้งบอท


# ---------------------------
# Game State (แยกต่อห้อง)
# ---------------------------

@dataclass
class GameState:  # อธิบาย: state ของเกมใน 1 ห้อง
    active: bool = False  # อธิบาย: เกมกำลังเล่นอยู่ไหม

    players: List[int] = field(default_factory=list)  # อธิบาย: ลิสต์ user_id (human)
    ai_players: List[str] = field(default_factory=list)  # อธิบาย: ลิสต์ชื่อ AI
    player_names: Dict[int, str] = field(default_factory=dict)  # อธิบาย: {user_id: display_name}

    current_idx: int = 0  # อธิบาย: index ของคนที่ถึงตา (รวม human + AI)
    word_chain: List[str] = field(default_factory=list)  # อธิบาย: ลำดับคำ
    used_words: Set[str] = field(default_factory=set)  # อธิบาย: กันคำซ้ำ

    turn_seconds: int = field(default_factory=lambda: config.turn_seconds)  # อธิบาย: เวลาต่อเทิร์น (ต่อห้อง)
    turn_task: Optional[asyncio.Task] = None  # อธิบาย: task นับถอยหลังต่อเทิร์น
    turn_message: Optional[discord.Message] = None  # อธิบาย: message เทิร์น (แก้ progress bar)

    player_streaks: Dict[int, int] = field(default_factory=dict)  # อธิบาย: streak ต่อคน
    combo_count: int = 0  # อธิบาย: combo ต่อห้อง

    cooldowns: Dict[int, float] = field(default_factory=dict)  # อธิบาย: cooldown ต่อคน (ใช้เฉพาะตอน "ไม่ใช่ตา")
    joining_users: Set[int] = field(default_factory=set)  # อธิบาย: กัน join ซ้อน
    adding_ais: Set[str] = field(default_factory=set)  # อธิบาย: กัน add_ai ซ้อน

    turn_token: int = 0  # อธิบาย: token เพิ่มทุกเทิร์น กัน AI/Timer ยิงซ้อน (race condition)


games: Dict[int, GameState] = {}  # อธิบาย: {channel_id: GameState}


# ---------------------------
# Persistence (scores)
# ---------------------------

def load_scores_sync():  # อธิบาย: โหลดคะแนนแบบ sync ตอนเริ่ม
    global scores_data  # อธิบาย: ใช้ dict กลาง
    try:  # อธิบาย: กันไฟล์ไม่มี/พัง
        with open(SCORES_FILE, "r", encoding="utf-8") as f:  # อธิบาย: เปิดไฟล์
            data = json.load(f)  # อธิบาย: อ่าน json
            scores_data = data if isinstance(data, dict) else {}  # อธิบาย: กัน format แปลก
    except FileNotFoundError:  # อธิบาย: ครั้งแรกยังไม่มี
        scores_data = {}  # อธิบาย: เริ่มใหม่
    except json.JSONDecodeError:  # อธิบาย: ไฟล์เสีย
        scores_data = {}  # อธิบาย: รีเซ็ต


async def save_scores_async():  # อธิบาย: เซฟคะแนนแบบ async + lock + atomic
    async with scores_lock:  # อธิบาย: กันชนกัน
        tmp_file = SCORES_FILE + ".tmp"  # อธิบาย: เขียนไปไฟล์ชั่วคราวก่อน
        with open(tmp_file, "w", encoding="utf-8") as f:  # อธิบาย: เขียน tmp
            json.dump(scores_data, f, indent=4, ensure_ascii=False)  # อธิบาย: เซฟ json
        os.replace(tmp_file, SCORES_FILE)  # อธิบาย: atomic replace


# ---------------------------
# Word list
# ---------------------------

async def load_valid_words_async():  # อธิบาย: โหลดคำอังกฤษจากไฟล์แบบ async-safe
    global VALID_WORDS  # อธิบาย: ใช้ global
    async with valid_words_lock:  # อธิบาย: กันโหลดซ้อน
        try:  # อธิบาย: กันไฟล์ไม่มี
            with open(config.words_file, "r", encoding="utf-8") as f:  # อธิบาย: อ่านไฟล์
                words = [line.strip().lower() for line in f if line.strip()]  # อธิบาย: normalize
            VALID_WORDS = set(words)  # อธิบาย: set lookup เร็ว
            print(f"Loaded {len(VALID_WORDS)} valid words")  # อธิบาย: log
        except FileNotFoundError:  # อธิบาย: ถ้าไม่มีไฟล์
            VALID_WORDS = set()  # อธิบาย: ว่างไว้ แล้ว fallback ไป spellchecker
            print("Warning: words file not found, using spellchecker fallback")  # อธิบาย: แจ้งเตือน


# ---------------------------
# Helpers
# ---------------------------

def get_game(channel_id: int) -> GameState:  # อธิบาย: ดึง state ตามห้อง
    if channel_id not in games:  # อธิบาย: ถ้ายังไม่มีให้สร้าง
        games[channel_id] = GameState()  # อธิบาย: init
    return games[channel_id]  # อธิบาย: คืน state


def total_players(state: GameState) -> int:  # อธิบาย: จำนวนผู้เล่นทั้งหมด
    return len(state.players) + len(state.ai_players)  # อธิบาย: human + AI


def current_player_info(state: GameState) -> Tuple[Optional[int], Optional[str]]:  # อธิบาย: (user_id, ai_name)
    tp = total_players(state)  # อธิบาย: จำนวนทั้งหมด
    if tp == 0:  # อธิบาย: ไม่มีผู้เล่น
        return None, None  # อธิบาย: ไม่มีใคร
    idx = state.current_idx % tp  # อธิบาย: normalize index
    if idx < len(state.players):  # อธิบาย: อยู่ในช่วง human
        return state.players[idx], None  # อธิบาย: คืน user_id
    ai_idx = idx - len(state.players)  # อธิบาย: index ในลิสต์ AI
    return None, state.ai_players[ai_idx]  # อธิบาย: คืนชื่อ AI


def peek_current_name(state: GameState) -> str:  # อธิบาย: ชื่อคนที่ถึงตาตอนนี้
    uid, ai_name = current_player_info(state)  # อธิบาย: ดึงคน/AI ปัจจุบัน
    if uid is not None:  # อธิบาย: เป็น human
        return state.player_names.get(uid, f"User {uid}")  # อธิบาย: ชื่อ
    return ai_name or "Unknown"  # อธิบาย: ชื่อ AI


def advance_turn(state: GameState):  # อธิบาย: เลื่อนเทิร์นไปคนถัดไป
    tp = total_players(state)  # อธิบาย: จำนวนทั้งหมด
    if tp <= 0:  # อธิบาย: กันหารศูนย์
        state.current_idx = 0  # อธิบาย: รีเซ็ต
        return  # อธิบาย: จบ
    state.current_idx = (state.current_idx + 1) % tp  # อธิบาย: เลื่อน index


def normalize_word(word: str) -> str:  # อธิบาย: normalize คำ
    return word.strip().lower()  # อธิบาย: strip + lower


def is_valid_word_basic(word: str) -> bool:  # อธิบาย: ตรวจรูปแบบคำ
    return word.isalpha() and 3 <= len(word) <= 15  # อธิบาย: ตัวอักษรล้วน และยาว 3-15 ตรงกับ AI


async def is_valid_english_word(word: str) -> bool:  # อธิบาย: ตรวจคำอังกฤษ
    if VALID_WORDS and word in VALID_WORDS:  # อธิบาย: ถ้ามี wordlist และพบ
        return True  # อธิบาย: ผ่าน
    return False  # อธิบาย: ไม่ใช้ spell fallback เพื่อความเข้ม


def create_progress_bar(current: int, total: int, length: int = 10) -> str:  # อธิบาย: สร้าง progress bar
    if total <= 0:  # อธิบาย: กันหารศูนย์
        return "▰" * length  # อธิบาย: เต็ม
    filled = int((current / total) * length)  # อธิบาย: จำนวนช่องเต็ม
    empty = max(0, length - filled)  # อธิบาย: จำนวนช่องว่าง
    return "▰" * filled + "▱" * empty  # อธิบาย: คืน bar


def build_turn_text(state: GameState, name: str, remaining: int) -> str:  # อธิบาย: สร้างข้อความเทิร์นแบบ deterministic
    bar = create_progress_bar(remaining, state.turn_seconds, 10)  # อธิบาย: progress bar
    if not state.word_chain:  # อธิบาย: ยังไม่มีคำเริ่ม
        return f"🎮 It's {name}'s turn! Start with any English word.\n{bar} ({remaining}s)"  # อธิบาย: ข้อความเริ่ม
    last_letter = state.word_chain[-1][-1]  # อธิบาย: ตัวท้ายคำล่าสุด
    return f"🎮 It's {name}'s turn! Word must start with '{last_letter}'.\n{bar} ({remaining}s)"  # อธิบาย: ข้อความต่อคำ


def sanitize_ai_key(ai_name: str) -> str:  # อธิบาย: ทำชื่อ AI ให้ปลอดภัยเป็น key
    safe = (ai_name or "AI").strip().lower()  # อธิบาย: trim + lower
    safe = safe.replace(" ", "_")  # อธิบาย: แทน space กัน key แปลก
    return f"ai_{safe}"  # อธิบาย: ใส่ prefix


# ---------------------------
# Turn timer (safe cancel + token)
# ---------------------------

async def cancel_turn_timer_async(state: GameState):  # อธิบาย: ยกเลิก timer แบบปลอดภัย
    current = asyncio.current_task()  # อธิบาย: task ที่กำลังรัน
    t = state.turn_task  # อธิบาย: task เดิม
    if t and not t.done() and t is not current:  # อธิบาย: cancel ได้เมื่อไม่ใช่ตัวเอง
        t.cancel()  # อธิบาย: cancel
        try:
            await t  # อธิบาย: รอให้จบจริง (กัน ghost task)
        except asyncio.CancelledError:
            pass  # อธิบาย: cancel สำเร็จ
        except Exception:
            pass  # อธิบาย: กัน error อื่น
    state.turn_task = None  # อธิบาย: เคลียร์ตัวชี้


async def send_turn_prompt(channel: discord.abc.Messageable, state: GameState):  # อธิบาย: ส่ง prompt เทิร์น
    state.turn_message = None  # อธิบาย: เคลียร์ก่อนส่งใหม่ กัน edit ข้อความผิด
    uid, ai_name = current_player_info(state)  # อธิบาย: ดึงคนที่ถึงตา
    if uid is None and ai_name is None:  # อธิบาย: ไม่มีผู้เล่น
        await channel.send("No players joined yet! Use !join or !add_ai", allowed_mentions=allowed_mentions_none)  # อธิบาย: แจ้ง
        return None  # อธิบาย: จบ

    name = state.player_names.get(uid, f"User {uid}") if uid is not None else (ai_name or "Unknown")  # อธิบาย: ชื่อผู้เล่น
    name = discord.utils.escape_markdown(name)  # อธิบาย: escape markdown/mentions
    text = build_turn_text(state, name, state.turn_seconds)  # อธิบาย: ข้อความเริ่มต้น
    msg = await channel.send(text, allowed_mentions=allowed_mentions_none)  # อธิบาย: ส่งข้อความ
    state.turn_message = msg  # อธิบาย: เก็บไว้แก้ progress
    return msg  # อธิบาย: คืน message


async def start_turn_timer(channel: discord.abc.Messageable, state: GameState):  # อธิบาย: เริ่ม timer เทิร์น
    await cancel_turn_timer_async(state)  # อธิบาย: ยกเลิกของเก่าก่อน

    # อธิบาย: token เพิ่มทุกครั้งที่เริ่มเทิร์น เพื่อกัน task/AI เก่าทำงานทับ
    state.turn_token += 1  # อธิบาย: bump token
    my_token = state.turn_token  # อธิบาย: token ของ task นี้

    async def timer():  # อธิบาย: task นับถอยหลัง
        try:
            tp = total_players(state)  # อธิบาย: จำนวนผู้เล่น
            if not state.active or tp == 0:  # อธิบาย: เกมปิดหรือไม่มีคน
                return  # อธิบาย: จบ

            uid, ai_name = current_player_info(state)  # อธิบาย: คนที่ถึงตาตอนเริ่ม timer

            # --- AI turn ---
            if ai_name is not None:  # อธิบาย: ถ้าเป็นตา AI
                await asyncio.sleep(getattr(config, "ai_think_delay", 1.0))  # อธิบาย: หน่วงให้ prompt แสดงก่อน

                # อธิบาย: ถ้า token ไม่ตรง แปลว่าเทิร์นเปลี่ยนแล้ว -> หยุดทันที
                if my_token != state.turn_token or not state.active:  # อธิบาย: ตรวจ token
                    return  # อธิบาย: จบ

                word = await generate_ai_word_async(state, ai_name)  # อธิบาย: ขอคำจาก AI แบบไม่ค้างบอท

                # อธิบาย: token ตรวจซ้ำกัน race condition
                if my_token != state.turn_token or not state.active:  # อธิบาย: ตรวจ token
                    return  # อธิบาย: จบ

                if word:  # อธิบาย: ถ้าได้คำ
                    await process_word_submission(channel, word, state, player_id=None, ai_player=ai_name)  # อธิบาย: ส่งเข้าระบบ
                    return  # อธิบาย: จบ (process_word_submission จะเปิดเทิร์นใหม่)
                # อธิบาย: AI คิดไม่ออก -> ข้าม
                advance_turn(state)  # อธิบาย: ข้ามไปคนถัดไป
                await channel.send(f"🤖 {ai_name} couldn't think of a word! Skipping...", allowed_mentions=allowed_mentions_none)  # อธิบาย: แจ้ง
                await send_turn_prompt(channel, state)  # อธิบาย: prompt เทิร์นใหม่
                await start_turn_timer(channel, state)  # อธิบาย: เริ่ม timer ใหม่
                return  # อธิบาย: จบ

            # --- Human turn countdown ---
            remaining = state.turn_seconds  # อธิบาย: เวลาที่เหลือ
            update_interval = 2  # อธิบาย: อัปเดตทุก 2 วินาที (ลดโอกาสโดน rate-limit)

            while remaining > 0:  # อธิบาย: นับถอยหลัง
                # อธิบาย: ถ้า token ไม่ตรง แปลว่าเทิร์นถูกเปลี่ยนแล้ว -> หยุด
                if my_token != state.turn_token or not state.active:  # อธิบาย: ตรวจ token
                    return  # อธิบาย: จบ

                tp2 = total_players(state)  # อธิบาย: จำนวนผู้เล่นปัจจุบัน (อาจเปลี่ยนได้)
                if tp2 == 0:  # อธิบาย: ไม่มีคนแล้ว
                    return  # อธิบาย: จบ

                # อธิบาย: อัปเดตข้อความ progress
                if state.turn_message and remaining < state.turn_seconds:  # อธิบาย: ไม่ใช่รอบแรก
                    name = peek_current_name(state)  # อธิบาย: ชื่อคนที่ถึงตา ณ ตอนนี้
                    try:
                        await state.turn_message.edit(content=build_turn_text(state, name, remaining))  # อธิบาย: แก้ไขข้อความ
                    except discord.errors.HTTPException:
                        pass  # อธิบาย: ถ้าแก้ไม่ได้ก็ข้าม

                sleep_time = min(update_interval, remaining)  # อธิบาย: กันเหลือ < interval
                await asyncio.sleep(sleep_time)  # อธิบาย: รอ
                remaining -= sleep_time  # อธิบาย: ลดเวลาที่เหลือ

            # --- Time's up -> skip human ---
            # อธิบาย: ถ้า token ไม่ตรง แปลว่าเทิร์นเปลี่ยนแล้ว -> ไม่ต้อง skip
            if my_token != state.turn_token or not state.active:  # อธิบาย: ตรวจ token
                return  # อธิบาย: จบ

            tp3 = total_players(state)  # อธิบาย: จำนวนผู้เล่นอีกครั้ง
            if tp3 == 0:  # อธิบาย: ไม่มีคน
                return  # อธิบาย: จบ

            # อธิบาย: รีเซ็ต streak/combo เมื่อโดนข้าม
            if uid is not None:  # อธิบาย: เป็นคน
                state.player_streaks[uid] = 0  # อธิบาย: รีเซ็ต streak คนนี้
            state.combo_count = 0  # อธิบาย: รีเซ็ต combo ห้อง

            name = state.player_names.get(uid, f"User {uid}") if uid is not None else "Unknown"  # อธิบาย: ชื่อคนที่โดนข้าม
            advance_turn(state)  # อธิบาย: เลื่อนไปคนถัดไป
            await channel.send(f"⏰ Time's up! Skipping {name}.", allowed_mentions=allowed_mentions_none)  # อธิบาย: แจ้ง
            await send_turn_prompt(channel, state)  # อธิบาย: ส่ง prompt ใหม่
            await start_turn_timer(channel, state)  # อธิบาย: เริ่ม timer ใหม่

        except asyncio.CancelledError:
            return  # อธิบาย: ถูก cancel ก็จบ
        except Exception as e:
            print(f"Timer error: {e}")  # อธิบาย: log error
            return  # อธิบาย: จบ

    state.turn_task = asyncio.create_task(timer())  # อธิบาย: สร้าง task ใหม่


# ---------------------------
# AI (OpenRouter via OpenAI SDK) - sync + to_thread
# ---------------------------

def generate_ai_word(state: GameState, ai_name: str) -> Optional[str]:  # อธิบาย: สร้างคำ AI (sync) กับ retry
    max_retries = 3  # อธิบาย: ลองใหม่ได้ 3 ครั้ง
    for attempt in range(max_retries):  # อธิบาย: ลูป retry
        try:
            if not OPENROUTER_API_KEY:  # อธิบาย: ถ้าไม่มี key
                print("AI error: OPENROUTER_API_KEY is not set")  # อธิบาย: log
                return None  # อธิบาย: จบ

            last_letter = state.word_chain[-1][-1] if state.word_chain else None  # อธิบาย: ตัวท้ายคำล่าสุด
            used_words_preview = state.word_chain[-20:] if state.word_chain else []  # อธิบาย: เอาท้าย ๆ 20 คำ (ตามลำดับเวลา)
            used_words_str = ", ".join(used_words_preview)  # อธิบาย: ทำเป็นสตริง

            prompt = "You are playing a Word Chain game.\n"  # อธิบาย: ตั้งบทบาท
            if last_letter:  # อธิบาย: ถ้ามีเงื่อนไขตัวอักษร
                prompt += f"Your word must start with '{last_letter}'.\n"  # อธิบาย: บอกกติกา
            else:
                prompt += "You can start with any word.\n"  # อธิบาย: เริ่มได้ทุกคำ
            prompt += f"Used words: {used_words_str}\n"  # อธิบาย: บอกคำที่ใช้แล้ว
            prompt += "Return ONE valid English word (3-15 letters), letters only, not used yet. Reply with only the word."  # อธิบาย: ข้อกำหนด

            resp = openai_client.chat.completions.create(  # อธิบาย: เรียกโมเดล
                model=config.ai_model,  # อธิบาย: โมเดลจาก config
                messages=[{"role": "user", "content": prompt}],  # อธิบาย: ข้อความ user
                max_tokens=config.ai_max_tokens,  # อธิบาย: จำกัด token
                temperature=config.ai_temperature,  # อธิบาย: ความสุ่ม
            )

            word = (resp.choices[0].message.content or "").strip().lower()  # อธิบาย: ดึงคำตอบ
            if not word:  # อธิบาย: กันคำตอบว่าง
                continue  # อธิบาย: ลองใหม่

            # อธิบาย: ทำความสะอาดคำตอบเผื่อมีเครื่องหมาย / ข้อความอื่น
            word = "".join(ch for ch in word if ch.isalpha())  # อธิบาย: เอาเฉพาะตัวอักษร

            if not is_valid_word_basic(word):  # อธิบาย: ตรวจรูปแบบ
                continue  # อธิบาย: ลองใหม่

            if word in state.used_words:  # อธิบาย: กันซ้ำ
                continue  # อธิบาย: ลองใหม่

            if last_letter and not word.startswith(last_letter):  # อธิบาย: ต้องเริ่มด้วยตัวท้ายเดิม
                continue  # อธิบาย: ลองใหม่

            return word  # อธิบาย: ผ่านทั้งหมด
        except Exception as e:
            print(f"AI word generation error (attempt {attempt + 1}): {e}")  # อธิบาย: log
            if attempt < max_retries - 1:  # อธิบาย: ถ้ายังไม่ครบ retry
                continue  # อธิบาย: ลองใหม่
    return None  # อธิบาย: ยอมแพ้หลัง retry หมด


async def generate_ai_word_async(state: GameState, ai_name: str) -> Optional[str]:  # อธิบาย: async wrapper
    return await asyncio.to_thread(generate_ai_word, state, ai_name)  # อธิบาย: ย้ายงาน sync ไป thread


# ---------------------------
# Core submission logic
# ---------------------------

async def process_word_submission(
    channel: discord.abc.Messageable,  # อธิบาย: ช่องที่จะส่งข้อความ
    word: str,  # อธิบาย: คำที่ส่งมา
    state: GameState,  # อธิบาย: state ห้อง
    player_id: Optional[int] = None,  # อธิบาย: user_id (ถ้าเป็นคน)
    ai_player: Optional[str] = None,  # อธิบาย: ai_name (ถ้าเป็น AI)
):
    word = normalize_word(word)  # อธิบาย: normalize

    # --- Validate basic ---
    if not is_valid_word_basic(word):  # อธิบาย: ตรวจรูปแบบคำ
        if ai_player:
            await channel.send(f"🤖 {ai_player} submitted invalid word format.", allowed_mentions=allowed_mentions_none)  # อธิบาย: แจ้ง
        else:
            await channel.send("Please enter a valid word (letters only, at least 2).", allowed_mentions=allowed_mentions_none)  # อธิบาย: แจ้ง
        return  # อธิบาย: จบ

    # --- Validate English ---
    if not await is_valid_english_word(word):  # อธิบาย: ตรวจคำอังกฤษ
        if ai_player:
            await channel.send(f"🤖 {ai_player} submitted invalid English word.", allowed_mentions=allowed_mentions_none)  # อธิบาย: แจ้ง
        else:
            await channel.send("Not a valid English word (dictionary check failed).", allowed_mentions=allowed_mentions_none)  # อธิบาย: แจ้ง
        return  # อธิบาย: จบ

    # --- Duplicate ---
    if word in state.used_words:  # อธิบาย: คำซ้ำ
        if ai_player:
            await channel.send(f"🤖 {ai_player} submitted already used word.", allowed_mentions=allowed_mentions_none)  # อธิบาย: แจ้ง
        else:
            await channel.send("Word already used!", allowed_mentions=allowed_mentions_none)  # อธิบาย: แจ้ง
        return  # อธิบาย: จบ

    # --- Chain rule ---
    if state.word_chain:  # อธิบาย: ถ้ามีคำก่อนหน้า
        last_word = state.word_chain[-1]  # อธิบาย: คำล่าสุด
        if word[0] != last_word[-1]:  # อธิบาย: ตัวแรกไม่ตรงตัวท้าย
            if ai_player:
                await channel.send(f"🤖 {ai_player} submitted word that doesn't chain properly.", allowed_mentions=allowed_mentions_none)  # อธิบาย: แจ้ง
            else:
                await channel.send(f"Word must start with '{last_word[-1]}'.", allowed_mentions=allowed_mentions_none)  # อธิบาย: แจ้ง
            return  # อธิบาย: จบ

    # --- Stop timer for this turn (safe) ---
    await cancel_turn_timer_async(state)  # อธิบาย: ยกเลิก timer รอบนี้ (ปลอดภัย)

    # --- Apply word ---
    state.word_chain.append(word)  # อธิบาย: เพิ่มใน chain
    state.used_words.add(word)  # อธิบาย: mark used

    # --- Scoring ---
    base_points = 1  # อธิบาย: คะแนนพื้นฐาน
    bonus_points = 0  # อธิบาย: คะแนนโบนัส

    if len(word) >= config.long_word_len:  # อธิบาย: โบนัสคำยาว
        bonus_points += config.long_word_bonus  # อธิบาย: บวกโบนัส

    if ai_player:  # อธิบาย: ถ้าเป็น AI
        key = sanitize_ai_key(ai_player)  # อธิบาย: key ปลอดภัย
        ai_display_names[key] = ai_player  # อธิบาย: เก็บ display name
        total_points = base_points + bonus_points  # อธิบาย: รวมคะแนน
        async with scores_lock:  # อธิบาย: lock เพื่อกัน lost update
            scores_data[key] = scores_data.get(key, 0) + total_points  # อธิบาย: เพิ่มคะแนน AI
            await save_scores_async()  # อธิบาย: เซฟ

        advance_turn(state)  # อธิบาย: เลื่อนไปคนถัดไป
        next_name = peek_current_name(state)  # อธิบาย: ชื่อคนถัดไปจริง
        next_name = discord.utils.escape_markdown(next_name)  # อธิบาย: escape

        await channel.send(  # อธิบาย: ส่งผลลัพธ์
            f"🤖 {discord.utils.escape_markdown(ai_player)} played '{word}' (+{total_points} pts). "
            f"Next starts with '{word[-1]}'. Next: {next_name}",
            allowed_mentions=allowed_mentions_none,
        )

    else:  # อธิบาย: ถ้าเป็น human
        if player_id is None:  # อธิบาย: กันกรณีข้อมูลไม่ครบ
            return  # อธิบาย: จบ

        streak = state.player_streaks.get(player_id, 0) + 1  # อธิบาย: เพิ่ม streak
        state.player_streaks[player_id] = streak  # อธิบาย: เก็บ streak
        if streak >= config.streak_min:  # อธิบาย: ถึงเกณฑ์ streak
            bonus_points += config.streak_bonus  # อธิบาย: บวกโบนัส

        state.combo_count += 1  # อธิบาย: เพิ่ม combo
        if config.combo_step > 0 and (state.combo_count % config.combo_step == 0):  # อธิบาย: ทุก ๆ step
            bonus_points += config.combo_bonus  # อธิบาย: บวกโบนัส

        total_points = base_points + bonus_points  # อธิบาย: รวมคะแนน
        key = str(player_id)  # อธิบาย: key ของ human
        async with scores_lock:  # อธิบาย: lock เพื่อกัน lost update
            scores_data[key] = scores_data.get(key, 0) + total_points  # อธิบาย: เพิ่มคะแนน human
            await save_scores_async()  # อธิบาย: เซฟ

        advance_turn(state)  # อธิบาย: เลื่อนไปคนถัดไป
        next_name = peek_current_name(state)  # อธิบาย: ชื่อคนถัดไปจริง
        next_name = discord.utils.escape_markdown(next_name)  # อธิบาย: escape

        bonus_text = f" (+{bonus_points} bonus)" if bonus_points > 0 else ""  # อธิบาย: ข้อความโบนัส
        await channel.send(  # อธิบาย: ส่งผลลัพธ์
            f"✅ Added '{word}' (+{total_points} pts{bonus_text}). Next starts with '{word[-1]}'. "
            f"Your total score: {scores_data[key]}. Next: {next_name}",
            allowed_mentions=allowed_mentions_none,
        )

    # --- Start next turn ---
    await send_turn_prompt(channel, state)  # อธิบาย: ส่ง prompt เทิร์นใหม่
    await start_turn_timer(channel, state)  # อธิบาย: เริ่ม timer เทิร์นใหม่


# ---------------------------
# Events
# ---------------------------

@bot.event
async def on_ready():  # อธิบาย: บอทพร้อม
    global SCORES_FILE  # อธิบาย: ใช้ scores_file global
    load_scores_sync()  # อธิบาย: โหลดคะแนน
    SCORES_FILE = config.scores_file  # อธิบาย: กำหนดไฟล์คะแนนจาก config ปัจจุบัน
    await load_valid_words_async()  # อธิบาย: โหลด wordlist

    print("Bot is ready")  # อธิบาย: log


@bot.event
async def on_message(message: discord.Message):  # อธิบาย: รับข้อความ
    if message.author == bot.user:  # อธิบาย: กัน loop
        return  # อธิบาย: จบ

    # อธิบาย: ให้ command ทำงานก่อน (รองรับ mention prefix + prefix ปัจจุบัน)
    await bot.process_commands(message)  # อธิบาย: สำคัญ

    # อธิบาย: ถ้าเป็น command (prefix หรือ mention) ให้หยุด ไม่เอาเข้าเกม
    try:
        prefixes = await bot.get_prefix(message)  # อธิบาย: ได้ list ของ prefix (รวม mention)
        if isinstance(prefixes, str):  # อธิบาย: กันกรณีเป็นสตริง
            prefixes = [prefixes]  # อธิบาย: ทำเป็น list
        if any(message.content.startswith(p) for p in prefixes):  # อธิบาย: เช็คทุก prefix
            return  # อธิบาย: จบ
    except Exception:
        # อธิบาย: fallback ถ้ามีอะไรแปลก
        if message.content.startswith(config.command_prefix):  # อธิบาย: เช็ค prefix ปกติ
            return  # อธิบาย: จบ

    state = get_game(message.channel.id)  # อธิบาย: state ห้อง
    if not state.active:  # อธิบาย: เกมไม่ active
        return  # อธิบาย: จบ

    if total_players(state) == 0:  # อธิบาย: ไม่มีผู้เล่น
        await message.channel.send("No players joined yet! Use !join or !add_ai", allowed_mentions=allowed_mentions_none)  # อธิบาย: แจ้ง
        return  # อธิบาย: จบ

    # อธิบาย: เช็คว่าเป็นตาของคนนี้หรือไม่ก่อน (สำคัญ: cooldown ห้าม block คนที่ถึงตา)
    uid, ai_name = current_player_info(state)  # อธิบาย: ดึงคนที่ถึงตา
    if uid != message.author.id:  # อธิบาย: ไม่ใช่ตาเขา
        # อธิบาย: quiet cooldown สำหรับ "not your turn" messages (กัน spam)
        now = time.monotonic()  # อธิบาย: เวลาปัจจุบัน
        last_quiet = not_your_turn_cooldowns.get(message.author.id, 0.0)  # อธิบาย: เวลาครั้งล่าสุดที่ส่งข้อความนี้
        if now - last_quiet < 5.0:  # อธิบาย: cooldown 5 วินาทีสำหรับข้อความนี้
            return  # อธิบาย: เงียบ ๆ ไม่ส่งข้อความซ้ำ
        not_your_turn_cooldowns[message.author.id] = now  # อธิบาย: อัปเดตเวลา

        name = state.player_names.get(uid, f"User {uid}") if uid is not None else (ai_name or "Unknown")  # อธิบาย: ชื่อคนที่ถึงตา
        name = discord.utils.escape_markdown(name)  # อธิบาย: escape
        await message.channel.send(f"🚫 Not your turn. It's {name}'s turn!", allowed_mentions=allowed_mentions_none)  # อธิบาย: แจ้ง
        return  # อธิบาย: จบ

    # อธิบาย: ถึงตาแล้ว ไม่ใช้ cooldown เพื่อไม่ block การเล่น
    await process_word_submission(message.channel, message.content, state, player_id=message.author.id, ai_player=None)  # อธิบาย: ประมวลผลคำ


@bot.event
async def on_disconnect():  # อธิบาย: หลุดการเชื่อมต่อ
    # อธิบาย: ไม่ต้องปิด session เพราะ discord อาจ reconnect เอง
    pass  # อธิบาย: เว้นไว้


@bot.event
async def on_error(event, *args, **kwargs):  # อธิบาย: log error ระดับ event
    print(f"Error in event: {event}")  # อธิบาย: log ชื่อ event


# ---------------------------
# Commands
# ---------------------------

@bot.command()
async def start_game(ctx):  # อธิบาย: เริ่มเกม
    state = get_game(ctx.channel.id)  # อธิบาย: state ห้อง
    state.active = True  # อธิบาย: เปิดเกม

    # อธิบาย: reset เกมในห้อง
    state.word_chain = []  # อธิบาย: รีเซ็ตคำ
    state.used_words = set()  # อธิบาย: รีเซ็ต used
    state.player_streaks = {}  # อธิบาย: รีเซ็ต streak
    state.combo_count = 0  # อธิบาย: รีเซ็ต combo
    state.turn_seconds = config.turn_seconds  # อธิบาย: ใช้ค่าจาก config ล่าสุด
    state.current_idx = 0  # อธิบาย: เริ่มที่คนแรก
    state.turn_token += 1  # อธิบาย: bump token เพื่อกัน task เก่าทับ

    await cancel_turn_timer_async(state)  # อธิบาย: ยกเลิก timer เก่า

    tp = total_players(state)  # อธิบาย: จำนวนผู้เล่นทั้งหมด
    if tp == 0:  # อธิบาย: ไม่มีผู้เล่น
        await ctx.send("🎮 Game started, but no players yet. Use !join or !add_ai", allowed_mentions=allowed_mentions_none)  # อธิบาย: แจ้ง
        return  # อธิบาย: จบ

    await ctx.send("🎮 Word chain started in this channel! Use !join / !add_ai then play in turn.", allowed_mentions=allowed_mentions_none)  # อธิบาย: แจ้งเริ่ม
    await send_turn_prompt(ctx.channel, state)  # อธิบาย: ส่ง prompt
    await start_turn_timer(ctx.channel, state)  # อธิบาย: เริ่ม timer


@bot.command()
@commands.has_permissions(manage_guild=True)
async def end_game(ctx):  # อธิบาย: จบเกม (admin only)
    state = get_game(ctx.channel.id)  # อธิบาย: state ห้อง
    state.active = False  # อธิบาย: ปิดเกม
    state.turn_token += 1  # อธิบาย: bump token เพื่อให้ task เก่าหยุดเอง
    await cancel_turn_timer_async(state)  # อธิบาย: ยกเลิก timer
    state.turn_message = None  # อธิบาย: เคลียร์ message อ้างอิง
    await ctx.send("🛑 Game ended in this channel.", allowed_mentions=allowed_mentions_none)  # อธิบาย: แจ้งจบ


@bot.command()
async def join(ctx):  # อธิบาย: เข้าร่วมเกม
    state = get_game(ctx.channel.id)  # อธิบาย: state ห้อง
    uid = ctx.author.id  # อธิบาย: id ผู้ใช้

    if uid in state.players:  # อธิบาย: กัน join ซ้ำ
        await ctx.send("You're already in this channel's game!", allowed_mentions=allowed_mentions_none)  # อธิบาย: แจ้ง
        return  # อธิบาย: จบ

    if uid in state.joining_users:  # อธิบาย: กัน join ซ้อน
        return  # อธิบาย: จบ

    state.joining_users.add(uid)  # อธิบาย: mark กำลัง join
    try:
        state.players.append(uid)  # อธิบาย: เพิ่มผู้เล่น
        state.player_names[uid] = ctx.author.display_name  # อธิบาย: เก็บชื่อ
        await ctx.send(f"➕ {ctx.author.display_name} joined this channel's game!", allowed_mentions=allowed_mentions_none)  # อธิบาย: แจ้ง
    finally:
        state.joining_users.discard(uid)  # อธิบาย: unmark

    # อธิบาย: ถ้าเกม active และผู้เล่นคนแรก -> เริ่ม prompt/timer
    if state.active and total_players(state) == 1:  # อธิบาย: คนแรกในห้อง
        state.current_idx = 0  # อธิบาย: ให้เริ่มที่คนแรก
        await send_turn_prompt(ctx.channel, state)  # อธิบาย: prompt
        await start_turn_timer(ctx.channel, state)  # อธิบาย: timer


@bot.command()
async def leave(ctx):  # อธิบาย: ออกจากเกม
    state = get_game(ctx.channel.id)  # อธิบาย: state ห้อง
    uid = ctx.author.id  # อธิบาย: id ผู้ใช้

    if uid not in state.players:  # อธิบาย: ไม่ได้อยู่ในเกม
        await ctx.send("You're not in this channel's game.", allowed_mentions=allowed_mentions_none)  # อธิบาย: แจ้ง
        return  # อธิบาย: จบ

    idx = state.players.index(uid)  # อธิบาย: index ในลิสต์ human (ฐาน global ก็เท่ากันเพราะ human อยู่ต้น)
    removed_global_idx = idx  # อธิบาย: global index ในลิสต์รวม (human อยู่ช่วงแรก)

    state.players.remove(uid)  # อธิบาย: ลบออก
    state.player_names.pop(uid, None)  # อธิบาย: ลบชื่อที่เก็บ
    state.player_streaks.pop(uid, None)  # อธิบาย: ลบ streak

    tp = total_players(state)  # อธิบาย: จำนวนผู้เล่นหลังลบ
    if tp > 0:  # อธิบาย: ยังมีผู้เล่น
        # อธิบาย: ถ้าคนที่ออกอยู่ก่อน current_idx -> ลด current_idx ลง
        if removed_global_idx < state.current_idx:  # อธิบาย: เทียบฐานเดียวกันแล้ว
            state.current_idx -= 1  # อธิบาย: เลื่อนกลับ
        state.current_idx %= tp  # อธิบาย: mod ด้วยจำนวนรวม (รวม AI)
    else:
        state.current_idx = 0  # อธิบาย: รีเซ็ต
        state.turn_token += 1  # อธิบาย: bump token ให้ task เก่าหยุด
        await cancel_turn_timer_async(state)  # อธิบาย: ไม่มีคนก็หยุด timer

    await ctx.send(f"➖ {ctx.author.display_name} left this channel's game!", allowed_mentions=allowed_mentions_none)  # อธิบาย: แจ้ง

    # อธิบาย: ถ้าเกม active และยังมีคน -> รีสตาร์ท prompt/timer (กันค้างเทิร์น)
    if state.active and tp > 0:  # อธิบาย: ยังเล่นได้
        state.turn_token += 1  # อธิบาย: bump token เพื่อกัน timer เดิมทับ
        await cancel_turn_timer_async(state)  # อธิบาย: ยกเลิก timer เดิม (ถ้ามี)
        await send_turn_prompt(ctx.channel, state)  # อธิบาย: prompt ใหม่
        await start_turn_timer(ctx.channel, state)  # อธิบาย: timer ใหม่


@bot.command()
async def add_ai(ctx, ai_name: str = "AI"):  # อธิบาย: เพิ่ม AI
    state = get_game(ctx.channel.id)  # อธิบาย: state ห้อง

    if ai_name in state.ai_players:  # อธิบาย: กันซ้ำ
        await ctx.send(f"🤖 {ai_name} is already in this channel's game!", allowed_mentions=allowed_mentions_none)  # อธิบาย: แจ้ง
        return  # อธิบาย: จบ

    if len(state.ai_players) >= config.max_ai_players:  # อธิบาย: จำกัดจำนวน AI
        await ctx.send(f"🤖 Maximum {config.max_ai_players} AI players allowed!", allowed_mentions=allowed_mentions_none)  # อธิบาย: แจ้ง
        return  # อธิบาย: จบ

    if ai_name in state.adding_ais:  # อธิบาย: กัน add_ai ซ้อน
        return  # อธิบาย: จบ

    state.adding_ais.add(ai_name)  # อธิบาย: mark
    try:
        state.ai_players.append(ai_name)  # อธิบาย: เพิ่ม AI
        await ctx.send(f"🤖 {ai_name} joined this channel's game!", allowed_mentions=allowed_mentions_none)  # อธิบาย: แจ้ง
    finally:
        state.adding_ais.discard(ai_name)  # อธิบาย: unmark

    # อธิบาย: ถ้าเกม active และเป็นผู้เล่นคนแรก -> เริ่ม prompt/timer
    if state.active and total_players(state) == 1:  # อธิบาย: คนแรกในห้อง
        state.current_idx = 0  # อธิบาย: เริ่มที่ index 0
        await send_turn_prompt(ctx.channel, state)  # อธิบาย: prompt
        await start_turn_timer(ctx.channel, state)  # อธิบาย: timer

    # อธิบาย: ถ้าเกม active และเทิร์นกำลังเดินอยู่ ให้รีสตาร์ท prompt/timer เพื่อ sync รายชื่อ
    if state.active and total_players(state) > 1 and state.turn_task:  # อธิบาย: มีเกมและมี timer อยู่
        state.turn_token += 1  # อธิบาย: bump token กัน task เดิม
        await cancel_turn_timer_async(state)  # อธิบาย: ยกเลิก task เดิม
        await send_turn_prompt(ctx.channel, state)  # อธิบาย: prompt ใหม่
        await start_turn_timer(ctx.channel, state)  # อธิบาย: timer ใหม่


@bot.command()
async def remove_ai(ctx, ai_name: str):  # อธิบาย: ลบ AI
    state = get_game(ctx.channel.id)  # อธิบาย: state ห้อง

    if ai_name not in state.ai_players:  # อธิบาย: ไม่มี AI นี้
        await ctx.send(f"🤖 {ai_name} is not in this channel's game.", allowed_mentions=allowed_mentions_none)  # อธิบาย: แจ้ง
        return  # อธิบาย: จบ

    ai_idx = state.ai_players.index(ai_name)  # อธิบาย: index ในลิสต์ AI
    removed_global_idx = len(state.players) + ai_idx  # อธิบาย: global index ของ AI ในลิสต์รวม "ก่อนลบ"

    state.ai_players.remove(ai_name)  # อธิบาย: ลบออก

    tp = total_players(state)  # อธิบาย: จำนวนผู้เล่นหลังลบ
    if tp > 0:  # อธิบาย: ยังมีผู้เล่น
        if removed_global_idx < state.current_idx:  # อธิบาย: ถ้า AI ที่ออกอยู่ก่อนเทิร์นปัจจุบัน
            state.current_idx -= 1  # อธิบาย: เลื่อนกลับ
        state.current_idx %= tp  # อธิบาย: mod ด้วยทั้งหมด
    else:
        state.current_idx = 0  # อธิบาย: รีเซ็ต
        state.turn_token += 1  # อธิบาย: bump token ให้ task เก่าหยุด
        await cancel_turn_timer_async(state)  # อธิบาย: ไม่มีคนก็หยุด timer

    await ctx.send(f"🤖 {ai_name} left this channel's game!", allowed_mentions=allowed_mentions_none)  # อธิบาย: แจ้ง

    if state.active and tp > 0:  # อธิบาย: ถ้ายังเล่นได้
        state.turn_token += 1  # อธิบาย: bump token เพื่อกัน timer เดิมทับ
        await cancel_turn_timer_async(state)  # อธิบาย: ยกเลิก timer เดิม
        await send_turn_prompt(ctx.channel, state)  # อธิบาย: prompt ใหม่
        await start_turn_timer(ctx.channel, state)  # อธิบาย: timer ใหม่


@bot.command()
@commands.has_permissions(manage_guild=True)
async def settime(ctx, seconds: int):  # อธิบาย: ตั้งเวลาเทิร์นต่อห้อง (admin only)
    state = get_game(ctx.channel.id)  # อธิบาย: state ห้อง
    seconds = max(config.min_turn_time, min(seconds, config.max_turn_time))  # อธิบาย: จำกัดช่วง
    state.turn_seconds = seconds  # อธิบาย: ตั้งค่า
    await ctx.send(f"⏳ Turn time set to {seconds}s for this channel.", allowed_mentions=allowed_mentions_none)  # อธิบาย: แจ้ง


@bot.command()
async def status(ctx):  # อธิบาย: ดูสถานะเกม
    state = get_game(ctx.channel.id)  # อธิบาย: state ห้อง

    if not state.active:  # อธิบาย: เกมไม่ active
        await ctx.send("ℹ️ No active game in this channel. Use !start_game", allowed_mentions=allowed_mentions_none)  # อธิบาย: แจ้ง
        return  # อธิบาย: จบ

    if total_players(state) == 0:  # อธิบาย: ไม่มีผู้เล่น
        await ctx.send("ℹ️ Game is active but no players joined. Use !join or !add_ai", allowed_mentions=allowed_mentions_none)  # อธิบาย: แจ้ง
        return  # อธิบาย: จบ

    turn_name = peek_current_name(state)  # อธิบาย: ชื่อคนที่ถึงตา
    last = state.word_chain[-1] if state.word_chain else "(none)"  # อธิบาย: คำล่าสุด

    await ctx.send(  # อธิบาย: สรุปสถานะ
        f"📣 Active: {state.active}\n"
        f"👥 Humans: {len(state.players)} | 🤖 AIs: {len(state.ai_players)}\n"
        f"🧠 Last word: {last}\n"
        f"🎯 Current turn: {turn_name}\n"
        f"⏳ Turn time: {state.turn_seconds}s\n"
        f"🔗 Chain length: {len(state.word_chain)}",
        allowed_mentions=allowed_mentions_none,
    )


@bot.command(name="scores")
async def leaderboard(ctx):  # อธิบาย: top 10 คะแนนรวม (รองรับ AI)
    if not scores_data:  # อธิบาย: ยังไม่มีคะแนน
        await ctx.send("No scores yet!", allowed_mentions=allowed_mentions_none)  # อธิบาย: แจ้ง
        return  # อธิบาย: จบ

    sorted_scores = sorted(scores_data.items(), key=lambda x: x[1], reverse=True)  # อธิบาย: เรียงคะแนน
    text = "🏆 **Leaderboard (Global)** 🏆\n"  # อธิบาย: หัวข้อ

    rank = 1  # อธิบาย: ลำดับ
    for user_key, score in sorted_scores:  # อธิบาย: วนทุกคน
        if rank > 10:  # อธิบาย: top 10
            break  # อธิบาย: จบ

        if str(user_key).startswith("ai_"):  # อธิบาย: ถ้าเป็น AI
            display_name = ai_display_names.get(user_key, str(user_key).replace("ai_", ""))  # อธิบาย: ใช้ display name ถ้ามี
            name = f"🤖 {display_name}"  # อธิบาย: ชื่อ AI
        else:
            try:
                u = bot.get_user(int(user_key))  # อธิบาย: ดึง user จาก cache
                name = u.display_name if u else f"User {user_key}"  # อธิบาย: fallback
            except Exception:
                name = f"User {user_key}"  # อธิบาย: กันข้อมูลแปลก

        text += f"{rank}. {name}: {score}\n"  # อธิบาย: ต่อบรรทัด
        rank += 1  # อธิบาย: เพิ่มอันดับ

    await ctx.send(text, allowed_mentions=allowed_mentions_none)  # อธิบาย: ส่ง


@bot.command()
async def myscore(ctx):  # อธิบาย: ดูคะแนนตัวเอง
    key = str(ctx.author.id)  # อธิบาย: key ของ user
    score = scores_data.get(key, 0)  # อธิบาย: คะแนน
    await ctx.send(f"📌 {ctx.author.display_name}, your total score is {score}.", allowed_mentions=allowed_mentions_none)  # อธิบาย: ส่ง


@bot.command()
@commands.has_permissions(manage_guild=True)
async def reload_config(ctx):  # อธิบาย: โหลด config ใหม่ (admin only)
    try:
        from config import GameConfig  # อธิบาย: import ตัวคลาส (ต้องมีในโปรเจกต์น้อง)
        global config, SCORES_FILE  # อธิบาย: ใช้ config และ scores_file global
        config = GameConfig()  # อธิบาย: โหลดใหม่จากไฟล์ของน้องเอง
        SCORES_FILE = config.scores_file  # อธิบาย: อัปเดตไฟล์คะแนนตาม config ใหม่

        if config.validate():  # อธิบาย: ตรวจความถูกต้อง
            await load_valid_words_async()  # อธิบาย: reload words เผื่อเปลี่ยนไฟล์
            await ctx.send("✅ Configuration reloaded successfully!", allowed_mentions=allowed_mentions_none)  # อธิบาย: แจ้งสำเร็จ
            await ctx.send(
                f"📋 Prefix: {config.command_prefix} | Turn: {config.turn_seconds}s | AI Model: {config.ai_model}",
                allowed_mentions=allowed_mentions_none,
            )  # อธิบาย: สรุป
        else:
            await ctx.send("❌ Configuration validation failed! Check your config.json values.", allowed_mentions=allowed_mentions_none)  # อธิบาย: แจ้ง
    except Exception as e:
        await ctx.send(f"❌ Error reloading configuration: {e}", allowed_mentions=allowed_mentions_none)  # อธิบาย: แจ้ง error


@bot.command()
async def hint(ctx):  # อธิบาย: ขอคำใบ้
    state = get_game(ctx.channel.id)  # อธิบาย: state ห้อง
    if not state.active:  # อธิบาย: เกมไม่เริ่ม
        await ctx.send("No active game in this channel.", allowed_mentions=allowed_mentions_none)  # อธิบาย: แจ้ง
        return  # อธิบาย: จบ

    if not state.word_chain:  # อธิบาย: ยังไม่มีคำ
        await ctx.send("No words yet. Start with any word!", allowed_mentions=allowed_mentions_none)  # อธิบาย: แจ้ง
        return  # อธิบาย: จบ

    if http_session is None or http_session.closed:  # อธิบาย: session ยังไม่พร้อม
        await ctx.send("HTTP session not ready.", allowed_mentions=allowed_mentions_none)  # อธิบาย: แจ้ง
        return  # อธิบาย: จบ

    last_letter = state.word_chain[-1][-1]  # อธิบาย: ตัวท้ายคำล่าสุด
    url = f"https://api.datamuse.com/words?sp={last_letter}*&max=20"  # อธิบาย: คำขึ้นต้นด้วย last_letter
    try:
        async with http_session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as r:  # อธิบาย: ยิง request
            data = await r.json()  # อธิบาย: อ่าน json
        suggestions = [w["word"] for w in data if w.get("word") and w["word"] not in state.used_words and len(w["word"]) > 2]  # อธิบาย: กรอง
        if suggestions:
            await ctx.send(f"💡 Hints for '{last_letter}': {', '.join(suggestions[:5])}", allowed_mentions=allowed_mentions_none)  # อธิบาย: ส่ง 5 คำ
        else:
            await ctx.send(f"💡 No hints left for '{last_letter}'.", allowed_mentions=allowed_mentions_none)  # อธิบาย: แจ้ง
    except Exception:
        await ctx.send("Couldn't fetch hints right now.", allowed_mentions=allowed_mentions_none)  # อธิบาย: แจ้ง


@bot.command()
@commands.has_permissions(manage_guild=True)
async def reset_scores(ctx):  # อธิบาย: รีเซ็ตคะแนนทั้งหมด (admin only)
    global scores_data, ai_display_names  # อธิบาย: เคลียร์ global
    scores_data = {}  # อธิบาย: รีเซ็ต dict
    ai_display_names = {}  # อธิบาย: เคลียร์ display names
    await save_scores_async()  # อธิบาย: เซฟไฟล์ว่าง
    await ctx.send("🗑️ All scores have been reset!", allowed_mentions=allowed_mentions_none)  # อธิบาย: แจ้ง


@bot.command()
@commands.has_permissions(manage_guild=True)
async def clear_channel(ctx):  # อธิบาย: เคลียร์ state ของห้องนี้ (admin only)
    state = get_game(ctx.channel.id)  # อธิบาย: state ห้อง
    state.active = False  # อธิบาย: ปิดเกม
    state.players = []  # อธิบาย: เคลียร์ผู้เล่น
    state.ai_players = []  # อธิบาย: เคลียร์ AI
    state.player_names = {}  # อธิบาย: เคลียร์ชื่อ
    state.word_chain = []  # อธิบาย: เคลียร์คำ
    state.used_words = set()  # อธิบาย: เคลียร์ used
    state.current_idx = 0  # อธิบาย: รีเซ็ต index
    state.player_streaks = {}  # อธิบาย: เคลียร์ streak
    state.combo_count = 0  # อธิบาย: เคลียร์ combo
    state.cooldowns = {}  # อธิบาย: เคลียร์ cooldowns
    state.turn_token += 1  # อธิบาย: bump token
    await cancel_turn_timer_async(state)  # อธิบาย: ยกเลิก timer
    state.turn_message = None  # อธิบาย: เคลียร์ message
    await ctx.send("🧹 Channel state has been cleared!", allowed_mentions=allowed_mentions_none)  # อธิบาย: แจ้ง


# ---------------------------
# Graceful shutdown (proper)
# ---------------------------

@bot.event
async def on_close():  # อธิบาย: ปิดบอท -> ปิด session
    global http_session  # อธิบาย: ใช้ global
    if http_session and not http_session.closed:  # อธิบาย: ถ้า session ยังเปิด
        await http_session.close()  # อธิบาย: ปิด
    http_session = None  # อธิบาย: เคลียร์


# ---------------------------
# Run
# ---------------------------

bot.run(TOKEN)  # อธิบาย: รันบอท