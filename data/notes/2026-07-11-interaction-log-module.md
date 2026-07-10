---
id: 2026-07-11-interaction-log-module
created_at: 2026-07-11T16:00:00
updated_at: 2026-07-10T16:36:52.364638+00:00
topic: 系统设计
tags: [交互日志, CLI, 自动记录, 使用分析, 导师]
trigger_by: user
source: 对话
status: discussion
---

# Interaction Log Module

## 摘要

新增轻量级交互日志模块(src/interaction/)。每次CLI命令执行自动记录：时间戳、命令、参数、输出摘要(长输出自动截断前500+尾200字符)、耗时、退出码。JSONL格式追加写入data/interaction_log.jsonl。提供interaction-log CLI命令(tail/search/stats/commands)。目的：让Claude能通过访问交互日志了解用户使用系统的完整画像，从而作为导师主动发现盲区、决策模式偏差、反复踩的坑。

## 关键要点

- 每次CLI命令自动记录，无需用户手动操作
- JSONL格式：一行一条记录，轻量追加写入
- 长输出自动截断：前500+尾200字符，清除ANSI转义码
- CLI: interaction-log tail/search/stats/commands
- 终极目的：Claude读取日志→了解用户使用模式→主动给出针对性建议

## 完整讨论

讨论了让Claude作为导师需要了解用户与系统交互的完整画像。已有的数据通道包括ctx_search(过去会话)、memory_recall(手动保存的观察)、投研笔记(讨论记录)、git log(代码变更)、持仓文件。但缺少用户日常使用CLI的交互日志。新增src/interaction/模块，在CLI main()的handler执行处用StringIO捕获stdout→写回真实stdout→自动记录到JSONL。记录不包含交互日志命令本身(避免递归)。输出截断策略：保留前500+尾200字符，中间用truncated标记。