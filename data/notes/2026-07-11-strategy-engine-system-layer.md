---
id: 2026-07-11-strategy-engine-system-layer
created_at: 2026-07-11T18:00:00
updated_at: 2026-07-10T16:58:09.663992+00:00
topic: 系统设计
tags: [策略引擎, 仓位管理, 退出策略, 加仓策略, 系统层, StrategyEngine]
trigger_by: both
source: 对话
status: discussion
---

# Strategy Engine System Layer

## 摘要

完成策略引擎系统层三大模块组装：1)PositionSizer(sizing.py) — Kelly/VolTarget/FixedFractional三模式仓位计算，含风险检查+手数取整+上限封顶；2)ExitRuleEngine(exit_rules.py) — ATR动态止损+时间止损+分批止盈(20%/40%)+保本止损四规则；3)AddRuleEngine(add_rules.py) — 金字塔/等额/信号三种加仓方式+6道安全门。StrategyEngine(engine.py)作为编排层，entry_rules留空等待用户学习后填入。三层已可独立运行。

## 关键要点

- PositionSizer: Kelly(1/4分数)+波动率目标+固定比例，自动选最佳模式
- ExitRuleEngine: ATR trailing→时间止损→分批止盈→保本止损，优先级递减
- AddRuleEngine: 金字塔(递减)/等额(盈利)/信号(强度)三模式，6道安全门
- StrategyEngine: 编排层，entry_rules留空(认知层—用户后续学习填入)
- 五空位现状: 仓位✅ 退出✅ 加仓✅ | 触发条件❓ 买入方式❓(留待学习)

## 完整讨论

通过4个并行subagent组装了策略引擎的系统层。PositionSizer复用了src/kelly/和src/routing/positioning.py的算法。ExitRuleEngine参考了RiskGuard的ATR止损设计。AddRuleEngine实现了经典的三种加仓模式。StrategyEngine作为编排器将三者串联：entry→exit→add→sizing→dedup→sort。entry_rules被显式留空——这是认知层，需要用户通过学习市场规律来自行设计。集成测试验证了保本止损在茅台场景下正确触发(曾浮盈+20%后回吐→EXIT HIGH)。