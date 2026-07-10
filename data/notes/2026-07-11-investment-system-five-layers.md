---
id: 2026-07-11-investment-system-five-layers
created_at: 2026-07-11T10:30:00
updated_at: 2026-07-10T16:14:48.842093+00:00
topic: 系统设计
tags: [系统架构, 投资框架, 选股, 仓位管理, 风控, 复盘]
trigger_by: user
source: 对话
status: discussion
---

# Investment System Five Layers

## 摘要

用户提出系统四大核心能力（选股/买卖时机/盯盘预警/复盘迭代），讨论后补充第五层：仓位管理。完整五层框架：选股(Alpha)→仓位管理(Sizing)→买卖时机(Timing)→盯盘风控(Monitor)→复盘进化(Evolution)。对应系统现有模块：admission+diagnosis / positioning+kelly / verdict+T+0 / risk_control+monitor / learner+backtest+evolution。

## 关键要点

- 五层框架：选股 → 仓位管理 → 买卖时机 → 盯盘风控 → 复盘进化
- 仓位管理是独立维度，凯利公式证明可数学优化，不在买卖点里
- 对应现有模块：admission/diagnosis → positioning/kelly → verdict/T+0 → risk_control/monitor → learner/backtest/evolution
- 系统架构已覆盖全部五层

## 完整讨论

用户列出四大核心能力：选股、买卖时机判断、盯盘预警（极致=自动交易）、复盘迭代。从专业投资角度补充了第五层：仓位管理/资金管理(Position Sizing)。仓位大小决定了最大亏损，不能用买卖点代替。凯利公式的存在证明仓位是可独立优化的数学维度。映射回现有系统架构，五层都已覆盖。