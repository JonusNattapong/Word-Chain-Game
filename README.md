# Word-Chain-Game

A Discord bot for playing the word chain game.

## Creating Your Discord Bot

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

## Setup

1. **Clone/Download this code**
2. **Install Python dependencies**:
   ```
   pip install -r requirements.txt
   ```
3. **Configure Environment**:
   Create a `.env` file with:
   ```
   DISCORD_TOKEN=your_bot_token_here
   OPENROUTER_API_KEY=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
   ```
   Replace with your actual tokens. You can copy `.env.example` as a template.

4. **Configure Game Settings** (Optional):
   Edit `config.json` to customize game settings:
   ```json
   {
     "turn_seconds": 20,
     "cooldown_seconds": 2.0,
     "long_word_len": 7,
     "long_word_bonus": 2,
     "ai_model": "meta-llama/llama-3.1-405b-instruct:free",
     "max_ai_players": 3
   }
   ```
   Use `!reload_config` command to apply changes without restarting the bot.

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

## Libraries Used

- **discord.py**: Main Discord API wrapper (https://discordpy.readthedocs.io/)
- **python-dotenv**: Environment variable management
- **pyspellchecker**: English word validation
- **requests**: HTTP requests for word hints API
- **openai**: OpenRouter API for AI players (https://openai.com/)

## Testing the Bot

1. **Create a Test Discord Server**: Create a private Discord server for testing
2. **Invite the Bot**: Use the OAuth2 URL from Discord Developer Portal to invite your bot to the test server
3. **Test Commands**:
   - `!join` - Join the game
   - `!add_ai [name]` - Add an AI player (e.g., `!add_ai Bot`)
   - `!start_game` - Start a new game
   - Submit words (e.g., "apple", then "elephant", etc.)
   - `!hint` - Get word suggestions
   - `!scores` - View leaderboard
   - `!myscore` - Check personal score
   - `!end_game` - End the game
4. **Verify Features**:
   - Turn-based gameplay (only current player's turn accepted)
   - Word validation (invalid words rejected)
   - Chain rules (words must start with correct letter)
   - Scoring (points awarded for valid words)
   - Hints (suggestions for next words)

## Troubleshooting

- **Bot not responding**: Check if token is correct and bot is online
- **Commands not working**: Ensure bot has proper permissions in the server
- **Word validation issues**: Make sure pyspellchecker is installed correctly
- **Hint not working**: Check internet connection for API calls

## How to Play

- Players join using `!join` or add AI players with `!add_ai [name]`
- Use `!start_game` to start a new game
- Players (human and AI) take turns saying words that start with the last letter of the previous word
- Words must be valid English words (checked against dictionary)
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

## Commands

- `!join`: Join the current game
- `!add_ai [name]`: Add an AI player to compete (configurable max AI players)
- `!remove_ai [name]`: Remove an AI player from the game
- `!start_game`: Start a new word chain game (after players join)
- `!reload_config`: Reload configuration from config.json file
- `!settime [seconds]`: Set turn time for the current channel
- `!hint`: Get word suggestions for the current required letter
- `!scores`: Display the leaderboard (top 10 players including AI)
- `!myscore`: Check your personal score
- `!status`: Show current game status
- `!end_game`: End the current game and save scores

## Performance Optimizations

- **Local Dictionary**: Uses pre-loaded English word list (~466,550 words) for instant validation
- **O(1) Lookup**: Words checked against hash set for sub-millisecond response
- **Race Condition Protection**: Async locks prevent timer conflicts with message processing
- **No API Latency**: Eliminates 1.5-5 second delays from external dictionary APIs
- **Optimized Scoring**: Efficient bonus calculation with minimal overhead

## Features

- **High-Performance Word Validation**: Local dictionary with instant O(1) lookups
- Turn-based gameplay with player joining
- Prevents duplicate words
- Enforces chain rules
- Bonus scoring system:
  - Long words bonus (+2 points for 7+ letters)
  - Personal streak bonuses (+1 point for 3+ consecutive turns)
  - Channel combo bonuses (+1 point every 5 words)
- Anti-spam cooldown protection (2-second minimum between submissions)
- Turn timer with auto-skip (20 seconds per turn)
- Visual progress bar for time indication
- Race condition protection with async locks
- Persistent scoring system
- Leaderboard ranking
- Word hint system using Datamuse API

