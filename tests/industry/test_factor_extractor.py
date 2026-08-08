# -*- coding: utf-8 -*-
"""P1-8 供不应求关键词提取 (文章共识 @LuBtc888 选股8标准 第④条)。

覆盖:
  FactorClassifier.classify
    ① "供不应求" → 基本面/中长期/不会自动消失
    ② "下游排队提货" → 基本面 (供应紧张信号)
    ③ "高溢价采购" → 基本面
  FactorClassifier.infer_direction
    ④ 供不应求文本 → positive (超级成长偏多)
    ⑤ "产能过剩" 对照 → negative (既有多空判定不受影响)

全部为纯函数测试, 不触发网络。
"""
from src.industry.factor_extractor import FactorClassifier


def test_classify_supply_shortage():
    """① 供不应求 → 基本面/中长期/不会自动消失。"""
    assert FactorClassifier.classify("公司产品供不应求，产线满产") == ("基本面", "中长期", "不会自动消失")


def test_classify_downstream_queue():
    """② 下游排队提货 → 基本面。"""
    cat, hor, per = FactorClassifier.classify("下游排队提货，交付周期延长")
    assert cat == "基本面" and hor == "中长期"


def test_classify_high_premium():
    """③ 接受高溢价 → 基本面。"""
    cat, hor, per = FactorClassifier.classify("客户接受高溢价采购，毛利提升")
    assert cat == "基本面"


def test_infer_direction_positive_for_shortage():
    """④ 供不应求文本 → positive。"""
    assert FactorClassifier.infer_direction("订单饱满，供不应求，排队等货") == "positive"
    assert FactorClassifier.infer_direction("一货难求，高溢价采购") == "positive"


def test_infer_direction_negative_unchanged():
    """⑤ 产能过剩 对照 → negative (既有多空不受影响)。"""
    assert FactorClassifier.infer_direction("行业产能过剩，价格下行") == "negative"


def test_classify_default_when_no_keyword():
    """⑥ 无关键词 → 默认 基本面/中长期。"""
    assert FactorClassifier.classify("今日成交活跃") == ("基本面", "中长期", "不会自动消失")
