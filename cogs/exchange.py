import discord
from discord import ui
from discord.ext import commands
from discord import app_commands
import json
import os
import datetime
from utils import is_allowed
import paypayu
import exodus_wallet
import price_api
from config import Config

_COGS_DIR = os.path.dirname(os.path.abspath(__file__))
_BASE_DIR = os.path.dirname(_COGS_DIR)

PAYPAY_DATA_FILE = os.path.join(_BASE_DIR, "paypay_data.json")
TRANSACTION_LOG_FILE = os.path.join(_BASE_DIR, "transactions.json")
EXODUS_DATA_FILE = os.path.join(_BASE_DIR, "exodus_data.json")


def load_paypay_data():
    if os.path.exists(PAYPAY_DATA_FILE):
        with open(PAYPAY_DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def load_transactions():
    if os.path.exists(TRANSACTION_LOG_FILE):
        with open(TRANSACTION_LOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_transactions(data):
    with open(TRANSACTION_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def log_transaction(user_id: str, jpy_amount: float, ltc_amount: float, to_address: str, txid: str, status: str):
    transactions = load_transactions()
    transactions.append({
        "user_id": user_id,
        "jpy_amount": jpy_amount,
        "ltc_amount": ltc_amount,
        "to_address": to_address,
        "txid": txid,
        "status": status,
        "timestamp": datetime.datetime.now().isoformat()
    })
    save_transactions(transactions)


def get_private_key() -> str:
    if os.path.exists(EXODUS_DATA_FILE):
        with open(EXODUS_DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("private_key", "")
    return ""


class ExchangeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="ltcレート", description="現在のLTC/JPYレートを確認します（CoinGecko）")
    async def ltc_rate(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            rate = await price_api.get_ltc_jpy_rate()
            if rate == 0:
                raise ValueError("レート取得失敗")
            embed = discord.Embed(
                title="💱 LTC/JPY レート",
                description=f"**¥{rate:,.0f}** / LTC",
                color=discord.Color.blue()
            )
            embed.set_footer(text="CoinGecko提供・本人確認不要")
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            embed = discord.Embed(
                title="❌ エラー",
                description=f"レートの取得に失敗しました: {e}",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(ExchangeCog(bot))
