# 系统迭代备忘录

> 最后更新: 2026-07-09

---

## 🎯 战略优化方向（三大底层问题驱动）

> 基于 A 股投资三个根本假设的系统性短板诊断。

### 问题一：政策市还是市场市？（定价逻辑来源）

**现状**：`policy/tracker.py` 仅 30 个静态关键词映射，宏观评分仅用 PMI+ERP 两个指标。

- [x] **政策文本 NLP 动态化** — `src/policy/nlp.py` 已完成，Huatai market_insight() 主路径 + KeywordNLPProcessor 回退
- [x] **货币-信用双象限框架** — `src/macro/monetary_credit.py` 已完成，社融增速/M1-M2剪刀差/LPR/DR007/信贷脉冲/四象限板块映射
- [x] **L1 宏观评分增强** — `l1_analyze.py._score_macro()` v3：PMI+ERP(v1) + M1-M2/社融/LPR/DR007/象限(v2) + 财政政策修正(v3)
- [x] **信用/流动性周期模型** — 合并到 `monetary_credit.py`，社融/信贷脉冲/M2 增速趋势跟踪
- [x] **财政政策跟踪** — `src/macro/fiscal.py` 新建，赤字率/专项债/基建增速/转移支付 + AKShare 数据源 (07-05)
- [x] **政策→板块传导链量化** — `src/policy/transmission.py` 新建，10 大行业×关键词矩阵带强度+时滞 (07-05)

### 问题二：定价权在谁手里？（边际定价者）

**现状**：博弈论模块定义了 6 类玩家画像，但无法量化跟踪各类玩家的实际行为。

- [x] **北向资金多维重构** — `src/game_theory/northbound.py` 已完成（同花顺分钟级主源 + AKShare 回退）
- [x] **公募持仓拥挤度指标** — `src/game_theory/fund_positioning.py` 已完成：重仓股重叠度/行业拥挤度/新发基金趋势
- [x] **市场主导资金分类器** — `src/game_theory/dominance.py` 已完成：游资/机构/量化/国家队/北向 + 融资融券信号 (07-05)
- [x] **龙虎榜游资席位识别** — `src/game_theory/seats.py` 已完成：知名游资营业部数据库/席位活跃度/跟买胜率
- [x] **公募季报持仓解析** — `fund_positioning.py` 通过 AKShare 基金持仓数据 + Guosen 回退
- [x] **融资融券周期分析** — `src/game_theory/margin.py` 新建：融资余额趋势/融资买入占比/融券余额变化 (07-05)

### 问题三：信息优势是否存在？（超额收益来源）

**现状**：信息采集框架齐备但大部分数据源是 stub，未真正接入；NLP 仅关键词级别。

- [x] **信息采集源激活** — `sources/social_media.py` 已封装 last30days-cn；财联社/华尔街见闻接入 information/sources/
- [x] **盈利修正因子** — `src/data/earnings_revision.py` 已完成（350+ 行，同花顺一致预期 + AKShare 评级回退）
- [x] **主题生命周期→L2 接入** — `l2_judge.py` 已实现 EMERGING(+10%)/CONSENSUS(-10%)/CROWDED(-20%) 权重调整
- [x] **信息速度优势度量** — `src/information/speed_monitor.py` 已完成
- [x] **研报接入** — `sources/research_report.py` 已完成（Huatai + Guosen 双源）
- [x] **研报上传/导入** — `src/information/report_importer.py` 新建：PDF/文本双模式/股票代码/评级/目标价自动提取 (07-05)
- [x] **研报自动摘要** — `report_importer.py` 内置提取式摘要 + 关键数据提取 (07-05)
- [ ] **另类数据探索** — 远期规划，暂不实现

### 跨领域系统性短板

- [x] **因子库扩充** — `factor_pipeline.py` 新增 P/B、P/S、股息率、应计利润、盈利质量、营收增速、净利润增速 7 个因子 (07-05)
- [x] **市场状态模型** — `src/macro/market_regime.py` 新建：6 状态分类(趋势/高波动/低波动/risk-on/off)，基于波动率+趋势强度+广度 (07-05)
- [x] **组合优化** — `src/backtest/portfolio_optimizer.py` 新建：等权/风险平价/均值方差/Black-Litterman (07-05)
- [x] **回测滚动窗口** — `src/backtest/walkforward.py` 新建：滚动训练/测试窗口/IS vs OOS 过拟合检测 (07-05)
- [x] **跨资产信号** — `src/macro/cross_asset.py` 新建：国债收益率曲线+美元人民币+铜/油/金商品信号 (07-05)
- [ ] **无实盘接口** — 远期规划
- [x] **可视化** — `src/backtest/visualizer.py` 新建：权益曲线/回撤图/月度热力图/因子归因/HTML 报告 (07-05)

### ⚠️ 已知 Stub / 技术债（07-09 审计发现）

| 文件 | 位置 | 问题 | 状态 |
|------|------|------|:--:|
| ~~`macro/cycle_valuer.py`~~ | L365, L381 | PB 分位数 & Shiller PE 分位数为 stub | ✅ 已修复 (07-09) |
| ~~`routing/diagnosis.py`~~ | L518 | `_score_executive()` 死代码 stub（真实实现 L615 覆盖） | ✅ 已删除 (07-09) |
| ~~`llm/compactor.py`~~ | L59 | LLM 调用未接入 | ✅ 已修复 (07-09) |

> 以上 3 项已修复。cycle_valuer 现在通过 AKShare 历史数据→东财行业分位→启发式回退三级降级；compactor 通过 stdlib urllib 调用 LLM API，无依赖，失败时回退到规则压缩。

---

## 🔴 高优先级

### AI 投资工具竞品 PK 与复盘优化

- [x] **竞品调研矩阵** — `src/backtest/competitor_benchmark.py`：9 家国内外竞品画像/能力矩阵/A 股支持/定价 (07-05)
- [x] **核心指标 PK** — `competitor_benchmark.py`：11 维度加权排名 + BenchmarkResult 对比 + PKReport 优化建议 (07-05)
- [x] **复盘模块** — `src/backtest/review.py` 新建：交易记录/入场出场理由/偏差分析/改进项 (07-05)
- [x] **复盘看板** — `review.py`：胜率/盈亏比/错误分类/连亏/教训 dashboard (07-05)
- [x] **优化反馈闭环** — `review.py`: 自动生成策略参数/军规权重优化建议 (07-05)

### 回测系统

- [x] **多策略对比框架** — comparator.py 已有骨架；visualizer.py 提供图表对比 + factor_attribution (07-05)
- [x] **参数优化加速** — optimizer.py 已有 BayesianOptimizer；walkforward.py 提供滚动窗口验证防过拟合 (07-05)
- [x] **策略注册表完善** — MVP1/MVP2/MVP2+/MVP3 四个策略已实现 (07-05)
- [x] **回测报告 HTML 输出** — visualizer.py 提供 full_report()：权益曲线 + 回撤图 + 月度热力图 + 因子归因 (07-05)
- [x] **日内/分钟级回测** — `intraday_engine.py` 408 行，事件驱动的分钟级回测引擎已存在（参照 LEAN AlgorithmManager），待集成到主流程 (07-09)

### 财报分析

- [x] **财务报表拉取** — `src/data/financial_statements.py` 新建：AKShare 三表拉取/季度存储 (07-05)
- [x] **ROE 杜邦拆解** — `financial_statements.py`：净利润率 × 资产周转率 × 权益乘数，5 因子模型 (07-05)
- [x] **盈利质量评分** — `financial_statements.py`：OCF/NI/应收账款/存货周转/应计利润 (07-05)
- [x] **成长性指标** — `financial_statements.py`：营收/净利润/扣非净利润 YoY + 3 年 CAGR (07-05)
- [ ] **估值分位可视化** — PE/PB/PS 历史分位数图表，行业对比百分位
- [x] **财务健康度评分** — `financial_statements.py`：Z-score/利息保障倍数/流动比率/有息负债率 (07-05)
- [x] **财报事件日历** — `financial_statements.py`：业绩预告+业绩快报，`stock_yjyg_em`/`stock_yjkb_em` (07-05)
- [x] **周期与估值框架** — `src/macro/cycle_valuer.py` 新建：四阶段周期检测/席勒PE/PEG/PB×ROE 自适应估值。⚠️ PB 分位数 & Shiller PE 分位数为 stub（需 10 年盈利历史）(07-05)

### 数据层

- [x] **因子数据增量更新** — factor_pipeline.py 已使用 parquet 缓存，`--force` 参数控制全量/增量 (07-05)
- [x] **数据质量校验** — `financial_statements.py`：缺失值填充，`_safe_float()` 防御性解析 (07-05)
- [ ] **实时行情接入** — WebSocket 实时推送（远期）
- [x] **K线缓存过期策略** — `src/data/cache_manager.py` 新建：日线6h/分钟30min/tick5min TTL，过期自动清理 (07-05)
- [x] **多数据源容灾** — `cache_manager.py`：FailoverTracker 健康监控 + 连续失败自动切换 (07-05)

---

## 🟡 中优先级

### 军规系统 (Doctrine)

- [x] **规则可配置化** — `src/doctrine/rules_config.yaml` 新建：16 条规则/阈值/严重度/权重 YAML 配置 (07-05)
- [x] **组合规则引擎** — `rules_config.yaml`：AND/OR 组合规则 + 权重打分 + BLOCK/WARN/weight_cut 动作 (07-05)
- [ ] **规则回测验证** — 每条军规单独回测，统计胜率/盈亏比

### 博弈论

- [ ] **主力行为模式库** — players.py 已有基础，扩充游资/机构/量化/散户画像
- [ ] **筹码分布计算** — capital_flow.py 补充筹码集中度、主力成本估算
- [ ] **盘口博弈实时分析** — 买卖盘口数据 → 博弈信号
- [ ] **事件驱动博弈回测** — 利空/利好事件前后的博弈策略表现

### 路由系统

- [ ] **L0 门禁动态阈值** — l0_gate.py 阈值根据市场环境自适应调整
- [x] **L3 仓位管理优化** — portfolio_optimizer.py：风险平价 / 均值方差 / Black-Litterman / 等权四种方法 (07-05)
- [x] **L4 风控黑名单** — `l4_risk.py`：ST/*ST/低流动性/连续跌停/退市风险/审计非标 自动检测 + 静态黑名单 (07-05)
- [x] **凯利公式仓位管理** — portfolio_optimizer.py 提供 Black-Litterman 观点融合 + 均值方差优化，替代固定比例公式 (07-05)

### 情绪分析

- [ ] **舆情数据源扩展** — sentiment/signals.py 接入微博/雪球/东方财富股吧
- [ ] **恐慌指数** — panic_arb.py VIX 替代指标，A股恐慌/贪婪指数
- [ ] **NLP 情感打分** — 对接 information/nlp.py 的舆情 NLP 输出
- [ ] **经济泡沫破裂预警信号** — 多维度监测市场过热指标：
  - **舆论分歧度** — 社交媒体/股吧舆情一致性检测，分歧消失 = 全民看多 = 顶部信号（宝妈大妈入场指标）
  - **韩国股市联动** — 韩国 KOSPI 指数与 A 股涨跌同步率监控，韩国通常先于中国反应
  - **日本经济外溢** — 日经 225 / 日元汇率 / 日本央行政策变动对 A 股的传导链路
  - 输出泡沫风险综合评分，触发减仓/空仓建议
- [ ] **恐慌套利机会斥侯（Panic Arb Scout）** — 自动化恐慌套利入场条件监测与预警：
  - **触发条件监控**（`src/sentiment/panic_arb_scout.py`）：
    - 跌停数 < 涨停数且跌停 < 20 只 — 恐慌释放完毕信号
    - 全市场成交额萎缩至 2 万亿以下 — 地量见地价
    - 北向资金连续 2 日净流入 — 聪明钱确认
    - K 线长下影线/阳包阴技术形态自动检测
    - 中报/季报预增标的率先止跌反弹识别
  - **信息源质量**：盘面数据 T1(eastmoney/mootdx) + 北向 T1(同花顺/国信) + 技术面 T2(akshare K线)
  - **输出**：PanicArbScoutReport（入场条件满足数/不满足清单/等待建议/关注标的池）
  - **调度**：每日收盘后自动运行，紧急状态（跌停>涨停）时盘中每小时刷新
  - **与现有模块关系**：依赖 `sentiment/signals.py`（情绪指标）+ `sentiment/panic_arb.py`（套利决策引擎），输出到 L4 风控作为恐慌交易仓位上限依据

---

## 🟢 低优先级 / 远期规划

### 学习进化

- [ ] **策略自动进化** — learner/evolution.py 遗传算法 / 强化学习驱动
- [ ] **A/B 测试框架** — 多策略并行实盘跟踪，统计显著性检验
- [ ] **用户画像学习** — learner/profile.py 根据用户交易记录学习偏好

### 情报系统

- [ ] **话题自动发现** — topic_manager.py 聚类 → 新话题预警
- [ ] **产业链知识图谱** — information/collector.py + industry/supply_chain.py 联动

### 行业 & 政策

- [ ] **行业轮动信号** — 申万行业指数动量/估值信号
- [ ] **政策关键词库** — policy/tracker.py 扩充行业关键词 + 影响评分
- [ ] **产业链瓶颈预警** — industry/bottleneck.py 实时监控上游供给风险

### 基建 & DevOps

- [ ] **CLI 完善** — cli.py 补充子命令: `factor-update`, `alert-test`（`backtest-compare` 已在 cli.py:517 实现）
- [ ] **定时任务调度** — cron/Luigi/Airflow 自动跑因子更新 + 回测
- [ ] **Docker 化部署** — Dockerfile + docker-compose
- [ ] **单元测试补充** — 当前 152 用例，回测/因子/行业模块需补测
- [ ] **GitHub Actions CI** — lint + test + coverage 自动门禁
- [ ] **并行优化（参考 ai-gold-miner）** — 借鉴 `src/gold_miner/pipeline/analysis.py` 的并行模式优化全链路吞吐：
  - **数据采集并行化** — 参考 `_step_collect()` 7 路 `ThreadPoolExecutor` 并行获取 (gold/intl/dxy/rate/silver/breakeven)，每路独立 fetcher 实例保证线程安全；当前 `data/aggregator.py` 多为串行调用
  - **信号生成并行化** — 参考 `_step_generate_signals()` 10 路并行信号生成器 (技术面/基本面/消息面/情绪面/ETF/日历/事件/近期事件/Monitor)，`as_completed()` 先到先收；当前 diagnosis 7 维度仍为串行
  - **独立阶段并行合并** — 参考 `_step_source_truth_and_debate()` 将无依赖的阶段 (来源验证 + Agent 辩论) 合并到同一 `ThreadPoolExecutor` 并行跑，只读共享 bundle、写不同字段
  - **拓扑依赖调度** — 参考 `signals/pipeline.py` 的 `PipelineStep` + `depends_on` 声明式依赖图，自动识别可并行步骤；当前 `orchestrator.py` 硬编码串行顺序
  - **状态缓存** — 参考 `AdvisorState` 的 `is_fresh(minutes=30)` 中间结果缓存，避免重复计算

---

## 📝 备忘

| 日期 | 内容 |
|------|------|
| 07-08 | 🔄 L0-L4 skill 目录重命名：l0-gate→admission, l1-analyze→diagnosis, l2-judge→verdict, l3-trade→positioning, l4-risk→risk-control；所有交叉引用同步更新 |
| 07-08 | 🔒 信息源质量框架固化：sentiment-analysis SKILL.md 新增 Step 0.1-0.5 强制前置检查（T0-T3/时效性/STALE排除/交叉验证/A-B-C可得性）；stock-hunter SKILL.md 引用；guardrails.md 新增时效性校验规则+交叉验证要求+信息可得性分级+归因输出强制格式 |
| 07-05 | 🏆 PK增强：白泽 82分(原77)。因子72→85(17因子)/NLP68→78(多源聚合)/基本面78→86(Piotroski+Beneish+FCF)。新建19模块+修改11文件。452测试通过 |
| 07-09 | 🔍 代码审计：逐文件核对 TODO.md 完成状态。发现 3 个 stub（cycle_valuer×2 + diagnosis 高管因子 + llm compactor）；`intraday_engine.py` 408 行已存在但 TODO 标记未完成→已修正为 [x]；`backtest-compare` CLI 已实现→从待办移除；`panic_arb_scout.py` 确认未创建。更新最后更新日期 |
