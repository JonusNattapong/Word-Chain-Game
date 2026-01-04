# Word Chain Discord Bot

A high-performance, thread-safe Discord bot for playing the word chain game with AI opponents and advanced scoring mechanics.

## ✨ Features

- **🎮 Turn-Based Gameplay**: Players take turns adding words that start with the last letter of the previous word
- **🤖 AI Opponents**: Add up to 3 AI players powered by OpenRouter API for competitive gameplay
- **⚡ High Performance**: Local dictionary with O(1) lookups for instant word validation
- **🔒 Thread Safety**: Advanced locking mechanisms prevent race conditions and data corruption
- **📊 Advanced Scoring**: Multiple bonus systems including streaks, combos, and long words
- **⏱️ Turn Timer**: Visual progress bar with configurable time limits
- **🛡️ Anti-Spam Protection**: Cooldown system prevents message flooding
- **💾 Persistent Scores**: Global leaderboard with automatic saving
- **🔍 Word Hints**: Get suggestions for valid next words
- **🐳 Docker Support**: Easy deployment with Docker and Docker Compose
- **⚙️ Flexible Configuration**: Extensive customization options via config files and environment variables

## 🚀 Quick Start

### Prerequisites
- Python 3.8+
- Discord Bot Token
- OpenRouter API Key (for AI features)

### Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/JonusNattapong/Word-Chain-Game.git
   cd Word-Chain-Game
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment**:
   ```bash
   cp .env.example .env
   # Edit .env with your tokens
   ```

4. **Run the bot**:
   ```bash
   python main.py
   ```

## 🤖 Creating Your Discord Bot

1. **Go to Discord Developer Portal**: Visit https://discord.com/developers/applications
2. **Create New Application**: Click "New Application" and give it a name
3. **Create Bot User**: Go to the "Bot" section and click "Add Bot"
4. **Copy Token**: Under "Token", click "Copy" - this is your `DISCORD_TOKEN`
5. **Bot Permissions**: In "Bot" section, enable:
   - Send Messages
   - Use Slash Commands
   - Read Message History
6. **Generate Invite Link**: Go to "OAuth2" > "URL Generator", select:
   - `bot` scope
   - `Send Messages`, `Use Slash Commands` permissions
   - Copy the generated URL to invite your bot

## Configuration

The bot supports extensive configuration through `config.json` file. Settings are loaded in this priority order:
1. Environment variables (highest priority)
2. `config.json` file
3. Default values (lowest priority)

### Configuration Options

| Setting | Description | Default | Environment Variable |
|---------|-------------|---------|---------------------|
| `turn_seconds` | Turn time limit in seconds | 20 | `TURN_SECONDS` |
| `cooldown_seconds` | Anti-spam cooldown between submissions | 2.0 | `COOLDOWN_SECONDS` |
| `long_word_len` | Minimum length for long word bonus | 7 | `LONG_WORD_LEN` |
| `long_word_bonus` | Points for long words | 2 | `LONG_WORD_BONUS` |
| `streak_min` | Minimum streak for personal bonus | 3 | `STREAK_MIN` |
| `streak_bonus` | Points for personal streaks | 1 | `STREAK_BONUS` |
| `combo_step` | Words between channel combo bonuses | 5 | `COMBO_STEP` |
| `combo_bonus` | Points for channel combos | 1 | `COMBO_BONUS` |
| `ai_model` | AI model for word generation | meta-llama/llama-3.1-405b-instruct:free | `AI_MODEL` |
| `ai_max_tokens` | Maximum tokens for AI responses | 20 | `AI_MAX_TOKENS` |
| `ai_temperature` | AI creativity (0.0-2.0) | 0.7 | `AI_TEMPERATURE` |
| `max_ai_players` | Maximum AI players allowed | 3 | `MAX_AI_PLAYERS` |
| `max_turn_time` | Maximum allowed turn time | 120 | `MAX_TURN_TIME` |
| `min_turn_time` | Minimum allowed turn time | 5 | `MIN_TURN_TIME` |
| `scores_file` | Path to scores file | data/scores.json | `SCORES_FILE` |
| `words_file` | Path to words dictionary | words.txt | `WORDS_FILE` |
| `command_prefix` | Bot command prefix | ! | `COMMAND_PREFIX` |

### Example Configuration

```json
{
  "turn_seconds": 15,
  "cooldown_seconds": 1.5,
  "long_word_len": 8,
  "long_word_bonus": 3,
  "ai_model": "anthropic/claude-3-haiku:beta",
  "max_ai_players": 5,
  "command_prefix": "?"
}
```

### Configuration Manager

Use the interactive configuration manager script:

```bash
python config-manager.py
```

This provides a user-friendly interface to modify game settings without editing JSON manually.
4. **Run the Bot**:
   ```
   python main.py
   ```

## Docker Setup

### Using Docker Compose (Recommended)

1. **Ensure Docker and Docker Compose are installed**
2. **Build and run the bot**:
   ```bash
   docker-compose up -d
   ```
3. **View logs**:
   ```bash
   docker-compose logs -f word-chain-bot
   ```
4. **Stop the bot**:
   ```bash
   docker-compose down
   ```

### Using Docker directly

1. **Build the image**:
   ```bash
   docker build -t word-chain-bot .
   ```
2. **Run the container**:
   ```bash
   docker run -d \
     --name word-chain-bot \
     --env-file .env \
     -v $(pwd)/scores.json:/app/scores.json \
     -v $(pwd)/data:/app/data \
     word-chain-bot
   ```
3. **View logs**:
   ```bash
   docker logs -f word-chain-bot
   ```

### Docker Helper Script

A helper script is provided for common Docker operations (Linux/macOS):

```bash
# Make script executable (first time only)
chmod +x docker-helper.sh

# Build the image
./docker-helper.sh build

# Start the bot
./docker-helper.sh up

# View logs
./docker-helper.sh logs

# Stop the bot
./docker-helper.sh down

# Restart the bot
./docker-helper.sh restart

# Open shell in container
./docker-helper.sh shell

# Clean up everything
./docker-helper.sh clean
```

### Manual Docker Commands

If you prefer manual commands:

```bash
# Build
docker-compose build

# Run
docker-compose up -d

# Logs
docker-compose logs -f word-chain-bot

# Stop
docker-compose down
```

### Docker Environment

- **Persistent Data**: Scores are stored in `scores.json` and mounted as a volume
- **Environment Variables**: Loaded from `.env` file
- **Automatic Restarts**: Container restarts automatically unless stopped manually
- **Data Directory**: Additional data can be stored in the `./data` directory

## 🏗️ Technical Architecture

### Core Components
- **Game State Management**: Thread-safe per-channel game state with activity tracking
- **Async Task System**: Non-blocking timer management with proper cancellation
- **Locking System**: Comprehensive async locks for data integrity
- **Memory Management**: Automatic cleanup of inactive resources
- **Persistence Layer**: Atomic file operations for score data

### Dependencies
- **discord.py**: Discord API wrapper for bot functionality
- **aiohttp**: Asynchronous HTTP client for hints and AI requests
- **openai**: OpenRouter API integration for AI players
- **python-dotenv**: Environment variable management
- **asyncio**: Python's asynchronous programming framework
- **dataclasses**: Type-safe data structures for game state

### Security Features
- **Input Validation**: Comprehensive word and command validation
- **Rate Limiting**: Anti-spam cooldowns and flood protection
- **Thread Safety**: Protected concurrent operations
- **Resource Cleanup**: Automatic memory management
- **Error Isolation**: Graceful error handling without crashes

## 🧪 Testing the Bot

1. **Create a Test Discord Server**: Create a private Discord server for testing
2. **Invite the Bot**: Use the OAuth2 URL from Discord Developer Portal to invite your bot
3. **Test Basic Commands**:
   - `!join` - Join the game
   - `!add_ai Bot` - Add an AI player
   - `!start_game` - Start a new game
   - Submit words (e.g., "apple", then "elephant", etc.)
4. **Test Advanced Features**:
   - `!hint` - Get word suggestions
   - `!scores` - View leaderboard
   - `!status` - Check game status
   - `!settime 30` - Change turn time (admin)
5. **Verify Thread Safety**:
   - Multiple players submitting simultaneously
   - Timer expiration during active play
   - Concurrent command usage
6. **Test AI Integration**:
   - AI player responses
   - AI scoring on leaderboard
   - AI removal and addition

## 🔧 Troubleshooting

### Common Issues

**Bot not responding to commands:**
- Check if the bot is online in your Discord server
- Verify the command prefix (default: `!`)
- Ensure bot has proper permissions in the channel

**Word validation not working:**
- Confirm `words.txt` file exists and is readable
- Check if the bot loaded the dictionary on startup
- Verify word format (letters only, 2+ characters)

**AI players not responding:**
- Check OpenRouter API key in `.env` file
- Verify internet connection for API calls
- Check bot logs for API errors

**Timer not working:**
- Ensure the bot has permission to send messages
- Check for thread safety issues in logs
- Verify timer configuration in `config.json`

**Memory usage increasing:**
- The bot automatically cleans up inactive games
- Check for long-running games that may need manual cleanup
- Monitor cooldown cleanup frequency

### Debug Mode
Run the bot with verbose logging:
```bash
python -c "import logging; logging.basicConfig(level=logging.DEBUG); import main"
```

### Performance Monitoring
- Check bot logs for performance warnings
- Monitor memory usage during extended play
- Verify cleanup tasks are running (check logs every hour)

## 🤝 Contributing

We welcome contributions! Please follow these guidelines:

1. **Fork the repository** and create a feature branch
2. **Test thoroughly** - ensure thread safety and performance
3. **Update documentation** - keep README and code comments current
4. **Follow code style** - maintain consistency with existing codebase
5. **Submit a pull request** with a clear description of changes

### Development Setup
```bash
git clone https://github.com/your-username/Word-Chain-Game.git
cd Word-Chain-Game
pip install -r requirements.txt
cp .env.example .env
# Configure your tokens in .env
python main.py
```

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- **Discord.py** community for the excellent Discord API wrapper
- **OpenRouter** for providing AI API access
- **Datamuse** for the word suggestion API
- **Python** asyncio community for concurrency patterns

---

**Enjoy playing Word Chain! 🎮**

## 🆕 Recent Improvements

### Thread Safety & Performance
- **Advanced Locking System**: Implemented comprehensive async locks to prevent race conditions
- **Memory Leak Prevention**: Automatic cleanup of inactive games and cooldowns
- **State Management**: Thread-safe game state modifications with activity tracking
- **Resource Optimization**: Background cleanup tasks for optimal memory usage

### Reliability Enhancements
- **Error Handling**: Improved exception handling in async operations
- **Task Management**: Enhanced task cancellation and resource cleanup
- **Data Integrity**: Atomic file operations for score persistence
- **Concurrent Safety**: Protected all shared data structures with appropriate locks

## 🎮 How to Play

- Players join using `!join` or add AI players with `!add_ai [name]`
- Use `!start_game` to start a new game
- Players (human and AI) take turns saying words that start with the last letter of the previous word
- Words must be valid English words (checked against local dictionary)
- Words cannot be repeated
- Each valid word earns 1 point + bonus points:
  - **Long words** (7+ letters): +2 bonus points
  - **Personal streaks** (3+ consecutive turns): +1 bonus point
  - **Channel combos** (every 5 words): +1 bonus point
- Anti-spam: 2-second cooldown between submissions
- Time limit: 20 seconds per turn (auto-skip if timeout, AI plays instantly)
- If it's not your turn, the bot will remind you
- Use `!end_game` to end the game

## AI Features

- **AI Players**: Add up to 3 AI players using `!add_ai [name]` (e.g., `!add_ai GPT`)
- **Smart AI**: AI uses OpenRouter GPT-3.5-turbo to generate valid words that follow chain rules
- **Instant Turns**: AI players respond immediately (no 20-second timer)
- **Fair Competition**: AI earns points and appears on leaderboards just like human players
- **Easy Management**: Add/remove AI players with `!add_ai` and `!remove_ai` commands

## 📋 Commands

### Game Management
- `!join` - Join the current game
- `!leave` - Leave the current game
- `!start_game` - Start a new word chain game
- `!end_game` - End the current game and save scores

### AI Players
- `!add_ai [name]` - Add an AI player to compete (max 3 by default)
- `!remove_ai [name]` - Remove an AI player from the game

### Scoring & Stats
- `!scores` - Display the global leaderboard (top 10 players including AI)
- `!myscore` - Check your personal score
- `!status` - Show current game status

### Game Features
- `!hint` - Get word suggestions for the current required letter
- `!settime [seconds]` - Set turn time for the current channel (admin only)
- `!reload_config` - Reload configuration from config.json file (admin only)
- `!clear_channel` - Clear all game data for the current channel (admin only)
- `!reset_scores` - Reset all scores (admin only)

## ⚡ Performance Optimizations

- **Local Dictionary**: Pre-loaded English word list (~466,550 words) for instant validation
- **O(1) Lookup**: Words checked against hash set for sub-millisecond response
- **Thread Safety**: Advanced async locking prevents race conditions and data corruption
- **Memory Management**: Automatic cleanup of inactive games and expired cooldowns
- **Atomic Operations**: File I/O operations prevent data corruption during saves
- **Resource Optimization**: Background cleanup tasks maintain optimal memory usage
- **No API Latency**: Eliminates delays from external dictionary services
- **Optimized Scoring**: Efficient bonus calculation with minimal computational overhead

## Features

- **High-Performance Word Validation**: Local dictionary with instant O(1) lookups
- **Thread-Safe Operations**: Advanced locking system prevents race conditions
- **Memory Leak Prevention**: Automatic cleanup of inactive resources
- **Turn-Based Gameplay**: Sequential player turns with timer enforcement
- **AI Integration**: OpenRouter-powered AI players with configurable models
- **Advanced Scoring System**: Multiple bonus types (streaks, combos, long words)
- **Anti-Spam Protection**: Configurable cooldown system
- **Visual Progress Bars**: Real-time turn timer display
- **Persistent Leaderboards**: Global scoring with automatic saving
- **Word Hint System**: Datamuse API integration for suggestions
- **Flexible Configuration**: Extensive customization via config files
- **Docker Support**: Containerized deployment with Docker Compose
- **Admin Controls**: Channel management and configuration commands

