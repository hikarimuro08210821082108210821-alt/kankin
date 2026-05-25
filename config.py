import json
import os

_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(_DIR, "config.json")

DEFAULT_CONFIG = {
    "discord_token": "MTUwMTgxNzUyNjE1NjM5ODY0Mg.GlvRYj.BqNGBEcgmjTHrawX48_ioItsF-uaCKB7sXgEg0",
    "money_rate": 95,
    "money_lite_rate": 80,
    "allowed_guild_id": None,
    "log_channel_id": None,
    "bot_paypay_phone": None,
    "bot_paypay_password": None
}

class Config:
    @staticmethod
    def load() -> dict:
        if not os.path.exists(CONFIG_FILE):
            Config.save(DEFAULT_CONFIG)
            return DEFAULT_CONFIG.copy()
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        for key, val in DEFAULT_CONFIG.items():
            if key not in data:
                data[key] = val
        return data

    @staticmethod
    def save(data: dict):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
