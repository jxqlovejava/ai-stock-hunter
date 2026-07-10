---
id: 2026-07-11-strategy-layer-gap-analysis
created_at: 2026-07-11T16:30:00
updated_at: 2026-07-10T16:42:44.175125+00:00
topic: 系统设计
tags: [策略引擎, 短板诊断, 回测, 场景自适应, 退出策略, ATR止损, 系统优化]
trigger_by: user
source: 对话
status: actionable
---

# Strategy Layer Gap Analysis

## 摘要

系统性诊断了当前交易策略层的四大短板：1)现有策略简单(MVP1/Verdict都是月调仓top-N等权，回测年化收益低、夏普差)；2)无场景自适应(牛熊震荡用同一套逻辑，没有regime-switching)；3)分析强行动弱(diagnose产出详尽但到"买不买/买多少/什么时候卖"的翻译层靠人工，没有策略引擎做条件分支决策)；4)退出策略单一(仅-25%固定止损，缺少ATR动态止损、分批止盈、trailing stop、时间止损)。这是接下来要补的最大短板。

## 关键要点

- 短板1: 策略太简单 — 月调仓top-N等权，回测年化收益低，夏普差
- 短板2: 无场景自适应 — 牛熊震荡同一套，缺少regime-switching
- 短板3: 分析强行动弱 — 诊断产出→交易决策的翻译层缺失
- 短板4: 退出不完善 — 只有固定-25%止损，缺ATR动态止损/分批止盈/trailing stop/时间止损
- 方向: 需要策略引擎 — 条件分支(score≥阈值+宏观+情绪)→自动输出买卖决策

## 完整讨论

通过逐模块审查确认了策略层是系统最大短板。backtest/有完整的回测框架(Cerebro/Broker/Analyzer/Walkforward)但策略本身很薄——MVP1用PE+ROE+动量月调仓，VerdictStrategy用评分排序月调仓，本质上都是同一句话。paper_trading/的引擎骨架完整但策略逻辑同样简单。关键缺失：没有把diagnosis管道的丰富产出转化为结构化的、可回测的、条件分支的策略规则。ATR动态止损在positioning模块里应该有(来自RiskGuard参考)但没被策略层调用。下一步要建立一个策略引擎层，把诊断→决策→执行这个翻译管道自动化。