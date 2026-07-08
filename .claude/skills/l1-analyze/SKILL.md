---
name: l1-analyze
description: 多维股票分析 — 宏观/价值/质量/动量/盈利修正/瓶颈/情绪 7 维度扫描。触发词：分析股票、多维扫描、L1、估值分析、基本面。
---

# L1 多维分析师 (Multi-Dimensional Analyzer)

对单只股票执行 7 维度量化+AI 分析，生成结构化分析报告。

## 分析维度

### 1. 宏观环境评分 (macro_score: 0-100)
- PMI 位置和方向 (50 基准 ±)
- ERP (股权风险溢价) 水平
- M1-M2 剪刀差 (资金活化程度)
- 社融增速趋势 (加速/减速)
- LPR 方向 (升/降/稳)
- DR007 相对政策利率位置
- 货币信用双象限修正 (±15分)

### 2. 价值评分 (value_score: 0-100)
- PE 分位数 (历史+行业)
- PB 分位数
- 股息率
- 自由现金流收益率

### 3. 质量评分 (quality_score: 0-100)
- ROE (扣非口径)
- 毛利率稳定性
- 资产负债率
- 盈利修正因子 (分析师上调/下调)
- 商誉/净资产比例

### 4. 动量评分 (momentum_score: 0-100)
- 北向资金多维画像 (主)
- 近期涨跌幅
- 换手率异常
- 成交量趋势

### 5. 盈利修正 (earnings_revision_score: 0-100)
- 分析师一致预期变化
- 上调/下调家数比
- 盈利惊喜历史

### 6. 物理瓶颈分析 (bottleneck_analysis)
- 供应链位置分类 (瓶颈拥有者/邻居/衍生品)
- 瓶颈类型 (产能/技术/资源/牌照/无)
- 瓶颈评分 (0-100)

### 7. 情绪信号 (sentiment_signal)
- 大盘情绪映射: PANIC / NORMAL / GREED

## 输出

```python
AnalysisReport(
    symbol="600519",
    name="贵州茅台",
    macro_score=55.0,
    value_score=75.0,
    quality_score=90.0,
    momentum_score=65.0,
    earnings_revision_score=60.0,
    bottleneck_analysis=BottleneckAnalysis(...),
    sentiment_signal="NORMAL",
    source_citations=[...],  # Phase 1: 数据溯源
    confidence=0.85,          # Phase 1: 综合信心度
)
```

## 护栏

- **每个维度标注数据来源** (source_citations)，包含 `tier` + `nature` + `freshness`
- **时效性校验**：各维度使用的数据必须通过时效性检查；新闻/事件类数据 > 12h 标记 `[STALE]`
- **confidence < 0.6 的结果标注低置信度**，阻止进入 L3
- **[UNSOURCED] 标记无法溯源的数据点**
- **[DATA_GAP] 声明**：单源/缺失/间接转述数据显式标注
- **多空双视角**: bull_case 和 bear_case 必须同时提供

## 引用

- Python 实现: `src/routing/l1_analyze.py`
- 瓶颈分析: `src/industry/bottleneck.py`
- 供应链: `src/industry/supply_chain.py`
- 因子数据: `src/data/factor_pipeline.py`
- 盈利修正: `src/data/earnings_revision.py`
- 依赖 Skill: `l0-gate`, `l2-judge`, `macro-monitor`, `game-theory`
