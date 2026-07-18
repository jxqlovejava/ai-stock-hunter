# Investment-News 参考分析

> 源码：https://github.com/simonlin1212/investment-news（MIT）  
> 本地：`~/Documents/workspace/investment-news`  
> 作者：Simon 林（同 TradingAgents-Astock）  
> 定位：A 股投资者的全球产业链资讯看板 — 100+ 源 → 12 赛道 → AI 中文摘要

---

## 一、项目全景

### 1.1 核心命题

A 股板块的真正驱动信号往往先出现在全球英文源里（半导体在 DIGITIMES/SemiAnalysis，AI 在 OpenAI/Google Research，新能源车在 Electrek/InsideEVs）。但这些信息：
- 分散在 100+ 个独立源
- 多为英文，阅读门槛高
- 信息过载，难以尽读

Investment-News 解决的是：**把全球产业链领先信号汇成一屏中文要点**。

### 1.2 技术约束（刻意极简）

| 维度 | 选择 | 原因 |
|------|------|------|
| 语言 | Python 3.7+ | 通用、零安装 |
| 依赖 | **纯标准库** | `pip install` 都不需要 |
| 大模型 | 用户自己的 Claude 订阅 / API key | 零成本（订阅模式）或按量（API 模式） |
| 存储 | 单文件 `data.js` | 无数据库、无迁移 |
| 前端 | 单文件 `index.html` | 零构建、零框架 |
| 网络 | 仅绑 `127.0.0.1` | 数据不出本机 |
| 源格式 | RSS 2.0 / Atom | 最广泛支持的开放协议 |

### 1.3 与白泽的关系

| 维度 | Investment-News | 白泽 |
|------|----------------|------|
| 输入 | 全球 RSS 源（108 个） | A 股行情/财务/宏观/资金/公告 |
| 处理 | LLM 摘要 + 翻译 | 多阶段分析管道（军规→准入→诊断→裁决→调度→风控） |
| 输出 | 浏览器看板（今日要点 + 双语列表） | CLI 报告 / 交易信号 / 风控决策 |
| 受众 | 人类投资者 | Agent + 人类投资者 |
| 角色 | **资讯输入层** | **分析决策层** |

**关键互补**：Investment-News 可以作为白泽 `topic-manager` + `sector-research` 的全球信号输入层，替代人工刷新闻。

---

## 二、管道架构详解

### 2.1 fetch.py — 多源并发抓取

```
sources.json (108 源, 每个源含 name/hint/type/url)
       │
       ▼  ThreadPoolExecutor(max_workers=40)
  urllib.request.urlopen(url, timeout=14)
       │
       ▼  xml.etree.ElementTree 解析 RSS/Atom
  提取 <item>/<entry> → title, link, pubDate, description
       │
       ▼  红线过滤 (redline_keywords: 赌博/加密/预测市场/色情)
       │  CUTOFF 过滤 (datetime.now(UTC) - timedelta(days=recent_days))
       │  北京时间归一 (MM-DD HH:MM)
       │  每源最多 PER=5 条
       ▼
  data.js (window.DATA = {industries: [...], generated_at: "..."})
```

关键设计决策：
- **40 线程并发**：RSS 源分散在全球，网络延迟是瓶颈，高并发掩盖延迟
- **per_source=5**：每源只取最新 5 条，控制总量（108×5=540 条上限）、避免 LLM 上下文溢出
- **红线过滤在 fetch 层**：脏数据不进管道，减少 LLM 处理量和安全风险
- **失败不阻塞**：单个源失败 → `None`，最终统计失败数但不影响其他源

### 2.2 digest.py — AI 要点 + 翻译

```
data.js (含原始条目)
       │
       ▼  ThreadPoolExecutor(max_workers=3)  // LLM 调用是瓶颈，3 并发足够
  每赛道取最新 TOPN=16 条
       │
       ▼  llm.call(system_prompt, user_prompt)
  system: "你是中文行业新闻分析助手。给某行业最近新闻列表，请做两件事:
          1) 提炼 3-5 条今日要点(≤40字, 聚合去重, 客观陈述, refs 标注来源序号)
          2) 逐条中文标题翻译
          只输出 JSON: {points:[{t, refs}], items:[{i, zh}]}"
       │
       ▼  ATTEMPTS=3 失败重试
       │  已有 points 的赛道自动跳过 (增量补跑)
       ▼
  data.js (含 AI 要点 + has_ai 标记)
```

关键设计决策：
- **TOPN=16**：给 LLM 足够的上下文但不超出 token 窗口
- **refs 溯源机制**：每条要点标注主要来源新闻序号 → 前端可跳转原文
- **ATTEMPTS=3**：`claude -p` 偶发超时/安全拒答，重试提高成功率
- **增量重跑**：`if ind.get("points"): return ind` — 失败栏补跑不重复处理成功栏
- **优雅降级**：某赛道 LLM 彻底失败 → 该赛道只有新闻列表，无要点，但不影响其他赛道

### 2.3 llm.py — 双 Provider 统一入口

```
llm.config.json
  ├── provider: "claude-cli"  → spawn 本机 claude -p
  │     • --disallowedTools 禁全部工具 (只处理文本)
  │     • --system-prompt-file 传系统提示
  │     • 鉴权靠 claude 自己的登录态 ($0)
  │     • 仅本机可用
  │
  └── provider: "api"  → POST /chat/completions
        • OpenAI 兼容端点 (DeepSeek/OpenAI/硅基/OpenRouter...)
        • urllib 手写 HTTP (无 openai 包依赖)
        • 任意机器可用, 按量付费
```

关键设计决策：
- **find_claude()** 多路径探测：`shutil.which("claude")` + 硬编码路径 fallback
- **临时文件传 system prompt**：`--system-prompt-file` 避免命令行注入
- **API 模式手动 HTTP**：不依赖 `openai` 包，保持纯标准库承诺

### 2.4 index.html — 单文件看板

- 左侧 12 赛道导航（固定侧栏，accent 色标识）
- 每栏顶部「今日要点」卡片（要点文本 + 原文链接 ↗）
- 下方新闻列表（中文翻译标题为主，英文原标题灰字备查）
- 左上角 ⟳ 按钮 → `POST /api/refresh` → 转圈等待 → 自动 `location.reload()`
- 零框架、零构建、零外部 CSS/JS

### 2.5 server.py — 本地 HTTP 服务

- `ThreadingHTTPServer(("127.0.0.1", 8793))`：仅绑回环，不暴露局域网
- `POST /api/refresh`：跑 `scripts/fetch.py` → `scripts/digest.py`，返回 JSON
- `GET /api/refresh`：**不触发刷新**（防 `<img>` CSRF）
- 子进程继承 PATH（确保能找到 `claude`）

---

## 三、赛道 ↔ A 股映射（完整）

| key | 赛道 | A 股板块 | 代表标的 | 领先信号来源 |
|-----|------|---------|---------|------------|
| `ai` | AI / 大模型 | 算力/大模型/智能体 | 寒武纪/海光信息/中科曙光 | OpenAI, Google Research, Hugging Face, 量子位, 机器之心 |
| `semi` | 半导体/芯片 | 设计/制造/封测/设备 | 中芯国际/北方华创/长鑫存储 | DIGITIMES, SemiAnalysis, IEEE Spectrum, EE Times |
| `robot` | 机器人/自动化 | 工业机器人/具身智能 | 埃斯顿/绿的谐波/智元 | The Robot Report, Robohub, IEEE Spectrum Robotics |
| `auto` | 汽车/新能源车 | 整车/智驾/电池 | 比亚迪/宁德时代/小鹏 | Electrek, InsideEVs, CnEVPost |
| `energy` | 能源/新能源 | 光伏/储能/电力 | 隆基/阳光电源/三峡能源 | CleanTechnica, PV Tech, Energy Storage News, 国际能源网 |
| `bio` | 生物医药/健康 | 创新药/CXO/器械 | 药明康德/百济神州/迈瑞 | STAT, Endpoints, Nature Biotech, GEN |
| `space` | 航天/太空 | 卫星互联网/航天 | 中国卫星/航天电器 | SpaceNews, NASA, Space.com, Payload |
| `security` | 网络安全 | 网安/信创 | 奇安信/深信服/启明星辰 | Krebs, The Hacker News, BleepingComputer, Dark Reading |
| `tech` | 科技/互联网 | 互联网/SaaS | 腾讯/阿里/字节 | TechCrunch, The Verge, 虎嗅, 36氪, 钛媒体 |
| `consumer` | 消费电子/数码 | 消费电子 | 立讯精密/歌尔股份 | 9to5Mac, GSMArena, Android Authority |
| `macro` | 财经/宏观 | 宏观策略 | — | CNBC, FT, WSJ, 华尔街见闻, 东方财富 |
| `science` | 科学/前沿 | 前沿科技 | — | Nature, ScienceDaily, Quanta Magazine, MIT News |

---

## 四、可复用机制深度分析

### 4.1 多源 RSS 聚合管道 → `data/aggregator.py`

白泽当前数据源以行情/财务 API 为主，缺少结构化的新闻抓取。Investment-News 的 fetch.py 提供了一套开箱即用的模式：

```python
# 可复用的核心模式
1. sources.json 声明式配置（name/hint/type/url）
2. ThreadPoolExecutor 并发抓取（网络 I/O 密集场景最优）
3. 统一时间归一化（UTC → 北京时间）
4. 红线关键词过滤（fetch 层拦截，不进管道）
5. 失败统计不阻塞（单个源挂不影响整体）
```

### 4.2 AI 摘要 + 翻译管道 → `last30days-cn` 输出增强

白泽的 `last30days-cn` 当前返回原始搜索结果。可借鉴 digest.py 的模式增加 AI 摘要层：

```
last30days-cn 搜索结果
  → 按主题/赛道分组
  → LLM 跨源聚合去重
  → 输出 3-5 条「核心要点」+ 溯源链接
```

### 4.3 双 LLM Provider 架构 → 白泽统一 LLM 入口

白泽当前各阶段调 LLM 的方式不统一（有的直接调 API，有的走 skill）。llm.py 的 provider 抽象可直接复用：

```python
# 统一入口模式
def call(system, user, cfg=None, timeout=240):
    if cfg.get("provider") == "api":
        return _call_api(system, user, cfg, timeout)
    return _call_cli(system, user, timeout)
```

### 4.4 增量重跑 → 断点续跑

白泽长链路分析（13 阶段）中途失败需要重跑。digest.py 的增量跳过机制可直接借鉴：

```python
# 已有结果的阶段自动跳过
if ind.get("points"): return ind  # 已有要点 → 跳过
```

对应白泽：每个分析阶段完成后写入 checkpoint，重跑时自动跳过已完成阶段。

### 4.5 信息源可配置化 → 数据源注册

sources.json 的设计让增删源不需要改代码。白泽的数据源注册可以借鉴：

```json
// 声明式数据源注册
{
  "sources": [
    {"name": "华泰证券", "hint": "market_data", "type": "api", "url": "...", "priority": 1},
    {"name": "国信证券", "hint": "market_data", "type": "api", "url": "...", "priority": 2}
  ]
}
```

---

## 五、边界与限制

| 维度 | 限制 | 对白泽的影响 |
|------|------|------------|
| 源格式 | 仅支持 RSS 2.0 / Atom | 需要额外适配无 RSS 的源（如微信公众号、抖音） |
| 时效性 | 依赖源的更新频率（部分源可能延迟 24h+） | 不能替代实时行情，仅作背景信号 |
| 中文源 | 通过 wechat2rss.xlab.app 桥接微信公众号 | 依赖第三方桥接稳定性 |
| LLM 质量 | 摘要质量取决于用户自己的模型 | claude-cli 模式质量稳定；api 模式取决于所选模型 |
| 无搜索 | 不主动搜索，只抓已配置的 RSS 源 | 需要人工维护 sources.json 源列表 |
| 单机 | 仅本地运行，无服务端 | 不能作为团队共享的资讯平台 |

---

## 六、集成建议

### 短期（直接复用）

1. **`sources.json` 赛道-源映射** → 导入 `topic-manager` 的信号源配置
2. **`redline_keywords` 过滤词表** → 补充 31 条军规的内容过滤规则
3. **双 provider LLM 入口** → 白泽统一 `llm.call()` 接口

### 中期（管道对接）

4. **fetch→digest 管道** → 作为 `last30days-cn` 的增强输出层
5. **12 赛道分类体系** → 与 `sector-research` + `serenity-bottleneck` 的产业链分层对齐
6. **增量 checkpoint** → 白泽长链路分析的中断恢复

### 长期（深度融合）

7. **赛道信号 → 主题生命周期**：当某赛道连续 N 天出现同类高频信号时，自动触发 `topic-manager` 的主题启动/加速判断
8. **AI 要点 → 归因输入**：`stock-attribution` 的 Phase 1 信息搜集可直接引用对应赛道的今日要点
9. **看板模式 → CLI dashboard**：`src/cli.py dashboard` 命令启动本地看板，聚合诊断结果
