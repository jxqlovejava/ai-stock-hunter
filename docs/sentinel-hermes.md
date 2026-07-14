# 白泽持仓哨兵 × Hermes（Phase A）

轻量盘中预警：只盯 `positions.json`，不跑全链路 `diagnose`。

## 三档分析体系

| 档 | 入口 | 耗时 | 用途 |
|----|------|------|------|
| **sentinel** | Hermes cron `baize_sentinel.py` | ~0.3s | 盘中持仓硬规则推送 |
| **light** | `python -m src diagnose CODE --light` | 约十秒级 | 持仓体检：行情+军规+轻诊断+**博弈/买卖点**+裁决+仓位/风控 |
| **daily/full** | `diagnose` / `analyze --deep` | 几十秒～分钟 | 建仓研究 / 深度研究 |

light **跳过**：四大师辩论、Munger 全量、T+0 深扫、行业/公司深度、多通道资讯、反操纵深扫。

light **保留**：`GameTheoryAnalyzer`（主导玩家/拥挤/席位/北向）+ `EntryExitEngine` 技术时机 → `gt_timing` 融合买/卖点。  
原则：买点卖点不能只看技术，必须看谁在定价。

## 行为（sentinel）

| 情况 | 输出 | Hermes |
|------|------|--------|
| 非交易时段 | 空 | 静默 |
| 无异动 | 空 | 静默 |
| 有异动 | 短卡片 | 推微信 |
| 报价失败 | stderr | 不推（避免刷屏） |

## 规则

### 价格 / 结构（Phase A）

| 级 | 规则 | 说明 |
|----|------|------|
| P0 | `stop_hit` | 现价 ≤ 止损 |
| P0 | `stop_near` | 距止损 ≤ 1.5% |
| P1 | `cost_break` | 跌破成本 |
| P1 | `day_drop` / `day_rise` | 日内 ±5% |
| P2 | `jump` / `accel` | 采样跳变 / 连续同向 |
| P2 | `amplitude_*` | 日内振幅阈值 |

### 轻量风控（非完整 L4）

| 级 | 规则 | 说明 |
|----|------|------|
| P0 | `float_loss` | 单票浮亏超阈（默认 8% 或持仓 `initial_stop_pct`） |
| P0 | `portfolio_loss` | 组合相对成本浮亏超阈（默认 5%） |
| P1 | `peak_drawdown` | 从持仓最高价回撤超阈（默认 8%） |

### 轻量仓位管理（非完整 L3）

读 `data/portfolio.yaml` → `position_limits`：

| 级 | 规则 | 说明 |
|----|------|------|
| P1 | `single_overweight` | 单票市值 / 总资金 > `max_single_pct`（默认 20%） |
| P1 | `total_exposure` | 总市值 / 资金 > `max_total_exposure`（默认 80%） |
| P1 | `cash_low` | 现金比例 < `min_cash_pct`（默认 20%） |

**仍然不跑** 完整 `positioning.py` / `risk_control.py` 管道。

冷却：P0 5min / P1 20min / P2 45min（可配置）。

## 本机试跑

```bash
# 忽略交易时段 + JSON 调试
.venv/bin/python -m src.sentinel --force --json

# 文本卡片（Hermes 模式）
.venv/bin/python -m src.sentinel --force

# 指定持仓
.venv/bin/python -m src.sentinel \
  --positions data/positions.json \
  --state data/sentinel_state.json \
  --force
```

## 部署到 Hermes 服务器

```bash
bash scripts/deploy_sentinel_to_hermes.sh
```

默认：

- 主机 `ubuntu@124.220.236.129`
- 密钥 `~/Documents/hermes.pem`
- 远程代码 `/home/ubuntu/ai-stock-hunter`
- 持仓 `/home/ubuntu/.hermes/baize/positions.json`
- 包装入口 `~/.hermes/scripts/baize_sentinel.py`

### 挂 cron

在 Hermes 增加 job（字段对齐现有 `jobs.json`）：

```json
{
  "name": "白泽持仓哨兵",
  "script": "baize_sentinel.py",
  "schedule": { "kind": "cron", "expr": "*/2 9-11,13-14 * * 1-5" },
  "enabled": true,
  "deliver": "origin",
  "origin": {
    "platform": "weixin",
    "chat_id": "<你的微信 chat_id>"
  }
}
```

或用 CLI（若版本支持）：

```bash
hermes cron  # 按本机 Hermes 版本交互添加
```

**重要**：`script` 模式、无异动静默；不要用大模型 prompt 每 2 分钟跑全分析。

### 同步持仓

本机改了 `data/positions.json` 后：

```bash
scp -i ~/Documents/hermes.pem \
  data/positions.json \
  ubuntu@124.220.236.129:/home/ubuntu/.hermes/baize/positions.json
```

或重跑 `deploy_sentinel_to_hermes.sh`。

## 报价源

1. **腾讯批量**（默认，免费）
2. 缺失时回退 **华泰 HT_APIKEY**（`~/.htsc-skills/config` 或环境变量）

## 非目标（Phase A 不做）

- 全市场扫描
- 完整 diagnose / 军规 / 辩论
- 自动下单
