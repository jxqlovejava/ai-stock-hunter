# GS Quant 参考分析

> 源码：https://github.com/goldmansachs/gs-quant  
> 文档：https://developer.gs.com/docs/gsquant/  
> 许可证：Apache 2.0  
> 分析日期：2026-07-16

**GS Quant** 是高盛量化团队维护的 Python 量化金融工具包，面向衍生品定价、交易策略开发与风险管理，沉淀约 25 年机构市场经验。完整 Marquee 数据/定价 API 需机构 client id/secret；**白泽借鉴的是模块划分、风险/时序/回测抽象与工程模式**，而非绑定其商业 API。

---

## 一、仓库模块地图

| 模块 | 职责 | 白泽对应 |
|------|------|---------|
| `gs_quant/risk/` | 风险度量、情景、聚合 | L4 风控、组合敞口 |
| `gs_quant/timeseries/` | 时序算子与统计变换 | `factor_pipeline`、动量/波动 |
| `gs_quant/backtests/` | 回测框架抽象 | `src/backtest/` |
| `gs_quant/markets/` | 市场对象与定价上下文 | 数据层 / 宏观 |
| `gs_quant/analytics/` | 分析与报表原语 | 分析输出标准化 |
| `gs_quant/models/` | 定价与统计模型 | 估值 / 波动模型 |
| `gs_quant/data/` | 数据请求与缓存抽象 | `data/aggregator.py` |
| `gs_quant/instrument/` | 金融工具对象模型 | 标的/合约 DTO |
| `gs_quant/entities/` | 实体与引用 | 公司/标的主数据 |
| `gs_quant/workflow/` | 研究工作流编排 | orchestrator plan |
| `gs_quant/datetime/` | 交易日历/日期工具 | A 股交易日 |
| `gs_quant/session.py` | 会话与鉴权上下文 | Config / session |
| `gs_quant/api/` | 远程 API 客户端 | 数据 provider 适配器 |
| `gs_quant/mcp/` | MCP 集成（较新） | 未来 tool-use 接入 |
| `gs_quant/skills/` | Agent Skill 封装（较新） | `.claude/skills/` 模式对照 |

---

## 二、设计原则（可迁移）

### 2.1 分层清晰

```
Instrument / Entity
        ↓
Market / Data context
        ↓
Pricing / Models
        ↓
Risk aggregation
        ↓
Backtest / Analytics / Report
```

对应白泽：

```
行情/财务 DTO
        ↓
因子 / 宏观 / 行业
        ↓
L1 诊断
        ↓
L2 裁决 → L3 仓位 → L4 风控
        ↓
回测 / 学习 / 输出
```

### 2.2 Session / Context

- 统一 session 承载鉴权、环境、默认市场  
- 避免各模块各自解析配置  
- 对齐 DojoAgents `ConfigStore` 与白泽「可移植优先」

### 2.3 时序算子可组合

- 指标不是散落函数，而是可组合变换链  
- 便于回测/实盘同一套变换  
- 建议 `factor_pipeline` 向算子注册表演进

### 2.4 风险度量分层

| 层 | 含义 | 白泽 |
|----|------|------|
| 单标的 | 波动、回撤、止损距离 | positioning / risk_control |
| 组合 | gross / net / 行业集中 | L4 + 军规仓位 |
| 情景 | 压力测试、极端路径 | 黑天鹅熔断、宏观 regime |

### 2.5 强类型与不可变倾向

- instrument / priceable 对象边界清晰  
- 与白泽 **DTO 优先 + frozen dataclass** 一致  

---

## 三、可迁移机制清单

| # | 机制 | 应用到本项目 |
|---|------|------------|
| 1 | 风险度量三层（单票/组合/情景） | L4 + positioning |
| 2 | 时序算子可组合 | `data/factor_pipeline.py` |
| 3 | 回测与定价/策略对象分离 | `backtest/` 与策略 DSL |
| 4 | Session/Context 统一配置 | 配置中心化 |
| 5 | 强类型 instrument 边界 | 跨层 DTO |
| 6 | datetime/交易日历工具 | A 股交易日工具统一 |
| 7 | analytics 声明式报表 | 分析输出标准化 |
| 8 | workflow 编排 | orchestrator plan 化 |
| 9 | data 抽象 + 缓存 | aggregator 缓存策略 |
| 10 | MCP/skills 封装（若演进） | tool-use / skill 入口 |

---

## 四、不直接借鉴 / 边界

| 项 | 原因 |
|----|------|
| Marquee 专属定价与机构数据 | 需 GS 机构账号，A 股个人场景不可用 |
| 衍生品全产品线（奇异期权等） | 白泽聚焦 A 股股票投研，非衍生品做市 |
| 直接 `pip install` 作为运行时核心依赖 | 体积大且大量能力依赖远程服务；按需引用设计思路 |
| 与 VectorBT 重复的回测微观结构 | A 股回测仍以 VectorBT / Backtrader 为主 |

---

## 五、与现有参考的分工

| 主题 | 主参考 | GS Quant 角色 |
|------|--------|---------------|
| 回测撮合/交易记录 | VectorBT、Backtrader | 抽象分层、机构级报表思路 |
| 风控硬规则 | RiskGuard | 组合/情景风险度量语言 |
| 因子时序 | 自研 factor_pipeline | 算子可组合、统计库习惯 |
| 配置/Session | DojoAgents | Session 上下文模式 |

---

## 六、建议落地优先级

1. **P0**：文档级——在风控/回测设计决策时对照 risk/backtests 模块边界  
2. **P1**：`factor_pipeline` 引入「注册算子 + 链式应用」接口草案  
3. **P2**：组合层风险指标清单对齐（gross/net/行业/情景）  
4. **P3**：评估是否局部依赖 `gs-quant` 中**纯本地**统计/时序工具（无 Marquee 时）  
