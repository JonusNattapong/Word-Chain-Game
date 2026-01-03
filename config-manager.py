#!/usr/bin/env python3
"""
Word Chain Game Configuration Manager
Helps manage config.json settings
"""

import json
import os
from config import GameConfig

def main():
    config_file = "config.json"

    print("Word Chain Game - Configuration Manager")
    print("=" * 50)

    # Load current config
    config = GameConfig()

    print("\nCurrent Configuration:")
    print(f"Turn seconds: {config.turn_seconds}")
    print(f"AI Model: {config.ai_model}")
    print(f"Max AI players: {config.max_ai_players}")
    print(f"Long word length: {config.long_word_len}")
    print(f"Command prefix: {config.command_prefix}")

    print("\nOptions:")
    print("1. Edit turn time")
    print("2. Change AI model")
    print("3. Set max AI players")
    print("4. Modify scoring settings")
    print("5. Change command prefix")
    print("6. Reset to defaults")
    print("7. Save current config")
    print("8. Exit")

    choice = input("\nEnter your choice (1-8): ").strip()

    if choice == "1":
        try:
            new_time = int(input(f"Enter turn time in seconds ({config.min_turn_time}-{config.max_turn_time}): "))
            if config.min_turn_time <= new_time <= config.max_turn_time:
                config.turn_seconds = new_time
                print(f"Turn time set to {new_time} seconds")
            else:
                print("Invalid turn time")
        except ValueError:
            print("Invalid input")

    elif choice == "2":
        models = [
            "meta-llama/llama-3.1-405b-instruct:free",
            "anthropic/claude-3-haiku:beta",
            "openai/gpt-3.5-turbo",
            "google/gemini-pro"
        ]
        print("\nAvailable AI models:")
        for i, model in enumerate(models, 1):
            print(f"{i}. {model}")

        try:
            model_choice = int(input("Choose model (1-4): ")) - 1
            if 0 <= model_choice < len(models):
                config.ai_model = models[model_choice]
                print(f"AI model set to {config.ai_model}")
            else:
                print("Invalid choice")
        except ValueError:
            print("Invalid input")

    elif choice == "3":
        try:
            max_ai = int(input("Enter max AI players (0-10): "))
            if 0 <= max_ai <= 10:
                config.max_ai_players = max_ai
                print(f"Max AI players set to {max_ai}")
            else:
                print("Invalid number")
        except ValueError:
            print("Invalid input")

    elif choice == "4":
        print("\nScoring Settings:")
        print(f"1. Long word length: {config.long_word_len}")
        print(f"2. Long word bonus: {config.long_word_bonus}")
        print(f"3. Streak minimum: {config.streak_min}")
        print(f"4. Streak bonus: {config.streak_bonus}")

        sub_choice = input("Which setting to change? (1-4): ").strip()

        if sub_choice == "1":
            try:
                config.long_word_len = int(input("Long word length: "))
            except ValueError:
                print("Invalid input")
        elif sub_choice == "2":
            try:
                config.long_word_bonus = int(input("Long word bonus: "))
            except ValueError:
                print("Invalid input")
        elif sub_choice == "3":
            try:
                config.streak_min = int(input("Streak minimum: "))
            except ValueError:
                print("Invalid input")
        elif sub_choice == "4":
            try:
                config.streak_bonus = int(input("Streak bonus: "))
            except ValueError:
                print("Invalid input")

    elif choice == "5":
        prefix = input("Enter new command prefix (single character): ").strip()
        if len(prefix) == 1:
            config.command_prefix = prefix
            print(f"Command prefix set to '{prefix}'")
        else:
            print("Prefix must be a single character")

    elif choice == "6":
        config = GameConfig()
        config._set_defaults()
        print("Configuration reset to defaults")

    elif choice == "7":
        pass  # Will save below

    elif choice == "8":
        print("Goodbye!")
        return

    else:
        print("Invalid choice")
        return

    # Save configuration
    try:
        config.save_to_file()
        print(f"\nConfiguration saved to {config_file}")
        print("Use '!reload_config' in Discord to apply changes without restarting the bot")
    except Exception as e:
        print(f"Error saving configuration: {e}")

if __name__ == "__main__":
    main()