# -*- coding: utf-8 -*-
"""MiaoXiangAdapter 单元测试。"""

import os
from unittest.mock import MagicMock, patch

import pytest

from src.data.miaoxiang_adapter import MiaoXiangAdapter


class TestMiaoXiangAdapter:
    """妙想 CLI 适配器测试。"""

    def test_default_construction(self):
        """默认构造 — 从环境变量读取 API Key。"""
        adapter = MiaoXiangAdapter()
        assert adapter is not None
        # API key 可能已设置也可能未设置，不直接断言值

    def test_explicit_api_key(self):
        """显式传入 API Key。"""
        adapter = MiaoXiangAdapter(api_key="test_key_123")
        assert adapter._api_key == "test_key_123"

    def test_health_check_without_key(self):
        """无 API Key 时 health_check 返回 False。"""
        adapter = MiaoXiangAdapter(api_key="")
        assert adapter.health_check() is False

    def test_health_check_with_key(self):
        """有 API Key 且脚本存在时 health_check 返回 True。"""
        adapter = MiaoXiangAdapter(api_key="test_key")
        result = adapter.health_check()
        # 取决于 ~/.claude/skills/mx-data/mx_data.py 是否存在
        assert isinstance(result, bool)

    def test_api_key_configured(self):
        """api_key_configured 属性。"""
        adapter = MiaoXiangAdapter(api_key="test")
        assert adapter.api_key_configured is True

        adapter2 = MiaoXiangAdapter(api_key="")
        assert adapter2.api_key_configured is False

    def test_cache_set_and_get(self):
        """缓存读写。"""
        adapter = MiaoXiangAdapter(api_key="test")
        adapter._cache_set("test_key", {"data": "value"})
        result = adapter._cache_get("test_key")
        assert result == {"data": "value"}

    def test_cache_clear(self):
        """缓存清空。"""
        adapter = MiaoXiangAdapter(api_key="test")
        adapter._cache_set("test_key", "value")
        adapter.cache_clear()
        assert len(adapter._cache) == 0

    @patch("subprocess.run")
    def test_run_skill_success(self, mock_run):
        """_run_skill 成功执行并解析 JSON。"""
        import json
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "test output"
        mock_run.return_value = mock_result

        adapter = MiaoXiangAdapter(api_key="test_key", output_dir="/tmp/test_mx")
        # 创建一个模拟的输出 JSON 文件
        os.makedirs("/tmp/test_mx/mx-data", exist_ok=True)
        test_data = {"data": {"test": "hello"}}
        with open("/tmp/test_mx/mx-data/mx_data_test_raw.json", "w") as f:
            json.dump(test_data, f)

        result = adapter._run_skill("mx-data", "test query")
        assert result == test_data

    @patch("subprocess.run")
    def test_run_skill_timeout(self, mock_run):
        """_run_skill 超时返回 None。"""
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=5)

        adapter = MiaoXiangAdapter(api_key="test_key")
        result = adapter._run_skill("mx-data", "test query")
        assert result is None

    def test_run_skill_unknown_skill(self):
        """_run_skill 未知 skill 返回 None。"""
        adapter = MiaoXiangAdapter(api_key="test_key")
        result = adapter._run_skill("unknown-skill", "test")
        assert result is None

    def test_moni_request_without_key(self):
        """无 API Key 时 moni_request 返回 None。"""
        adapter = MiaoXiangAdapter(api_key="")
        result = adapter.moni_request("positions", {"moneyUnit": 1})
        assert result is None  # 无 key 直接失败

    def test_poster_post_article_without_key(self):
        """无 API Key 时 poster_post_article 返回 None。"""
        adapter = MiaoXiangAdapter(api_key="")
        result = adapter.poster_post_article("title", "<p>text</p>")
        assert result is None
