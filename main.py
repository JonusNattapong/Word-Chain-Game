import os  # อธิบาย: ใช้อ่าน env และไฟล์
import json  # อธิบาย: เก็บ/อ่านคะแนน
import asyncio  # อธิบาย: ใช้ timeout/ task / lock
import time  # cooldown timing
from dataclasses import dataclass, field  # อธิบาย: โครงสร้าง state
from typing import Dict, List, Set, Optional  # อธิบาย: type hints

import discord  # อธิบาย: discord api
from discord.ext import commands  # อธิบาย: command framework
from dotenv import load_dotenv  # อธิบาย: โหลด .env
from spellchecker import SpellChecker  # อธิบาย: ตรวจคำอังกฤษแบบ offline
import aiohttp  # อธิบาย: เรียก API แบบ async (ไม่ค้างบอท)
from openai import OpenAI  # อธิบาย: ใช้ OpenRouter API สำหรับ AI player

from config import config  # อธิบาย: โหลดการตั้งค่า


# ---------------------------
# Config / Setup
# ---------------------------

load_dotenv()  # อธิบาย: โหลดค่าใน .env
TOKEN = os.getenv("DISCORD_TOKEN")  # อธิบาย: token ของบอท

intents = discord.Intents.default()  # อธิบาย: intents พื้นฐาน
intents.message_content = True  # อธิบาย: ต้องเปิดเพื่ออ่าน message.content
intents.members = False  # ปรับเป็น False เพื่อไม่ขอ privileged members intent

bot = commands.Bot(command_prefix=config.command_prefix, intents=intents)  # อธิบาย: สร้างบอท

# OpenRouter AI client setup
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")  # อธิบาย: API key สำหรับ OpenRouter
OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"  # อธิบาย: OpenRouter endpoint
openai_client = OpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url=OPENROUTER_API_BASE,
    default_headers={
        "HTTP-Referer": "https://github.com/JonusNattapong/Word-Chain-Game",
        "X-Title": "Word Chain Discord Bot",
    },
)

spell = SpellChecker()  # อธิบาย: ตัวเช็คคำอังกฤษ (offline)

SCORES_FILE = config.scores_file  # อธิบาย: ไฟล์คะแนนรวม
scores_data: Dict[str, int] = {}  # อธิบาย: {"user_id": score}

scores_lock = asyncio.Lock()  # อธิบาย: กันการเขียนไฟล์ชนกัน

# Scoring / anti-spam tuning
LONG_WORD_LEN = config.long_word_len
LONG_WORD_BONUS = config.long_word_bonus
STREAK_MIN = config.streak_min
STREAK_BONUS = config.streak_bonus
COMBO_STEP = config.combo_step
COMBO_BONUS = config.combo_bonus
COOLDOWN_SECONDS = config.cooldown_seconds

# Word validation
VALID_WORDS: Set[str] = set()  # อธิบาย: ชุดคำอังกฤษที่ถูกต้อง (โหลดจากไฟล์)


# ---------------------------
# Game State (แยกต่อห้อง)
# ---------------------------

@dataclass
class GameState:  # อธิบาย: state ของเกมใน 1 ห้อง
    active: bool = False  # อธิบาย: เกมกำลังเล่นอยู่ไหม
    players: List[int] = field(default_factory=list)  # อธิบาย: ลิสต์ user_id
    ai_players: List[str] = field(default_factory=list)  # อธิบาย: ลิสต์ AI player names
    player_names: Dict[int, str] = field(default_factory=dict)  # อธิบาย: {user_id: display_name}
    current_idx: int = 0  # อธิบาย: index ของคนที่ถึงตา
    word_chain: List[str] = field(default_factory=list)  # อธิบาย: ลำดับคำ
    used_words: Set[str] = field(default_factory=set)  # อธิบาย: กันคำซ้ำ
    turn_seconds: int = field(default_factory=lambda: config.turn_seconds)  # อธิบาย: เวลาต่อเทิร์น (ปรับได้)
    turn_task: Optional[asyncio.Task] = None  # อธิบาย: task นับถอยหลังต่อเทิร์น
    turn_message: Optional[discord.Message] = None  # อธิบาย: ข้อความเทิร์น (สำหรับแก้ไข progress bar)
    player_streaks: Dict[int, int] = field(default_factory=dict)  # per-player successful turn streaks
    combo_count: int = 0  # consecutive valid words in this channel
    cooldowns: Dict[int, float] = field(default_factory=dict)  # anti-spam per-user timestamps


games: Dict[int, GameState] = {}  # อธิบาย: {channel_id: GameState}
http_session: Optional[aiohttp.ClientSession] = None  # อธิบาย: session รวมทั้งบอท


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


async def save_scores_async():  # อธิบาย: เซฟคะแนนแบบ async + lock
    async with scores_lock:  # อธิบาย: กันชนกัน
        with open(SCORES_FILE, "w", encoding="utf-8") as f:  # อธิบาย: เขียนทับ
            json.dump(scores_data, f, indent=4, ensure_ascii=False)  # อธิบาย: เซฟ json


# ---------------------------
# Helpers
# ---------------------------

def get_game(channel_id: int) -> GameState:  # อธิบาย: ดึง state ตามห้อง
    if channel_id not in games:  # อธิบาย: ถ้ายังไม่มีให้สร้าง
        games[channel_id] = GameState()  # อธิบาย: init
    return games[channel_id]  # อธิบาย: คืน state


def current_player_id(state: GameState) -> Optional[int]:  # อธิบาย: user_id คนที่ถึงตา
    if not state.players:  # อธิบาย: ไม่มีคน
        return None  # อธิบาย: คืน None

    state.current_idx %= len(state.players)  # อธิบาย: กัน index หลุด
    return state.players[state.current_idx]  # อธิบาย: คืน id


def current_player_info(state: GameState) -> tuple[Optional[int], Optional[str]]:  # อธิบาย: (user_id, ai_name) คนที่ถึงตา
    """Returns (user_id, ai_name) for current player. One will be None, the other will have value."""
    total_players = len(state.players) + len(state.ai_players)
    if total_players == 0:
        return None, None
    
    current_idx = state.current_idx % total_players
    print(f"DEBUG: current_player_info - current_idx: {state.current_idx}, total: {total_players}, normalized: {current_idx}")
    
    if current_idx < len(state.players):
        # Human player
        user_id = state.players[current_idx]
        print(f"DEBUG: Human player turn - user_id: {user_id}")
        return user_id, None
    else:
        # AI player
        ai_idx = current_idx - len(state.players)
        ai_name = state.ai_players[ai_idx]
        print(f"DEBUG: AI player turn - ai_name: {ai_name}")
        return None, ai_name


def total_players(state: GameState) -> int:  # อธิบาย: จำนวนผู้เล่นทั้งหมด
    return len(state.players) + len(state.ai_players)  # อธิบาย: คน + AI


def advance_turn(state: GameState):  # อธิบาย: เลื่อนเทิร์นไปคนถัดไป
    tp = total_players(state)  # อธิบาย: จำนวนทั้งหมด
    if tp <= 0:  # อธิบาย: กันหารศูนย์
        state.current_idx = 0  # อธิบาย: รีเซ็ต
        return  # อธิบาย: จบ
    state.current_idx = (state.current_idx + 1) % tp  # อธิบาย: เลื่อนไปคนถัดไป


def peek_current_name(state: GameState) -> str:  # อธิบาย: ชื่อคนที่ถึงตาตอนนี้ (หลัง advance แล้วใช้ได้)
    uid, ai_name = current_player_info(state)  # อธิบาย: ดึง info เทิร์นปัจจุบัน
    if uid is not None:  # อธิบาย: เป็นคน
        return state.player_names.get(uid, f"User {uid}")  # อธิบาย: ชื่อคน
    return ai_name or "Unknown"  # อธิบาย: ชื่อ AI หรือ fallback


def create_progress_bar(current: int, total: int, length: int = 10) -> str:  # อธิบาย: สร้าง progress bar ด้วย emoji
    if total <= 0:  # อธิบาย: กัน divide by zero
        return "▰" * length  # อธิบาย: เต็ม
    filled = int((current / total) * length)  # อธิบาย: คำนวณจำนวนเต็ม
    empty = length - filled  # อธิบาย: คำนวณจำนวนว่าง
    return "▰" * filled + "▱" * empty  # อธิบาย: สร้าง bar


def is_valid_word_basic(word: str) -> bool:  # อธิบาย: ตรวจรูปแบบคำเบื้องต้น
    return word.isalpha() and len(word) >= 2  # อธิบาย: ต้องเป็นตัวอักษรล้วนและยาวพอ


def normalize_word(word: str) -> str:  # อธิบาย: normalize คำ (ลบ space และเป็นตัวเล็ก)
    return word.strip().lower()  # อธิบาย: strip และ lower


def load_valid_words():  # อธิบาย: โหลดคำอังกฤษจากไฟล์
    global VALID_WORDS  # อธิบาย: ใช้ global set
    try:  # อธิบาย: กันไฟล์ไม่มี
        with open(config.words_file, "r", encoding="utf-8") as f:  # อธิบาย: อ่านไฟล์
            words = [line.strip().lower() for line in f if line.strip()]  # อธิบาย: normalize
            VALID_WORDS = set(words)  # อธิบาย: แปลงเป็น set สำหรับ lookup เร็ว
        print(f"Loaded {len(VALID_WORDS)} valid words")  # อธิบาย: log
    except FileNotFoundError:  # อธิบาย: ไฟล์ไม่มี
        print("Warning: words.txt not found, using spellchecker fallback")  # อธิบาย: แจ้งเตือน
        VALID_WORDS = set()  # อธิบาย: ว่างไว้


async def is_valid_english_word(word: str) -> bool:  # อธิบาย: ตรวจคำอังกฤษ (local ก่อน)
    if VALID_WORDS and word in VALID_WORDS:  # อธิบาย: ถ้ามี word list และเจอ
        return True  # อธิบาย: ผ่าน
    # อธิบาย: fallback ใช้ spellchecker ถ้าไม่มีไฟล์หรือไม่เจอ
    return word in spell


def generate_ai_word(state: GameState, ai_name: str) -> str:  # อธิบาย: สร้างคำสำหรับ AI player
    """Generate a word for AI player using OpenRouter GPT model"""
    try:
        # Prepare context for AI
        last_letter = state.word_chain[-1][-1] if state.word_chain else None
        used_words_str = ", ".join(list(state.used_words)[:10])  # Show last 10 used words
        
        prompt = f"You are playing Word Chain game. "
        if last_letter:
            prompt += f"The previous word ends with '{last_letter}', so your word must start with '{last_letter}'. "
        else:
            prompt += "You can start with any word. "
        
        prompt += f"Used words so far: {used_words_str}. "
        prompt += "Generate ONE valid English word (3-15 letters) that hasn't been used. Reply with only the word, nothing else."
        
        if not OPENROUTER_API_KEY:
            print("AI word generation error: OPENROUTER_API_KEY is not set")
            return None

        response = openai_client.chat.completions.create(
            model=config.ai_model,  # Using configured AI model
            messages=[{"role": "user", "content": prompt}],
            max_tokens=config.ai_max_tokens,
            temperature=config.ai_temperature
        )
        
        word = response.choices[0].message.content.strip().lower()
        
        # Validate the word (basic validation only for sync function)
        if is_valid_word_basic(word) and word not in state.used_words:
            if last_letter and not word.startswith(last_letter):
                return None  # Invalid chain
            return word
        return None
        
    except Exception as e:
        print(f"AI word generation error: {e}")
        return None


async def generate_ai_word_async(state: GameState, ai_name: str) -> Optional[str]:  # อธิบาย: เรียก AI แบบไม่ค้างบอท
    return await asyncio.to_thread(generate_ai_word, state, ai_name)  # อธิบาย: ย้ายงาน sync ไป thread


async def process_word_submission(channel: discord.abc.Messageable, word: str, state: GameState, player_id: int = None, ai_player: str = None):  # อธิบาย: ประมวลผลคำที่ส่งมา
    """Process a word submission from either human or AI player"""
    
    # Validate word format
    if not is_valid_word_basic(word):
        if ai_player:
            await channel.send(f"🤖 {ai_player} submitted invalid word format.")
        else:
            await channel.send("Please enter a valid word (letters only, at least 2).")
        return

    # Validate English word
    if not await is_valid_english_word(word):
        if ai_player:
            await channel.send(f"🤖 {ai_player} submitted invalid English word.")
        else:
            await channel.send("Not a valid English word (dictionary check failed).")
        return

    # Check for duplicates
    if word in state.used_words:
        if ai_player:
            await channel.send(f"🤖 {ai_player} submitted already used word.")
        else:
            await channel.send("Word already used!")
        return

    # Check chain rule
    if state.word_chain:
        last_word = state.word_chain[-1]
        if word[0] != last_word[-1]:
            if ai_player:
                await channel.send(f"🤖 {ai_player} submitted word that doesn't chain properly.")
            else:
                await channel.send(f"Word must start with '{last_word[-1]}'.")
            return

    # Word is valid - process it
    cancel_turn_timer(state)
    state.word_chain.append(word)
    state.used_words.add(word)

    # Calculate points
    if ai_player:
        # AI gets points too (stored with AI name as key)
        uid = f"ai_{ai_player}"
        base_points = 1
        bonus_points = 0
        
        # Long word bonus
        if len(word) >= LONG_WORD_LEN:
            bonus_points += LONG_WORD_BONUS
            
        # AI doesn't get streak bonuses for simplicity
        total_points = base_points + bonus_points
        scores_data[uid] = scores_data.get(uid, 0) + total_points
        await save_scores_async()
        
        # Get next player name for AI message
        advance_turn(state)  # อธิบาย: เลื่อนเทิร์นแค่ครั้งเดียว
        next_name = peek_current_name(state)  # อธิบาย: คนที่ถึงตาถัดไปจริง ๆ
        
        print("DEBUG: About to send AI message")
        await channel.send(f"🤖 {ai_player} played '{word}' (+{total_points} pts). Next starts with '{word[-1]}'. Next: {next_name}")
        print("DEBUG: AI message sent successfully")
        
    else:
        # Human player scoring (existing logic)
        uid = str(player_id) if player_id else "unknown"
        base_points = 1
        bonus_points = 0

        # Long word bonus
        if len(word) >= LONG_WORD_LEN:
            bonus_points += LONG_WORD_BONUS

        # Personal streak bonus
        if player_id:
            player_streak = state.player_streaks.get(player_id, 0) + 1
            state.player_streaks[player_id] = player_streak
            if player_streak >= STREAK_MIN:
                bonus_points += STREAK_BONUS

        # Channel combo bonus
        state.combo_count += 1
        if state.combo_count % COMBO_STEP == 0:
            bonus_points += COMBO_BONUS

        total_points = base_points + bonus_points
        scores_data[uid] = scores_data.get(uid, 0) + total_points
        await save_scores_async()

        # Get next player name
        advance_turn(state)  # อธิบาย: เลื่อนเทิร์นแค่ครั้งเดียว
        next_name = peek_current_name(state)  # อธิบาย: คนที่ถึงตาถัดไปจริง ๆ

        bonus_text = f" (+{bonus_points} bonus)" if bonus_points > 0 else ""
        await channel.send(
            f"✅ Added '{word}' (+{total_points} pts{bonus_text}). Next starts with '{word[-1]}'. "
            f"Your total score: {scores_data[uid]}. Next: {next_name}"
        )

    await send_turn_prompt(channel, state)  # อธิบาย: ส่ง prompt เทิร์นใหม่
    await start_turn_timer(channel, state)  # อธิบาย: เริ่มจับเวลาใหม่


def build_turn_text(state: GameState, name: str, remaining: int) -> str:  # อธิบาย: สร้างข้อความเทิร์นใหม่เสมอ
    progress_bar = create_progress_bar(remaining, state.turn_seconds, 10)  # อธิบาย: bar ตามเวลาที่เหลือ
    if not state.word_chain:  # อธิบาย: ยังไม่มีคำ
        return f"🎮 It's {name}'s turn! Start with any English word.\n{progress_bar} ({remaining}s)"  # อธิบาย: ข้อความเริ่ม
    last_letter = state.word_chain[-1][-1]  # อธิบาย: ตัวท้าย
    return f"🎮 It's {name}'s turn! Word must start with '{last_letter}'.\n{progress_bar} ({remaining}s)"  # อธิบาย: ข้อความต่อคำ


async def send_turn_prompt(channel: discord.abc.Messageable, state: GameState):  # อธิบาย: บอกว่าใครถึงตา + ตัวอักษร
    print("DEBUG: send_turn_prompt called")
    user_id, ai_name = current_player_info(state)  # อธิบาย: ได้ทั้ง human และ AI
    print(f"DEBUG: send_turn_prompt - current_player_info returned user_id={user_id}, ai_name={ai_name}")
    if user_id is None and ai_name is None:  # อธิบาย: ไม่มีคน
        await channel.send("No players joined yet! Use !join or !add_ai")  # อธิบาย: แจ้ง
        return None  # อธิบาย: จบ

    if user_id is not None:
        name = state.player_names.get(user_id, f"User {user_id}")  # อธิบาย: ชื่อผู้ใช้
    else:
        name = ai_name  # อธิบาย: ชื่อ AI

    turn_text = build_turn_text(state, name, state.turn_seconds)  # อธิบาย: ข้อความเทิร์นเริ่มต้น
    message = await channel.send(turn_text)  # อธิบาย: ส่งข้อความเทิร์น

    state.turn_message = message  # อธิบาย: เก็บข้อความไว้แก้ไข progress bar
    return message  # อธิบาย: คืน message


def cancel_turn_timer(state: GameState):  # อธิบาย: ยกเลิกตัวจับเวลาเดิม
    current_task = asyncio.current_task()
    if state.turn_task and not state.turn_task.done():  # อธิบาย: ถ้ามี task และยังไม่จบ
        if state.turn_task is not current_task:
            state.turn_task.cancel()  # ?????? task ????
    state.turn_task = None  # อธิบาย: เคลียร์

async def start_turn_timer(channel: discord.abc.Messageable, state: GameState):  # อธิบาย: เริ่มนับเวลาเทิร์นใหม่
    cancel_turn_timer(state)  # อธิบาย: ยกเลิกของเก่า

    async def timer():  # อธิบาย: coroutine ตัวจับเวลา
        try:
            user_id, ai_name = current_player_info(state)  # อธิบาย: เช็คว่าเป็น human หรือ AI
            
            # Countdown timer (both human and AI)
            remaining = state.turn_seconds  # อธิบาย: เวลาที่เหลือ
            update_interval = 2  # อธิบาย: อัปเดตทุก 2 วินาที

            while remaining > 0:  # อธิบาย: ลูปนับถอยหลัง
                total_players = len(state.players) + len(state.ai_players)
                if not state.active or total_players == 0:  # อธิบาย: เกมถูกปิดหรือไม่มีผู้เล่น
                    return  # อธิบาย: จบ

                # อธิบาย: อัปเดต progress bar ทุก 2 วินาที
                if state.turn_message and remaining < state.turn_seconds:  # อธิบาย: มีข้อความและไม่ใช่รอบแรก
                    name = peek_current_name(state)  # อธิบาย: ชื่อคนที่ถึงตา
                    new_text = build_turn_text(state, name, remaining)  # อธิบาย: สร้างข้อความใหม่
                    try:
                        await state.turn_message.edit(content=new_text)  # อธิบาย: แก้ไขข้อความ
                    except discord.errors.HTTPException:  # อธิบาย: rate limit หรือข้อผิดพลาดอื่น
                        pass  # อธิบาย: ข้ามไป

                await asyncio.sleep(min(update_interval, remaining))  # อธิบาย: รอ 2 วินาที หรือเหลือน้อยกว่าก็รอจนหมด
                remaining -= update_interval  # อธิบาย: ลดเวลาที่เหลือ

            # อธิบาย: หมดเวลา -> ข้ามคนปัจจุบัน
            total_players = len(state.players) + len(state.ai_players)
            if not state.active or total_players == 0:  # อธิบาย: ตรวจสอบอีกครั้ง
                return  # อธิบาย: จบ

            if ai_name is not None:
                # AI player's turn - generate word after countdown
                await asyncio.sleep(1)  # Small delay for UX
                word = await generate_ai_word_async(state, ai_name)
                if word:
                    await process_word_submission(channel, word, state, player_id=None, ai_player=ai_name)
                else:
                    advance_turn(state)  # อธิบาย: เลื่อนเทิร์นไปคนถัดไป
                    await channel.send(f"🤖 {ai_name} couldn't think of a word! Skipping...")
                    await send_turn_prompt(channel, state)
                    await start_turn_timer(channel, state)
                return

            # Reset streaks and combo for skipped player
            if user_id is not None:
                state.player_streaks[user_id] = 0
            state.combo_count = 0
            
            name = state.player_names.get(user_id, f"User {user_id}") if user_id else ai_name

            advance_turn(state)  # อธิบาย: ข้ามไปคนถัดไป
            await channel.send(f"⏰ Time's up! Skipping {name}.")  # อธิบาย: แจ้งข้าม
            await send_turn_prompt(channel, state)  # อธิบาย: บอกเทิร์นใหม่
            await start_turn_timer(channel, state)  # อธิบาย: เริ่มจับเวลาใหม่
        except asyncio.CancelledError:
            return  # อธิบาย: ถูกยกเลิกก็จบเงียบ ๆ

    state.turn_task = asyncio.create_task(timer())  # อธิบาย: สร้าง task


# ---------------------------
# Events
# ---------------------------

@bot.event
async def on_ready():  # อธิบาย: บอทพร้อม
    global http_session  # อธิบาย: จะ init session
    load_scores_sync()  # อธิบาย: โหลดคะแนน
    load_valid_words()  # อธิบาย: โหลดคำอังกฤษ
    http_session = aiohttp.ClientSession()  # อธิบาย: เปิด session ใช้ร่วมทั้งบอท
    print("Bot is ready")  # อธิบาย: log


@bot.event
async def on_disconnect():  # อธิบาย: หลุดการเชื่อมต่อ
    # อธิบาย: ไม่ปิด session ที่นี่ เพราะ discord อาจ reconnect เอง
    pass  # อธิบาย: เว้นไว้


@bot.event
async def on_message(message: discord.Message):  # อธิบาย: รับข้อความ
    if message.author == bot.user:  # อธิบาย: กัน loop
        return  # อธิบาย: จบ

    # อธิบาย: ให้ commands ทำงานก่อน/พร้อมกัน
    await bot.process_commands(message)  # อธิบาย: สำคัญ

    # อธิบาย: ถ้าข้อความถูก process เป็น command แล้ว จะไม่ทำอะไรต่อ
    # อธิบาย: ไม่เอาข้อความที่ขึ้นต้นด้วย prefix มาเล่นเกม
    if message.content.startswith("!"):  # อธิบาย: เป็นคำสั่ง
        return  # อธิบาย: จบ

    state = get_game(message.channel.id)  # อธิบาย: เกมของห้องนี้

    if not state.active:  # อธิบาย: เกมไม่ active
        return  # อธิบาย: จบ

    if not state.players:  # อธิบาย: ยังไม่มีคน join
        await message.channel.send("No players joined yet! Use !join")  # อธิบาย: แจ้ง
        return  # อธิบาย: จบ

    # Check cooldown to prevent spam (but allow during turn)
    now = time.monotonic()
    last = state.cooldowns.get(message.author.id, 0.0)
    if now - last < config.cooldown_seconds:  # Reduced cooldown for better gameplay
        return
    state.cooldowns[message.author.id] = now

    # Check if it's the current player's turn
    user_id, ai_name = current_player_info(state)
    if user_id != message.author.id:  # Not this human player's turn
        if user_id is not None:
            name = state.player_names.get(user_id, f"User {user_id}")
        else:
            name = ai_name
        await message.channel.send(f"🚫 Not your turn. It's {name}'s turn!")
        return

    word = normalize_word(message.content)
    await process_word_submission(message.channel, word, state, player_id=message.author.id)
# ---------------------------
# Commands
# ---------------------------

@bot.command()
async def start_game(ctx):  # อธิบาย: เริ่มเกม (เฉพาะห้องนี้)
    state = get_game(ctx.channel.id)  # อธิบาย: ดึง state ห้อง
    state.active = True  # อธิบาย: เปิดเกม
    state.word_chain = []  # อธิบาย: รีเซ็ตคำ
    state.used_words = set()  # อธิบาย: รีเซ็ต used
    state.current_idx = 0  # อธิบาย: รีเซ็ตเทิร์น
    cancel_turn_timer(state)  # อธิบาย: กัน timer เก่าค้าง

    total_players = len(state.players) + len(state.ai_players)
    await ctx.send("🎮 Word chain started in this channel! Use !join or !add_ai then wait your turn.")  # อธิบาย: แจ้งเริ่ม
    if total_players > 0:  # อธิบาย: ถ้ามีคนหรือ AI อยู่แล้ว
        await send_turn_prompt(ctx.channel, state)  # อธิบาย: บอกเทิร์นแรก
        await start_turn_timer(ctx.channel, state)  # อธิบาย: เริ่มจับเวลา


@bot.command()
async def end_game(ctx):  # อธิบาย: จบเกม (เฉพาะห้องนี้)
    state = get_game(ctx.channel.id)  # อธิบาย: state ห้อง
    state.active = False  # อธิบาย: ปิดเกม
    cancel_turn_timer(state)  # อธิบาย: ยกเลิก timer
    state.turn_message = None  # อธิบาย: เคลียร์ข้อความเทิร์น
    await ctx.send("🛑 Game ended in this channel.")  # อธิบาย: แจ้งจบ


@bot.command()
async def join(ctx):  # อธิบาย: เข้าร่วมเกมห้องนี้
    state = get_game(ctx.channel.id)  # อธิบาย: state ห้อง
    uid = ctx.author.id  # อธิบาย: id ผู้ใช้

    if uid in state.players:  # อธิบาย: กัน join ซ้ำ
        await ctx.send("You're already in this channel's game!")  # อธิบาย: แจ้ง
        return  # อธิบาย: จบ

    # Check if already processing this join to prevent duplicates
    if hasattr(state, 'joining_users') and uid in state.joining_users:
        return

    if not hasattr(state, 'joining_users'):
        state.joining_users = set()

    state.joining_users.add(uid)

    try:
        state.players.append(uid)  # อธิบาย: เพิ่มผู้เล่น
        state.player_names[uid] = ctx.author.display_name  # อธิบาย: เก็บชื่อ
        await ctx.send(f"➕ {ctx.author.display_name} joined this channel's game!")  # อธิบาย: แจ้ง
    finally:
        state.joining_users.discard(uid)

    if state.active and len(state.players) == 1:  # อธิบาย: ถ้าเกมกำลังเล่นและเพิ่งมีคนแรก
        state.current_idx = 0  # อธิบาย: ให้คนแรกเริ่ม
        await send_turn_prompt(ctx.channel, state)  # อธิบาย: บอกเทิร์นแรก
        await start_turn_timer(ctx.channel, state)  # อธิบาย: เริ่มจับเวลา


@bot.command()
async def leave(ctx):  # อธิบาย: ออกจากเกมห้องนี้
    state = get_game(ctx.channel.id)  # อธิบาย: state ห้อง
    uid = ctx.author.id  # อธิบาย: id ผู้ใช้

    if uid not in state.players:  # อธิบาย: ไม่ได้อยู่ในเกม
        await ctx.send("You're not in this channel's game.")  # อธิบาย: แจ้ง
        return  # อธิบาย: จบ

    idx = state.players.index(uid)  # อธิบาย: index เดิม
    state.players.remove(uid)  # อธิบาย: ลบออก

    # อธิบาย: ปรับ current_idx ให้ไม่เพี้ยน
    if state.players:  # อธิบาย: ยังมีคนเหลือ
        if idx < state.current_idx:  # อธิบาย: ถ้าคนที่ออกอยู่ก่อนเทิร์นปัจจุบัน
            state.current_idx -= 1  # อธิบาย: เลื่อนกลับ
        state.current_idx %= len(state.players)  # อธิบาย: กันเกิน
    else:
        state.current_idx = 0  # อธิบาย: รีเซ็ต
        cancel_turn_timer(state)  # อธิบาย: ไม่มีคนก็หยุดเวลา

    await ctx.send(f"➖ {ctx.author.display_name} left this channel's game!")  # อธิบาย: แจ้ง

    # อธิบาย: ถ้าเกม active และคนที่ออกเป็นคนถึงตา/หรือทำให้เทิร์นเปลี่ยน ให้ประกาศใหม่
    if state.active and state.players:  # อธิบาย: ยังเล่นต่อได้
        await send_turn_prompt(ctx.channel, state)  # อธิบาย: บอกเทิร์นปัจจุบัน
        await start_turn_timer(ctx.channel, state)  # อธิบาย: เริ่มจับเวลาใหม่


@bot.command()
async def add_ai(ctx, ai_name: str = "AI"):  # อธิบาย: เพิ่ม AI เข้าเกม
    state = get_game(ctx.channel.id)  # อธิบาย: state ห้อง

    if ai_name in state.ai_players:  # อธิบาย: กัน AI ซ้ำ
        await ctx.send(f"🤖 {ai_name} is already in this channel's game!")  # อธิบาย: แจ้ง
        return  # อธิบาย: จบ

    if len(state.ai_players) >= config.max_ai_players:  # อธิบาย: จำกัด AI ไม่เกินที่กำหนด
        await ctx.send(f"🤖 Maximum {config.max_ai_players} AI players allowed!")  # อธิบาย: แจ้ง
        return  # อธิบาย: จบ

    # Check if already processing this AI addition to prevent duplicates
    if hasattr(state, 'adding_ais') and ai_name in state.adding_ais:
        return

    if not hasattr(state, 'adding_ais'):
        state.adding_ais = set()

    state.adding_ais.add(ai_name)

    try:
        state.ai_players.append(ai_name)  # อธิบาย: เพิ่ม AI
        await ctx.send(f"🤖 {ai_name} joined this channel's game!")  # อธิบาย: แจ้ง
    finally:
        state.adding_ais.discard(ai_name)

    if state.active and len(state.players) + len(state.ai_players) == 1:  # อธิบาย: ถ้า AI เป็นคนแรก
        state.current_idx = 0  # อธิบาย: ให้ AI เริ่ม
        await send_turn_prompt(ctx.channel, state)  # อธิบาย: บอกเทิร์นแรก
        await start_turn_timer(ctx.channel, state)  # อธิบาย: เริ่มจับเวลา


@bot.command()
async def remove_ai(ctx, ai_name: str):  # อธิบาย: ลบ AI ออกจากเกม
    state = get_game(ctx.channel.id)  # อธิบาย: state ห้อง

    if ai_name not in state.ai_players:  # อธิบาย: AI ไม่ได้อยู่ในเกม
        await ctx.send(f"🤖 {ai_name} is not in this channel's game.")  # อธิบาย: แจ้ง
        return  # อธิบาย: จบ

    idx = state.ai_players.index(ai_name)  # อธิบาย: index เดิม
    state.ai_players.remove(ai_name)  # อธิบาย: ลบออก

    # อธิบาย: ปรับ current_idx ให้ไม่เพี้ยน
    total_players = len(state.players) + len(state.ai_players)
    if total_players > 0:  # อธิบาย: ยังมีคนเหลือ
        ai_start_idx = len(state.players)  # อธิบาย: AI เริ่มที่ index นี้
        if ai_start_idx + idx < state.current_idx:  # อธิบาย: ถ้า AI ที่ออกอยู่ก่อนเทิร์นปัจจุบัน
            state.current_idx -= 1  # อธิบาย: เลื่อนกลับ
        state.current_idx %= total_players  # อธิบาย: กันเกิน
    else:
        state.current_idx = 0  # อธิบาย: รีเซ็ต
        cancel_turn_timer(state)  # อธิบาย: ไม่มีคนก็หยุดเวลา

    await ctx.send(f"🤖 {ai_name} left this channel's game!")  # อธิบาย: แจ้ง

    # อธิบาย: ถ้าเกม active และยังมีผู้เล่น ให้ประกาศเทิร์นใหม่
    if state.active and total_players > 0:  # อธิบาย: ยังเล่นต่อได้
        await send_turn_prompt(ctx.channel, state)  # อธิบาย: บอกเทิร์นปัจจุบัน
        await start_turn_timer(ctx.channel, state)  # อธิบาย: เริ่มจับเวลาใหม่


@bot.command()
async def reload_config(ctx):  # อธิบาย: โหลด config ใหม่
    """Reload configuration from config.json file"""
    try:
        # Reinitialize config
        from config import GameConfig
        global config
        config = GameConfig()

        if config.validate():
            await ctx.send("✅ Configuration reloaded successfully!")
            await ctx.send(f"📋 Current settings: Turn time: {config.turn_seconds}s, AI Model: {config.ai_model}")
        else:
            await ctx.send("❌ Configuration validation failed! Check your config.json values.")
    except Exception as e:
        await ctx.send(f"❌ Error reloading configuration: {e}")


@bot.command(name="scores")
async def leaderboard(ctx):  # อธิบาย: top 10 คะแนนรวม
    if not scores_data:  # อธิบาย: ยังไม่มีคะแนน
        await ctx.send("No scores yet!")  # อธิบาย: แจ้ง
        return  # อธิบาย: จบ

    sorted_scores = sorted(scores_data.items(), key=lambda x: x[1], reverse=True)  # อธิบาย: เรียงคะแนน
    text = "🏆 **Leaderboard (Global)** 🏆\n"  # อธิบาย: หัวข้อ

    rank = 1  # อธิบาย: ลำดับ
    for user_key, score in sorted_scores:  # อธิบาย: วนลูปคะแนน
        if rank > 10:  # อธิบาย: จำกัด top 10
            break  # อธิบาย: จบ

        if str(user_key).startswith("ai_"):  # อธิบาย: ถ้าเป็น AI
            name = str(user_key).replace("ai_", "🤖 ")  # อธิบาย: แสดงชื่อ AI
        else:
            try:
                user = bot.get_user(int(user_key))  # อธิบาย: ดึง user จาก cache
                name = user.display_name if user else f"User {user_key}"  # อธิบาย: fallback
            except ValueError:
                name = f"User {user_key}"  # อธิบาย: กันข้อมูลแปลก

        text += f"{rank}. {name}: {score}\n"  # อธิบาย: ต่อบรรทัด
        rank += 1  # อธิบาย: เพิ่มอันดับ

    await ctx.send(text)  # อธิบาย: ส่ง


@bot.command()
async def myscore(ctx):  # อธิบาย: ดูคะแนนตัวเอง
    uid = str(ctx.author.id)  # อธิบาย: key เป็น str
    score = scores_data.get(uid, 0)  # อธิบาย: default 0
    await ctx.send(f"📌 {ctx.author.display_name}, your total score is {score}.")  # อธิบาย: ส่ง


@bot.command()
async def status(ctx):  # อธิบาย: ดูสถานะเกมของห้องนี้
    state = get_game(ctx.channel.id)  # อธิบาย: state ห้อง
    if not state.active:  # อธิบาย: ยังไม่เริ่ม
        await ctx.send("ℹ️ No active game in this channel. Use !start_game")  # อธิบาย: แจ้ง
        return  # อธิบาย: จบ

    if not state.players and not state.ai_players:  # อธิบาย: ไม่มีผู้เล่น
        await ctx.send("ℹ️ Game is active but no players joined. Use !join")  # อธิบาย: แจ้ง
        return  # อธิบาย: จบ

    uid, ai_name = current_player_info(state)  # อธิบาย: ดึงคนที่ถึงตา
    turn_name = state.player_names.get(uid, f"User {uid}") if uid is not None else (ai_name or "Unknown")  # อธิบาย: ชื่อเทิร์น

    last = state.word_chain[-1] if state.word_chain else "(none)"  # อธิบาย: คำล่าสุด
    await ctx.send(  # อธิบาย: สรุป state
        f"📣 Active: {state.active}\n"
        f"👥 Humans: {len(state.players)} | 🤖 AIs: {len(state.ai_players)}\n"
        f"🧠 Last word: {last}\n"
        f"🎯 Current turn: {turn_name}\n"
        f"⏳ Turn time: {state.turn_seconds}s"
    )


@bot.command()
async def settime(ctx, seconds: int):  # อธิบาย: ปรับเวลาเทิร์น
    state = get_game(ctx.channel.id)  # อธิบาย: state ห้อง
    seconds = max(config.min_turn_time, min(seconds, config.max_turn_time))  # อธิบาย: จำกัดตาม config
    state.turn_seconds = seconds  # อธิบาย: ตั้งค่า
    await ctx.send(f"⏳ Turn time set to {seconds}s for this channel.")  # อธิบาย: แจ้ง


@bot.command()
async def countdown(ctx, seconds: int = 10):  # อธิบาย: ทดสอบ countdown แบบ text (จำลอง)
    seconds = max(1, min(seconds, config.max_turn_time))  # อธิบาย: จำกัดตาม config
    message = await ctx.send(f"⏳ {seconds}")  # อธิบาย: ส่งข้อความเริ่ม

    for i in range(seconds - 1, 0, -1):  # อธิบาย: นับถอยหลัง
        await asyncio.sleep(1)  # อธิบาย: รอ 1 วิ
        try:
            await message.edit(content=f"⏳ {i}")  # อธิบาย: แก้ไขข้อความ
        except Exception:
            break  # อธิบาย: ถ้าแก้ไม่ได้ก็หยุด

    await message.edit(content="⏰ Time's up!")  # อธิบาย: จบ


# ---------------------------
# Graceful shutdown (optional)
# ---------------------------

@bot.event
async def on_close():  # อธิบาย: event นี้อาจไม่ถูกเรียกทุกกรณี
    if http_session and not http_session.closed:  # อธิบาย: ถ้ามี session
        await http_session.close()  # อธิบาย: ปิด


bot.run(TOKEN)  # อธิบาย: รันบอท
