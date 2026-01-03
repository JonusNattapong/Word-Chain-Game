"""
Configuration settings for Word Chain Game Discord Bot
"""

import os
import json
from typing import Dict, Any

# Game Configuration
class GameConfig:
    """Configuration class for game settings"""

    def __init__(self):
        # Set default values first
        self._set_defaults()
        
        # Load from JSON config file if it exists
        self._load_from_file()

        # Override with environment variables (higher priority)
        self._load_from_env()

    def _set_defaults(self):
        """Set default configuration values"""
        self.turn_seconds = 20
        self.cooldown_seconds = 2.0
        self.long_word_len = 7
        self.long_word_bonus = 2
        self.streak_min = 3
        self.streak_bonus = 1
        self.combo_step = 5
        self.combo_bonus = 1
        self.ai_model = "meta-llama/llama-3.1-405b-instruct:free"
        self.ai_max_tokens = 20
        self.ai_temperature = 0.7
        self.max_ai_players = 3
        self.max_turn_time = 120
        self.min_turn_time = 5
        self.scores_file = "data/scores.json"
        self.words_file = "words.txt"
        self.command_prefix = "!"

    def _load_from_file(self):
        """Load configuration from config.json file"""
        config_file = os.path.join(os.path.dirname(__file__), "config.json")
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.from_dict(data)
            except (json.JSONDecodeError, IOError) as e:
                print(f"Warning: Could not load config.json: {e}")

    def _load_from_env(self):
        """Load configuration from environment variables"""
        # Timing settings
        if "TURN_SECONDS" in os.environ:
            self.turn_seconds = int(os.getenv("TURN_SECONDS"))
        if "COOLDOWN_SECONDS" in os.environ:
            self.cooldown_seconds = float(os.getenv("COOLDOWN_SECONDS"))

        # Scoring settings
        if "LONG_WORD_LEN" in os.environ:
            self.long_word_len = int(os.getenv("LONG_WORD_LEN"))
        if "LONG_WORD_BONUS" in os.environ:
            self.long_word_bonus = int(os.getenv("LONG_WORD_BONUS"))
        if "STREAK_MIN" in os.environ:
            self.streak_min = int(os.getenv("STREAK_MIN"))
        if "STREAK_BONUS" in os.environ:
            self.streak_bonus = int(os.getenv("STREAK_BONUS"))
        if "COMBO_STEP" in os.environ:
            self.combo_step = int(os.getenv("COMBO_STEP"))
        if "COMBO_BONUS" in os.environ:
            self.combo_bonus = int(os.getenv("COMBO_BONUS"))

        # AI settings
        if "AI_MODEL" in os.environ:
            self.ai_model = os.getenv("AI_MODEL")
        if "AI_MAX_TOKENS" in os.environ:
            self.ai_max_tokens = int(os.getenv("AI_MAX_TOKENS"))
        if "AI_TEMPERATURE" in os.environ:
            self.ai_temperature = float(os.getenv("AI_TEMPERATURE"))

        # Game limits
        if "MAX_AI_PLAYERS" in os.environ:
            self.max_ai_players = int(os.getenv("MAX_AI_PLAYERS"))
        if "MAX_TURN_TIME" in os.environ:
            self.max_turn_time = int(os.getenv("MAX_TURN_TIME"))
        if "MIN_TURN_TIME" in os.environ:
            self.min_turn_time = int(os.getenv("MIN_TURN_TIME"))

        # File paths
        if "SCORES_FILE" in os.environ:
            self.scores_file = os.getenv("SCORES_FILE")
        if "WORDS_FILE" in os.environ:
            self.words_file = os.getenv("WORDS_FILE")

        # Bot settings
        if "COMMAND_PREFIX" in os.environ:
            self.command_prefix = os.getenv("COMMAND_PREFIX")

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary for JSON serialization"""
        return {
            "turn_seconds": self.turn_seconds,
            "cooldown_seconds": self.cooldown_seconds,
            "long_word_len": self.long_word_len,
            "long_word_bonus": self.long_word_bonus,
            "streak_min": self.streak_min,
            "streak_bonus": self.streak_bonus,
            "combo_step": self.combo_step,
            "combo_bonus": self.combo_bonus,
            "ai_model": self.ai_model,
            "ai_max_tokens": self.ai_max_tokens,
            "ai_temperature": self.ai_temperature,
            "max_ai_players": self.max_ai_players,
            "max_turn_time": self.max_turn_time,
            "min_turn_time": self.min_turn_time,
            "scores_file": self.scores_file,
            "words_file": self.words_file,
            "command_prefix": self.command_prefix
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'GameConfig':
        """Create config from dictionary"""
        config = cls.__new__(cls)  # Create instance without calling __init__
        # Set default values first
        config._set_defaults()
        
        # Override with loaded values
        for key, value in data.items():
            if hasattr(config, key):
                setattr(config, key, value)
        return config

    def validate(self) -> bool:
        """Validate configuration values"""
        try:
            assert self.min_turn_time <= self.turn_seconds <= self.max_turn_time
            assert self.cooldown_seconds >= 0
            assert self.long_word_len > 0
            assert self.max_ai_players >= 0
            assert self.ai_max_tokens > 0
            assert 0 <= self.ai_temperature <= 2.0
            return True
        except AssertionError:
            return False

    def save_to_file(self, filepath: str = None):
        """Save current configuration to JSON file"""
        if filepath is None:
            filepath = os.path.join(os.path.dirname(__file__), "config.json")

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
            print(f"Configuration saved to {filepath}")
        except IOError as e:
            print(f"Error saving configuration: {e}")

# Global config instance
config = GameConfig()

# Export for easy importing
__all__ = ['config', 'GameConfig']