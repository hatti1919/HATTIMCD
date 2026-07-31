```markdown
# MCD-mobile-py 🍔
Python用のマクドナルド モバイルオーダー APIラッパー  
(非公式ライブラリ / 直近の仕様変更やトークン周りに合わせて組み直し済み)

> ⚠️ **注意**: 本プロジェクトは教育・研究目的で公開されています。自己責任でご利用ください。


## 📦 インストール
現在 `pip` 配布はしていません。リポジトリをクローンするか、`main.py` を直接プロジェクトに置いて利用してください。

```bash
git clone [https://github.com/あなたのユーザー名/MCD-mobile-py.git](https://github.com/あなたのユーザー名/MCD-mobile-py.git)

```

### 必須ライブラリ

```bash
pip install requests

```

---

## ⚠️ 始める前に確認すること

### 認証トークンの挙動

* `access_token` と `root_paseto` はAPI呼び出し前に自動でリフレッシュ・再取得される設計にしています。
* `root_paseto` は `oauth2/code` を挟んで取得する仕様です (`v2.local.` 形式)。

---

## Let's Go! 🚀

#### `example.py`

```python
from main import MCD, TokenSet, decode_hex

# 1. トークンが既にある場合の設定
tokens = TokenSet(
    refresh_token="ここにリフレッシュトークン"
)

mcd = MCD(tokens=tokens)

# 2. ログインから行う場合
# mfa_token = mcd.login("example@email.com", "Password123")
# tokens = mcd.login_with_mfa(mfa_token, "123456") # SMS等のOTPを入力

# ------------------------------------------------------------------ #
# 店舗情報・登録カードの取得
# ------------------------------------------------------------------ #

# 店舗名を取得 (group-h 〜 group-e を自動でフォールバック探索)
store_name = mcd.get_store_name("01001")
print(f"店名: {store_name}")

# アカウントに登録されているカード一覧を取得
cards = mcd.get_cards()
print(f"登録カード: {cards}")


# ------------------------------------------------------------------ #
# HEX (QRコード情報) からワンショットで決済を完了させる
# ------------------------------------------------------------------ #

hex_str = "ここにQRコードからデコードしたHEX文字列"

# HEXの解析だけ先にやりたい場合
decoded = decode_hex(hex_str)
print(f"店舗ID: {decoded.store_id}")
print(f"受け取り方法: {decoded.pickup_method}") # テイクアウト / イートイン / デリバリー
print(f"合計金額: {decoded.amount_cents}円")

# 決済実行 (StoreOrder -> AuthoriseOrder -> GetPaidOrder を自動走破)
result = mcd.pay_from_hex(hex_str)

print(f"注文完了！")
print(f"受け取り番号: {result.receipt_number}")
print(f"店舗名: {result.store_name}")
print(f"受け取り形態: {result.pickup_method}")
print(f"ステータス: {result.status}")

```

---

## もう少し知る 💡

### 注文グループ (Group E ~ H)

店舗によって `group-e`, `group-f`, `group-g`, `group-h` のどれに属しているかが異なります。

`store_order` では `group-e` から `group-h` まで順番にトライして、適合するエンドポイントを自動判別します。

### クレジットカードの追加 (Veritrans + 3DS)

Veritrans経由でカードをトークン化し、3Dセキュア認証を回して登録する機能も実装しています。

```python
# 1. トークン化
v_token = mcd.tokenize_card(
    card_number="4111111111111111",
    expiry="2512", # YYMM
    cvv="123",
    cardholder_name="TAROU YAMADA"
)

# 2. 3DS認証の開始
three_ds_id, acs_url = mcd.add_card_with_3ds(v_token)
print(f"以下のURLをWebView等で開いて3DS認証を完了させてください:\n{acs_url}")

# 3. 認証完了後にcard_idを取得
# card_id = mcd.get_add_card_result(three_ds_id)

```

### その他の便利機能

```python
# MOP店頭提示用クーポンコード一覧の取得
coupons = mcd.get_remaining_coupons()

# ユーザーのタグや設定値を取得
tags = mcd.get_user_tags()
prefs = mcd.get_user_prefs()

# 呼び出し（バズー）番号の確認
buzzer = mcd.get_order_buzzer_notification(order_token="...")

```

---

## 💬 コンタクト

* **Discord**: `hatti_ssub`

```

```
