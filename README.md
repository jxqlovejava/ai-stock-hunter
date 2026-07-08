# 🦄 白泽 (Baize) — A 股智能投资决策系统

> **《山海经》有兽名白泽，通晓万物之情状，能人言。白泽看穿市场噪声、辨识各路玩家，把复杂世界翻译成你能听懂的话。**

> **投资不是赌博，是概率游戏。系统帮你算概率，军规帮你管住手。**

49,000+ 行 Python · 654 个测试用例 · 26 个模块 · 5 层路由管道 · 28 个量化因子 · 31 条军规 · 分钟级数据管道 · T+0 日内时机 · 宏观事件因果链

---

## 🌟 亮点

### 🔍 Alpha Lens — 寻找真正的超额收益

A 股最致命的不是买贵了，是**追了已经被充分定价的"好故事"**。白泽独创三维 Alpha 评估引擎：

| 维度 | 核心问题 | 白泽做什么 |
|------|---------|-----------|
| **信息层级** | 这条消息还有 Alpha 空间吗？ | 区分一手/二手/三手信息，量化噪音比例 |
| **共识缺口** | 市场理解对了吗？还是夸大了？ | 检测市场叙事与基本面的偏离度，识别逻辑漏洞 |
| **叙事生命周期** | 我们处于故事的哪个阶段？ | 潜伏→兴起→扩散→共识→拥挤→消退，6 阶段精准定位 |

### ⚡ 长线 / 短线双模式

一套系统，两种打法。通过投资者画像中的 `trading_style` 自动切换：

| 维度 | 🔭 长线价值投资 | ⚡ 短线波段套利 |
|------|---------------|---------------|
| **分析引擎** | 基本面为主（宏观/价值/质量） | 技术面为主（趋势/反转/量价/波动/均线/打板） |
| **因子库** | 10 个基本面因子（value/quality/growth/composite） | 18 个技术因子（MACD/RSI/KDJ/DMI/布林/ATR/OBV/MFI…） |
| **入场** | 估值合理 + ROE 稳定 | 放量突破 / 金叉 / 回踩支撑 / 超卖反弹 |
| **止损** | 固定 -2% | ATR 倍率 + 时间止损 + 移动止损 |
| **盯盘** | 按需手动 | 实时后台盯盘（机会发现 + 风险速报） |

### 🎲 博弈论全景 — 看清对手是谁

| 模块 | 核心能力 |
|------|---------|
| **北向资金画像** | 分行业净流入、风格偏好、流入加速度、大小盘偏好 |
| **主导玩家分类** | 基于波动率/换手率/涨停结构判断定价权归属（游资/机构/量化/国家队） |
| **公募拥挤度** | 重仓股重叠度、行业拥挤度、新发基金趋势 |
| **龙虎榜席位** | 知名游资营业部识别、席位活跃度、跟买胜率 |
| **价格冲击模型** | 预估下单对市场的影响，大资金小票自动预警 |

### 🛡️ 数据护栏 — 没有来源的数字不进管道

```python
# 每一个数据点强制携带来源引用
SourceCitation(
    provider="guosen",       # 国信/mootdx/akshare/tencent/huatai
    confidence=0.90,         # 来源置信度
    data_freshness="5min",   # 数据新鲜度
    tier="primary",          # primary/secondary/tertiary
    nature="fact",           # fact/interpretation/speculation
)
```

- ≥2 源交叉验证 — 差异 > 5% 标记 DISPUTED，不进管道
- `[UNSOURCED]` / `[DATA_GAP]` 强制标注
- `confidence < 0.6` 阻止进入仓位调度阶段

### ⏱️ T+0 日内时机分析 — 日线+分钟线双维度决策

"该不该买"靠全链路分析，"什么时候买"靠 T+0 时机引擎。结合近20天日线趋势 + 今日盘中分钟级数据，给出**即时操作建议**：

| 维度 | 日线层 | 日内层 |
|------|--------|--------|
| **技术位** | MA5/MA10/MA20 均线偏离 | VWAP 成交量加权均价 |
| **形态** | 锤子线/十字星/大阴线自动识别 | 单边下跌/V型反弹/二次探底 |
| **量价** | 近3日/5日累计涨跌幅 | 成交量结构（恐慌区/反弹区/尾盘） |
| **资金** | 北向资金流向 | 大单买卖方向统计（>50万股/分钟） |
| **关键位** | 近期支撑/阻力 | 斐波那契 0.382/0.5/0.618 回撤 |

→ 输出：🟢加仓 / 🟡观望 / 🟠减仓 / 🔴坚决减仓 + 具体操作价位 + 止损 + 触发条件

### 🌍 宏观事件因果链分析 — 先看天再下地

个股分析前，先搞清楚"今天发生了什么大事"→"怎么传导到A股"。8 条传导路径 + 规则引擎 + 历史类比 + LLM 深度推演：

```
美股暴跌 → 美股映射(次日低开) → 风险偏好(VIX传导) → 北向资金(次日流出) → A股承压
美联储加息 → 全球流动性收紧 → 汇率(人民币贬值) → 北向流出 → 出口预期变化
```

| 传导路径 | 触发场景 | 时间尺度 |
|---------|---------|---------|
| 美股映射 | 纳指暴跌/VIX飙升/科技股重挫 | 即时 |
| 全球流动性 | Fed 加息/降息/QE | 即时 |
| 北向资金 | 美债收益率/美股波动 | 即时 |
| 汇率 | 美元指数变动 | 短期 |
| 风险偏好 | 地缘冲突/VIX | 即时 |
| 行业制裁 | 芯片/技术禁令 | 短期 |
| 出口预期 | 关税/贸易政策 | 中期 |
| 国内政策 | 央行/财政响应 | 中期 |

### 🧠 逆向思考 + 策略进化

| 机制 | 做什么 |
|------|--------|
| **反共识检验** | 市场一致看多时，自动触发反向论证 |
| **恐慌套利引擎** | 极端恐慌时逆向触发买入信号（别人恐惧我贪婪的量化版） |
| **策略进化** | 投喂学术论文 → 自动提取策略 → 回测验证 → 模拟盘 → 实战，9 状态全生命周期 |

---

## 🏗️ 系统架构

### 9 层路由管道 + 军规前置

```
CLI → 军规(31条) → 准入检查 → 宏观事件因果链 → 多维诊断 → 综合裁决 → 仓位调度 → 风控执行
        ↑ Phase 3: MacroRegime / Northbound / EarningsRevision / TopicLifecycle
        ↑ Phase 2.5: 宏观事件→8条传导路径→影响估计→策略建议
        ↑ Phase 9: T+0 日内时机(日线+分钟线双维度)
```

| 阶段 | 中文名 | 英文名（类名） | 职责 | AI 参与度 |
|------|--------|-------------|------|----------|
| **军规** | 投资军规 | `DoctrineChecker` | 31 条硬性门禁（block/warn/info），行为偏差拦截 | 0% |
| **准入检查** | 准入检查 | `AdmissionCheck` | ST/\*ST 否决、次新股冷静、流动性过滤、涨跌停/停牌排除 | 0% |
| **多维诊断** | 多维诊断 | `DiagnosisEngine` | 宏观+价值+质量+动量+估值+周期+情绪+高管 8 维打分 | 30% |
| **综合裁决** | 综合裁决 | `VerdictEngine` | 加权评分 + 置信度校准 + 反共识检验 + 主题生命周期调整 | 20% |
| **仓位调度** | 仓位调度 | `PositioningEngine` | 信号→仓位映射（核心仓/交易仓分治），凯利公式仓位管理 | 10% |
| **风控执行** | 风控执行 | `RiskControlEngine` | 单票上限/行业上限/组合回撤/黑天鹅熔断，短线支持 ATR+时间+移动止损 | 0% |

> **设计原则**：规则引擎做主路径，AI 做分析增强。军规/准入检查/风控执行纯规则（0% AI），多维诊断/综合裁决量化为主 AI 为辅。

### Agent Worker 模式

| Agent | 职责 | 权限 |
|-------|------|------|
| `orchestrator-agent` | 全链路编排，加载投资者画像并注入管道 | 只读协调 |
| `data-worker` | 数据获取（mootdx/腾讯/国信/AKShare/华泰/妙想） | 只读 |
| `analysis-worker` | 军规→准入检查→多维诊断→综合裁决 分析管道 | 只读分析 |
| `signal-writer` | 仓位调度→风控执行→最终输出 | **唯一写权限** |

---

## 📦 模块全景

| 模块 | 路径 | 核心能力 |
|------|------|---------|
| 🛤️ 路由 | `src/routing/` | 9 层管道编排 + Agent-Worker 模式 + 护栏执行器 + T+0 时机 + 宏观事件 |
| 🔍 Alpha Lens | `src/alpha/` | 信息层级判定、共识缺口检测、叙事生命周期定位、Alpha 衰减追踪 |
| 🗄️ 数据层 | `src/data/` | 5 源聚合 + 交叉验证 + TTL 缓存 + 分钟/tick 级行情 + 数据聚合器(Tick→Bar) + 数据馈送抽象 |
| ⏱️ T+0 分析 | `src/analysis/` | 日线+分钟线双维度 T+0 时机引擎：均线/VWAP/K线形态/大单方向/斐波那契/分时形态 |
| ⚡ 技术因子 | `src/factors/` | 28 个量化因子：10 基本面 + 18 技术（趋势/反转/量价/波动/均线） |
| 📜 军规 | `src/doctrine/` | 31 条 A 股专属军规 + 232 个 Munger 思维模型动态匹配 |
| 🔔 盯盘 | `src/monitor/` | 实时预警引擎：机会发现（突破/金叉/放量/龙头）+ 风险速报（炸板/天地板/北向/急跌） |
| 📊 回测 | `src/backtest/` | Backtrader 引擎 + 网格/贝叶斯优化 + 策略注册中心 + 防过拟合 |
| 🎲 博弈论 | `src/game_theory/` | 北向画像、公募拥挤度、龙虎榜席位、主导玩家分类、操盘手法识别 |
| 📈 宏观 | `src/macro/` | 货币-信用双象限 + 宏观事件因果链(8条传导路径) + 历史类比 + 策略建议 |
| 😱 情绪 | `src/sentiment/` | 恐慌套利引擎、市场情绪信号、过度反应检测 |
| 🏭 行业 | `src/industry/` | 物理瓶颈分析链、供应链映射、SA 瓶颈阶梯 |
| 📰 政策 | `src/policy/` | NLP 关键词追踪、政策→板块传导映射 |
| 📡 信息 | `src/information/` | 主题生命周期管理（4 阶段状态机）、互动易问答、信息速度监控 |
| 🧬 进化 | `src/evolution/` | 论文驱动策略进化，9 状态全生命周期（论文→回测→模拟盘→实战） |
| 💰 估值 | `src/valuation/` | 多维估值：DCF + 资产重估 + 清算价值，三情景估值 |
| 📐 凯利 | `src/kelly/` | 凯利公式仓位管理：热启动 f* 计算 + 冷启动线性回退 |
| 🧠 学习 | `src/learner/` | 反馈闭环、用户能力画像、投资者偏好（时间维度 + 盯盘配置） |
| 💸 模拟交易 | `src/paper_trading/` | L3 信号→mx-moni 模拟账户、批量执行、反馈录入 |
| 🔄 周期 | `src/cycle/` | 经济周期阶段判定 + 行业轮动映射 |

---

## 🚀 快速开始

> 要求 **Python 3.11+**。一行命令完成安装。

### 🤖 自动安装（推荐）

```bash
git clone https://github.com/jxqlovejava/ai-stock-hunter.git
cd ai-stock-hunter
chmod +x setup.sh && ./setup.sh
```

安装脚本自动完成：环境检查 → 依赖安装 → .env 配置 → API 密钥检测 → 连接测试。

### 🔧 手动安装

```bash
# 1. 克隆仓库
git clone https://github.com/jxqlovejava/ai-stock-hunter.git
cd ai-stock-hunter

# 2. 安装依赖（Python 3.11+）
pip install -r requirements.txt

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env，至少配置一个 AI 模型密钥（Anthropic / OpenAI / DeepSeek 任选一）
# 数据源密钥可选——不填则自动使用免费数据源（mootdx + 腾讯 + AKShare）

# 4. 验证安装
python -m src diagnose 600519
```

> 💡 **零成本即可使用**：mootdx、腾讯行情、AKShare 均为免费数据源，无需任何 API 密钥。详见 [SECRET.md](SECRET.md)。

### 🆘 常见问题

| 问题 | 解决 |
|------|------|
| `pip install` 失败 | 尝试 `pip install --upgrade pip` 或使用 `uv pip install -r requirements.txt` |
| `mootdx` 连接超时 | 通达信服务器可能需要 VPN，系统会自动降级到腾讯行情 |
| 诊断结果为空 | 检查 `.env` 中是否配置了 AI 模型密钥 |
| 数据源全部失败 | 运行 `python -m src macro` 测试免费数据源是否可用 |

### 核心命令

```bash
# 🏥 一键诊断（小白入口 — 从这里开始！）
python -m src diagnose 000858

# 📊 单只股票全链路分析
python -m src analyze 600519

# 🔍 Alpha 视角分析
python -m src alpha 600519

# 📄 全市场选股扫描
python -m src scan --preset value

# 🌍 宏观快照
python -m src macro

# 😱 情绪信号检测
python -m src sentiment
```

### 短线 / 波段

```bash
# 🔬 技术分析报告（6 维评分 + 入场/出场时机）
python -m src technical 000001 --name 平安银行

# ⏱️ T+0 日内时机分析（建仓/加仓/减仓信号）
python -m src timing 002460

# 🔎 波段选股扫描
python -m src swing-scan --preset aggressive

# 🔔 实时盯盘（单次扫描）
python -m src monitor once --symbols 000001,600519,300750
```

### 宏观事件分析

```bash
# 🌍 宏观事件因果链分析（事件→A股传导→策略建议）
python -m src macro-event "美联储意外加息50bp" --category monetary
python -m src macro-event "纳斯达克暴跌4%，英伟达跌8%，VIX飙升至35" --category financial_crisis --symbol 002460
```

### 交易 & 风控

```bash
# 📊 回测
python -m src backtest

# 💰 模拟交易
python -m src paper-trade

# 👤 投资者偏好管理
python -m src preference setup      # 设置向导（含交易风格/持有周期）
python -m src preference view       # 查看当前配置

# 🔔 自选股管理
python -m src alert watch-add 600519 --name 茅台 --stop-price 1800
python -m src sweep                  # 自选股扫雷
```

### 进化 & 学习

```bash
# 🧬 策略进化 — 导入论文
python -m src evolution import https://arxiv.org/abs/2301.12345

# 🧬 策略进化 — 查看状态
python -m src evolution list

# 📈 交易追踪（凯利公式）
python -m src trade-track list
```

完整 CLI 参考：[`src/cli.py`](src/cli.py)

---

## 🎓 用户成长路径

系统设计目标是**让你最终不再需要它**：

```
依赖期(0-3月)  →  理解期(3-6月)  →  协作期(6-12月)  →  独立期(12月+)
完全跟单          有自己的判断       系统做对手方        系统=风控安全带
```

三种模式一个内核：
- 🟢 **小白**：一键诊断 · ✅/⚠️/🔴 三色信号 · 白话解释
- 🟡 **进阶**：多维对比 · 因子深潜 · 雷达图
- 🔴 **专业**：自定义筛选 · 策略回测 · 论文驱动进化 · 短线技术分析

投资者画像支持配置 `trading_style`（长线/波段/短线）和 `holding_period`，系统自动切换分析管道参数。

---

## 📚 31 条投资军规

分为 7 大类，严重度 block/warn/info 三级：

| 类别 | 数量 | 示例 |
|------|------|------|
| 仓位资金 | 5 条 | 单票 ≤ 20%、总仓位 ≤ 80%、永不满仓 |
| 选股估值 | 6 条 | ST/\*ST 一票否决、不懂不投、商誉雷预警 |
| 买卖纪律 | 5 条 | 不追涨停、不接飞刀、不赌财报 |
| 情绪纪律 | 5 条 | 不在恐慌中决策、拒绝爱上持仓 |
| 信息纪律 | 3 条 | 小作文零信任、信源交叉验证 |
| 风控止盈 | 4 条 | 单笔止损 2%（短线用 ATR）、组合回撤熔断 15% |
| 元风控 | 1 条 | 系统整体连续犯错 → 全局静默 |

详见：[`src/doctrine/rules.py`](src/doctrine/rules.py)

---

## 🗺️ 开发路线图

| Phase | 主题 | 状态 |
|-------|------|------|
| Phase 1 | MVP：3 因子 + 回测 + 军规 + 护栏体系 | ✅ |
| Phase 2 | 数据聚合层（国信/mootdx/AKShare/腾讯/华泰）+ 龙虎榜验证 | ✅ |
| Phase 3 | 宏观货币信用 + 北向多维 + 盈利修正 + 主题生命周期 + 博弈论全景 | ✅ |
| Phase 4 | Alpha Lens + 策略进化 + 用户反馈闭环 + 政策 NLP + 信息速度监控 | ✅ |
| Phase 5 | 技术因子库 + 短线管道 + 实时盯盘 + 入场/出场引擎 + 投资者画像时间维度 | ✅ |
| Phase 6 | Web 可视界面 + 实盘券商 API 对接 + 跨资产信号 + 组合优化 | 🔜 |

---

## 🙏 致敬

本项目深度借鉴了以下开源项目：

| 项目 | 借鉴要点 |
|------|---------|
| [ai-berkshire](https://github.com/xbtlin/ai-berkshire) | 四大师方法论、多 Agent 并行投研框架 |
| [FinceptTerminal](https://github.com/Fincept-Corporation/FinceptTerminal) | 宏观/公司研究数据模型 |
| [OpenStock](https://github.com/Open-Dev-Society/OpenStock) | 跨源情绪聚合 |
| [Backtrader](https://github.com/mementum/backtrader) | 回测引擎核心 |
| [cyberagent](https://pypi.org/project/cyberagent/) | 物理瓶颈分析链（`pip install cyberagent`） |
| [AlphaEvo](https://github.com/ZhuLinsen/alphaevo) | 策略自我进化 + 防过拟合 |
| [open-xquant](https://github.com/xingwudao/open-xquant) | 可复现回测审计流水线 |
| [PanWatch](https://github.com/TNT-Likely/PanWatch) | 盯盘 + 多 Agent 调度 |

完整借鉴清单：[`docs/open-source-credits.md`](docs/open-source-credits.md)

---

## 📖 进一步阅读

| 文档 | 内容 |
|------|------|
| [`.claude/CLAUDE.md`](.claude/CLAUDE.md) | 项目架构 & 开发工作流 |
| [`.claude/plans/short-term-swing-trading.plan.md`](.claude/plans/short-term-swing-trading.plan.md) | 短线波段套利完整设计 |
| [`.claude/plans/ai-stock-hunter.plan.md`](.claude/plans/ai-stock-hunter.plan.md) | 完整系统设计计划 |
| [`.claude/rules/guardrails.md`](.claude/rules/guardrails.md) | 统一护栏规则 |
| [`docs/data-provenance.md`](docs/data-provenance.md) | 数据溯源三要素规范 |
| [`docs/open-source-credits.md`](docs/open-source-credits.md) | 开源项目参考清单 |

---

## ⚠️ 免责声明

本系统仅提供数据分析和决策辅助，**不构成任何投资建议**。所有交易决策由用户自行做出并承担相应风险。A 股有风险，投资需谨慎。

---

## 📄 许可证

MIT License

---

<p align="center">
  <b>安全边际 + 能力圈 + 概率思维 + 逆向思考 = 活下来，赚到钱</b>
</p>
