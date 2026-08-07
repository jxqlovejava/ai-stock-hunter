# -*- coding: utf-8 -*-
"""AI Stock Hunter — A 股智能投资系统."""

__version__ = "0.1.0"

# 应用入口：确保国内金融数据源（东财/腾讯/同花顺/巨潮等）绕过 macOS 系统代理直连。
# 任何 `import src.*`（CLI / tests / cron）都会先执行，单点覆盖 requests/curl_cffi/urllib。
from src.utils.proxy import configure_no_proxy

configure_no_proxy()
