# A 股财报分析详细工作流

## Phase 1: 数据收集 — API 端点映射

### 东财 datacenter-web (主)

| 数据 | API 路径 | 参数 |
|------|---------|------|
| 利润表 | `datacenter-web/income_statement` | code, report_type, end_date |
| 资产负债表 | `datacenter-web/balance_sheet` | code, report_type, end_date |
| 现金流量表 | `datacenter-web/cash_flow` | code, report_type, end_date |
| 盈利预测 | `datacenter-web/earnings_forecast` | code |
| 分红记录 | `datacenter-web/dividend` | code |

### 巨潮资讯网 (cninfo)

| 数据 | API 路径 |
|------|---------|
| 年报 PDF | `http://www.cninfo.com.cn/new/disclosure/detail?plate=&orgId={orgId}&stockCode={code}&announcementId={id}` |
| 公告列表 | `http://www.cninfo.com.cn/new/hisAnnouncement/query` |

### 同花顺 iFinD (如有)

| 数据 | API 路径 |
|------|---------|
| 一致预期 EPS | `ths_iFinD/consensus_eps` |
| 分析师评级 | `ths_iFinD/analyst_ratings` |
| 上调/下调历史 | `ths_iFinD/revision_history` |

## Phase 2: 分析 — 关键指标计算

### A 股特定指标

1. **扣非净利润 = 归母净利润 - 非经常性损益**
   - 来源: 利润表 "归属于母公司股东的净利润" - "非经常性损益"
   - 用途: 排除一次性收益影响

2. **经营现金流/净利润**
   - > 1.0: 现金流健康
   - < 0.5: 现金流紧张 (可能是应收账款堆积)
   - 连续 3 年 < 0.7: 红旗

3. **商誉/净资产**
   - < 0.1: 健康
   - 0.1-0.3: 关注
   - > 0.3: 减值风险高

4. **应收账款/营收**
   - 同比变化: 应收增速 > 营收增速 → 可能放宽信用政策 (红旗)
   - 区分: 银行承兑汇票 (低风险) vs 商业承兑汇票 (高风险)

5. **关联交易占比**
   - > 营收 30%: 需审查关联方
   - > 营收 50%: 重大红旗

6. **大股东质押比例**
   - < 50%: 正常
   - 50-80%: 关注
   - > 80%: 高风险 (平仓风险)

## Phase 5: 质量控制 — 三表勾稽

### 核心勾稽关系

1. **资产 = 负债 + 权益**
   ```
   BS: total_assets == total_liabilities + total_equity
   ```

2. **净利润勾稽**
   ```
   IS: net_income + BS(begin): retained_earnings - dividends == BS(end): retained_earnings
   ```

3. **现金勾稽**
   ```
   BS: cash(end) - BS: cash(begin) ≈ CF: net_change_in_cash
   ```

## A 股披露时间表

| 报告期 | 披露截止 | 特点 |
|--------|---------|------|
| 一季报 | 4月30日 | 与年报同期披露 (4月密集) |
| 中报 | 8月31日 | 半年报 |
| 三季报 | 10月31日 | — |
| 年报 | 次年4月30日 | 需审计，信息最全 |

**业绩预告规则**：
- 净利润为负 → 1月31日前预告
- 净利润同比 ±50% → 1月31日前预告
- 扭亏为盈 → 1月31日前预告
