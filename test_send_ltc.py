"""
LTC テスト送金スクリプト
使い方:
    python test_send_ltc.py <送金先アドレス> [送金量LTC]

例:
    python test_send_ltc.py LMLFShAw8jqVxfe5bTXueAy1TvYnFNa26C
    python test_send_ltc.py LMLFShAw8jqVxfe5bTXueAy1TvYnFNa26C 0.001
"""

import sys
import json
import os
import asyncio
import exodus_wallet

EXODUS_DATA_FILE = "exodus_data.json"
DEFAULT_AMOUNT_LTC = 0.001  # デフォルト最低送金量


def load_private_key() -> str:
    if not os.path.exists(EXODUS_DATA_FILE):
        print(f"[ERROR] {EXODUS_DATA_FILE} が見つかりません。")
        sys.exit(1)
    with open(EXODUS_DATA_FILE, "r") as f:
        data = json.load(f)
    key = data.get("private_key", "")
    if not key:
        print("[ERROR] private_key が空です。")
        sys.exit(1)
    return key


async def main():
    if len(sys.argv) < 2:
        print("使い方: python test_send_ltc.py <送金先アドレス> [送金量LTC]")
        print("例:     python test_send_ltc.py LMLFShAw8jqVxfe5bTXueAy1TvYnFNa26C 0.001")
        sys.exit(1)

    to_address = sys.argv[1]
    amount_ltc = float(sys.argv[2]) if len(sys.argv) >= 3 else DEFAULT_AMOUNT_LTC

    if not exodus_wallet.validate_ltc_address(to_address):
        print(f"[ERROR] 無効なLTCアドレス: {to_address}")
        sys.exit(1)

    private_key = load_private_key()
    from_address = exodus_wallet.get_ltc_address_from_private_key(private_key)
    balance = exodus_wallet.get_ltc_balance_from_private_key(private_key)

    print(f"送金元アドレス : {from_address}")
    print(f"現在の残高     : {balance:.8f} LTC")
    print(f"送金先アドレス : {to_address}")
    print(f"送金量         : {amount_ltc:.8f} LTC")
    print("-" * 50)

    confirm = input("この内容で送金しますか？ [y/N]: ").strip().lower()
    if confirm != "y":
        print("キャンセルしました。")
        sys.exit(0)

    print("送金中...")
    result = await exodus_wallet.send_ltc(private_key, to_address, amount_ltc)

    print("-" * 50)
    if result.get("success"):
        print(f"✅ 送金成功！")
        print(f"TXID: {result['txid']}")
        print(f"確認: https://blockchair.com/litecoin/transaction/{result['txid']}")
    else:
        print(f"❌ 送金失敗: {result.get('error')}")


if __name__ == "__main__":
    asyncio.run(main())
