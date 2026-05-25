import discord
from discord.ext import commands
import asyncio
import os
import sys
from config import Config

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

COGS = [
    "cogs.paypay",
    "cogs.exchange",
    "cogs.panel",
]

@bot.event
async def on_ready():
    print(f"[BOT] ログイン成功: {bot.user} (ID: {bot.user.id})")
    try:
        config = Config.load()
        guild_id = config.get("allowed_guild_id")
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            synced = await bot.tree.sync(guild=guild)
            print(f"[BOT] スラッシュコマンド同期完了（ギルド）: {len(synced)}個")
        else:
            synced = await bot.tree.sync()
            print(f"[BOT] スラッシュコマンド同期完了（グローバル）: {len(synced)}個")
    except Exception as e:
        print(f"[BOT] コマンド同期エラー: {e}")

async def load_cogs():
    for cog in COGS:
        try:
            await bot.load_extension(cog)
            print(f"[COG] ロード成功: {cog}")
        except Exception as e:
            print(f"[COG] ロード失敗 {cog}: {e}")

async def main():
    config = Config.load()
    token = config.get("discord_token", "")

    if not token or token == "YOUR_DISCORD_BOT_TOKEN_HERE":
        print("[ERROR] config.jsonにDiscordボットトークンを設定してください。")
        sys.exit(1)

    async with bot:
        await load_cogs()
        await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())
