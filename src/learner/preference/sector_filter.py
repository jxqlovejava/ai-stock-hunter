# -*- coding: utf-8 -*-
"""能力圈 → 行业板块 → 成分股代码 三级映射与过滤。

桥接投资者能力圈关键词与东财行业板块名称，按需拉取成分股代码，
为 scan/screen 命令提供行业级预过滤能力。

设计原则:
  - 零额外依赖：复用现有 fetch_em_industry_stocks
  - 降级友好：任何环节失败都静默跳过该行业
  - 空能力圈 → 不过滤（向后兼容）
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# 能力圈关键词 → 东财行业板块名称 映射
# ------------------------------------------------------------------
# 每个能力圈关键词可对应多个东财行业板块（中文名称，支持模糊匹配）。
# 东财行业板块名称来自东财 push2 接口 m:90+t:2 的 f14 字段。
# 新增行业时在对应关键词列表中添加板块名称即可。

COMPETENCE_TO_INDUSTRY: dict[str, list[str]] = {
    "新能源": [
        "光伏设备", "风电设备", "电池", "能源金属", "电网设备",
        "新能源", "电力行业", "电源设备", "充电桩", "储能",
    ],
    "科技": [
        "软件开发", "IT服务", "计算机设备", "通信服务",
        "互联网服务", "电子元件", "消费电子",
    ],
    "半导体": [
        "半导体", "电子元件", "集成电路", "芯片",
    ],
    "AI": [
        "人工智能", "云计算", "大数据", "机器人", "软件开发",
        "互联网服务", "计算机设备",
    ],
    "航天": [
        "航天航空", "军工", "船舶制造", "大飞机",
    ],
    "消费": [
        "食品饮料", "酿酒行业", "家电行业", "汽车整车",
        "汽车零部件", "医药制造", "商业百货", "旅游酒店",
        "纺织服装", "文化传媒",
    ],
}


def resolve_competence_industries(
    circle_of_competence: dict[str, int],
    competence_map: dict[str, list[str]] | None = None,
) -> list[str]:
    """从能力圈解析出东财行业板块名称列表。

    Args:
        circle_of_competence: {行业关键词: 熟悉度(0-5)}
        competence_map: 能力圈→行业映射表，默认 COMPETENCE_TO_INDUSTRY

    Returns:
        东财行业板块名称列表（去重），跳过 familiarity=0 的行业
    """
    if not circle_of_competence:
        return []

    mapping = competence_map or COMPETENCE_TO_INDUSTRY
    industries: list[str] = []
    seen: set[str] = set()

    for keyword, familiarity in circle_of_competence.items():
        if familiarity <= 0:
            continue
        mapped = mapping.get(keyword, [keyword])
        for ind in mapped:
            if ind not in seen:
                seen.add(ind)
                industries.append(ind)

    if not industries:
        logger.debug("能力圈中无 familiarity>0 的行业，跳过行业过滤")
    return industries


def _fetch_industry_code_map() -> dict[str, str]:
    """获取东财行业板块 名称→代码 映射（一次API调用）。"""
    from src.data.eastmoney_fallback import _em_get, PUSH2_CLIST_URL

    try:
        params = {
            "pn": "1", "pz": "200", "po": "1", "np": "1",
            "fltt": "2", "invt": "2", "fs": "m:90+t:2",
            "fields": "f12,f14",
        }
        headers = {"Referer": "https://quote.eastmoney.com/"}
        r = _em_get(PUSH2_CLIST_URL, params=params, headers=headers, timeout=15)
        d = r.json()
        items = d.get("data", {}).get("diff", [])
        code_map = {}
        for item in items:
            name = item.get("f14", "")
            code = item.get("f12", "")
            if name and code:
                code_map[name] = code
        return code_map
    except Exception:
        logger.debug("获取东财行业板块列表失败", exc_info=True)
        return {}


def _fetch_stocks_by_code(industry_code: str, page_size: int = 200) -> list[dict]:
    """按行业代码直接拉取成分股（跳过行业列表查询）。"""
    from src.data.eastmoney_fallback import _em_get, PUSH2_CLIST_URL

    try:
        params = {
            "pn": "1", "pz": str(page_size), "po": "0", "np": "1",
            "fltt": "2", "invt": "2",
            "fs": f"b:{industry_code}+f:!200",
            "fields": "f12",
        }
        headers = {"Referer": "https://quote.eastmoney.com/"}
        r = _em_get(PUSH2_CLIST_URL, params=params, headers=headers, timeout=15)
        d = r.json()
        items = d.get("data", {}).get("diff", [])
        return [{"code": item.get("f12", "")} for item in items]
    except Exception:
        logger.debug("获取行业代码 [%s] 成分股失败", industry_code, exc_info=True)
        return []


def build_competence_symbol_set(
    circle_of_competence: dict[str, int],
    competence_map: dict[str, list[str]] | None = None,
) -> set[str] | None:
    """构建能力圈内所有可投股票代码集合。

    优化: 一次拉取全行业板块列表 → 本地匹配 → 按代码拉成分股。
    相比逐行业调用 fetch_em_industry_stocks (每次2次API调用)，
    减少 API 调用量约 50%。

    Args:
        circle_of_competence: {行业关键词: 熟悉度(0-5)}
        competence_map: 能力圈→行业映射表，默认 COMPETENCE_TO_INDUSTRY

    Returns:
        可投股票代码集合（6 位数字代码），或 None 表示不过滤
    """
    industries = resolve_competence_industries(circle_of_competence, competence_map)
    if not industries:
        return None  # None = 不过滤，向后兼容

    # 1. 一次拉取全行业板块 名称→代码 映射
    code_map = _fetch_industry_code_map()
    if not code_map:
        logger.warning("能力圈过滤：无法获取东财行业板块列表，跳过行业过滤")
        return None

    # 2. 本地模糊匹配目标行业名称 → 行业代码
    matched_codes: dict[str, str] = {}  # industry_name → bk_code
    for target in industries:
        for bk_name, bk_code in code_map.items():
            if target in bk_name:
                if bk_code not in matched_codes.values():
                    matched_codes[target] = bk_code
                break

    if not matched_codes:
        logger.warning(
            "能力圈过滤：%d 个目标行业在 %d 个东财板块中无匹配",
            len(industries), len(code_map),
        )
        return None

    # 3. 按行业代码批量拉取成分股
    symbols: set[str] = set()
    success_count = 0

    for industry_name, bk_code in matched_codes.items():
        stocks = _fetch_stocks_by_code(bk_code)
        if stocks:
            for s in stocks:
                code = s.get("code", "")
                if code and len(code) == 6:
                    symbols.add(code)
            success_count += 1
            logger.debug("行业 [%s](%s) → %d 只成分股", industry_name, bk_code, len(stocks))
        else:
            logger.debug("行业 [%s](%s) 无成分股数据，跳过", industry_name, bk_code)

    if not symbols:
        logger.warning(
            "能力圈行业过滤：%d 个行业中 %d 个获取成功，但无可用成分股",
            len(matched_codes), success_count,
        )
        return None

    logger.info(
        "能力圈过滤：%d 个行业关键词 → %d 个东财板块 → %d 只成分股",
        len(circle_of_competence), success_count, len(symbols),
    )
    return symbols
