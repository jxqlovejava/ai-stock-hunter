# -*- coding: utf-8 -*-
"""代理配置测试 — 验证 macOS 系统代理对国内数据源请求的正确绕过。

不依赖真实网络：所有断言基于 requests.utils.should_bypass_proxies /
monkeypatch 的 Session.send 捕获，验证 NO_PROXY 生效、_em_no_proxy 正确
patch/恢复、akshare 东财方法在无代理下被调用。
"""

from __future__ import annotations

import pytest

from src.utils.proxy import configure_no_proxy, direct_session


# ---------------------------------------------------------------------------
# configure_no_proxy — NO_PROXY 环境变量
# ---------------------------------------------------------------------------

class TestConfigureNoProxy:
    def test_domains_added(self):
        """国内金融域应进入 NO_PROXY 并生效。"""
        configure_no_proxy()
        assert "eastmoney.com" in __import__("os").environ.get("NO_PROXY", "")

    def test_bypass_returns_true(self):
        """eastmoney / 腾讯 / 同花顺 / hexin / cninfo 应绕过代理。"""
        import requests.utils
        configure_no_proxy()
        for url in (
            "https://push2.eastmoney.com/api/qt/clist/get",
            "https://push2his.eastmoney.com/api/qt/stock/kline/get",
            "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
            "https://basic.10jqka.com.cn/new/000001/worth.html",
            "https://data.hexin.cn/market/hsgtApi/",
            "https://irm.cninfo.com.cn/newircs/index/queryKeyboardInfo",
        ):
            assert requests.utils.should_bypass_proxies(url, None) is True, url

    def test_overseas_keeps_proxy(self):
        """海外源 dramexchange 和普通域名应保持走代理。"""
        import requests.utils
        configure_no_proxy()
        for url in (
            "https://www.dramexchange.com/",
            "https://www.baidu.com/",
            "https://api.openai.com/v1/models",
        ):
            assert requests.utils.should_bypass_proxies(url, None) is False, url

    def test_idempotent(self, monkeypatch):
        """重复调用不膨胀 NO_PROXY。"""
        monkeypatch.setattr("src.utils.proxy._configured", False)
        import os
        configure_no_proxy()
        before = os.environ["NO_PROXY"]
        # 重置标记再调用一次
        monkeypatch.setattr("src.utils.proxy._configured", False)
        configure_no_proxy()
        assert os.environ["NO_PROXY"] == before


# ---------------------------------------------------------------------------
# direct_session — 直连 Session
# ---------------------------------------------------------------------------

class TestDirectSession:
    def test_trust_env_false(self):
        """direct_session 应返回 trust_env=False + proxies 清空的 session。"""
        session = direct_session()
        assert session is not None
        assert session.trust_env is False
        assert session.proxies.get("http") is None
        assert session.proxies.get("https") is None

    def test_no_proxy_on_request(self, monkeypatch):
        """设死代理后 direct_session 请求应绕过代理（不触发代理连接）。"""
        import os
        import requests

        # 设置一个不可用的死代理
        monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
        monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")

        # patch Session.send 捕获，断言请求未走代理
        sent = []

        original_send = requests.Session.send

        def _capture_send(self, request, **kwargs):
            sent.append((request.url, self.trust_env))
            # 返回假响应避免真实网络
            from requests.models import Response
            resp = Response()
            resp.status_code = 200
            resp._content = b'{"rc":0}'
            resp.url = request.url
            resp.request = request
            return resp

        monkeypatch.setattr(requests.Session, "send", _capture_send)

        session = direct_session()
        session.get("https://push2.eastmoney.com/api/qt/clist/get", timeout=5)

        assert len(sent) == 1
        url, trust_env = sent[0]
        assert trust_env is False  # trust_env=False 保证不走环境代理


# ---------------------------------------------------------------------------
# _em_no_proxy — akshare 东财方法 patch/恢复
# ---------------------------------------------------------------------------

class TestEmNoProxy:
    def test_patch_and_restore(self):
        """_em_no_proxy 上下文内 requests.get/post 被替换，退出后恢复。"""
        import requests
        from src.data import akshare

        original_get = requests.get
        original_post = requests.post

        with akshare._em_no_proxy():
            assert requests.get is not original_get
            assert requests.post is not original_post
            # session 方法 trust_env=False
            assert requests.get.__self__.trust_env is False

        # 退出后恢复
        assert requests.get is original_get
        assert requests.post is original_post

    def test_akshare_hist_fallback_in_no_proxy(self, monkeypatch):
        """东财历史K线 fallback 应在 _em_no_proxy 内调用（绕过代理）。"""
        import requests
        from src.data import akshare

        # 模拟：腾讯源失败 → 东财 fallback
        captured_in_proxy = {}

        def fake_tx(*args, **kwargs):
            raise ConnectionError("tx fail")

        def fake_em(*args, **kwargs):
            # 记录当前 requests.get 是否被 patch（即处于 no_proxy 上下文）
            captured_in_proxy["patched"] = requests.get.__self__.trust_env is False
            import pandas as pd
            return pd.DataFrame()

        monkeypatch.setattr(akshare.ak, "stock_zh_a_hist_tx", fake_tx)
        monkeypatch.setattr(akshare, "_orig_stock_zh_a_hist", fake_em)

        result = akshare._patched_stock_zh_a_hist("000001", "daily")
        assert captured_in_proxy.get("patched") is True

    def test_spot_tier1_in_no_proxy(self, monkeypatch):
        """全市场行情 Tier-1 stock_zh_a_spot 应在 _em_no_proxy 内调用。"""
        import requests
        from src.data import akshare

        captured = {}

        def fake_spot():
            captured["patched"] = requests.get.__self__.trust_env is False
            import pandas as pd
            return pd.DataFrame({"code": ["000001"]})

        monkeypatch.setattr(akshare, "_PUSH2_UNAVAILABLE", False)
        monkeypatch.setattr(akshare.ak, "stock_zh_a_spot", fake_spot)

        # 清缓存强制重新拉取
        prov = akshare.AKShareProvider()
        prov._spot_cache = None
        prov._spot_cache_time = None
        df = prov._get_spot()
        assert captured.get("patched") is True
        assert len(df) > 0
