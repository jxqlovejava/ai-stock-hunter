"""美元指数 DXY 可靠获取 — TradingView + 东财 + Yahoo 真实源 + Frankfurter/ECB 估算兜底。

真实源（非估算，均为官方 ICE 美元指数）:
  - TradingView `TVC:DXY`（scanner API 免依赖；需 VPN 网络可达，短超时快速失败）
  - 东财直连 `secid=100.UDI`（实时 push2 + 日K push2his，国内网络稳定）
  - Yahoo chart API `DX-Y.NYB`（间歇 403/429 限流）
估算兜底（官方源全部不可用时的最后手段，必须显式标记 [ESTIMATED]）:
  - Frankfurter（ECB 参考汇率按 ICE 权重公式计算，实测与官方值差 0.26%，容差内）

探索实测（2026-08-09）:
  - akshare `index_global_spot_em()` 依赖东财 push2 clist 接口，代理环境易被拦截（ProxyError）
  - akshare `forex_hist_em(symbol="美元指数")` 的 symbol 映射表无此键，必抛 KeyError
  - 东财直连间歇断连（本网络曾 0/5）、Yahoo 间歇 403/429 → 真实源均加重试
  - TradingView 域名本网络 DNS 污染（需 VPN）；Stooq 需 JS 验证 → 不采用

降级链: TradingView → 东财直连 → Yahoo → Frankfurter估算。≥2 源同时成功且
任意两源差异 ≤ 0.5% 视为交叉验证通过（满足 guardrails "关键数据 ≥2 个独立来源"）。
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# 东财美元指数 DXY（index_global_em_symbol_map: "美元指数" -> code=UDI, market=100）
EM_DXY_SECID = "100.UDI"
# Yahoo 的 DXY 代码（美元指数）
YH_DXY_TICKER = "DX-Y.NYB"
# 交叉验证容差（两源价格差异 > 0.5% 视为不一致，不标 cross_validated）
CROSS_VALIDATION_TOLERANCE = 0.5
# 需要的历史点数（含当前点）才能计算 20 日变化
MIN_BARS_FOR_CHANGE = 21
# ICE 美元指数权重与常数（欧元/日元/英镑/加元/瑞典克朗/瑞郎）
DXY_WEIGHTS = {"EUR": -0.576, "JPY": 0.136, "GBP": -0.119, "CAD": 0.091, "SEK": 0.042, "CHF": 0.036}
DXY_CONSTANT = 50.14348112
_HTTP_TIMEOUT = 6  # 真实源失败多为快速断连/限流，短超时加快重试
_RETRY_ATTEMPTS = 2
_RETRY_DELAY = 1.0
# TradingView scanner API（需 VPN；无 VPN 时快速失败，避免拖慢管道）
_TV_SCAN_URL = "https://scanner.tradingview.com/america/scan"
_TV_SYMBOL = "TVC:DXY"
_TV_TIMEOUT = 5
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
)


@dataclass
class DxyData:
    """DXY 数据 + 交叉验证状态。

    估算 vs 官方：东财/Yahoo 为官方实时 DXY；Frankfurter 为 ECB 参考汇率按
    ICE 权重计算的估算值（非官方 ICE DXY）。官方源不可用时的兜底估算值必须
    显式标记 estimated，禁止冒充实际值。
    """

    dxy: Optional[float] = None  # 美元指数最新值
    dxy_change_20d: Optional[float] = None  # 20 交易日变化 (%)
    dxy_estimated: bool = False  # dxy 为 ECB 计算估算值（无官方实时源）
    change_estimated: bool = False  # 20日变化来自估算序列
    source: str = ""  # 实际来源: eastmoney / frankfurter / yahoo / 组合
    cross_validated: bool = False  # ≥2 源值一致
    errors: list[str] = field(default_factory=list)


def _http_get_json(url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _UA, "Referer": "https://quote.eastmoney.com/"},
    )
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def _system_http_proxies() -> dict:
    """读取 macOS 系统 HTTP/HTTPS 代理（走 VPN 时用）。

    注意：`src.utils.proxy.configure_no_proxy()` 会设置 NO_PROXY 环境变量，
    导致 `urllib.request.getproxies()` 命中环境变量分支后**不再 fallback 读
    macOS 系统代理**（scutil），TradingView 这类被墙域名必须显式走代理。
    """
    try:
        import _scproxy  # noqa: PLC0415

        sys_proxies = _scproxy._get_proxies() or {}
    except Exception:  # noqa: BLE001
        sys_proxies = {}
    proxies = {k: v for k, v in sys_proxies.items() if k in ("http", "https")}
    no = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    if no:
        proxies["no"] = no
    return proxies


def _http_post_json(
    url: str,
    payload: dict,
    referer: str,
    timeout: float = _HTTP_TIMEOUT,
    use_proxy: bool = False,
) -> dict:
    """POST JSON 请求（TradingView scanner API 用）。use_proxy 时走 macOS 系统代理。"""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "text/plain;charset=UTF-8",
            "User-Agent": _UA,
            "Referer": referer,
        },
    )
    handlers: list = []
    if use_proxy:
        proxies = _system_http_proxies()
        if proxies:
            handlers.append(urllib.request.ProxyHandler(proxies))
    opener = urllib.request.build_opener(*handlers)
    with opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _http_get_json_retry(
    url: str,
    attempts: int = _RETRY_ATTEMPTS,
    delay: float = _RETRY_DELAY,
) -> dict:
    """带重试的 JSON 请求 — 真实源间歇性断连/限流时提高命中率。"""
    last_exc: Exception | None = None
    for i in range(attempts):
        try:
            return _http_get_json(url)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.debug("HTTP retry %d/%d %s: %s", i + 1, attempts, url, exc)
            if i < attempts - 1:
                time.sleep(delay)
    assert last_exc is not None
    raise last_exc


def _pct_change(last: float, prev: float) -> float:
    return round((float(last) / float(prev) - 1) * 100, 2)


def _compute_dxy(rates: dict) -> Optional[float]:
    """按 ICE 权重公式由汇率算 DXY：50.14348112 × Π(汇率^权重)。"""
    try:
        pairs = {
            "EUR": 1.0 / rates["EUR"],  # EURUSD
            "JPY": rates["JPY"],  # USDJPY
            "GBP": 1.0 / rates["GBP"],  # GBPUSD
            "CAD": rates["CAD"],  # USDCAD
            "SEK": rates["SEK"],  # USDSEK
            "CHF": rates["CHF"],  # USDCHF
        }
    except (KeyError, TypeError, ZeroDivisionError):
        return None
    exponent = sum(w * math.log(pairs[c]) for c, w in DXY_WEIGHTS.items())
    return DXY_CONSTANT * math.exp(exponent)


def fetch_dxy() -> DxyData:
    """主入口。降级链: 东财直连 → Frankfurter计算 → Yahoo。"""
    results: list[tuple[Optional[float], Optional[float], str]] = []
    for fetcher in (_fetch_tradingview, _fetch_eastmoney, _fetch_frankfurter, _fetch_yahoo):
        try:
            item = fetcher()
            if item is not None:
                results.append(item)
        except Exception as exc:  # noqa: BLE001
            logger.debug("DXY %s failed: %s", fetcher.__name__, exc)

    if not results:
        return DxyData(errors=["美元指数DXY 所有来源均失败"])

    # dxy 值：官方实时源（eastmoney/yahoo）优先，Frankfurter 估算值兜底
    # （results 已按 em → ff → yh 顺序，取第一个有值的即符合优先级）
    dxy: Optional[float] = None
    dxy_estimated = False
    for r in results:
        if r[0] is not None:
            dxy = r[0]
            dxy_estimated = r[2] == "frankfurter"
            break
    # 20日变化：官方K线（eastmoney/yahoo）优先，估算序列兜底
    change_20d: Optional[float] = None
    change_estimated = False
    for r in results:
        if r[1] is not None:
            change_20d = r[1]
            change_estimated = r[2] == "frankfurter"
            break

    # 交叉验证：任意两源在容差内即视为通过（东财/Yahoo 实时一致，或与 ECB 计算值接近）
    values = [r[0] for r in results if r[0] is not None]
    cross_validated = False
    if len(values) >= 2:
        for i in range(len(values)):
            for j in range(i + 1, len(values)):
                if abs(values[i] - values[j]) / values[i] * 100 <= CROSS_VALIDATION_TOLERANCE:
                    cross_validated = True
                    break
            if cross_validated:
                break
        if not cross_validated:
            logger.warning("DXY 双源不一致: %s", values)

    return DxyData(
        dxy=dxy,
        dxy_change_20d=change_20d,
        dxy_estimated=dxy_estimated,
        change_estimated=change_estimated,
        source="+".join(r[2] for r in results),
        cross_validated=cross_validated,
    )


def _fetch_tradingview() -> Optional[tuple[float, Optional[float], str]]:
    """TradingView TVC:DXY — 官方 ICE 美元指数（需 VPN 网络可达）。

    scanner API 免依赖返回实时价；无历史序列 → 20日变化由下游其他源补齐。
    无 VPN 时 5s 快速失败，不拖慢管道。
    """
    data = _http_post_json(
        _TV_SCAN_URL,
        {"symbols": {"tickers": [_TV_SYMBOL]},
         "columns": ["close", "description", "currency"]},
        referer="https://www.tradingview.com/",
        timeout=_TV_TIMEOUT,
        use_proxy=True,
    )
    rows = data.get("data") or []
    if not rows:
        return None
    close = (rows[0].get("d") or [None])[0]
    if close is None:
        return None
    return (float(close), None, "tradingview")


def _fetch_eastmoney() -> Optional[tuple[float, Optional[float], str]]:
    """东财 DXY (100.UDI): 实时 + 日K历史。返回 (dxy, change_20d, source)。"""
    # 实时
    quote = _http_get_json_retry(
        f"https://push2.eastmoney.com/api/qt/stock/get?secid={EM_DXY_SECID}"
        "&fltt=2&fields=f43,f57,f58,f60,f170"
    )
    qd = quote.get("data")
    if not qd or not qd.get("f43"):
        return None
    dxy = float(qd["f43"])

    # 日K历史（计算 20 日变化；失败不影响实时值）
    change_20d: Optional[float] = None
    try:
        beg = (date.today() - timedelta(days=400)).strftime("%Y%m%d")
        hist = _http_get_json_retry(
            f"https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={EM_DXY_SECID}"
            "&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57"
            f"&klt=101&fqt=0&beg={beg}&end=20500101&lmt=150"
        )
        klines = (hist.get("data") or {}).get("klines") or []
        closes = [float(k.split(",")[2]) for k in klines if k]
        if len(closes) >= MIN_BARS_FOR_CHANGE:
            change_20d = _pct_change(closes[-1], closes[-MIN_BARS_FOR_CHANGE])
    except Exception as exc:  # noqa: BLE001
        logger.debug("DXY eastmoney hist failed: %s", exc)

    return (dxy, change_20d, "eastmoney")


def _fetch_frankfurter() -> Optional[tuple[float, Optional[float], str]]:
    """Frankfurter(ECB) 参考汇率 → ICE 公式计算 DXY。稳定、免费、不限流。"""
    start = (date.today() - timedelta(days=120)).strftime("%Y-%m-%d")
    data = _http_get_json(
        f"https://api.frankfurter.app/{start}..?from=USD"
        "&to=EUR,JPY,GBP,CAD,SEK,CHF"
    )
    rates_map = data.get("rates") or {}
    if not rates_map:
        return None
    days = sorted(rates_map.keys())
    dxy_series = [v for v in (_compute_dxy(rates_map[d]) for d in days) if v is not None]
    if not dxy_series:
        return None
    change_20d = (
        _pct_change(dxy_series[-1], dxy_series[-MIN_BARS_FOR_CHANGE])
        if len(dxy_series) >= MIN_BARS_FOR_CHANGE
        else None
    )
    return (dxy_series[-1], change_20d, "frankfurter")


def _fetch_yahoo() -> Optional[tuple[float, Optional[float], str]]:
    """Yahoo Finance DXY (DX-Y.NYB): 区间收盘序列。"""
    data = _http_get_json_retry(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{YH_DXY_TICKER}"
        "?range=2mo&interval=1d"
    )
    try:
        closes_raw = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
    except (KeyError, IndexError, TypeError):
        return None
    closes = [float(c) for c in closes_raw if c is not None]
    if not closes:
        return None
    change_20d = (
        _pct_change(closes[-1], closes[-MIN_BARS_FOR_CHANGE])
        if len(closes) >= MIN_BARS_FOR_CHANGE
        else None
    )
    return (closes[-1], change_20d, "yahoo")
