# -*- coding: utf-8 -*-
"""结构化输出 + provider 降级工具测试。"""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest import mock

from src.llm.structured import (
    _extract_json,
    _validate,
    dataclass_to_json_schema,
    invoke_structured_or_freetext,
)


@dataclass
class DemoSignal:
    signal: str
    confidence: float = 0.5
    reasons: list[str] = field(default_factory=list)


SCHEMA = dataclass_to_json_schema(DemoSignal)


class TestDataclassToJsonSchema:
    def test_required_only_no_default(self):
        assert SCHEMA["required"] == ["signal"]

    def test_field_types(self):
        props = SCHEMA["properties"]
        assert props["signal"]["type"] == "string"
        assert props["confidence"]["type"] == "number"
        assert props["reasons"]["type"] == "array"
        assert props["reasons"]["items"]["type"] == "string"

    def test_optional_field_not_required(self):
        assert "confidence" not in SCHEMA["required"]
        assert "reasons" not in SCHEMA["required"]


class TestExtractJson:
    def test_plain_json(self):
        assert _extract_json('{"a": 1}') == {"a": 1}

    def test_markdown_fence(self):
        assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_json_embedded_in_prose(self):
        assert _extract_json('结论如下 {"signal": "BUY"} 完毕') == {"signal": "BUY"}

    def test_no_json(self):
        assert _extract_json("没有任何 JSON") is None


class TestValidate:
    def test_valid_passes(self):
        assert _validate({"signal": "BUY", "confidence": 0.9}, SCHEMA) == []

    def test_missing_required(self):
        errs = _validate({"confidence": 0.9}, SCHEMA)
        assert any("signal" in e for e in errs)

    def test_wrong_type(self):
        errs = _validate({"signal": "BUY", "confidence": "high"}, SCHEMA)
        assert any("confidence" in e for e in errs)

    def test_enum_violation(self):
        s = {"type": "object", "properties": {"signal": {"type": "string", "enum": ["BUY", "SELL"]}}, "required": ["signal"]}
        assert any("枚举" in e for e in _validate({"signal": "HOLD"}, s))


class TestInvokeStructuredOrFreetext:
    def test_structured_path_returns_dict(self):
        with mock.patch("src.llm.structured._chat", return_value='{"signal": "BUY", "confidence": 0.9}'):
            result = invoke_structured_or_freetext("prompt", schema=SCHEMA)
        assert isinstance(result, dict)
        assert result["signal"] == "BUY"

    def test_structured_invalid_falls_back_to_freetext(self):
        # 第一次 json_schema 返回结构不合格, 第二次自由文本返回合格 JSON
        calls = [0]

        def fake_chat(messages, **kwargs):
            calls[0] += 1
            if kwargs.get("response_format"):
                return "这不是 JSON"
            return '{"signal": "SELL", "confidence": 0.7}'

        with mock.patch("src.llm.structured._chat", side_effect=fake_chat):
            result = invoke_structured_or_freetext("prompt", schema=SCHEMA)
        assert calls[0] == 2  # 两条路径都试了
        assert result["signal"] == "SELL"

    def test_both_fail_returns_raw_text(self):
        def fake_chat(messages, **kwargs):
            if kwargs.get("response_format"):
                return "文本1"
            return "这是纯文本, 没有 JSON"

        with mock.patch("src.llm.structured._chat", side_effect=fake_chat):
            result = invoke_structured_or_freetext("prompt", schema=SCHEMA)
        assert result == "这是纯文本, 没有 JSON"

    def test_no_api_key_returns_empty(self):
        with mock.patch("src.llm.structured._resolve_api", return_value=None):
            result = invoke_structured_or_freetext("prompt", schema=SCHEMA)
        assert result == ""
