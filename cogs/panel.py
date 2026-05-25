import discord
from discord import ui
from discord.ext import commands
from discord import app_commands
import json
import os
import uuid
import random
import datetime
from utils import is_allowed, load_allowed_users, save_allowed_users
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


def save_paypay_data(data):
    with open(PAYPAY_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


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


def load_exodus_data() -> dict:
    if os.path.exists(EXODUS_DATA_FILE):
        with open(EXODUS_DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_exodus_data(data: dict):
    with open(EXODUS_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def get_private_key() -> str:
    exodus_data = load_exodus_data()
    return exodus_data.get("private_key", "")


async def send_log(bot: commands.Bot, embed: discord.Embed):
    config = Config.load()
    channel_id = config.get("log_channel_id")
    if not channel_id:
        return
    try:
        channel = bot.get_channel(int(channel_id))
        if channel:
            await channel.send(embed=embed)
    except Exception as e:
        print(f"[LOG] ログチャンネルへの送信失敗: {e}")


# ─────────────────────────────────────────────
# PayPay登録モーダル（送金リンク金額確認のみ）
# ─────────────────────────────────────────────
class PayPayRegisterModal(ui.Modal):
    def __init__(self, required_amount: int):
        super().__init__(title=f"{required_amount}円を送金して下さい", timeout=300)
        self.required_amount = required_amount

        self.link_input = ui.TextInput(
            label="PayPay送金リンク",
            placeholder="https://pay.paypay.ne.jp/xxxxxxxx",
            min_length=10,
            max_length=200,
            required=True
        )
        self.add_item(self.link_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        link = self.link_input.value.strip()

        embed_checking = discord.Embed(
            title="⏳ 確認中...",
            description="送金リンクの金額を確認しています...",
            color=discord.Color.yellow()
        )
        await interaction.followup.send(embed=embed_checking, ephemeral=True)

        link_info = await paypayu.check_link(link)
        if not link_info:
            embed = discord.Embed(
                title="❌ 登録失敗",
                description="送金リンクが無効か、すでに受け取り済みです。\n有効なリンクを入力してください。",
                color=discord.Color.red()
            )
            await interaction.edit_original_response(embed=embed)
            return

        amount_info = link_info.get("payload", {}).get("pendingP2PInfo", {})
        link_amount = int(amount_info.get("amount", 0))

        if link_amount != self.required_amount:
            embed = discord.Embed(
                title="❌ 登録失敗",
                description=(
                    f"送金リンクの金額が一致しません。\n\n"
                    f"必要な金額: **¥{self.required_amount}**\n"
                    f"リンクの金額: **¥{link_amount}**"
                ),
                color=discord.Color.red()
            )
            await interaction.edit_original_response(embed=embed)
            return

        # 送信者のPayPay IDを取得して登録情報に保存（バグ2対応）
        sender_id = amount_info.get("senderId", "") or amount_info.get("externalSenderId", "")

        paypay_data = load_paypay_data()
        user_id_str = str(interaction.user.id)
        paypay_data[user_id_str] = {
            "registered_at": datetime.datetime.now().isoformat(),
            "paypay_sender_id": sender_id
        }
        save_paypay_data(paypay_data)

        embed = discord.Embed(
            title="✅ 登録完了",
            description="PayPay本人確認が完了しました。\nパネルの「💱 換金する」から換金できます。",
            color=discord.Color.green()
        )
        await interaction.edit_original_response(embed=embed)


# ─────────────────────────────────────────────
# 登録開始ボタン（金額確認後に押す）
# ─────────────────────────────────────────────
class StartRegisterView(ui.View):
    def __init__(self, required_amount: int):
        super().__init__(timeout=300)
        self.required_amount = required_amount

    @ui.button(label="登録フォームを開く", style=discord.ButtonStyle.primary)
    async def open_modal(self, interaction: discord.Interaction, button: ui.Button):
        modal = PayPayRegisterModal(self.required_amount)
        await interaction.response.send_modal(modal)


# ─────────────────────────────────────────────
# 再登録確認ボタン（登録済みの場合）
# ─────────────────────────────────────────────
class ReRegisterView(ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @ui.button(label="再登録する", style=discord.ButtonStyle.danger)
    async def re_register(self, interaction: discord.Interaction, button: ui.Button):
        required_amount = random.randint(10, 30)
        embed = discord.Embed(
            title="📱 PayPay再登録",
            description=f"**{required_amount}円**の送金リンクを作成して入力してください。",
            color=discord.Color.blue()
        )
        await interaction.response.edit_message(embed=embed, view=StartRegisterView(required_amount))


# ─────────────────────────────────────────────
# Exodus秘密鍵登録モーダル
# ─────────────────────────────────────────────
class ExodusKeyModal(ui.Modal, title="Exodus LTC 秘密鍵登録"):
    key_input = ui.TextInput(
        label="秘密鍵（WIF形式）",
        placeholder="TまたはLまたは6で始まる秘密鍵を入力",
        min_length=50,
        max_length=55,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        key = self.key_input.value.strip()

        try:
            address = exodus_wallet.get_ltc_address_from_private_key(key)
        except Exception:
            embed = discord.Embed(
                title="❌ 秘密鍵エラー",
                description="秘密鍵が正しくありません。WIF形式の秘密鍵を確認してください。",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        save_exodus_data({"private_key": key})

        embed = discord.Embed(
            title="✅ 秘密鍵登録完了",
            description=f"Exodusウォレットの秘密鍵を登録しました。\n\nウォレットアドレス: `{address}`",
            color=discord.Color.green()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


# ─────────────────────────────────────────────
# BotのPayPay認証情報登録モーダル
# ─────────────────────────────────────────────
class BotLoginModal(ui.Modal, title="BotのPayPayログイン"):
    phone_input = ui.TextInput(
        label="PayPay 電話番号",
        placeholder="例: 09012345678",
        min_length=10,
        max_length=13,
        required=True
    )
    password_input = ui.TextInput(
        label="PayPay パスワード",
        placeholder="PayPayのパスワードを入力",
        min_length=1,
        max_length=50,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        phone = self.phone_input.value.strip()
        password = self.password_input.value.strip()

        result = await paypayu.start_login(phone, password)

        if result["status"] == "ok":
            embed = discord.Embed(
                title="✅ ログイン完了",
                description="OTP不要でログインできました。換金が利用可能になりました。",
                color=discord.Color.green()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

        elif result["status"] == "otp":
            embed = discord.Embed(
                title="📱 OTPを確認してください",
                description=(
                    "PayPayから SMS でOTPコードが届きます。\n"
                    "届いたら下のボタンを押してコードを入力してください。"
                ),
                color=discord.Color.blue()
            )
            await interaction.followup.send(embed=embed, view=BotOTPView(), ephemeral=True)

        else:
            embed = discord.Embed(
                title="❌ ログイン失敗",
                description="電話番号またはパスワードが正しくありません。",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)


class BotOTPView(ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @ui.button(label="OTPを入力する", style=discord.ButtonStyle.primary)
    async def enter_otp(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(BotOTPModal())


class BotOTPModal(ui.Modal, title="OTPコードを入力"):
    otp_input = ui.TextInput(
        label="SMSで届いたOTPコード",
        placeholder="例: 123456",
        min_length=4,
        max_length=8,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        otp = self.otp_input.value.strip()
        success = await paypayu.complete_login(otp)

        if success:
            embed = discord.Embed(
                title="✅ ログイン完了",
                description="PayPayへのログインが完了しました。換金が利用可能になりました。",
                color=discord.Color.green()
            )
        else:
            embed = discord.Embed(
                title="❌ OTP認証失敗",
                description="OTPコードが正しくないか期限切れです。\n`/bot-paypayログイン` からやり直してください。",
                color=discord.Color.red()
            )
        await interaction.followup.send(embed=embed, ephemeral=True)


# ─────────────────────────────────────────────
# 種類選択セレクトメニュー → 換金モーダルを開く
# ─────────────────────────────────────────────
class MoneyTypeSelect(ui.Select):
    def __init__(self):
        config = Config.load()
        money_rate = int(config.get("money_rate", 95))
        money_lite_rate = int(config.get("money_lite_rate", 80))
        options = [
            discord.SelectOption(
                label=f"💴 PayPayマネー（換金率 {money_rate}%）",
                value="money",
                description=f"1円あたり {money_rate}% 分のLTCを受け取れます"
            ),
            discord.SelectOption(
                label=f"🪙 PayPayマネーライト（換金率 {money_lite_rate}%）",
                value="money_lite",
                description=f"1円あたり {money_lite_rate}% 分のLTCを受け取れます"
            ),
        ]
        super().__init__(placeholder="PayPayマネーの種類を選択してください", options=options)

    async def callback(self, interaction: discord.Interaction):
        money_type = self.values[0]
        modal = ExchangeModal(money_type)
        await interaction.response.send_modal(modal)


class MoneyTypeSelectView(ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.add_item(MoneyTypeSelect())


# ─────────────────────────────────────────────
# 換金モーダル（Botアカウントで匿名受け取り）
# ─────────────────────────────────────────────
class ExchangeModal(ui.Modal):
    def __init__(self, money_type: str):
        config = Config.load()
        if money_type == "money_lite":
            rate_label = f"PayPayマネーライト（{int(config.get('money_lite_rate', 80))}%）"
        else:
            rate_label = f"PayPayマネー（{int(config.get('money_rate', 95))}%）"
        super().__init__(title=f"換金: {rate_label}", timeout=300)
        self.money_type = money_type

        self.link_input = ui.TextInput(
            label="PayPay送金リンク",
            placeholder="https://pay.paypay.ne.jp/xxxxxxxx",
            min_length=10,
            max_length=200,
            required=True
        )
        self.link_password_input = ui.TextInput(
            label="リンクパスワード（ある場合のみ）",
            placeholder="パスワードなしの場合は空欄",
            required=False,
            max_length=20
        )
        self.ltc_address_input = ui.TextInput(
            label="送金先LTCアドレス",
            placeholder="LまたはMまたはltc1で始まるアドレス",
            min_length=26,
            max_length=62,
            required=True
        )
        self.add_item(self.link_input)
        self.add_item(self.link_password_input)
        self.add_item(self.ltc_address_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        user_id_str = str(interaction.user.id)
        paypay_data = load_paypay_data()

        if user_id_str not in paypay_data:
            embed = discord.Embed(
                title="❌ 未登録",
                description="先に「📱 PayPay登録」ボタンで本人確認を完了してください。",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        link = self.link_input.value.strip()
        link_pass = self.link_password_input.value.strip() or None
        to_ltc_address = self.ltc_address_input.value.strip()

        creds = paypayu.load_credentials()
        if not creds:
            embed = discord.Embed(
                title="❌ 設定エラー",
                description="BotがPayPayにログインしていません。\n管理者に `/bot-paypayログイン` を実行してもらってください。",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        if not exodus_wallet.validate_ltc_address(to_ltc_address):
            embed = discord.Embed(
                title="❌ アドレスエラー",
                description="LTCアドレスの形式が正しくありません。\nLまたはMまたはltc1で始まるアドレスを入力してください。",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        private_key = get_private_key()
        if not private_key:
            embed = discord.Embed(
                title="❌ 設定エラー",
                description="Exodus秘密鍵が登録されていません。\n管理者に連絡してください。",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        embed_checking = discord.Embed(
            title="⏳ 処理中...",
            description="PayPayリンクを確認しています...",
            color=discord.Color.yellow()
        )
        await interaction.followup.send(embed=embed_checking, ephemeral=True)

        link_info = await paypayu.check_link(link)
        if not link_info:
            embed = discord.Embed(
                title="❌ リンクエラー",
                description="送金リンクが無効か、すでに受け取り済みです。",
                color=discord.Color.red()
            )
            await interaction.edit_original_response(embed=embed)
            return

        amount_info = link_info.get("payload", {}).get("pendingP2PInfo", {})
        jpy_amount = float(amount_info.get("amount", 0))

        if jpy_amount <= 0:
            embed = discord.Embed(
                title="❌ 金額エラー",
                description="送金金額を取得できませんでした。",
                color=discord.Color.red()
            )
            await interaction.edit_original_response(embed=embed)
            return

        # ── 登録アカウント照合チェック（バグ2対応）─────────────────
        exchange_sender_id = amount_info.get("senderId", "") or amount_info.get("externalSenderId", "")
        user_data = paypay_data.get(user_id_str, {})
        registered_sender_id = user_data.get("paypay_sender_id", "")

        if registered_sender_id and exchange_sender_id and registered_sender_id != exchange_sender_id:
            # 登録時と異なるPayPayアカウントから送金されている
            # → 送金リンクは受け取るが、LTCは送金しない
            embed_receiving = discord.Embed(
                title="⏳ 処理中...",
                description="PayPayリンクを受け取っています...",
                color=discord.Color.yellow()
            )
            await interaction.edit_original_response(embed=embed_receiving)

            device_uuid = creds.get("device_uuid") or str(uuid.uuid4())
            await paypayu.link_rev(link, creds["phone"], creds["password"], device_uuid, link_pass)

            log_transaction(user_id_str, jpy_amount, 0, "", "", "wrong_paypay_account")

            embed = discord.Embed(
                title="❌ 送金できません",
                description="登録されていないアカウントです。",
                color=discord.Color.red()
            )
            await interaction.edit_original_response(embed=embed)

            log_embed = discord.Embed(
                title="⚠️ 未登録アカウントで換金試行",
                color=discord.Color.orange(),
                timestamp=datetime.datetime.now()
            )
            log_embed.add_field(name="ユーザー", value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=False)
            log_embed.add_field(name="受け取り金額", value=f"¥{jpy_amount:,.0f}", inline=True)
            log_embed.add_field(name="登録済みPayPay ID", value=f"`{registered_sender_id}`", inline=False)
            log_embed.add_field(name="送信元PayPay ID", value=f"`{exchange_sender_id}`", inline=False)
            await send_log(interaction.client, log_embed)
            return
        # ────────────────────────────────────────────────────────────

        embed_rate = discord.Embed(
            title="⏳ 処理中...",
            description=f"¥{jpy_amount:,.0f} を確認しました。\nレートを取得中...",
            color=discord.Color.yellow()
        )
        await interaction.edit_original_response(embed=embed_rate)

        rate = await price_api.get_ltc_jpy_rate()
        if rate == 0:
            embed = discord.Embed(
                title="❌ レート取得失敗",
                description="LTC/JPYレートの取得に失敗しました。しばらく後にお試しください。",
                color=discord.Color.red()
            )
            await interaction.edit_original_response(embed=embed)
            return

        # ── 換金率を config から読み込み、LTC送金量を計算（バグ1対応）──
        config = Config.load()
        if self.money_type == "money_lite":
            exchange_rate = int(config.get("money_lite_rate", 80))
            money_type_label = "PayPayマネーライト"
        else:
            exchange_rate = int(config.get("money_rate", 95))
            money_type_label = "PayPayマネー"

        # exchange_rate = 93 のとき:
        #   ltc_amount = (jpy / rate) * 0.93  → 93% 分のLTCをユーザーに送金
        ltc_amount = round((jpy_amount / rate) * (exchange_rate / 100.0), 8)

        print(f"[EXCHANGE] type={self.money_type} rate={exchange_rate}% jpy={jpy_amount} ltc_rate={rate} ltc={ltc_amount}")

        if ltc_amount <= 0:
            embed = discord.Embed(
                title="❌ 換算エラー",
                description="LTC換算量の計算に失敗しました。",
                color=discord.Color.red()
            )
            await interaction.edit_original_response(embed=embed)
            return

        try:
            wallet_address = exodus_wallet.get_ltc_address_from_private_key(private_key)
            balance = await exodus_wallet.get_ltc_balance_async(wallet_address)
        except Exception as e:
            embed = discord.Embed(
                title="❌ ウォレットエラー",
                description=f"ウォレット情報の取得に失敗しました: `{e}`",
                color=discord.Color.red()
            )
            await interaction.edit_original_response(embed=embed)
            return

        if balance < ltc_amount:
            embed = discord.Embed(
                title="❌ 残高不足",
                description=(
                    f"Exodusウォレットの残高が不足しています。\n\n"
                    f"残高: **{balance:.8f} LTC**\n"
                    f"必要: **{ltc_amount:.8f} LTC**"
                ),
                color=discord.Color.red()
            )
            await interaction.edit_original_response(embed=embed)
            return

        embed_receiving = discord.Embed(
            title="⏳ 処理中...",
            description="PayPayリンクを受け取っています...",
            color=discord.Color.yellow()
        )
        await interaction.edit_original_response(embed=embed_receiving)

        device_uuid = creds.get("device_uuid") or str(uuid.uuid4())
        result = await paypayu.link_rev(
            link,
            creds["phone"],
            creds["password"],
            device_uuid,
            link_pass
        )

        if result == "LOGINERR":
            embed = discord.Embed(
                title="❌ PayPayログインエラー",
                description=(
                    "BotのPayPay認証情報が無効か、OTPが要求されました。\n"
                    "管理者に `/bot-paypayログイン` で再ログインしてもらってください。"
                ),
                color=discord.Color.red()
            )
            await interaction.edit_original_response(embed=embed)
            return

        if not result:
            embed = discord.Embed(
                title="❌ 受け取り失敗",
                description="PayPayリンクの受け取りに失敗しました。",
                color=discord.Color.red()
            )
            await interaction.edit_original_response(embed=embed)
            return

        embed_sending = discord.Embed(
            title="⏳ 処理中...",
            description=f"✅ PayPay ¥{jpy_amount:,.0f} 受け取り完了\nExodusからLTCを送金中...",
            color=discord.Color.yellow()
        )
        await interaction.edit_original_response(embed=embed_sending)

        send_result = await exodus_wallet.send_ltc(private_key, to_ltc_address, ltc_amount)

        if send_result.get("success"):
            txid = send_result.get("txid", "")
            log_transaction(user_id_str, jpy_amount, ltc_amount, to_ltc_address, txid, "completed")

            embed = discord.Embed(
                title="🎉 換金・送金完了！",
                color=discord.Color.green()
            )
            embed.add_field(name="マネー種別", value=money_type_label, inline=True)
            embed.add_field(name="換金率", value=f"{exchange_rate}%", inline=True)
            embed.add_field(name="受け取り金額", value=f"¥{jpy_amount:,.0f}", inline=True)
            embed.add_field(name="送金LTC量", value=f"**{ltc_amount:.8f} LTC**", inline=True)
            embed.add_field(name="送金先アドレス", value=f"`{to_ltc_address}`", inline=False)
            embed.add_field(name="トランザクションID", value=f"`{txid}`", inline=False)
            await interaction.edit_original_response(embed=embed)

            log_embed = discord.Embed(
                title="✅ 換金ログ",
                color=discord.Color.green(),
                timestamp=datetime.datetime.now()
            )
            log_embed.add_field(name="ユーザー", value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=False)
            log_embed.add_field(name="マネー種別", value=money_type_label, inline=True)
            log_embed.add_field(name="換金率", value=f"{exchange_rate}%", inline=True)
            log_embed.add_field(name="受け取り金額", value=f"¥{jpy_amount:,.0f}", inline=True)
            log_embed.add_field(name="送金LTC量", value=f"{ltc_amount:.8f} LTC", inline=True)
            log_embed.add_field(name="送金先アドレス", value=f"`{to_ltc_address}`", inline=False)
            log_embed.add_field(name="TXID", value=f"`{txid}`", inline=False)
            await send_log(interaction.client, log_embed)

        else:
            log_transaction(user_id_str, jpy_amount, ltc_amount, to_ltc_address, "", "paypay_received_ltc_failed")

            embed = discord.Embed(
                title="⚠️ PayPay受取済・LTC送金失敗",
                description=(
                    f"PayPayは受け取りましたが、LTCの送金に失敗しました。\n"
                    f"エラー: `{send_result.get('error', '不明')}`\n\n"
                    f"手動でExodusから送金してください。"
                ),
                color=discord.Color.orange()
            )
            embed.add_field(name="マネー種別", value=money_type_label, inline=True)
            embed.add_field(name="換金率", value=f"{exchange_rate}%", inline=True)
            embed.add_field(name="送金すべきLTC量", value=f"{ltc_amount:.8f} LTC", inline=True)
            embed.add_field(name="送金先アドレス", value=f"`{to_ltc_address}`", inline=False)
            await interaction.edit_original_response(embed=embed)

            log_embed = discord.Embed(
                title="⚠️ PayPay受取済・LTC送金失敗",
                color=discord.Color.orange(),
                timestamp=datetime.datetime.now()
            )
            log_embed.add_field(name="ユーザー", value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=False)
            log_embed.add_field(name="マネー種別", value=money_type_label, inline=True)
            log_embed.add_field(name="換金率", value=f"{exchange_rate}%", inline=True)
            log_embed.add_field(name="受け取り金額", value=f"¥{jpy_amount:,.0f}", inline=True)
            log_embed.add_field(name="送金LTC量", value=f"{ltc_amount:.8f} LTC", inline=True)
            log_embed.add_field(name="送金先アドレス", value=f"`{to_ltc_address}`", inline=False)
            await send_log(interaction.client, log_embed)


# ─────────────────────────────────────────────
# パネルのView（ボタン4つ）
# ─────────────────────────────────────────────
class ExchangePanelView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="📱 PayPay登録", style=discord.ButtonStyle.success, custom_id="panel_register", row=0)
    async def register_button(self, interaction: discord.Interaction, button: ui.Button):
        paypay_data = load_paypay_data()
        user_id_str = str(interaction.user.id)

        if user_id_str in paypay_data:
            embed = discord.Embed(
                title="✅ 登録済み",
                description="すでに本人確認が完了しています。",
                color=discord.Color.green()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True, view=ReRegisterView())
            return

        required_amount = random.randint(10, 30)
        embed = discord.Embed(
            title="📱 PayPay本人確認",
            description=f"**{required_amount}円**の送金リンクを作成して入力してください。",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True, view=StartRegisterView(required_amount))

    @ui.button(label="💼 残高確認", style=discord.ButtonStyle.secondary, custom_id="panel_balance", row=0)
    async def balance_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)

        private_key = get_private_key()
        if not private_key:
            embed = discord.Embed(
                title="❌ 設定エラー",
                description="Exodus秘密鍵が登録されていません。\n管理者に連絡してください。",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        try:
            wallet_address = exodus_wallet.get_ltc_address_from_private_key(private_key)
            balance = await exodus_wallet.get_ltc_balance_async(wallet_address)
            rate = await price_api.get_ltc_jpy_rate()
            jpy_value = balance * rate

            embed = discord.Embed(title="💼 Exodus LTC残高", color=discord.Color.blue())
            embed.add_field(name="LTC残高", value=f"**{balance:.8f} LTC**", inline=True)
            embed.add_field(name="JPY換算", value=f"¥{jpy_value:,.0f}", inline=True)
            embed.add_field(name="ウォレットアドレス", value=f"`{wallet_address}`", inline=False)
            embed.add_field(name="LTC/JPYレート", value=f"¥{rate:,.0f}/LTC", inline=False)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            embed = discord.Embed(
                title="❌ エラー",
                description=f"残高の取得に失敗しました: `{e}`",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

    @ui.button(label="💱 換金する", style=discord.ButtonStyle.primary, custom_id="panel_exchange", row=1)
    async def exchange_button(self, interaction: discord.Interaction, button: ui.Button):
        paypay_data = load_paypay_data()
        user_id_str = str(interaction.user.id)

        if user_id_str not in paypay_data:
            embed = discord.Embed(
                title="❌ 未登録",
                description="先に「📱 PayPay登録」ボタンで本人確認を完了してください。",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        config = Config.load()
        money_rate = int(config.get("money_rate", 95))
        money_lite_rate = int(config.get("money_lite_rate", 80))
        embed = discord.Embed(
            title="💱 換金するマネーの種類を選択",
            description=(
                f"💴 **PayPayマネー** — 換金率 **{money_rate}%**\n"
                f"🪙 **PayPayマネーライト** — 換金率 **{money_lite_rate}%**"
            ),
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed, view=MoneyTypeSelectView(), ephemeral=True)

    @ui.button(label="📊 取引履歴", style=discord.ButtonStyle.secondary, custom_id="panel_history", row=1)
    async def history_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)

        transactions = load_transactions()
        user_id_str = str(interaction.user.id)
        user_txs = [t for t in transactions if t.get("user_id") == user_id_str]

        if not user_txs:
            embed = discord.Embed(
                title="取引履歴なし",
                description="まだ取引履歴がありません。",
                color=discord.Color.orange()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(title="📊 取引履歴（直近5件）", color=discord.Color.blue())
        status_map = {
            "completed": "✅ 完了",
            "paypay_received_ltc_failed": "⚠️ PayPay受取済・LTC送金失敗",
            "wrong_paypay_account": "❌ 未登録アカウント"
        }
        for tx in user_txs[-5:]:
            status = status_map.get(tx.get("status"), tx.get("status"))
            txid = tx.get("txid", "なし")
            if txid and txid != "なし":
                value = f"状態: {status}\n日時: {tx.get('timestamp', '不明')[:19]}\nTXID: `{txid[:20]}...`"
            else:
                value = f"状態: {status}\n日時: {tx.get('timestamp', '不明')[:19]}"
            embed.add_field(
                name=f"¥{tx.get('jpy_amount', 0):,.0f} → {tx.get('ltc_amount', '?')} LTC",
                value=value,
                inline=False
            )
        await interaction.followup.send(embed=embed, ephemeral=True)


# ─────────────────────────────────────────────
# PanelCog
# ─────────────────────────────────────────────
class PanelCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(ExchangePanelView())

    @app_commands.command(name="パネル設置", description="換金パネルをこのチャンネルに設置します")
    @is_allowed()
    @app_commands.describe(
        money_rate="PayPayマネーの換金率（%）例: 95 → ユーザーに95%分のLTCを送金",
        money_lite_rate="PayPayマネーライトの換金率（%）例: 80 → ユーザーに80%分のLTCを送金"
    )
    async def setup_panel(
        self,
        interaction: discord.Interaction,
        money_rate: app_commands.Range[int, 1, 100] = None,
        money_lite_rate: app_commands.Range[int, 1, 100] = None
    ):
        config = Config.load()

        if money_rate is not None:
            config["money_rate"] = money_rate
        if money_lite_rate is not None:
            config["money_lite_rate"] = money_lite_rate
        if money_rate is not None or money_lite_rate is not None:
            Config.save(config)

        current_money_rate = int(config.get("money_rate", 95))
        current_money_lite_rate = int(config.get("money_lite_rate", 80))

        embed = discord.Embed(
            title="💱 PayPay → LTC 換金パネル",
            description=(
                "下のボタンから操作してください。\n\n"
                "📱 **初回のみPayPay登録が必要です。**）\n"
                "💼 **残高確認** — 換金可能なLTC残高を確認\n"
                "💱 **換金する** — PayPay送金リンクを入力してLTCに換金\n"
                "📊 **取引履歴** — 自分の過去の換金履歴を確認\n\n"
                "**── 現在の換金率 ──**\n"
                f"💴 PayPayマネー: **{current_money_rate}%**\n"
                f"🪙 PayPayマネーライト: **{current_money_lite_rate}%**"
            ),
            color=discord.Color.blue()
        )
        embed.set_footer(text="換金ルールをよくお読みください")
        await interaction.response.send_message(embed=embed, view=ExchangePanelView())

    @app_commands.command(name="レート変更", description="換金率のみを変更します（パネルの再設置は不要）")
    @is_allowed()
    @app_commands.describe(
        money_rate="PayPayマネーの換金率（1〜100%）",
        money_lite_rate="PayPayマネーライトの換金率（1〜100%）"
    )
    async def change_rate(
        self,
        interaction: discord.Interaction,
        money_rate: app_commands.Range[int, 1, 100] = None,
        money_lite_rate: app_commands.Range[int, 1, 100] = None
    ):
        config = Config.load()

        if money_rate is None and money_lite_rate is None:
            cur_money = int(config.get("money_rate", 95))
            cur_lite = int(config.get("money_lite_rate", 80))
            embed = discord.Embed(
                title="📊 現在の換金率",
                description=(
                    f"💴 PayPayマネー: **{cur_money}%**\n"
                    f"🪙 PayPayマネーライト: **{cur_lite}%**\n\n"
                    "変更するには引数を指定してください。\n"
                    "例: `/レート変更 money_rate:90 money_lite_rate:75`"
                ),
                color=discord.Color.blue()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        changes = []

        if money_rate is not None:
            old = int(config.get("money_rate", 95))
            config["money_rate"] = money_rate
            changes.append(f"💴 PayPayマネー: **{old}%** → **{money_rate}%**")

        if money_lite_rate is not None:
            old_lite = int(config.get("money_lite_rate", 80))
            config["money_lite_rate"] = money_lite_rate
            changes.append(f"🪙 PayPayマネーライト: **{old_lite}%** → **{money_lite_rate}%**")

        Config.save(config)

        embed = discord.Embed(
            title="✅ 換金率を変更しました",
            description="\n".join(changes),
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="exodus登録", description="ExodusウォレットのLTC秘密鍵（WIF形式）を登録します")
    @is_allowed()
    async def register_exodus(self, interaction: discord.Interaction):
        modal = ExodusKeyModal()
        await interaction.response.send_modal(modal)

    @app_commands.command(name="exodus情報", description="登録済みのExodusウォレット情報を確認します")
    @is_allowed()
    async def exodus_info(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        private_key = get_private_key()
        if not private_key:
            embed = discord.Embed(
                title="Exodus未登録",
                description="`/exodus登録` で秘密鍵を登録してください。",
                color=discord.Color.orange()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        try:
            address = exodus_wallet.get_ltc_address_from_private_key(private_key)
            embed = discord.Embed(title="💼 Exodus登録情報", color=discord.Color.blue())
            embed.add_field(name="ステータス", value="✅ 登録済み", inline=False)
            embed.add_field(name="ウォレットアドレス", value=f"`{address}`", inline=False)
        except Exception:
            embed = discord.Embed(
                title="⚠️ 秘密鍵エラー",
                description="登録済みの秘密鍵が無効です。`/exodus登録` で再登録してください。",
                color=discord.Color.orange()
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="exodus削除", description="登録済みのExodus秘密鍵を削除します")
    @is_allowed()
    async def exodus_delete(self, interaction: discord.Interaction):
        if os.path.exists(EXODUS_DATA_FILE):
            os.remove(EXODUS_DATA_FILE)
            embed = discord.Embed(
                title="🗑️ 削除完了",
                description="Exodus秘密鍵情報を削除しました。",
                color=discord.Color.green()
            )
        else:
            embed = discord.Embed(
                title="情報なし",
                description="削除する秘密鍵情報が見つかりません。",
                color=discord.Color.orange()
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="bot-paypayログイン", description="BotのPayPayアカウントにログインします（OTP対応）")
    @is_allowed()
    async def paypay_login(self, interaction: discord.Interaction):
        await interaction.response.send_modal(BotLoginModal())

    @app_commands.command(name="bot-paypayセッション確認", description="BotのPayPayログイン状態を確認します")
    @is_allowed()
    async def paypay_session_check(self, interaction: discord.Interaction):
        creds = paypayu.load_credentials()
        if creds:
            embed = discord.Embed(
                title="✅ ログイン済み",
                description=f"電話番号: `{creds['phone']}`\n換金を受け付けられます。",
                color=discord.Color.green()
            )
        else:
            embed = discord.Embed(
                title="⚠️ 未ログイン",
                description="`/bot-paypayログイン` でログインしてください。",
                color=discord.Color.orange()
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="ログチャンネル設定", description="換金ログを送信するチャンネルを設定します")
    @is_allowed()
    @app_commands.describe(channel="ログを送信するチャンネル")
    async def set_log_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        config = Config.load()
        config["log_channel_id"] = channel.id
        Config.save(config)
        embed = discord.Embed(
            title="✅ ログチャンネル設定完了",
            description=f"{channel.mention} に換金ログを送信します。",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="ログチャンネル解除", description="換金ログの送信先チャンネルを解除します")
    @is_allowed()
    async def unset_log_channel(self, interaction: discord.Interaction):
        config = Config.load()
        config["log_channel_id"] = None
        Config.save(config)
        embed = discord.Embed(
            title="✅ ログチャンネル解除完了",
            description="換金ログの送信を無効にしました。",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


    # ── 許可ユーザー管理（Discordサーバー管理者のみ） ───────────────

    @app_commands.command(name="許可ユーザー追加", description="このBotのコマンドを使用できるユーザーを追加します（サーバー管理者専用）")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(user="コマンド使用を許可するユーザー")
    async def add_allowed_user(self, interaction: discord.Interaction, user: discord.Member):
        allowed = load_allowed_users()
        user_id_str = str(user.id)

        if user_id_str in allowed:
            embed = discord.Embed(
                title="ℹ️ 既に登録済み",
                description=f"{user.mention} はすでに許可ユーザーに登録されています。",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        allowed.append(user_id_str)
        save_allowed_users(allowed)

        embed = discord.Embed(
            title="✅ 許可ユーザー追加完了",
            description=f"{user.mention} (`{user.id}`) をBotコマンドの許可ユーザーに追加しました。",
            color=discord.Color.green()
        )
        embed.set_footer(text=f"現在の許可ユーザー数: {len(allowed)}人")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @add_allowed_user.error
    async def add_allowed_user_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            embed = discord.Embed(
                title="❌ 権限エラー",
                description="このコマンドはDiscordサーバーの管理者のみ実行できます。",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="許可ユーザー削除", description="Botコマンドの許可ユーザーからユーザーを削除します（サーバー管理者専用）")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(user="許可を取り消すユーザー")
    async def remove_allowed_user(self, interaction: discord.Interaction, user: discord.Member):
        allowed = load_allowed_users()
        user_id_str = str(user.id)

        if user_id_str not in allowed:
            embed = discord.Embed(
                title="ℹ️ 未登録",
                description=f"{user.mention} は許可ユーザーに登録されていません。",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        allowed.remove(user_id_str)
        save_allowed_users(allowed)

        if not allowed:
            note = "\n\n⚠️ 許可ユーザーが0人になりました。全ユーザーがコマンドを使用できる状態に戻ります。"
        else:
            note = f"\n\n現在の許可ユーザー数: {len(allowed)}人"

        embed = discord.Embed(
            title="✅ 許可ユーザー削除完了",
            description=f"{user.mention} (`{user.id}`) を許可ユーザーから削除しました。{note}",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @remove_allowed_user.error
    async def remove_allowed_user_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            embed = discord.Embed(
                title="❌ 権限エラー",
                description="このコマンドはDiscordサーバーの管理者のみ実行できます。",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="許可ユーザー一覧", description="Botコマンドを使用できる許可ユーザーの一覧を表示します（サーバー管理者専用）")
    @app_commands.checks.has_permissions(administrator=True)
    async def list_allowed_users(self, interaction: discord.Interaction):
        allowed = load_allowed_users()

        if not allowed:
            embed = discord.Embed(
                title="📋 許可ユーザー一覧",
                description="現在、許可ユーザーは登録されていません。\n全ユーザーがコマンドを使用できる状態です。",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        lines = []
        for uid in allowed:
            member = interaction.guild.get_member(int(uid)) if interaction.guild else None
            if member:
                lines.append(f"• {member.mention} (`{uid}`)")
            else:
                lines.append(f"• `{uid}` （サーバー未参加）")

        embed = discord.Embed(
            title=f"📋 許可ユーザー一覧（{len(allowed)}人）",
            description="\n".join(lines),
            color=discord.Color.blue()
        )
        embed.set_footer(text="この一覧にいるユーザーのみBotのコマンドを使用できます")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @list_allowed_users.error
    async def list_allowed_users_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            embed = discord.Embed(
                title="❌ 権限エラー",
                description="このコマンドはDiscordサーバーの管理者のみ実行できます。",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(PanelCog(bot))
