# -*- coding: utf-8 -*-
"""网络代理工具 — 统一处理 macOS 系统代理对国内数据源请求的拦截。

macOS 系统代理（如 Clash Verge @ 127.0.0.1:7897）通过
urllib.request.getproxies() 自动注入到所有 requests 请求，导致东财等
国内金融数据源被 WAF 拦截（东财 push2 CDN 对 requests TLS 指纹做针对性封堵）。

本模块提供两个机制：
1. configure_no_proxy() — 把国内金融域追加进 NO_PROXY/no_proxy 环境变量，
   使 requests/curl_cffi/urllib 对该批域名直连绕过系统代理（幂等，任意入口调用一次）。
2. direct_session() — 返回 trust_env=False + proxies 清空的直连 Session，
   供未使用全局 NO_PROXY 的模块防御性统一。

注意：海外源（如 dramexchange.com）不进 NO_PROXY 清单，保持走代理。
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# 国内金融域（按 hostname 后缀匹配；eastmoney.com 覆盖其全部子域含 82.push2 等）。
# 出现在此清单内的域名请求将直连绕过系统代理。
_DOMESTIC_NO_PROXY_DOMAINS = (
    "eastmoney.com",
    "eastmoney.com.cn",
    "dfcfw.com",        # 东财研报 PDF
    "gtimg.cn",         # 腾讯行情 K线
    "10jqka.com.cn",    # 同花顺 THS
    "hexin.cn",         # 北向资金（hexin）
    "cninfo.com.cn",    # 巨潮/互动易
)

# 已配置标记：避免重复 append 膨胀环境变量（线程/多次 import 安全）
_configured: bool = False


def configure_no_proxy() -> None:
    """幂等地把国内金融域追加进 NO_PROXY / no_proxy 环境变量。

    - macOS 的 urllib.request.getproxies() 读取系统网络配置（scutil），
      同时也会参考 NO_PROXY/no_proxy 环境变量做域名豁免。
    - requests.should_bypass_proxies 按 hostname 后缀匹配，与代理来源无关。
    - curl_cffi 由底层 libcurl 读 no_proxy env，同样生效。
    - 幂等：仅首次调用真正修改环境变量，之后 no-op。
    """
    global _configured
    if _configured:
        return
    _configured = True

    existing = os.environ.get("NO_PROXY", "")
    missing = [d for d in _DOMESTIC_NO_PROXY_DOMAINS if d not in existing]
    if not missing:
        # 已有完整覆盖，仅确保小写镜像
        os.environ["no_proxy"] = os.environ["NO_PROXY"]
        return

    pattern = ",".join(missing)
    os.environ["NO_PROXY"] = f"{existing},{pattern}" if existing else pattern
    # macOS 的 urllib 也读取小写版本
    os.environ["no_proxy"] = os.environ["NO_PROXY"]
    logger.debug("NO_PROXY 已追加国内金融域: %s", pattern)


def direct_session() -> "Optional[object]":
    """返回 trust_env=False + proxies 清空的直连 Session（绕过系统代理）。

    Returns:
        requests.Session 实例；requests 不可用时返回 None。
    """
    try:
        import requests
    except ImportError:
        logger.warning("requests 未安装，direct_session 不可用")
        return None

    session = requests.Session()
    session.trust_env = False
    session.proxies = {"http": None, "https": None}
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        ),
    })
    return session
