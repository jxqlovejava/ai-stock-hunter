---
name: sector-research
description: 行业研究框架 — 申万分类→TAM→竞争格局→估值→催化剂→供应链瓶颈。触发词：行业、板块、赛道、sector、产业链、供应链、竞争格局。
---

# 行业研究 (Sector Research)

系统化 A 股行业研究框架。覆盖申万行业分类、行业特定指标、竞争格局、供应链分析。

## 分析框架

> ⚠️ **强制完整执行**：以下 6+1 步 Workflow 必须全部完成。输出必须附带 checklist（见输出格式）。`SectorWorkflowValidator` 会自动检查步骤完整性，缺失步骤写入 `data_gaps` 并降低 `confidence`。

### Step 1: 行业定位
- **申万行业分类**：一级 (31 个) / 二级 (138 个) / 三级
- 确定分析范围 (全行业 vs 细分赛道)
- 识别行业生命周期阶段 (导入期/成长期/成熟期/衰退期)

### Step 2: 市场规模与增长 (TAM)
- A 股该行业总市值
- 近 3 年营收复合增长率
- 行业集中度 (CR5/CR10)
- 政策驱动 vs 内生增长

### Step 3: 竞争格局

**A 股行业特定指标**：

| 行业 | 关键指标 |
|------|---------|
| 消费 (白酒/调味品) | 品牌力、渠道覆盖率、提价能力 |
| 科技 (半导体/消费电子) | 研发费用率、专利数、制程/良率 |
| 新能源 (光伏/锂电) | 产能、技术路线、成本曲线 |
| 金融 (银行/券商) | 净息差、不良率、ROE |
| 医药 (创新药/器械) | 管线进度、获批数量、集采影响 |
| 周期 (钢铁/化工) | 产能利用率、库存周期、期货价格 |

**竞争维度**：
- 价格竞争 vs 产品差异化
- 谁在获得/失去份额，为什么
- 新进入者威胁
- 替代品压力

### Step 4: 估值背景
- 申万行业 PE/PB 当前分位 vs 历史区间
- 行业溢价/折价驱动因素
- 行业拥挤度 (基金超配比例)
- 北向资金行业配置

### Step 5: 催化剂
- 近期行业催化剂清单
- 政策事件 (产业规划/补贴/监管)
- 技术突破
- M&A 活动

### Step 6: 供应链瓶颈
- 供应链映射 (上游→中游→下游 8 层)
- 瓶颈定位 (产能/技术/资源/牌照)
- 瓶颈评分: OWNER (100) > ADJACENT (70) > DERIVATIVE (40) > NONE (5)
- 成本传导系数 + 价格弹性
- 上下游遍历 (find_upstream / find_downstream)

### Step 7: 全球供需平衡（门控）
> ⚠️ **仅对全球定价大宗商品行业触发**（有色金属/石油石化/煤炭/钢铁/基础化工）。国内定价行业（白酒/水泥/地产等）自动跳过。

- **海外产能跟踪**：全球主要矿山/油田/盐湖产能、产量、扩产进度
- **海外龙头对标**：海外对标公司 (yfinance best-effort) — 股价/PE/PB/市值
- **全球成本曲线**：从 Tier 0 (极低成本) 到 Tier 3 (高成本) 排序
- **地缘政治风险矩阵**：资源国国有化/贸易限制/制裁/FEOC/外资审查
- **需求端分地区拆解**：按应用领域 (EV/储能/消费电子/...) 拆分需求占比
- **定价机制**：国内期货 vs 海外现货 vs 拍卖 vs 长协
- **数据质量**：所有数据标注 `tier=T2, nature=interpretation`；yfinance 失败用硬编码配置 fallback，标注 `[DATA_GAP]`

## 输出

### 强制 Checklist 格式

每次分析输出必须以 `📋 Workflow 执行清单` 开头：

```
📋 Workflow 执行清单:
  ✅ 行业定位 — tier=T1 conf=0.85 24h
  ✅ 市场规模 — tier=T2 conf=0.55 24h
  ✅ 竞争格局 — tier=T2 conf=0.65 168h
  ✅ 估值背景 — tier=T2 conf=0.60 24h
  ✅ 催化剂 — tier=T2 conf=0.60 12h
  ✅ 供应链瓶颈 — tier=T2 conf=0.70 168h
  ✅/❌ 全球供需平衡 — (有色金属自动触发；食品饮料标记跳过)

  综合置信度: 0.65
  数据缺口: N 项
```

### DTO 输出

```python
# 行业概览
SectorOverview(
    sector_name="半导体",
    sw_level=2,                    # 申万二级
    tam=8000e8,                    # A 股市值
    cagr_3y=0.25,                  # 近 3 年 CAGR
    cr5=0.45,                      # CR5 集中度
    lifecycle="成长期",
    current_pe_percentile=65,      # PE 历史分位
    crowding_score=55,             # 拥挤度 (0-100)
    top_picks=["688981", "002371"],
    catalysts=["国产替代加速", "AI 算力需求"],
)
```

## A 股特定

- 申万行业分类是 A 股标准行业分类体系
- 行业轮动受政策和流动性驱动强
- 行业拥挤度 = 基金超配 + 北向集中 + 换手率异常
- 供应链瓶颈分析适配 "卡脖子" 概念

## 护栏

- **行业判断不替代个股分析**
- **估值分位仅参考，历史不代表未来**
- **拥挤度 > 70 时降权**
- **Workflow 步骤必须全部完成** — `SectorWorkflowValidator` 在输出前自动验证，缺失步骤写入 `data_gaps`
- **信息源质量**：行业数据/催化剂必须标注 T0-T3 分级 + 时效性，新闻事件类催化剂 > 12h 标记 `[STALE]`
- **全球供需数据均为 T2 级别** — 硬编码配置 + yfinance best-effort，用于提供结构化的全球视角而非精确量化

## 引用

- Python 实现: `src/industry/bottleneck.py`, `src/industry/supply_chain.py`, `src/industry/workflow_validator.py`, `src/industry/global_commodity.py`, `src/industry/research.py`
- 数据源: 申万行业分类, AKShare (行业 PE/PB), 东财板块, yfinance (海外对标, best-effort)
- 依赖 Skill: `diagnosis`, `game-theory`, `topic-manager`
