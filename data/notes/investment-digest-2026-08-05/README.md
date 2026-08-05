# 投资资讯精读研究 — 2026-08-05

从 tweet-disgest 服务器（`124.220.236.129`）最近 200 篇文章中筛出的炒股/投资相关文章（30 篇），多 Agent 精读 + 投资视角审查 + 最终汇总结论。

## 数据来源
- 文章归档：服务器 `/home/ubuntu/tweet-disgest/data/`（meta.json 共 1172 篇，按 savedTimestamp 取最近 200 篇）
- 筛词：股票/投资/量化/交易/仓位/MACD/均线 等 80+ 关键词（标题+正文+作者）
- 30 篇净入选（原 36 命中，剔除 4 篇用户指定 + 2 篇误报）

## 目录结构
```
source/articles_extract/    # 30 篇原文纯文本（frontmatter + 正文）
videos/                     # 5 个视频的 whisper 转写文本（NN_*.txt）
docs/                       # 30 篇精读文档（关键信息提取 + 投资视角审查）
synthesis.md                # 最终汇总结论（供投资系统参考）
```

## 产出流程
1. 服务器提取 30 篇全文 → 本地 source/
2. 5 个 Agent 并行精读 25 篇纯文本 → docs/
3. 5 篇视频文章：本地 whisper.cpp（Metal 加速）转写 → 视频 Agent 精读 → docs/
4. 汇总 synthesis.md

## 视频转写技术栈
- 视频托管：腾讯云 COS（articlevideo-1316871392，公有读）
- 音频提取：`ffmpeg -i <url> -vn -ac 1 -ar 16000`（流式，不落盘视频）
- 转写：`whisper-cli`（whisper.cpp，Metal 加速）+ `ggml-small-q5_1.bin`（~190MB，中文质量可接受）
- 注意：视频无字幕，Python whisper 无 Metal 时 ~2x 实时，whisper.cpp Metal ~4x 实时

## 内容分层
- 高价值：量化闭环系统架构（13）、散户生存法则量价系列（19/21/22/28）、AI 三层投资框架（29）、VWAP 策略（11）
- 中价值：仓位管理（15/25）、均线体系（16/27）、交易心理（12）、市场有效性（30）
- 低价值/警示：营销话术、加密行情预测、纯引流帖（01/09/14/18）
