# Kronos: Foundation Model for Financial Market Language

> [shiyu-coder/Kronos](https://github.com/shiyu-coder/Kronos) — 金融市场时序 Foundation Model，使用 Transformer + BSQ 将 K 线数据量化为 token 序列进行自回归预训练。
> 论文: [Kronos: A Foundation Model for the Language of Financial Markets](https://arxiv.org/abs/2508.02739)

## 核心思路

Kronos 将金融 K 线数据视为一种"语言"，通过两大核心组件处理：

1. **Binary Spherical Quantization (BSQ) tokenizer** — 将连续的 OHLCV 数据离散化为 token 序列
2. **Transformer predictor** — 在 market token 序列上进行自回归预训练

预训练规模：**12+ billion K-line records**，覆盖 **45+ 全球交易所**，7 种时间粒度（1min/5min/30min/1h/4h/1d/1w）。

## 架构要点

```
OHLCV Data → BSQ Tokenizer → Token Sequence → Transformer → Prediction
                     ↑                              ↑
              (离散化连续量价)                (自回归预训练)
```

### BSQ Tokenizer

与传统的 VQ-VAE 不同，BSQ 将每个 K 线向量映射到高维球面上的二进制编码，而非离散码本。优势：
- 不存在码本坍塌（codebook collapse）问题
- 编码紧凑且保留了相对位置关系
- 适合金融时序的连续变化特性

### Transformer 结构

- 标准 decoder-only 架构
- 预训练目标：next token prediction（类比 LLM）
- 支持多种时间粒度的联合建模

## A 股落地适配

### 1. Qlib Finetuning Pipeline

通过 [workflow-shiyu-coder-kronos-qlib-finetuning](https://github.com/leeroopedia/workflow-shiyu-coder-kronos-qlib-finetuning) 将 Kronos 适配到 A 股：

| 步骤 | 说明 |
|------|------|
| 准备数据 | `python prepare_data.py` — 通过 Qlib `cn_data` 拉取 CSI300/CSI800/CSI1000 日线数据 |
| Finetune Tokenizer | `torchrun train_tokenizer.py` — 先微调 BSQ tokenizer 适配 A 股量价分布 |
| Finetune Predictor | `torchrun train_predictor.py` — 再微调 Transformer predictor |
| 回测 | `python run_backtest.py` — TopK 组合回测 |

默认配置：90 天 lookback、10 天预测窗口、CSI300 标的池、时间跨度 2011-2025。

### 2. AKShare 数据集成

`prediction_cn_markets_day.py` 提供了无需 Qlib 的独立 A 股预测版本：
- 直接用 AKShare 获取 A 股日线数据
- 自动列名映射（日期→timestamps, 开盘→open, 等）
- **A 股涨跌停限制**（±10% 价格约束）

### 3. A 股专用预测工具

| 工具 | 用途 |
|------|------|
| GUI Predictor | Tkinter 界面，支持股票代码输入、预测天数选择、可视化 |
| KronosBacktester | 基于模型 BUY/SELL 信号的信号级回测 |
| HistoricalBacktester | Walk-forward 测试，含准确率指标和买入持有对比 |
| EnhancedMarketFactorAnalyzer | 多维情绪分析（宏观周期/板块动量/基本面评分） |

## 性能指标

| 指标 | 提升幅度 | 对比基线 |
|------|---------|---------|
| 价格预测 RankIC | +93% | 领先 TSFM |
| 波动率预测 MAE | -9% | 最佳非预训练基线 |
| 合成 K 线保真度 | +22% | 传统生成方法 |

## 对 Baize 的借鉴价值

### 1. K 线特征表达的替代方案

当前 Baize 的技术面分析基于预定义规则（MACD/KDJ/均线/量价形态）。Kronos 的 BSQ tokenizer 提供了一种**数据驱动的 K 线表示**思路：
- 可将 Baize 的 `src/routing/diagnosis.py` 中技术面评分改造为：先由 BSQ 提取隐式特征 → 再由规则层增强
- 短期不适合替换，但可作为 future work 的 ML 增强模块

### 2. 多时间粒度联合建模

Kronos 在 7 种粒度上联合预训练，可互相补充信号：
- Baize 的 T+0 日内分析目前是独立的，若能参考 Kronos 的多粒度架构，可将日线趋势信号与分钟级入场信号融合
- 可尝试在 `tactics` 管道的技术评分阶段引入 Kronos 式多粒度特征

### 3. Qlib + Foundation Model 的集成模式

Kronos 的 Qlib 微调管道展示了一套**基础模型 + 传统量化框架**的集成模式：
- 对 Baize 而言，如果未来引入 ML 预测模块，可参考此两阶段微调思路
- 先适配 tokenizer（让模型理解 A 股特有的量价分布）→ 再适配 predictor（针对特定预测任务）

### 4. 信号后处理约束

Kronos 明确强调：**原始预测信号 ≠ alpha**，生产环境需叠加：
- Risk factor neutralization
- Portfolio optimization
- Transaction cost modeling
- Stop-loss / risk management

这与 Baize 的设计哲学一致：`signal-writer` 必须经过 L4 风控检查后才能输出信号，且 `confidence < 0.6` 阻止进入 L3 交易阶段。

### 5. AKShare 镜像使用

Baize 和 Kronos 都使用 AKShare 作为数据源之一。可借鉴 Kronos 的自动列映射 + 涨跌停约束逻辑，增强 Baize 中 `src/data/aggregator.py` 的 AKShare 数据处理。

## 关键区别

| 维度 | Kronos | Baize |
|------|--------|-------|
| 核心方法 | 数据驱动 ML（Transformer + BSQ） | 规则+多 Agent 编排（军规/辩论/思维模型） |
| 预测输出 | 连续价格/波动率预测 | 离散评分 + 分类信号（BUY/HOLD/REDUCE） |
| 解释性 | 黑盒（token 序列 → 预测） | 白盒（逐阶段输出+数据溯源+可证伪条件） |
| 数据依赖 | 海量 K 线预训练（12B+ records） | 多源实时数据聚合 + 主题/政策/情绪 |
| A 股覆盖 | 通过 Qlib + AKShare 适配 | 原生 A 股设计（国信/华泰/腾讯/mootdx/AKShare） |
| 回测 | TopK 组合回测（Qlib） | 完整回测引擎（军规/风控/仓位/凯利） |

Baize 的**可解释性**和**白盒分阶段决策**是相对于 Kronos 的显著优势。Kronos 在**端到端时序预测**方面的强项，可作为 Baize 未来 ML 增强模块的参考基础。

## 潜在集成方向

1. **作为 Baize Alpha Lens 的补充因子** — 在 `Alpha Lens` 阶段引入 Kronos-style 的预测信号作为一个独立 alpha 源（经置信度加权后进入多维诊断）
2. **技术面特征的 BSQ 编码** — 替换或增强当前 `tactics` 管道中技术 6 维评分的手工特征工程
3. **多粒度信号融合** — 将 Kronos 的 7 粒度联合建模思路用于 Baize 中日线+分钟级信号的交叉验证

## 参考链接

- GitHub: [github.com/shiyu-coder/Kronos](https://github.com/shiyu-coder/Kronos)
- 论文: [Kronos: A Foundation Model for the Language of Financial Markets](https://arxiv.org/abs/2508.02739)
- Qlib Finetuning: [workflow-shiyu-coder-kronos-qlib-finetuning](https://github.com/leeroopedia/workflow-shiyu-coder-kronos-qlib-finetuning)
- DeepWiki: [A-Share Market Prediction](https://deepwiki.com/shiyu-coder/Kronos/6.3-fine-tuning-examples)
