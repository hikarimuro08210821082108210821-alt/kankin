import asyncio
import aiohttp
import requests
from bitcoinlib.keys import Key
from bitcoinlib.transactions import Transaction

LTC_NETWORK = "litecoin"
BLOCKCYPHER_BASE = "https://api.blockcypher.com/v1/ltc/main"
BLOCKCHAIR_BASE = "https://api.blockchair.com/litecoin"
BLOCKCYPHER_TOKEN = "d483cde7f08b42daa2a69778ea720f9d"

DUST_LIMIT = 546


def load_blockcypher_token() -> str:
    return BLOCKCYPHER_TOKEN

def save_blockcypher_token(token: str):
    pass


def get_ltc_address_from_private_key(private_key_wif: str) -> str:
    key = Key(private_key_wif, network=LTC_NETWORK)
    return key.address()


def get_ltc_balance_from_private_key(private_key_wif: str) -> float:
    try:
        address = get_ltc_address_from_private_key(private_key_wif)
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(asyncio.run, _get_balance_async(address)).result()
            return loop.run_until_complete(_get_balance_async(address))
        except RuntimeError:
            return asyncio.run(_get_balance_async(address))
    except Exception as e:
        print(f"[WALLET] 残高取得エラー: {e}")
        return 0.0


async def get_ltc_balance_async(address: str) -> float:
    return await _get_balance_async(address)


async def _get_balance_async(address: str) -> float:
    # 優先: BlockCypher（final_balance = confirmed + unconfirmed）
    try:
        token = load_blockcypher_token()
        url = f"{BLOCKCYPHER_BASE}/addrs/{address}/balance?token={token}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json(content_type=None)
                return data.get("final_balance", data.get("balance", 0)) / 1e8
    except Exception as e:
        print(f"[WALLET] 残高取得エラー(BlockCypher): {e}")
    # フォールバック: Blockchair
    try:
        url2 = f"{BLOCKCHAIR_BASE}/dashboards/address/{address}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url2, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json(content_type=None)
                addr_data = data.get("data", {}).get(address, {}).get("address", {})
                return addr_data.get("balance", 0) / 1e8
    except Exception as e:
        print(f"[WALLET] 残高取得エラー(Blockchair): {e}")
        return 0.0


def _get_utxos(address: str) -> list:
    # 優先: BlockCypher
    try:
        token = load_blockcypher_token()
        url = f"{BLOCKCYPHER_BASE}/addrs/{address}?unspentOnly=true&includeScript=true&token={token}"
        resp = requests.get(url, timeout=15)
        print(f"[WALLET] UTXO取得(BlockCypher) → HTTP {resp.status_code}: {resp.text[:200]}")
        if resp.ok:
            data = resp.json()
            txrefs = data.get("txrefs", [])
            unconfirmed = data.get("unconfirmed_txrefs", [])
            all_refs = txrefs + unconfirmed
            utxos = []
            for ref in all_refs:
                utxos.append({
                    "txid": ref["tx_hash"],
                    "vout": ref["tx_output_n"],
                    "value": ref["value"],
                    "status": {"confirmed": ref.get("confirmations", 0) > 0}
                })
            if utxos:
                return utxos
    except Exception as e:
        print(f"[WALLET] UTXO取得エラー(BlockCypher): {e}")

    # フォールバック: Blockchair
    try:
        url2 = f"{BLOCKCHAIR_BASE}/outputs?q=recipient({address}),is_spent(false)&limit=100"
        resp2 = requests.get(url2, timeout=15)
        print(f"[WALLET] UTXO取得(Blockchair) → HTTP {resp2.status_code}: {resp2.text[:200]}")
        if resp2.ok:
            data2 = resp2.json()
            outputs = data2.get("data", [])
            utxos = []
            for out in outputs:
                utxos.append({
                    "txid": out["transaction_hash"],
                    "vout": out["index"],
                    "value": out["value"],
                    "status": {"confirmed": out.get("block_id") is not None}
                })
            return utxos
    except Exception as e:
        print(f"[WALLET] UTXO取得エラー(Blockchair): {e}")

    raise Exception("全UTXOプロバイダーが失敗しました（BlockCypher / Blockchair）")


def _get_fee_rate() -> int:
    # BlockCypherのブロックチェーン情報から取得
    try:
        token = load_blockcypher_token()
        url = f"{BLOCKCYPHER_BASE}?token={token}"
        resp = requests.get(url, timeout=10)
        if resp.ok:
            data = resp.json()
            # medium_fee_per_kb (satoshi/KB) → sat/vB
            fee_per_kb = data.get("medium_fee_per_kb", 10000)
            fee_per_vb = max(int(fee_per_kb / 1000), 5)
            print(f"[WALLET] 手数料レート(BlockCypher): {fee_per_vb} sat/vB (元: {fee_per_kb} sat/KB)")
            return fee_per_vb
    except Exception as e:
        print(f"[WALLET] 手数料レート取得エラー(BlockCypher): {e}")
    print("[WALLET] デフォルト手数料レート使用: 10 sat/vB")
    return 10


def _broadcast_tx(raw_hex: str) -> dict:
    """ブロードキャスト: BlockCypher優先 → Blockchairフォールバック"""
    # 優先: BlockCypher
    try:
        token = load_blockcypher_token()
        broadcast_url = f"{BLOCKCYPHER_BASE}/txs/push?token={token}"
        resp = requests.post(
            broadcast_url,
            json={"tx": raw_hex},
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        print(f"[WALLET] broadcast(BlockCypher) → HTTP {resp.status_code}: {resp.text[:300]}")
        if resp.ok:
            txid = resp.json().get("tx", {}).get("hash", "")
            return {"success": True, "txid": txid}
        else:
            print(f"[WALLET] BlockCypher broadcast失敗: {resp.status_code}")
    except Exception as e:
        print(f"[WALLET] broadcast例外(BlockCypher): {e}")

    # フォールバック: Blockchair
    try:
        resp2 = requests.post(
            f"{BLOCKCHAIR_BASE}/push/transaction",
            data={"data": raw_hex},
            timeout=30
        )
        print(f"[WALLET] broadcast(Blockchair) → HTTP {resp2.status_code}: {resp2.text[:300]}")
        if resp2.ok:
            txid = resp2.json().get("data", {}).get("transaction_hash", "")
            return {"success": True, "txid": txid}
        else:
            return {"success": False, "error": f"Blockchair broadcast失敗 ({resp2.status_code}): {resp2.text[:300]}"}
    except Exception as e:
        return {"success": False, "error": f"全ブロードキャストプロバイダーが失敗: {e}"}


def _simple_spend_sync(private_key_wif: str, to_address: str, amount_ltc: float, token: str) -> dict:
    try:
        amount_satoshi = int(amount_ltc * 1e8)
        key = Key(private_key_wif, network=LTC_NETWORK)
        from_address = key.address()

        print(f"[WALLET] 送金開始: {amount_satoshi} sat ({amount_ltc} LTC) → {to_address}")
        print(f"[WALLET] 送金元アドレス: {from_address}")

        # UTXO取得（BlockCypher → Blockchair）
        utxos = _get_utxos(from_address)
        if not utxos:
            return {"success": False, "error": "UTXOがありません（残高0または未承認のTX待ち）"}

        confirmed_utxos = [u for u in utxos if u.get("status", {}).get("confirmed", False)]
        if not confirmed_utxos:
            confirmed_utxos = utxos  # 未承認でも試みる
        print(f"[WALLET] UTXO数: {len(confirmed_utxos)} (全体: {len(utxos)})")

        # 手数料計算
        fee_rate = _get_fee_rate()
        n_inputs = len(confirmed_utxos)
        estimated_size = 148 * n_inputs + 34 * 2 + 10
        fee = fee_rate * estimated_size
        print(f"[WALLET] 手数料率: {fee_rate} sat/vB, 推定サイズ: {estimated_size} vB, 手数料: {fee} sat")

        total_available = sum(u["value"] for u in confirmed_utxos)
        print(f"[WALLET] 利用可能残高: {total_available} sat, 送金+手数料: {amount_satoshi + fee} sat")

        if total_available < amount_satoshi + fee:
            return {
                "success": False,
                "error": f"残高不足: 利用可能 {total_available} sat / 必要 {amount_satoshi + fee} sat (手数料 {fee} sat含む)"
            }

        change = total_available - amount_satoshi - fee

        # P2PKH locking script: OP_DUP OP_HASH160 <20bytes> OP_EQUALVERIFY OP_CHECKSIG
        locking_script = b'\x76\xa9\x14' + key.hash160 + b'\x88\xac'

        # トランザクション構築（レガシーP2PKH）
        t = Transaction(network=LTC_NETWORK, witness_type="legacy")

        for utxo in confirmed_utxos:
            t.add_input(
                prev_txid=utxo["txid"],
                output_n=utxo["vout"],
                keys=[key],
                script_type="sig_pubkey",
                locking_script=locking_script,
                value=utxo["value"],
                witness_type="legacy",
            )

        t.add_output(amount_satoshi, to_address)
        if change > DUST_LIMIT:
            t.add_output(change, from_address)
            print(f"[WALLET] お釣り: {change} sat → {from_address}")

        # 署名
        t.sign()
        raw_hex = t.raw_hex()
        print(f"[WALLET] raw tx: {len(raw_hex) // 2} bytes")

        # ブロードキャスト（BlockCypher → Blockchair）
        result = _broadcast_tx(raw_hex)
        if result["success"]:
            txid = result["txid"]
            print(f"[WALLET] 送金成功: {txid}")
            return {"success": True, "txid": txid, "amount_ltc": amount_ltc, "to_address": to_address}
        else:
            return {"success": False, "error": result["error"]}

    except Exception as e:
        import traceback
        print(f"[WALLET] 例外: {traceback.format_exc()}")
        return {"success": False, "error": str(e)}


async def send_ltc(private_key_wif: str, to_address: str, amount_ltc: float) -> dict:
    token = load_blockcypher_token()
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, _simple_spend_sync, private_key_wif, to_address, amount_ltc, token
    )


def validate_ltc_address(address: str) -> bool:
    if not address:
        return False
    if address.startswith("L") or address.startswith("M") or address.startswith("ltc1"):
        return 26 <= len(address) <= 62
    return False
