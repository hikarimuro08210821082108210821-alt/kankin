import discord
from discord.ext import commands
from functools import wraps
import json
import os

_DIR = os.path.dirname(os.path.abspath(__file__))
ALLOWED_USERS_FILE = os.path.join(_DIR, "allowed_users.json")


def load_allowed_users() -> list:
    if os.path.exists(ALLOWED_USERS_FILE):
        with open(ALLOWED_USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_allowed_users(data: list):
    with open(ALLOWED_USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def is_allowed():
    def decorator(func):
        @wraps(func)
        async def wrapper(self, interaction: discord.Interaction, *args, **kwargs):
            allowed = load_allowed_users()
            if not allowed or str(interaction.user.id) in allowed:
                return await func(self, interaction, *args, **kwargs)
            embed = discord.Embed(
                title="❌ 権限エラー",
                description="このコマンドは管理者のみ実行することができます。",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        return wrapper
    return decorator
