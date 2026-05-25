# PayPay → LTC 自動換金 Discord BOT

PayPayの送金リンクを受け取り、Exodusウォレット（秘密鍵）から直接LTCを送金するDiscord BOTです。
取引所アカウントや本人確認は一切不要です。

## セットアップ手順

### 1. config.jsonを編集する

`discord-bot/config.json` を開き、Discordトークンだけ設定してください：

```json
{
    "discord_token": "DiscordボットのTokenをここに",
    "fee_percent": 0,
    "allowed_guild_id": null
}
```

**Discord トークンの取得方法:**
1. https://discord.com/developers/applications にアクセス
2. New Application → Bot → Token をコピー
3. Privileged Gateway Intents: MESSAGE CONTENT INTENT を有効化

**fee_percent:** 手数料率（0 = 手数料なし）

**allowed_guild_id:** サーバーIDを設定するとスラッシュコマンドが即座に反映されます（nullでグローバル同期）

### 2. BOTを起動する

```bash
cd discord-bot
python3 bot.py
```

### 3. Exodus秘密鍵を登録する（起動後）

`config.json` に秘密鍵を書く必要はありません。
起動後に `/exodus登録` コマンドでモーダルから安全に入力できます。

**Exodus LTC秘密鍵（WIF形式）の取得方法:**
1. Exodusアプリを開く
2. 左メニュー → Settings（設定）
3. Backup → Export Private Keys
4. パスワードを入力 → ダウンロードされたCSVを開く
5. `LTC` の行の `privatekey` 列の値をコピー（T または 6 で始まる文字列）

### 4. 換金パネルを設置する

パネルを設置したいチャンネルで `/パネル設置` を実行すると、
ボタン付きの換金パネルが投稿されます。

---

## スラッシュコマンド一覧

| コマンド | 説明 |
|---|---|
| `/パネル設置` | 換金パネル（ボタン付き）をチャンネルに設置 |
| `/exodus登録` | ExodusウォレットのLTC秘密鍵をモーダルで安全に登録 |
| `/exodus情報` | 登録済みのExodusウォレットアドレスを確認 |
| `/exodus削除` | 登録済みの秘密鍵を削除 |
| `/paypayログイン` | PayPayアカウントにログインして登録 |
| `/paypay情報` | 登録済みのPayPay情報を確認 |
| `/paypay削除` | PayPay登録情報を削除 |
| `/ltcレート` | 現在のLTC/JPYレートを確認（CoinGecko） |

---

## 換金パネルのボタン

パネル設置後、ボタンを押すと自分だけに結果が表示されます（他の人には見えません）。

| ボタン | 動作 |
|---|---|
| 💼 残高確認 | ExodusウォレットのLTC残高・JPY換算額を確認 |
| 💱 換金する | PayPay送金リンク・パスワード・送金先LTCアドレスを入力して換金 |
| 📊 取引履歴 | 自分の過去5件の換金履歴を確認 |

---

## 処理フロー（換金ボタン押下後）

```
PayPay送金リンク + パスワード（任意） + 送金先LTCアドレス 入力
    ↓
リンク有効性確認（PENDING状態チェック）
    ↓
CoinGeckoからLTC/JPYレート取得
    ↓
Exodusウォレットの残高確認
    ↓
PayPayリンク受け取り（円を受領）
    ↓
ExodusウォレットからLTCを直接送金
    ↓
トランザクションID通知（自分だけに表示）
```

---

## ファイル構成

```
discord-bot/
├── bot.py              # BOTメインファイル
├── config.py           # 設定管理
├── config.json         # 設定ファイル（discord_tokenのみ設定）
├── paypayu.py          # PayPay API操作
├── exodus_wallet.py    # Exodus秘密鍵でLTC送金
├── price_api.py        # CoinGeckoでLTC/JPYレート取得
├── utils.py            # ユーティリティ（権限チェック）
├── requirements.txt    # Python依存パッケージ
├── exodus_data.json    # Exodus秘密鍵（/exodus登録 で自動生成）
├── paypay_data.json    # PayPayアカウント情報（自動生成）
├── transactions.json   # 取引ログ（自動生成）
└── cogs/
    ├── panel.py        # 換金パネル・Exodus登録コマンド
    ├── paypay.py       # PayPay関連コマンド
    └── exchange.py     # LTCレートコマンド
```

---

## 注意事項

- **秘密鍵の管理**: `/exodus登録` で入力した秘密鍵は `exodus_data.json` に保存されます。このファイルは絶対に他人に見せないでください
- **残高確認**: 換金前にパネルの「残高確認」ボタンで残高が足りているか確認できます
- **レート**: CoinGeckoのレートを使用します（リアルタイム）
- **ネットワーク手数料**: LTCネットワーク手数料は自動的に差し引かれます
- **結果表示**: すべての操作結果はあなただけに表示されます（ephemeral）
