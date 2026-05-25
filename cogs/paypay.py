import discord
from discord import ui
from discord.ext import commands
from discord import app_commands
import json
import os
import uuid
from utils import is_allowed
import paypayu

_COGS_DIR = os.path.dirname(os.path.abspath(__file__))
_BASE_DIR = os.path.dirname(_COGS_DIR)

PAYPAY_DATA_FILE = os.path.join(_BASE_DIR, "paypay_data.json")

def load_paypay_data():
    if os.path.exists(PAYPAY_DATA_FILE):
        with open(PAYPAY_DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_paypay_data(data):
    with open(PAYPAY_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


class PayPayOTPModal(ui.Modal, title="PayPay OTP認証"):
    def __init__(self, phone, password, set_uuid, otpid, otp_pre):
        super().__init__(timeout=300)
        self.phone = phone
        self.password = password
        self.set_uuid = set_uuid
        self.otpid = otpid
        self.otp_pre = otp_pre

    otp_input = ui.TextInput(
        label="ワンタイムパスワード",
        placeholder="SMSに届いた4桁の認証コードを入力",
        min_length=4,
        max_length=6,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        otp_result = await paypayu.login_otp(self.set_uuid, self.otp_input.value, self.otpid, self.otp_pre)

        if otp_result == "OK":
            paypay_data = load_paypay_data()
            user_id_str = str(interaction.user.id)
            paypay_data[user_id_str] = {
                "phone": self.phone,
                "password": self.password,
                "uuid": self.set_uuid
            }
            save_paypay_data(paypay_data)
            embed = discord.Embed(
                title="✅ PayPay登録完了",
                description="PayPayアカウント情報の登録が完了しました。",
                color=discord.Color.green()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

        elif otp_result == "ERR":
            embed = discord.Embed(
                title="❌ PayPayログインエラー",
                description="OTPコードが正しくありません。",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

        else:
            embed = discord.Embed(
                title="⚠️ PayPayログインエラー",
                description="開発者にお問い合わせください。",
                color=discord.Color.orange()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)


class PaypayCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        if not os.path.exists(PAYPAY_DATA_FILE):
            save_paypay_data({})

    @app_commands.command(name="paypayログイン", description="PayPayアカウントにログインします")
    @is_allowed()
    @app_commands.describe(phone="電話番号（例: 09012345678）", password="PayPayパスワード")
    async def paypay_login(self, interaction: discord.Interaction, phone: str, password: str):
        set_uuid = str(uuid.uuid4())
        result = await paypayu.login(phone, password, set_uuid)

        if result.get("response_type") == "ErrorResponse":
            embed = discord.Embed(
                title="❌ PayPayログインエラー",
                description="```ログイン情報とパスワードが一致していません。\n情報を正しく入力してください。```",
                color=0xff3333
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        otpid = result.get("otp_reference_id")
        otp_pre = result.get("otp_prefix")
        modal = PayPayOTPModal(phone, password, set_uuid, otpid, otp_pre)
        await interaction.response.send_modal(modal)

    @app_commands.command(name="paypay情報", description="登録済みのPayPayアカウント情報を確認します")
    @is_allowed()
    async def paypay_info(self, interaction: discord.Interaction):
        paypay_data = load_paypay_data()
        user_id_str = str(interaction.user.id)

        if user_id_str not in paypay_data:
            embed = discord.Embed(
                title="PayPay情報なし",
                description="/paypayログイン でアカウントを登録してください。",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        data = paypay_data[user_id_str]
        embed = discord.Embed(title="📱 PayPay登録情報", color=discord.Color.blue())
        embed.add_field(name="電話番号", value=f"||{data['phone']}||", inline=False)
        embed.add_field(name="ステータス", value="✅ 登録済み", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="paypay削除", description="登録済みのPayPayアカウント情報を削除します")
    @is_allowed()
    async def paypay_delete(self, interaction: discord.Interaction):
        paypay_data = load_paypay_data()
        user_id_str = str(interaction.user.id)

        if user_id_str in paypay_data:
            del paypay_data[user_id_str]
            save_paypay_data(paypay_data)
            embed = discord.Embed(
                title="🗑️ 削除完了",
                description="PayPayアカウント情報を削除しました。",
                color=discord.Color.green()
            )
        else:
            embed = discord.Embed(
                title="情報なし",
                description="削除するアカウント情報が見つかりません。",
                color=discord.Color.orange()
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(PaypayCog(bot))
