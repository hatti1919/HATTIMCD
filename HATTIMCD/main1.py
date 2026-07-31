import time
import json
import base64
import requests
from dataclasses import dataclass, field
from typing import Optional


_VMOB_HEADERS = {
    "User-Agent":                      "McDonaldsJapan-Prod/5.5.30 (iPhone; iOS 26.3.1; Scale/3.00)",
    "x-vmob-device_os_version":        "26.3.1",
    "x-vmob-location_accuracy":        "6.076432",
    "x-vmob-device_network_type":      "wifi",
    "x-vmob-location_longitude":       "135.730272",
    "x-vmob-device":                   "iPhone",
    "x-vmob-application_version":      "1657",
    "x-vmob-uid":                      "2B616927-5749-4191-80FE-69D38D63719C",
    "x-vmob-beacons":                  "",
    "x-vmob-device_timezone_id":       "Asia/Tokyo",
    "x-vmob-device_utc_offset":        "+09:00",
    "x-vmob-device_screen_resolution": "2532x1170",
    "x-vmob-mobile_operator":          "--",
    "Accept-Language":                 "ja-JP",
    "x-vmob-device_type":              "i_p",
    "x-vmob-sdk_version":              "5.11.1.593",
    "Accept":                          "application/json",
    "Content-Type":                    "application/json",
    "x-vmob-location_latitude":        "34.997026",
    "x-vmob-cost-center":              "McD-Japan",
    "x-vmob-authorization":            "77c0e8d4-19ef-4e39-8348-859c5d60aebc",
}

_QOR_HEADERS = {
    "x-wmop-deviceid":         "DF219981-0E63-4822-A6A7-B9D9852A76FB",
    "x-fb-instance-id":        "39841F4EE97D4ECB8135DCD2DDFC3B7F",
    "x-wmop-app-version":      "5.5.30",
    "x-wmop-app-build":        "1657",
    "x-wmob-bundle-id":        "jp.mcdonalds.coupon",
    "x-wmop-bundle-id":        "jp.mcdonalds.coupon",
    "x-wmop-platform-version": "26.3.1",
    "x-wmop-platform":         "iOS",
    "Accept":                  "*/*",
    "Accept-Language":         "ja",
    "Cache-Control":           "no-cache",
    "Content-Type":            "application/x-www-form-urlencoded",
    "User-Agent":              "McDonaldsJapan-Prod/1657 CFNetwork/3860.400.51 Darwin/25.3.0",
    "Connection":              "keep-alive",
}

_OAUTH2_CLIENT_ID = "164d4a98beb14f13ce02a6fb62c7712c"


_DATA_GROUPS = ["group-h", "group-g", "group-f", "group-e"]






class MCDError(Exception):
    pass

class MCDAuthError(MCDError):
    pass

class MCDOrderError(MCDError):
    pass

class MCDNetworkError(MCDError):
    pass






@dataclass
class Product:
    product_id: str
    has_field1: bool = True
    addons: list["Product"] = field(default_factory=list)

    def __repr__(self):
        return f"Product({self.product_id!r}, addons={[a.product_id for a in self.addons]})"


@dataclass
class DecodedOrder:
    store_id: str
    short_order_code: str
    amount_cents: int
    products: list[Product]
    redirect_urls: list[str]
    pickup_method: str = ""   


@dataclass
class OrderResult:
    order_code: str
    short_code: str
    status: int
    store_id: str
    order_token: str
    group: str
    raw_hex: str
    receipt_number: str = ""   
    store_name: str = ""       
    pickup_method: str = ""    


@dataclass
class TokenSet:
    access_token: str = ""
    refresh_token: str = ""
    authorization_token: str = ""
    root_paseto: str = ""
    root_paseto_exp: float = 0.0
    access_token_exp: float = 0.0
    refresh_token_exp: float = 0.0






def _varint_encode(n: int) -> bytes:
    buf = b""
    while True:
        bits = n & 0x7F
        n >>= 7
        buf += bytes([bits | 0x80]) if n else bytes([bits])
        if not n:
            break
    return buf


def _varint_decode(data: bytes, pos: int) -> tuple[int, int]:
    result = shift = 0
    while pos < len(data):
        b = data[pos]; pos += 1
        result |= (b & 0x7F) << shift
        shift += 7
        if not (b & 0x80):
            break
    return result, pos


def _pb_str(field: int, s: str) -> bytes:
    b = s.encode("utf-8")
    return _varint_encode((field << 3) | 2) + _varint_encode(len(b)) + b


def _pb_msg(field: int, data: bytes) -> bytes:
    return _varint_encode((field << 3) | 2) + _varint_encode(len(data)) + data


def _pb_int(field: int, n: int) -> bytes:
    return _varint_encode((field << 3) | 0) + _varint_encode(n)


def _proto_parse(data: bytes) -> dict:
    fields: dict[int, list] = {}
    pos = 0
    while pos < len(data):
        try:
            tag, pos = _varint_decode(data, pos)
        except Exception:
            break
        fn, wt = tag >> 3, tag & 0x7
        if wt == 0:
            v, pos = _varint_decode(data, pos)
            fields.setdefault(fn, []).append(v)
        elif wt == 2:
            l, pos = _varint_decode(data, pos)
            fields.setdefault(fn, []).append(data[pos: pos + l]); pos += l
        elif wt == 5:
            fields.setdefault(fn, []).append(data[pos: pos + 4]); pos += 4
        elif wt == 1:
            fields.setdefault(fn, []).append(data[pos: pos + 8]); pos += 8
        else:
            break
    return fields


def _try_str(b) -> str:
    if isinstance(b, bytes):
        try:
            return b.decode("utf-8")
        except Exception:
            return b.hex()
    return str(b)


def _jwt_exp(token: str) -> float:
    try:
        payload = token.split(".")[1]
        payload += "=" * (4 - len(payload) % 4)
        return float(json.loads(base64.b64decode(payload)).get("exp", 0))
    except Exception:
        return 0.0






def _detect_pickup_method(hex_str: str) -> str:
    """
    HEXのfield[7]サブメッセージから受け取り方を日本語で返す。
    field[7] が空 → テイクアウト
    field[7].field[1] が存在 → イートイン / テーブルデリバリー
    field[7].field[2] が存在 → デリバリー
    """
    try:
        data = bytes.fromhex(hex_str.strip())
        top = _proto_parse(data)
        f7_list = top.get(7, [])
        if not f7_list:
            return "テイクアウト"
        f7_raw = f7_list[0]
        if not isinstance(f7_raw, bytes) or len(f7_raw) == 0:
            return "テイクアウト"
        inner = _proto_parse(f7_raw)
        if 2 in inner:
            return "デリバリー"
        if 1 in inner:
            return "イートイン"
        return "テイクアウト"
    except Exception:
        return "テイクアウト"






def _parse_product(raw: bytes) -> Product:
    f = _proto_parse(raw)
    product_id = ""
    for v in f.get(2, []):
        s = _try_str(v)
        if s and not s.startswith("0x"):
            product_id = s
    addons = [
        _parse_product(r) for r in f.get(5, []) if isinstance(r, bytes)
    ]
    return Product(product_id=product_id, has_field1=(1 in f), addons=addons)


def decode_hex(hex_str: str) -> DecodedOrder:
    data = bytes.fromhex(hex_str.strip())
    top  = _proto_parse(data)

    store_id = short_code = ""
    amount   = 0
    products: list[Product] = []
    redirect_urls: list[str] = []

    for v in top.get(1, []):
        store_id = _try_str(v)

    for wf in [3, 2]:
        for raw in top.get(wf, []):
            if not isinstance(raw, bytes):
                continue
            rf = _proto_parse(raw)
            urls = [
                _try_str(v)
                for fn in [1, 2, 3]
                for v in rf.get(fn, [])
                if isinstance(v, bytes) and _try_str(v).startswith("http")
            ]
            if urls:
                redirect_urls = urls
                break

    for f8_raw in top.get(8, []):
        if not isinstance(f8_raw, bytes):
            continue
        for f2_raw in _proto_parse(f8_raw).get(2, []):
            if not isinstance(f2_raw, bytes):
                continue
            f2 = _proto_parse(f2_raw)
            for v in f2.get(2, []):
                short_code = _try_str(v)
            for v in f2.get(4, []):
                if isinstance(v, int):
                    amount = v
            for pr in f2.get(5, []):
                if isinstance(pr, bytes):
                    p = _parse_product(pr)
                    if p.product_id:
                        products.append(p)

    pickup_method = _detect_pickup_method(hex_str)

    return DecodedOrder(
        store_id=store_id,
        short_order_code=short_code,
        amount_cents=amount,
        products=products,
        redirect_urls=redirect_urls,
        pickup_method=pickup_method,
    )


def _build_order_item(p: Product) -> bytes:
    b = b""
    if p.has_field1:
        b += _pb_int(1, 1)
    b += _pb_str(2, p.product_id)
    b += _pb_int(3, 1)
    for sub in p.addons:
        b += _pb_msg(5, _build_order_item(sub))
    return b


def _build_store_order_body(
    store_id: str,
    short_order_code: str,
    amount_cents: int,
    products: list[Product],
    pos_paseto: str,
    card_id: str = "",
) -> bytes:
    b = _pb_str(1, store_id)
    b += _pb_msg(2, _pb_msg(2, b""))
    if card_id:
        card_inner = _pb_str(1, card_id)
        b += _pb_msg(3, _pb_msg(1, _pb_msg(2, card_inner)))
    else:
        b += _pb_msg(3, _pb_msg(1, b""))
    b += _pb_msg(7, b"")
    inner = b""
    if short_order_code:
        inner += _pb_str(2, short_order_code)
    inner += _pb_int(3, 1)
    if amount_cents:
        inner += _pb_int(4, amount_cents)
    for p in products:
        inner += _pb_msg(5, _build_order_item(p))
    b += _pb_msg(8, _pb_msg(2, inner))
    if pos_paseto:
        b += _pb_str(12, pos_paseto)
    return b


def _build_authorise_order_body(order_token: str) -> bytes:
    return _pb_str(1, order_token) + _pb_msg(2, _pb_msg(2, b""))


def _build_get_paid_order_body(order_token: str) -> bytes:
    return _pb_str(1, order_token)


def _parse_order_response(data: bytes) -> dict:
    top = _proto_parse(data)
    raw = next((v for v in top.get(2, []) if isinstance(v, bytes)), None)
    if raw is None:
        raw = next((v for v in top.get(1, []) if isinstance(v, bytes)), None)
    if raw is None:
        return {fn: _try_str(vals[0]) for fn, vals in top.items()}
    of = _proto_parse(raw)
    return {
        "order_code":     _try_str(of[1][0])  if 1  in of else "",
        "short_code":     _try_str(of[2][0])  if 2  in of else "",
        "status":         of[3][0]             if 3  in of else 0,
        "store_id":       _try_str(of[4][0])  if 4  in of else "",
        "receipt_number": _try_str(of[9][0])  if 9  in of else "",
        "order_token":    _try_str(of[10][0]) if 10 in of else "",
        "raw_hex":        data.hex(),
    }


def _parse_error(data: bytes) -> str:
    if not data:
        return "(empty response)"
    try:
        return json.loads(data).get("message", data.decode("utf-8", errors="replace")[:300])
    except Exception:
        pass
    try:
        fields = _proto_parse(data)
        return " | ".join(_try_str(v) for vals in fields.values() for v in vals)[:300]
    except Exception:
        return data.decode("utf-8", errors="replace")[:300]






class MCD:
    def __init__(
        self,
        tokens: Optional[TokenSet] = None,
        timeout: int = 20,
        proxy: str | dict = None,
    ):
        self.tokens  = tokens or TokenSet()
        self.timeout = timeout
        self._sess   = requests.Session()
        self._sess.headers.update(_VMOB_HEADERS)

        if isinstance(proxy, str):
            if not proxy.startswith("http"):
                proxy = "http://" + proxy
            self._sess.proxies = {"http": proxy, "https": proxy}
        elif isinstance(proxy, dict):
            self._sess.proxies = proxy

    
    
    

    def _refresh_access_token(self) -> None:
        """access_token を refresh_token で更新。毎回強制実行。"""
        if not self.tokens.refresh_token:
            raise MCDAuthError("No refresh_token in TokenSet.")
        try:
            resp = self._sess.get(
                "https://authorization-vmob-prod-jpe.vmobapps.com/Authorization/AccessToken",
                headers={**_VMOB_HEADERS, "refreshToken": self.tokens.refresh_token},
                timeout=self.timeout,
            )
        except Exception as e:
            raise MCDNetworkError(e)
        if resp.status_code != 200:
            raise MCDAuthError(f"access_token refresh failed: {resp.status_code} {resp.text[:200]}")
        d = resp.json()
        if new := d.get("jwtAccessToken"):
            self.tokens.access_token     = new
            self.tokens.access_token_exp = _jwt_exp(new)
        if new := d.get("jwtRefreshToken"):
            self.tokens.refresh_token     = new
            self.tokens.refresh_token_exp = _jwt_exp(new)

    def _get_oauth2_code(self) -> str:
        """jwtAccessToken → oauth2/code (30秒有効) を発行。"""
        if not self.tokens.access_token:
            raise MCDAuthError("access_token required for oauth2/code.")
        try:
            resp = self._sess.post(
                "https://authorization-vmob-prod-jpe.vmobapps.com///oauth2/code",
                headers={
                    **_VMOB_HEADERS,
                    "Authorization": f"Bearer {self.tokens.access_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "client_id":      _OAUTH2_CLIENT_ID,
                    "scope":          "openid email profile",
                    "code_challenge": "",
                    "response_type":  "code",
                    "grant_type":     "authorization_code",
                },
                timeout=self.timeout,
            )
        except Exception as e:
            raise MCDNetworkError(e)
        if resp.status_code != 200:
            raise MCDAuthError(f"oauth2/code failed: {resp.status_code} {resp.text[:200]}")
        code = resp.json().get("code", "")
        if not code:
            raise MCDAuthError(f"oauth2/code: empty code in response: {resp.text[:200]}")
        return code

    def _refresh_root_paseto(self) -> None:
        """
        access_token → oauth2/code → VerifyPlexureAuthorizationCode → root PASETO。
        毎回強制取得。
        """
        code = self._get_oauth2_code()
        jwt_b = code.encode("utf-8")
        body  = b"\x0a" + _varint_encode(len(jwt_b)) + jwt_b
        try:
            resp = self._sess.post(
                "https://user-api.dir.prod.mop.mcd.qorcommerce.com/app/mcduser.AuthorizationService/VerifyPlexureAuthorizationCode",
                headers={**_QOR_HEADERS},
                data=body,
                timeout=self.timeout,
            )
        except Exception as e:
            raise MCDNetworkError(e)
        if resp.status_code != 200:
            raise MCDAuthError(f"root_paseto refresh failed: {resp.status_code} {resp.content[:100]}")
        fields = _proto_parse(resp.content)
        raw = next((v for v in fields.get(1, []) if isinstance(v, bytes)), None)
        if not raw:
            raise MCDAuthError(f"root_paseto: empty response: {resp.content.hex()[:100]}")
        paseto = _try_str(raw)
        if not paseto.startswith("v2.local."):
            raise MCDAuthError(f"root_paseto: invalid format: {paseto[:60]}")
        self.tokens.root_paseto     = paseto
        self.tokens.root_paseto_exp = time.time() + 3600

    def _ensure_auth(self) -> None:
        """
        API呼び出し前に毎回両方リフレッシュする。
        access_token → root_paseto の順で必ず再取得。
        """
        self._refresh_access_token()
        self._refresh_root_paseto()

    def _root(self) -> str:
        return self.tokens.root_paseto

    
    
    

    def login(self, email: str, password: str) -> str:
        """ログイン → MFAトークン返却。"""
        try:
            resp = self._sess.post(
                "https://con-japan-east-prod.vmobapps.com/v3/logins",
                json={
                    "username": email,
                    "password": password,
                    "returnConsumerInfo": False,
                    "returnCrossReferences": False,
                    "grant_type": "password",
                },
                timeout=self.timeout,
            )
        except Exception as e:
            raise MCDNetworkError(e)
        if resp.status_code not in (200, 202):
            raise MCDAuthError(f"login failed: {resp.status_code}")
        d = resp.json()
        mfa_token = d.get("jwtMfaToken") or d.get("jwtAccessToken", "")
        if not mfa_token:
            raise MCDAuthError("login: no MFA token in response")
        return mfa_token

    def login_with_mfa(self, mfa_token: str, otp: str) -> TokenSet:
        """MFA認証 → TokenSet 返却。"""
        try:
            resp = self._sess.post(
                "https://con-japan-east-prod.vmobapps.com/v3/loginwithmfa",
                headers={**_VMOB_HEADERS, "Authorization": f"Bearer {mfa_token}"},
                json={
                    "Otp": otp,
                    "returnConsumerInfo": True,
                    "returnCrossReferences": True,
                },
                timeout=self.timeout,
            )
        except Exception as e:
            raise MCDNetworkError(e)
        if resp.status_code != 200:
            raise MCDAuthError(f"MFA failed: {resp.status_code}")
        d = resp.json()
        access  = d.get("jwtAccessToken", "")
        refresh = d.get("jwtRefreshToken", "")
        self.tokens = TokenSet(
            access_token=access,
            refresh_token=refresh,
            root_paseto="",
            root_paseto_exp=0.0,
            access_token_exp=_jwt_exp(access),
            refresh_token_exp=_jwt_exp(refresh),
        )
        return self.tokens

    
    
    

    def refresh_access_token(self) -> bool:
        self._refresh_access_token()
        return True

    def get_root_paseto(self) -> str:
        """oauth2/code経由でPASETOを取得・更新する。"""
        self._refresh_root_paseto()
        return self.tokens.root_paseto

    
    
    

    def get_store_name(self, store_id: str) -> str:
        """
        data.cat API から店名を取得する。
        group-h → group-g → group-f → group-e の順に試す。
        取得できない場合は空文字を返す。
        """
        for group in _DATA_GROUPS:
            url = f"https://data.cat.{group}.prod.mop.mcd.qorcommerce.com/{store_id}.json"
            try:
                resp = self._sess.get(url, timeout=self.timeout)
                if resp.status_code == 200:
                    data = resp.json()
                    name = data.get("store", {}).get("name", "")
                    if name:
                        return name
            except Exception:
                continue
        return ""

    def get_store(self, store_id: str) -> dict:
        """
        data.cat API から店舗情報をフルで取得する。
        group-h → group-g → group-f → group-e の順に試す。
        """
        for group in _DATA_GROUPS:
            url = f"https://data.cat.{group}.prod.mop.mcd.qorcommerce.com/{store_id}.json"
            try:
                resp = self._sess.get(url, timeout=self.timeout)
                if resp.status_code == 200:
                    return resp.json()
            except Exception:
                continue
        return {}

    
    
    

    def get_pos_paseto(self, group: str = "group-f") -> str:
        try:
            resp = self._sess.post(
                f"https://tid.ord.{group}.prod.mop.mcd.qorcommerce.com/app/mcdtid.UserPosIdService/GetUserPosIdToken",
                headers={**_QOR_HEADERS, "Authorization": f"Bearer {self._root()}"},
                data=b"",
                timeout=self.timeout,
            )
        except Exception as e:
            raise MCDNetworkError(e)
        if resp.status_code != 200:
            raise MCDAuthError(f"get_pos_paseto failed: {resp.status_code} {resp.content[:100]}")
        fields = _proto_parse(resp.content)
        raw = next((v for v in fields.get(1, []) if isinstance(v, bytes)), None)
        if not raw:
            raise MCDAuthError(f"get_pos_paseto: empty response: {resp.content.hex()[:60]}")
        paseto = _try_str(raw)
        if not paseto.startswith("v2.local."):
            raise MCDAuthError(f"get_pos_paseto: invalid format: {paseto[:60]}")
        return paseto

    
    
    

    def get_cards(self) -> list[dict]:
        """GetCardInfos → 登録カード一覧を返す。"""
        self._ensure_auth()
        try:
            resp = self._sess.post(
                "https://pay.dir.prod.mop.mcd.qorcommerce.com/app/mcdpay.CardService/GetCardInfos",
                headers={**_QOR_HEADERS, "Authorization": f"Bearer {self._root()}"},
                data=b"",
                timeout=self.timeout,
            )
        except Exception as e:
            raise MCDNetworkError(e)
        if resp.status_code != 200:
            raise MCDAuthError(f"get_cards failed: {resp.status_code} {resp.content[:100]}")
        cards = []
        top = _proto_parse(resp.content)
        for raw in top.get(1, []):
            if not isinstance(raw, bytes):
                continue
            f = _proto_parse(raw)
            cards.append({
                "card_id": _try_str(f[1][0]) if 1 in f else "",
                "masked":  _try_str(f[2][0]) if 2 in f else "",
                "expiry":  _try_str(f[3][0]) if 3 in f else "",
                "name":    _try_str(f[4][0]) if 4 in f else "",
            })
        return cards

    def get_default_card_id(self) -> Optional[str]:
        """デフォルトカードのcard_idを返す。"""
        cards = self.get_cards()
        return cards[0]["card_id"] if cards else None

    
    
    

    _GROUPS = ["group-e", "group-f", "group-g", "group-h"]

    def store_order(self, decoded: DecodedOrder, card_id: str = "") -> OrderResult:
        """
        StoreOrder: QRコードから注文を登録する。
        card_id を指定しない場合はデフォルトカードを自動取得。
        """
        if not card_id:
            card_id = self.get_default_card_id() or ""

        last_err: Exception | None = None
        for group in self._GROUPS:
            try:
                pos_paseto = self.get_pos_paseto(group=group)
            except (MCDAuthError, MCDNetworkError) as e:
                last_err = e
                continue

            body = _build_store_order_body(
                store_id=decoded.store_id,
                short_order_code=decoded.short_order_code,
                amount_cents=decoded.amount_cents,
                products=decoded.products,
                pos_paseto=pos_paseto,
                card_id=card_id,
            )
            try:
                resp = self._sess.post(
                    f"https://ord.{group}.prod.mop.mcd.qorcommerce.com/app/mcdord.UserOrderService/StoreOrder",
                    headers={**_QOR_HEADERS, "Authorization": f"Bearer {self._root()}"},
                    data=body,
                    timeout=self.timeout,
                )
            except Exception as e:
                last_err = MCDNetworkError(e)
                continue

            if resp.status_code == 200 and resp.content:
                d = _parse_order_response(resp.content)
                return OrderResult(
                    order_code=d["order_code"],
                    short_code=d["short_code"],
                    status=d["status"],
                    store_id=d["store_id"],
                    order_token=d["order_token"],
                    group=group,
                    raw_hex=d["raw_hex"],
                )

            err_body = resp.content.decode("utf-8", errors="replace")
            if "StoreNotInGroup" in err_body or resp.status_code == 422:
                last_err = MCDOrderError(f"{group}: {resp.status_code} {err_body[:200]}")
                continue

            last_err = MCDOrderError(f"{group}: {resp.status_code} {err_body[:200]}")
            break

        raise last_err or MCDOrderError("StoreOrder: all groups failed")

    def authorise_order(
        self,
        order_token: str,
        group: str = "group-f",
    ) -> OrderResult:
        """
        AuthoriseOrder: 支払い確定。
        root_paseto を強制再生成してから実行。
        """
        
        self._refresh_root_paseto()
        body = _build_authorise_order_body(order_token)
        try:
            resp = self._sess.post(
                f"https://ord.{group}.prod.mop.mcd.qorcommerce.com/app/mcdord.UserOrderService/AuthoriseOrder",
                headers={**_QOR_HEADERS, "Authorization": f"Bearer {self._root()}"},
                data=body,
                timeout=self.timeout,
            )
        except Exception as e:
            raise MCDNetworkError(e)
        if resp.status_code != 200 or not resp.content:
            raise MCDOrderError(
                f"AuthoriseOrder {resp.status_code}: {resp.content.decode('utf-8', 'replace')[:300]}"
            )
        d = _parse_order_response(resp.content)
        return OrderResult(
            order_code=d["order_code"],
            short_code=d["short_code"],
            status=d["status"],
            store_id=d["store_id"],
            order_token=order_token,
            group=group,
            raw_hex=d["raw_hex"],
            receipt_number=d.get("receipt_number", ""),
        )

    def get_paid_order(self, order_token: str, group: str = "group-f") -> OrderResult:
        """GetPaidOrder: 決済済み注文を確認。receipt_number (受け取り番号) を含む。"""
        body = _build_get_paid_order_body(order_token)
        try:
            resp = self._sess.post(
                f"https://ord.{group}.prod.mop.mcd.qorcommerce.com/app/mcdord.UserOrderService/GetPaidOrder",
                headers={**_QOR_HEADERS, "Authorization": f"Bearer {self._root()}"},
                data=body,
                timeout=self.timeout,
            )
        except Exception as e:
            raise MCDNetworkError(e)
        if resp.status_code != 200 or not resp.content:
            raise MCDOrderError(f"GetPaidOrder {resp.status_code}: {resp.content[:200]}")
        d = _parse_order_response(resp.content)
        return OrderResult(
            order_code=d["order_code"],
            short_code=d["short_code"],
            status=d["status"],
            store_id=d["store_id"],
            order_token=order_token,
            group=group,
            raw_hex=d["raw_hex"],
            receipt_number=d.get("receipt_number", ""),
        )

    
    
    

    def pay_from_hex(
        self,
        hex_str: str,
        card_id: Optional[str] = None,
    ) -> OrderResult:
        """
        QRコードのhex文字列から支払いを完結させる。

        フロー:
          1. access_token リフレッシュ
          2. root_paseto リフレッシュ
          3. decode_hex → DecodedOrder (store_id, pickup_method 取得)
          4. store_order → order_token 取得
          5. authorise_order (内部でさらに root_paseto 再リフレッシュ)
          6. get_paid_order → receipt_number 取得
          7. get_store_name → store_name 取得
          8. OrderResult に全フィールドをセットして返す

        返値の OrderResult:
          - receipt_number : 注文番号 (例: "7166")
          - store_name     : 店名 (例: "代々木店")
          - pickup_method  : 受け取り方 (例: "テイクアウト")
        """
        
        self._ensure_auth()

        
        decoded = decode_hex(hex_str)
        if not decoded.store_id:
            raise MCDOrderError("Could not extract storeId from hex.")

        
        so = self.store_order(decoded, card_id=card_id or "")
        if not so.order_token:
            raise MCDOrderError(f"StoreOrder returned no order_token: {so}")

        
        auth = self.authorise_order(so.order_token, group=so.group)

        
        receipt_number = auth.receipt_number
        if not receipt_number:
            try:
                paid = self.get_paid_order(auth.order_token, group=so.group)
                receipt_number = paid.receipt_number
            except Exception:
                receipt_number = ""

        
        store_name = self.get_store_name(decoded.store_id)

        
        return OrderResult(
            order_code=auth.order_code,
            short_code=auth.short_code,
            status=auth.status,
            store_id=decoded.store_id,
            order_token=auth.order_token,
            group=so.group,
            raw_hex=auth.raw_hex,
            receipt_number=receipt_number,
            store_name=store_name,
            pickup_method=decoded.pickup_method,
        )

    
    
    

    _VERITRANS_TOKEN_API_KEY = "9d179769-488a-4769-b84a-e725f233257b"

    def tokenize_card(
        self,
        card_number: str,
        expiry: str,
        cvv: str,
        cardholder_name: str,
    ) -> str:
        """Veritrans でカードをトークン化する。返値は Veritrans token UUID。"""
        import uuid as _uuid
        headers = {
            "Content-Type": "application/json",
            "X-Vmob-Application_version": "5.5.30",
            "X-Mop-Bundle-Id": "jp.mcdonalds.coupon",
            "X-Vmob-Uid": _VMOB_HEADERS["x-vmob-uid"],
            "X-Vmob-Sessionid": str(_uuid.uuid4()).upper(),
            "X-Mop-Platform-Version": "26.3.1",
            "X-Mop-Platform": "ios",
            "X-Mop-App-Version": "5.5.30(1657)",
            "X-Mop-Session-Token": "",
            "User-Agent": "McDonaldsJapan-Prod/1657 CFNetwork/3860.400.51 Darwin/25.3.0",
        }
        body = {
            "token_api_key": self._VERITRANS_TOKEN_API_KEY,
            "card_number": card_number,
            "card_expire": expiry,
            "security_code": cvv,
            "cardholder_name": cardholder_name,
        }
        try:
            resp = self._sess.post(
                "https://api3.veritrans.co.jp/4gtoken",
                json=body,
                headers=headers,
                timeout=self.timeout,
            )
        except Exception as e:
            raise MCDNetworkError(e)
        data = resp.json()
        token = data.get("token")
        if not token:
            raise MCDError(f"tokenize_card failed: {data}")
        return token

    def add_card_with_3ds(self, veritrans_token: str) -> tuple[str, str]:
        """Veritransトークンで3DSカード登録を開始する。
        返値: (three_ds_order_id, acs_url)
        acs_urlをWebViewで開いて3DS認証後、get_add_card_result()を呼ぶ。
        """
        self._ensure_auth()
        body = _pb_str(1, veritrans_token) + _pb_str(2, "mcdonaldsjp://3ds")
        try:
            resp = self._sess.post(
                "https://pay.dir.prod.mop.mcd.qorcommerce.com/app/mcdpay.CardService/AddCardWithThreeDS",
                headers={**_QOR_HEADERS, "Authorization": f"Bearer {self._root()}"},
                data=body,
                timeout=self.timeout,
            )
        except Exception as e:
            raise MCDNetworkError(e)
        if resp.status_code != 200:
            raise MCDError(f"add_card_with_3ds failed: {resp.status_code} {resp.content[:100]}")
        top = _proto_parse(resp.content)
        outer = next((v for v in top.get(1, []) if isinstance(v, bytes)), None)
        if not outer:
            raise MCDError(f"add_card_with_3ds: empty response: {resp.content.hex()[:60]}")
        inner = _proto_parse(outer)
        three_ds_id = _try_str(inner[1][0]) if 1 in inner else ""
        acs_url     = _try_str(inner[2][0]) if 2 in inner else ""
        return three_ds_id, acs_url

    def get_add_card_result(self, three_ds_order_id: str) -> Optional[str]:
        """3DS完了後にcard_idを取得する。処理中ならNoneを返す。"""
        self._ensure_auth()
        body = _pb_str(1, three_ds_order_id)
        try:
            resp = self._sess.post(
                "https://pay.dir.prod.mop.mcd.qorcommerce.com/app/mcdpay.CardService/GetAddCardWithThreeDSResult",
                headers={**_QOR_HEADERS, "Authorization": f"Bearer {self._root()}"},
                data=body,
                timeout=self.timeout,
            )
        except Exception as e:
            raise MCDNetworkError(e)
        if not resp.content:
            return None
        top = _proto_parse(resp.content)
        raw = next((v for v in top.get(2, []) if isinstance(v, bytes)), None)
        return _try_str(raw) if raw else None

    
    
    

    def get_order_buzzer_notification(self, order_token: str, group: str = "group-f") -> Optional[int]:
        """呼び出し(バズー)番号を確認する。まだなら None を返す。"""
        body = _pb_str(1, order_token)
        try:
            resp = self._sess.post(
                f"https://ord.{group}.prod.mop.mcd.qorcommerce.com/app/mcdord.UserOrderService/GetOrderBuzzerNotification",
                headers={**_QOR_HEADERS, "Authorization": f"Bearer {self._root()}"},
                data=body,
                timeout=self.timeout,
            )
        except Exception as e:
            raise MCDNetworkError(e)
        if not resp.content:
            return None
        top = _proto_parse(resp.content)
        inner_raw = next((v for v in top.get(2, []) if isinstance(v, bytes)), None)
        if not inner_raw:
            return None
        inner = _proto_parse(inner_raw)
        return inner.get(1, [None])[0]

    
    
    

    def get_remaining_coupons(self) -> list[str]:
        """MOP店頭提示用クーポンコード一覧(16文字英数字)を返す。"""
        self._ensure_auth()
        try:
            resp = self._sess.post(
                "https://user-coupon.dir.prod.mop.mcd.qorcommerce.com/app/mcdcoupon.UserCouponService/GetUserRemainingCoupons",
                headers={**_QOR_HEADERS, "Authorization": f"Bearer {self._root()}"},
                data=b"",
                timeout=self.timeout,
            )
        except Exception as e:
            raise MCDNetworkError(e)
        top = _proto_parse(resp.content)
        return [_try_str(v) for v in top.get(1, []) if isinstance(v, bytes)]

    def get_user_tags(self) -> list[str]:
        """MOPユーザータグ一覧を返す。"""
        self._ensure_auth()
        try:
            resp = self._sess.post(
                "https://tag-user-api.dir.prod.mop.mcd.qorcommerce.com/app/mcdtag.UserTagService/GetUserTags",
                headers={**_QOR_HEADERS, "Authorization": f"Bearer {self._root()}"},
                data=b"",
                timeout=self.timeout,
            )
        except Exception as e:
            raise MCDNetworkError(e)
        top = _proto_parse(resp.content)
        return [_try_str(v) for v in top.get(1, []) if isinstance(v, bytes)]

    def get_user_prefs(self) -> list[str]:
        """MOPユーザー設定値一覧を返す。"""
        self._ensure_auth()
        try:
            resp = self._sess.post(
                "https://prefs-user-api.dir.prod.mop.mcd.qorcommerce.com/app/mcdprefs.UserPrefsService/GetUserPrefs",
                headers={**_QOR_HEADERS, "Authorization": f"Bearer {self._root()}"},
                data=b"",
                timeout=self.timeout,
            )
        except Exception as e:
            raise MCDNetworkError(e)
        top = _proto_parse(resp.content)
        return [_try_str(v) for v in top.get(1, []) if isinstance(v, bytes)]