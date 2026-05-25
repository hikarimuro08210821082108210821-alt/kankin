import aiohttp
import datetime
import json
import os
import uuid as _uuid
from useragent_changer import UserAgent

ua = UserAgent('iphone')

PROXY_URL = None
_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_FILE = os.path.join(_DIR, "bot_credentials.json")
LOGIN_TEMP_FILE = os.path.join(_DIR, "login_temp.json")


def save_credentials(phone: str, password: str, device_uuid: str = None):
    data = {"phone": phone, "password": password}
    if device_uuid:
        data["device_uuid"] = device_uuid
    with open(CREDENTIALS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)


def load_credentials() -> dict | None:
    if os.path.exists(CREDENTIALS_FILE):
        with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


async def start_login(phone: str, password: str) -> dict:
    """
    ログインを開始する。
    戻り値:
      {"status": "ok"}    — OTP不要でログイン成功（認証情報保存済み）
      {"status": "otp"}   — OTPが必要
      {"status": "error"} — 認証失敗
    """
    set_uuid = str(_uuid.uuid4())
    headers = {
        'User-Agent': ua.set(),
        'Accept': 'application/json, text/plain, */*',
        'Content-Type': 'application/json',
        'Origin': 'https://www.paypay.ne.jp',
        'Referer': 'https://www.paypay.ne.jp/app/account/sign-in',
    }
    payload = {
        "scope": "SIGN_IN",
        "client_uuid": set_uuid,
        "grant_type": "password",
        "username": phone,
        "password": password,
        "add_otp_prefix": True,
        "language": "ja"
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://www.paypay.ne.jp/app/v1/oauth/token",
            headers=headers, json=payload, proxy=PROXY_URL
        ) as resp:
            data = await resp.json()

    if "access_token" in data:
        save_credentials(phone, password, set_uuid)
        return {"status": "ok"}

    if "otp_reference_id" in data:
        with open(LOGIN_TEMP_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "phone": phone,
                "password": password,
                "uuid": set_uuid,
                "otp_reference_id": data["otp_reference_id"],
                "otp_pre": data.get("otp_prefix", "")
            }, f)
        return {"status": "otp"}

    return {"status": "error"}


async def complete_login(otp: str) -> bool:
    """OTPでログインを完了し認証情報を保存する。"""
    if not os.path.exists(LOGIN_TEMP_FILE):
        return False

    with open(LOGIN_TEMP_FILE, "r", encoding="utf-8") as f:
        temp = json.load(f)

    try:
        os.remove(LOGIN_TEMP_FILE)
    except Exception:
        pass

    headers = {
        'User-Agent': ua.set(),
        'Accept': 'application/json, text/plain, */*',
        'Content-Type': 'application/json',
        'Origin': 'https://www.paypay.ne.jp',
        'Referer': 'https://www.paypay.ne.jp/app/account/sign-in',
    }
    payload = {
        "scope": "SIGN_IN",
        "client_uuid": temp["uuid"],
        "grant_type": "otp",
        "otp_prefix": str(temp["otp_pre"]),
        "otp": otp,
        "otp_reference_id": temp["otp_reference_id"],
        "username_type": "MOBILE",
        "language": "ja"
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://www.paypay.ne.jp/app/v1/oauth/token",
            headers=headers, json=payload, proxy=PROXY_URL
        ) as resp:
            data = await resp.json()

    if "access_token" in data:
        save_credentials(temp["phone"], temp["password"], temp["uuid"])
        return True

    return False


async def check_link(cd):
    if "https://" in cd:
        cd = cd.replace("https://pay.paypay.ne.jp/", "")

    headers = {
        "Accept": "application/json, text/plain, */*",
        'User-Agent': ua.set(),
        "Content-Type": "application/json"
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"https://www.paypay.ne.jp/app/v2/p2p-api/getP2PLinkInfo?verificationCode={cd}", headers=headers, proxy=PROXY_URL) as response:
                response.raise_for_status()
                link_info = await response.json()
        except aiohttp.ClientError as e:
            print(f"API_REQ_EXC: {e}")
            return False

    result_code = link_info.get("header", {}).get("resultCode")
    if result_code != "S0000":
        return False

    order_status = link_info.get("payload", {}).get("orderStatus")
    if order_status == "PENDING":
        return link_info
    else:
        return False


async def link_rev(cd: str, phoneNumber: str, password: str, uuid: str, link_password: str = None):
    if "https://" in cd:
        cd = cd.replace("https://pay.paypay.ne.jp/", "")

    async with aiohttp.ClientSession() as session:
        base_headers = {
            "Accept": "application/json, text/plain, */*",
            'User-Agent': ua.set(),
            "Content-Type": "application/json"
        }

        try:
            async with session.get(f"https://www.paypay.ne.jp/app/v2/p2p-api/getP2PLinkInfo?verificationCode={cd}", headers=base_headers, proxy=PROXY_URL) as response:
                response.raise_for_status()
                link_info = await response.json()

            if link_info.get("payload", {}).get("orderStatus") != "PENDING":
                return False

            if link_info.get("payload", {}).get("pendingP2PInfo", {}).get("isSetPasscode") and link_password is None:
                return False

        except aiohttp.ClientError as e:
            print(f"LINK_REQ_EXC: {e}")
            return False

        login_payload = {
            "scope": "SIGN_IN",
            "client_uuid": f"{uuid}",
            "grant_type": "password",
            "username": phoneNumber,
            "password": password,
            "add_otp_prefix": True,
            "language": "ja"
        }

        login_headers = {
            'User-Agent': ua.set(),
            'Accept': 'application/json, text/plain, */*',
            'Content-Type': 'application/json',
            'Origin': 'https://www.paypay.ne.jp',
            'Referer': 'https://pay.paypay.ne.jp/' + cd,
        }

        async with session.post("https://www.paypay.ne.jp/app/v1/oauth/token", headers=login_headers, json=login_payload, proxy=PROXY_URL) as response:
            login_response = await response.json()
            try:
                login_response = (login_response["access_token"])
            except:
                try:
                    login_response["otp_reference_id"]
                    return "LOGINERR"
                except:
                    return "LOGINERR"

        receive_payload = {
            "verificationCode": cd,
            "client_uuid": uuid,
            "requestAt": str(datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime('%Y-%m-%dT%H:%M:%S+0900')),
            "requestId": link_info["payload"]["message"]["data"]["requestId"],
            "orderId": link_info["payload"]["message"]["data"]["orderId"],
            "senderMessageId": link_info["payload"]["message"]["messageId"],
            "senderChannelUrl": link_info["payload"]["message"]["chatRoomId"],
            "iosMinimumVersion": "3.45.0",
            "androidMinimumVersion": "3.45.0"
        }

        if link_password:
            receive_payload["passcode"] = link_password

        try:
            async with session.post("https://www.paypay.ne.jp/app/v2/p2p-api/acceptP2PSendMoneyLink", json=receive_payload, headers=base_headers, proxy=PROXY_URL) as response:
                response.raise_for_status()
                receive_data = await response.json()

                if receive_data.get("header", {}).get("resultCode") == "S0000":
                    amount = link_info.get("payload", {}).get("pendingP2PInfo", {}).get("amount", 0)
                    return {"success": True, "amount": amount}
                else:
                    return False

        except aiohttp.ClientError as e:
            print(f"REVERR: {e}")
            return False


async def login(phoneNumber: str, password: str, uuid: str):
    headers = {
        'User-Agent': ua.set(),
        'Accept': 'application/json, text/plain, */*',
        'Content-Type': 'application/json',
        'Origin': 'https://www.paypay.ne.jp',
        'Referer': 'https://www.paypay.ne.jp/app/account/sign-in',
    }
    payload = {
        "scope": "SIGN_IN",
        "client_uuid": f"{uuid}",
        "grant_type": "password",
        "username": phoneNumber,
        "password": password,
        "add_otp_prefix": True,
        "language": "ja"
    }
    async with aiohttp.ClientSession() as session:
        async with session.post("https://www.paypay.ne.jp/app/v1/oauth/token", headers=headers, json=payload, proxy=PROXY_URL) as resp:
            return await resp.json()


async def login_otp(set_uuid, otp, otpid, otp_pre):
    headers = {
        'User-Agent': ua.set(),
        'Accept': 'application/json, text/plain, */*',
        'Content-Type': 'application/json',
        'Origin': 'https://www.paypay.ne.jp',
        'Referer': 'https://www.paypay.ne.jp/app/account/sign-in',
    }
    payload = {
        "scope": "SIGN_IN",
        "client_uuid": f"{set_uuid}",
        "grant_type": "otp",
        "otp_prefix": str(otp_pre),
        "otp": otp,
        "otp_reference_id": otpid,
        "username_type": "MOBILE",
        "language": "ja"
    }
    async with aiohttp.ClientSession() as session:
        async with session.post("https://www.paypay.ne.jp/app/v1/oauth/token", headers=headers, json=payload, proxy=PROXY_URL) as response:
            login_response = await response.json()
            try:
                if login_response["response_type"] == "ErrorResponse":
                    return "ERR"
            except:
                return "OK"
