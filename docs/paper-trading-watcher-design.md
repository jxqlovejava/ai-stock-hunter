# Hermes 模拟交易监视器 — 设计与决策记录

> 日期：2026-08-08
> 状态：已部署 Hermes，全模式验证通过
> 代码：`src/paper_trading/watcher.py`、`src/paper_trading/engine.py`、`scripts/deploy_paper_watcher_to_hermes.sh`

## 一、系统目标

以 **20 万元** 模拟账户、**12 支自选股**，在 Hermes 服务器定时驱动，基于真实股价做模拟买卖（不做真交易），记录每笔交易与盈亏，并通过微信推送关键事件。**不硬操作**——无信号时静默。

## 二、架构：四条独立触发路径

```
Hermes cron (CST)
├── 路径 A: 每日简报
│     09:20 盘前分析 → 微信
│     15:05 盘后复盘 (=每日复盘) → 微信
├── 路径 B: 盘中每30分钟轻量快检 (09:30-11:30, 13:00-15:00)
│     12支快筛(并行秒级) → 有候选才全量分析+模拟交易 → 成交才推送
├── 路径 C: 事件驱动强信号 (独立, 每2分钟)
│     缠论买点(10日内)/连续跌破MA20 → 触发即微信+立即执行, 24h去重
└── 路径 D: 定期盈亏复盘
      周五 周复盘 / 月末 月复盘 / 季末 季复盘 → 微信
      (复盘日边界判断: 月末/季末最后交易日才输出)
```

**关键原则**：分析频率可高（盘中每30分钟/强信号每2分钟），但**决策频率低**（只有真正信号才执行+推送）——分析免费、交易有成本。

## 三、佣金校准（用真实成交验证）

用户真实成交（卖出 100股 @47.29 = 4729 元）：
| 项目 | 实际 | 模型 | 判定 |
|------|:---:|:---:|:---:|
| 手续费 | 5.00 | 5.00（万1.154×4729=0.55 < 最低5元）| ✅ |
| 印花税 | 2.36 | 2.36（千0.5）| ✅ |
| 过户费 | 0.05 | 0.05（万0.1）| ✅ |

**关键洞察**：最低 5 元佣金的阈值名义金额 ≈ 4.33 万（5 ÷ 万1.154）。20w 账户单票上限 20%=4 万 < 4.33 万，**几乎所有单票建仓佣金都是 5 元兜底**。佣金率只在单票超 4.3 万时才起作用。

**无滑点**：用户费率不含滑点，模拟交易成本设 `slippage_rate=0`。

## 四、关键设计决策

### 1. 快筛分层（避免全量管道拖垮盘中周期）
`_fast_check`（秒级）：缠论买点 + MA20 支撑距离 + 连续跌破 MA20。**只在有候选时**才跑 `execute_symbol`（全量 Orchestrator）→ 有信号才成交。否则每30分钟跑 12 支全量管道（每次 12 分钟）不可行。

### 2. 缠论买点时效过滤
原始 `_check_chanlun_buy_signal` 返回最近买卖点（可能是一个月前），直接触发会造成"旧信号误买"。`_chanlun_recent` 解析信号日期，**超过 10 天视为过期**不触发。

### 3. `backtest/__init__.py` 弹性化
Hermes 系统 python 被 PEP 668 保护（`--break-system-packages` 风险高），且只装了 pandas/numpy。原 `__init__.py` 急切导入 comparator/engine（需 backtrader）→ 整个包崩。改为：
- 轻量核心（cerebro/broker/result/strategy，无 backtrader）**总是导入**
- 重依赖子模块 **try/except 降级**（缺 backtrader 时跳过，`__all__` 相应缩减）

### 4. Hermes cron 追加而非替换
`crontab <file>` 会**替换整个 crontab**，抹掉既有 gold-miner/sentinel 任务。必须：
```bash
( crontab -l 2>/dev/null | grep -v baize_paper ; cat 新任务 ) | crontab -
```

### 5. 微信投递 = stdout 约定
Hermes 约定：监视器 stdout **非空 = 投递微信，空 = 静默**。watcher 只 print 要推送的内容，无信号输出空串。

## 五、修复的 Bug

| Bug | 根因 | 修复 |
|-----|------|------|
| `AShareCostCalculator` 无法设滑点=0 | `slippage_rate or DEFAULT` — 0.0 是 falsy 被默认值覆盖 | 改 `is not None` 判断（所有 5 个参数） |
| Hermes 上 watcher 崩 | `src.backtest.__init__` 急切导入需 backtrader | try/except 降级 |

## 六、操作手册

```bash
# 本地初始化/查看
python -m src paper-trade start          # 初始化账户 (20w)
python -m src paper-trade status          # 账户状态
python -m src paper-trade history         # 交易记录

# 本地手动跑监视器
python -m src.paper_trading.watcher --mode close --force
python -m src.paper_trading.watcher --mode review --period weekly --force

# 部署到 Hermes
bash scripts/deploy_paper_watcher_to_hermes.sh

# Hermes 侧
crontab -l | grep baize_paper             # 查看 cron
python3 ~/.hermes/scripts/baize_paper.py --mode close --force  # 手动测试
tail -f /home/ubuntu/ai-stock-hunter/data/paper_trading/watcher.log
```

## 七、数据与持久化

- `data/paper_trading/config.yaml` — 账户配置（20w 本金、仓位约束）
- `data/paper_trading/watchlist.json` — 模拟交易独立自选（12支，与主 watchlist 独立）
- `data/paper_trading/state.json` + `trades.jsonl` — 持仓状态 + 逐笔交易（盈亏/佣金/印花/过户）
- `data/paper_trading/strong_signals.json` — 强信号去重（24h 冷却）

## 八、边界与已知限制

- 快筛在降级网络下偏慢（本地东财不可达→mootdx 兜底）；Hermes 云服务器网络正常
- 缠论买点时效阈值 10 天为经验值，可调
- 复盘依赖 `is_trading_day` 交易日历（节假日自动跳过）
- 盘中分析用实时报价，收盘后跑用当日收盘价
