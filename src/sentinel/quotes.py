# -*- coding: utf-8 -*-
"""轻量报价 — 腾讯批量为主，华泰 queryIndicator 可选回退。"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from .models import QuoteSnapshot

UA = "Mozilla/5.0 (compatible; BaizeSentinel/1.0)"


def infer_market(symbol: str) -> str:
    s = symbol.strip()
    if s.startswith(("5", "6", "9")):
        return "SH"
    if s.startswith(("0", "1", "2", "3")):
        return "SZ"
    return "SZ"


def tencent_prefix(symbol: str) -> str:
    m = infer_market(symbol)
    return ("sh" if m == "SH" else "sz") + symbol


def fetch_tencent_batch(symbols: list[str], timeout: float = 10.0) -> dict[str, QuoteSnapshot]:
    """腾讯财经批量行情。"""
    if not symbols:
        return {}
    prefixed = [tencent_prefix(s) for s in symbols]
    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read().decode("gbk", errors="replace")

    out: dict[str, QuoteSnapshot] = {}
    for line in data.strip().split(";"):
        if not line.strip() or "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        raw = line.split('"', 1)[1].rsplit('"', 1)[0]
        vals = raw.split("~")
        if len(vals) < 35:
            continue
        code = key[2:] if len(key) > 2 else key
        try:
            price = float(vals[3] or 0)
        except ValueError:
            continue
        if price <= 0:
            continue
        out[code] = QuoteSnapshot(
            symbol=code,
            name=vals[1] or "",
            price=price,
            change_pct=_f(vals[32]),
            open=_f_opt(vals[5]),
            high=_f_opt(vals[33]),
            low=_f_opt(vals[34]),
            prev_close=_f_opt(vals[4]),
            source="tencent",
        )
    return out


def fetch_huatai_quote(
    symbol: str,
    name: str = "",
    api_key: str = "",
    timeout: float = 15.0,
) -> Optional[QuoteSnapshot]:
    """华泰妙想 queryIndicator 单票回退（需 HT_APIKEY）。"""
    key = api_key or os.environ.get("HT_APIKEY", "")
    if not key:
        key = _load_ht_key_from_files()
    if not key:
        return None

    label = f"{name}({symbol})" if name else symbol
    body = json.dumps({"query": f"{label}最新价 涨跌幅 最高价 最低价 开盘价"}, ensure_ascii=False).encode(
        "utf-8"
    )
    req = urllib.request.Request(
        "https://ai.zhangle.com/edge/entry/gate/api/finAnalysis/queryIndicator",
        data=body,
        method="POST",
        headers={
            "apiKey": key,
            "skillCode": "mx_1779108020995",
            "Content-Type": "application/json",
            "User-Agent": UA,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None

    if payload.get("code") not in (0, None) and not payload.get("ok"):
        # 兼容 code==0 或 ok 字段
        if payload.get("code") != 0:
            return None
    data = payload.get("data") or {}
    answer = data.get("answer") or ""
    if not answer:
        return None

    price = _re_price(answer, r"最新价(?:为|是)?[：:]?\s*(\d+\.?\d*)")
    if price is None:
        price = _re_price(answer, r"现价(?:为|是)?[：:]?\s*(\d+\.?\d*)")
    if price is None:
        return None

    return QuoteSnapshot(
        symbol=symbol,
        name=name,
        price=price,
        change_pct=_re_price(answer, r"涨跌幅(?:为|是)?[：:]?\s*(-?\d+\.?\d*)") or 0.0,
        high=_re_price(answer, r"最高价(?:为|是)?[：:]?\s*(\d+\.?\d*)"),
        low=_re_price(answer, r"最低价(?:为|是)?[：:]?\s*(\d+\.?\d*)"),
        open=_re_price(answer, r"开盘价(?:为|是)?[：:]?\s*(\d+\.?\d*)"),
        source="huatai",
    )


def fetch_quotes(
    symbols: list[str],
    names: Optional[dict[str, str]] = None,
    prefer_huatai: bool = False,
) -> tuple[dict[str, QuoteSnapshot], list[str]]:
    """批量拉报价。返回 (quotes, errors)。"""
    names = names or {}
    errors: list[str] = []
    quotes: dict[str, QuoteSnapshot] = {}

    if not prefer_huatai:
        try:
            quotes = fetch_tencent_batch(symbols)
        except Exception as e:
            errors.append(f"腾讯行情失败: {e}")

    missing = [s for s in symbols if s not in quotes]
    for s in missing:
        try:
            q = fetch_huatai_quote(s, names.get(s, ""))
            if q:
                quotes[s] = q
            else:
                errors.append(f"{s} 报价缺失")
        except Exception as e:
            errors.append(f"{s} 报价异常: {e}")

    return quotes, errors


def _load_ht_key_from_files() -> str:
    candidates = [
        Path.home() / ".htsc-skills" / "config",
        Path.home() / ".hermes" / ".env",
        Path("data") / ".env",
        Path(".env"),
    ]
    for p in candidates:
        if not p.exists():
            continue
        try:
            for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if line.startswith("HT_APIKEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            continue
    return ""


def _f(v: str) -> float:
    try:
        return float(v) if v else 0.0
    except ValueError:
        return 0.0


def _f_opt(v: str) -> Optional[float]:
    try:
        return float(v) if v else None
    except ValueError:
        return None


def _re_price(text: str, pattern: str) -> Optional[float]:
    m = re.search(pattern, text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None
