# Serenity.skill 参考分析

> 源码：https://github.com/muxuuu/serenity-skill  
> 许可证：MIT  
> 分析日期：2026-07-16  
> 别名：白毛股神 skill / Serenity 式供应链瓶颈投研

Serenity.skill 把 [Serenity / @aleabitoreddit](https://x.com/aleabitoreddit) 公开内容中可观察到的投研路径做成 **Agent Skill**：从热点出发拆产业链，找供应链瓶颈，筛候选公司和基金方向，再检查公告/财报/客户/产能/风险，输出**优先研究清单**（非买卖指令）。

与白泽现有 `industry/bottleneck.py` + `cyberagent` 瓶颈链**互补**：cyberagent 偏物理瓶颈身份分类；Serenity 偏完整「热点→卡点→证据→排序」研究 workflow。

---

## 一、核心研究路径

```
market story
  → system change
  → required parts
  → supply-chain layers
  → scarce constraints（卡点）
  → public companies
  → evidence
  → what the market may be missing
  → what could prove the idea wrong
```

默认纪律：

1. **Deep research 为默认**，禁止热点速答。
2. **先排产业链层级，再排公司**。
3. 主题扫描：尽量 ≥20 候选公司、≥25 信源；受限时标注「初扫」与缺口。
4. 社交媒体 = 线索；强结论必须回到公告/交易所/财报/专利/标准等。

---

## 二、请求路由（Request Router）

| 模式 | 触发 | 白泽场景映射 |
|------|------|-------------|
| Theme scan | 主题/赛道/概念 | 场景四主题分析、有主题荐股 |
| Single-company challenge | 单票挑战 | 场景 4b 单票深度 / diagnose |
| Candidate comparison | 多票对比 | 荐股阶段三横向排名 |
| Research partner | 讨论/追问 | 交互式投研对话 |
| Learning mode | 学方法 | 教学式拆解（可选） |

---

## 三、研究 Workflow 9 步

| 步 | 内容 | 白泽对接 |
|----|------|---------|
| 1. Set scope | 市场/主题/时间窗 | `topic-manager` 输入 |
| 2. System change | 技术/经济变化 + 物理约束 | 叙事→基本面传导 |
| 3. Map value chain | 8 层价值链 | `supply_chain.py` |
| 4. Find scarce layer | 稀缺约束排序 | `bottleneck.py` |
| 5. Company universe | ≥20 候选再过滤 | 选股初筛 |
| 6. Evidence grade | 证据分级 | guardrails tier/nature |
| 7. Rank priorities | 需求压力×卡点接近度×证据… | L1/L2 加权 |
| 8. What goes wrong | 失败条件 | L2 可证伪条件 |
| 9. Next research move | 下一步核验清单 | 输出「待查」 |

### 8 层价值链（建议细化白泽供应链节点）

1. 下游需求  
2. 系统集成  
3. 模块/子系统  
4. 芯片/器件  
5. 工艺与封装  
6. 设备与测试  
7. 材料与耗材  
8. 物理基础设施（电力/冷却/机房…）

### 稀缺层信号

- 低供应商数量  
- 长验证/认证周期  
- 扩产困难  
- 关键 know-how  
- 材料纯度要求  
- 专用设备  
- 长交期 / 产能预留  

---

## 四、证据标准

| 强度 | 含义 | 白泽对应 |
|------|------|---------|
| strong | 公告/交易所/财报/电话会/监管项目/专利标准/正式订单 | T0–T1, nature=fact |
| medium | 可信媒体/行业刊/专业分析 | T1–T2, interpretation |
| weak | 间接推断 | T2–T3 |
| unverified lead | 社媒/传闻线索 | T3, speculation；≤0.5 confidence |

A 股证据路径（`market-source-playbook`）：

- 年报/半年报/季报、临时公告  
- 交易所问询函  
- 互动易 / 上证 e 互动  
- 招投标、环评/能评、地方项目备案  
- 专利、客户认证、海关  
- 应收/存货/现金流、关联交易  

---

## 五、捆绑资源清单

| 路径 | 用途 |
|------|------|
| `SKILL.md` | 主 workflow 与路由 |
| `references/deep-research-workflow.md` | 深度扫描细节 |
| `references/evidence-ladder.md` | 证据阶梯 |
| `references/market-source-playbook.md` | 分市场信源路径 |
| `references/risk-and-compliance.md` | 研究边界 |
| `assets/bottleneck-scorecard.json` | 打分输入模板 |
| `assets/thesis-template.md` | 论点 memo 模板 |
| `scripts/serenity_scorecard.py` | 本地可重复打分 |
| `examples/*.md` | A 股 AI 半导体等示例 |

---

## 六、可迁移机制清单

| # | 机制 | 应用到本项目 |
|---|------|------------|
| 1 | 主题→系统变化翻译 | `topic-manager` + `sector-research` |
| 2 | 8 层价值链地图 | `industry/supply_chain.py` |
| 3 | 稀缺层判定维度 | `industry/bottleneck.py` |
| 4 | 证据阶梯 | guardrails + data provenance |
| 5 | A 股证据路径 | 归因/主题信息搜集 |
| 6 | 瓶颈 scorecard 脚本 | L1 瓶颈可配置打分 |
| 7 | 请求路由 5 模式 | 用户交互 workflow |
| 8 | 失败条件 + 下一步核验 | L2 可证伪 + 输出清单 |
| 9 | 先层后票输出格式 | 主题分析/荐股报告结构 |
| 10 | 「优先研究」非买卖指令 | 与禁止具体买卖建议护栏一致 |

---

## 七、不直接借鉴 / 边界

- 不做自动交易执行、收益承诺  
- 不复制其 Agent Skill 安装路径为运行时依赖（方法论进代码/文档即可）  
- 与 cyberagent 瓶颈分类并存，避免两套打分互相覆盖而不说明权重  

---

## 八、建议落地优先级

1. **P0**：主题分析输出改为「先层后票」+ 失败条件 + 下一步核验（文档/CLI 格式）  
2. **P1**：`bottleneck.py` 增加稀缺层信号字段与 scorecard 对齐  
3. **P2**：证据阶梯与现有 T0–T3 做映射表，统一 citation  
4. **P3**：可选安装 serenity-skill 为 Claude Code 用户级 skill，供交互式深度主题研究  
