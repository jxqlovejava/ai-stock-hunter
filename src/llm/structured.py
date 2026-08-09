# -*- coding: utf-8 -*-
"""结构化输出 + provider 降级 (Structured Output with Provider Degradation)。

借鉴 TradingAgents `agents/utils/structured.py` 的契约思想:
  - 先尝试 provider 原生结构化输出 (OpenAI-compatible `json_schema` response_format)
  - 失败则降级为自由文本 + JSON 提取 + 轻量 schema 校验
  - 两条路径都失败时返回原始文本, 由调用方决定如何降级 (绝不静默编造)

与 compactor 一致, 仅依赖 stdlib urllib, 无第三方依赖。

Usage:
    from src.llm.structured import invoke_structured_or_freetext

    result = invoke_structured_or_freetext(
        "给一个看多/看空结论",
        schema={
            "type": "object",
            "properties": {
                "signal": {"type": "string", "enum": ["BUY", "HOLD", "SELL"]},
                "confidence": {"type": "number"},
            },
            "required": ["signal"],
        },
        model="deepseek-chat",
    )
    # result 为 dict (结构化) 或 str (两条路径都失败时的原始文本)
"""

from __future__ import annotations

import json
import logging
import re
import typing
import urllib.request
from dataclasses import is_dataclass
from typing import Any, Optional, Union

from src.llm.compactor import _resolve_api

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dataclass → JSON Schema (轻量, 支持嵌套 dataclass 与 list)
# ---------------------------------------------------------------------------

_TYPE_MAP = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def dataclass_to_json_schema(cls: type, name: str | None = None) -> dict:
    """把 @dataclass DTO 转成 JSON Schema (供 json_schema 结构化输出用)。

    支持字段类型 str/int/float/bool/list[X]/Optional[X]/嵌套 dataclass。
    兼容 `from __future__ import annotations` (注解是字符串): 用
    typing.get_type_hints 解析为真实类型, 解析失败时回退字符串名映射。
    不支持的类型回落为 {"type": "string"} (宽松), 并在 log 里提示。
    """
    if not is_dataclass(cls):
        raise TypeError(f"{cls.__name__} 不是 dataclass")
    import dataclasses

    try:
        hints = typing.get_type_hints(cls)
    except Exception:
        hints = {f.name: f.type for f in dataclasses.fields(cls)}

    props: dict[str, Any] = {}
    required: list[str] = []
    for f in dataclasses.fields(cls):
        has_default = (f.default is not dataclasses.MISSING) or (
            f.default_factory is not dataclasses.MISSING
        )
        ftype = hints.get(f.name, f.type)
        _push_field_schema(props, f.name, ftype, required, not has_default)
    return {
        "type": "object",
        "name": name or cls.__name__,
        "properties": props,
        "required": required,
    }


def _push_field_schema(props: dict, name: str, ftype: Any, required: list[str], is_required: bool) -> None:
    """把一个字段类型递归填入 props[name], 并处理 Optional/list[嵌套] 与 required。"""
    origin = getattr(ftype, "__origin__", None)

    if origin is not None and getattr(ftype, "_name", None) == "Optional":
        inner = ftype.__args__[0]
        props[name] = _type_to_schema(inner)
        return  # Optional 字段不强制 required

    if is_required:
        required.append(name)

    props[name] = _type_to_schema(ftype)


def _type_to_schema(ftype: Any) -> dict:
    origin = getattr(ftype, "__origin__", None)
    if origin is Union:
        args = [a for a in getattr(ftype, "__args__", ()) if a is not type(None)]
        if len(args) == 1:
            return _type_to_schema(args[0])
        return {"type": "string"}  # 多类型 Union → 宽松
    if origin is list:
        item = ftype.__args__[0] if getattr(ftype, "__args__", None) else str
        return {"type": "array", "items": _type_to_schema(item)}
    if is_dataclass(ftype):
        return dataclass_to_json_schema(ftype)
    base = _TYPE_MAP.get(ftype)
    if base:
        return {"type": base}
    # 未识别类型 → 宽松 string (结构化失败会走降级, 不阻塞)
    logger.debug("structured: 字段类型 %r 未映射, 回落 string", ftype)
    return {"type": "string"}


# ---------------------------------------------------------------------------
# LLM 调用
# ---------------------------------------------------------------------------


def _chat(
    messages: list[dict],
    *,
    model: str,
    response_format: Optional[dict] = None,
    max_tokens: int = 2048,
    temperature: float = 0.0,
    timeout: int = 60,
) -> str | None:
    """一次 OpenAI-compatible chat 调用, 返回 assistant 文本; 失败返回 None。"""
    resolved = _resolve_api(model)
    if not resolved:
        logger.debug("structured: %s 未配置 API key, 跳过", model)
        return None
    base_url, api_key = resolved
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if response_format is not None:
        body["response_format"] = response_format
    req = urllib.request.Request(
        base_url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            return content or None
    except Exception as e:
        logger.debug("structured: LLM 调用失败 — %s", e)
        return None


def _extract_json(text: str) -> Optional[dict]:
    """从自由文本里尽力提取 JSON 对象 (去 markdown 代码块围栏)。"""
    if not text:
        return None
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", t, re.S)
    if m:
        t = m.group(1)
    # 直接尝试
    try:
        return json.loads(t)
    except Exception:
        pass
    # 找第一个 { 到最后一个 }
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(t[start : end + 1])
        except Exception:
            return None
    return None


def _validate(data: dict, schema: dict) -> list[str]:
    """轻量 schema 校验: required 必须存在, 任何存在的字段类型/枚举须匹配。

    返回错误列表(空=通过)。
    """
    errors: list[str] = []
    props = schema.get("properties", {})

    for req in schema.get("required", []):
        if req not in data:
            errors.append(f"缺少字段: {req}")

    for key, value in data.items():
        prop = props.get(key)
        if not prop:
            continue
        ptype = prop.get("type")
        if ptype == "string" and not isinstance(value, str):
            errors.append(f"{key} 应为 string")
        elif ptype == "number" and isinstance(value, bool):
            errors.append(f"{key} 应为 number")
        elif ptype == "number" and not isinstance(value, (int, float)):
            errors.append(f"{key} 应为 number")
        elif ptype == "integer" and not isinstance(value, int):
            errors.append(f"{key} 应为 integer")
        elif ptype == "boolean" and not isinstance(value, bool):
            errors.append(f"{key} 应为 boolean")
        elif ptype == "array" and not isinstance(value, list):
            errors.append(f"{key} 应为 array")
        enum = prop.get("enum")
        if enum and value not in enum:
            errors.append(f"{key} 不在枚举 {enum} 内")
    return errors


# ---------------------------------------------------------------------------
# 对外 API
# ---------------------------------------------------------------------------


def invoke_structured_or_freetext(
    prompt: str,
    *,
    schema: dict,
    model: str = "deepseek-chat",
    system: str | None = None,
    max_tokens: int = 2048,
    temperature: float = 0.0,
    timeout: int = 60,
) -> dict | str:
    """结构化输出 + provider 降级。

    优先级:
      1. json_schema response_format → 解析 + 校验, 通过则返回 dict
      2. 自由文本 → JSON 提取 + 校验, 通过则返回 dict
      3. 都失败 → 返回原始文本 str (调用方决定如何降级)

    Args:
        prompt: 用户提示词。
        schema: JSON Schema dict (可用 dataclass_to_json_schema 生成)。
        model / system / max_tokens / temperature / timeout: LLM 参数。

    Returns:
        dict 表示拿到结构化结果; str 表示结构化失败降级 (调用方需处理)。
    """
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    name = schema.get("name") or "result"
    try:
        raw = _chat(
            messages,
            model=model,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": name, "schema": {k: v for k, v in schema.items() if k != "name"}},
            },
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
        )
        if raw:
            data = _extract_json(raw)
            if data is not None and not _validate(data, schema):
                return data
    except Exception as e:
        logger.debug("structured: json_schema 路径异常 — %s", e)

    # 降级: 自由文本 + JSON 提取
    raw = _chat(
        messages,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
    )
    if raw:
        data = _extract_json(raw)
        if data is not None and not _validate(data, schema):
            return data
        return raw  # 有文本但结构不达标 → 返回原文, 调用方降级
    return ""  # 无任何输出
