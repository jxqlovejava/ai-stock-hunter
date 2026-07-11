#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Fetch AI-tech A-share stocks: quotes, history, financials, northbound, margin.
Usage:
    cd /Users/jiangxiaoqiang/Documents/workspace/ai-stock-hunter
    .venv/bin/python scripts/fetch_ai_stocks.py
"""

import json
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

from src.data.aggregator import DataAggregator
from src.data.akshare import AKShareProvider
from src.data.source_citation import make_citation, make_data_gap_citation

STOCKS = [
    ("688256", "寒武纪", "SH"),
    ("688041", "海光信息", "SH"),
    ("688008", "澜起科技", "SH"),
    ("603019", "中科曙光", "SH"),
    ("000977", "浪潮信息", "SZ"),
    ("601138", "工业富联", "SH"),
    ("300308", "中际旭创", "SZ"),
    ("300502", "新易盛", "SZ"),
    ("300394", "天孚通信", "SZ"),
    ("002230", "科大讯飞", "SZ"),
    ("300624", "万兴科技", "SZ"),
    ("300442", "润泽科技", "SZ"),
    ("300499", "高澜股份", "SZ"),
    ("002371", "北方华创", "SZ"),
    ("688012", "中微公司", "SH"),
]

NOW = datetime.now()
FETCH_TS = NOW.strftime("%Y-%m-%d %H:%M:%S")

def fmt_val(v, fmt=".2f"):
    if v is None: return "N/A"
    try: return f"{v:{fmt}}"
    except: return str(v)

# ── 1. Source Status ──
agg = DataAggregator()
status = agg.source_status()
print("=== 1. Data Source Status ===")
for src, st in status.items():
    print(f"  {src}: {st}")

# ── 2. Batch Quotes ──
print("\n=== 2. Batch Quotes ===")
quotes = agg.get_quotes_batch([(s[0], s[2]) for s in STOCKS])
quote_map = {q.symbol: q for q in quotes}

header = f"{'Code':<8} {'Name':<10} {'Price':>10} {'Chg%':>8} {'Volume':>12} {'Turnover':>14} {'PE_TTM':>8} {'PB':>8} {'MktCap(亿)':>12}"
print(header)
print("-" * 100)
for code, name, market in STOCKS:
    q = quote_map.get(code)
    if q is None:
        print(f"{code:<8} {name:<10} {'[DATA_GAP]':>10}")
        continue
    mcap_yi = q.market_cap / 1e8 if q.market_cap else None
    print(f"{code:<8} {q.name or name:<10} {fmt_val(q.price,'.2f'):>10} {fmt_val(q.change_pct,'.2f'):>8} {q.volume:>12,} {fmt_val(q.turnover,'.0f'):>14} {fmt_val(q.pe_ttm,'.2f'):>8} {fmt_val(q.pb,'.2f'):>8} {fmt_val(mcap_yi,'.2f'):>12}")

src_provider = quote_map[STOCKS[0][0]].source if STOCKS[0][0] in quote_map else "N/A"
print(f"\nSource: {src_provider} | Fetched: {FETCH_TS}")

# ── 3. Daily History (60 trading days) ──
print("\n=== 3. 60-Day History ===")
end_date = NOW.strftime("%Y%m%d")
start_date = (NOW - timedelta(days=90)).strftime("%Y%m%d")

for code, name, market in STOCKS:
    try:
        df = agg.get_history(code, start_date=start_date, end_date=end_date, period="daily")
    except Exception as e:
        print(f"  {code} {name}: [DATA_GAP] {e}")
        continue
    if df is None or df.empty:
        print(f"  {code} {name}: [DATA_GAP] empty")
        continue

    col_map = {
        "日期":"date","开盘":"open","收盘":"close","最高":"high","最低":"low",
        "成交量":"volume","成交额":"amount","涨跌幅":"pct_chg","换手率":"turnover",
        "date":"date","open":"open","close":"close","high":"high","low":"low",
        "volume":"volume","amount":"amount","turnover":"turnover",
    }
    if hasattr(df, "rename"):
        df = df.rename(columns={c: col_map[c] for c in df.columns if c in col_map})

    last60 = df.tail(60)
    first_c = float(last60["close"].iloc[0])
    last_c = float(last60["close"].iloc[-1])
    period_chg = (last_c / first_c - 1) * 100
    high_60 = float(last60["high"].max())
    low_60 = float(last60["low"].min())

    print(f"\n  {code} {name}:")
    print(f"    60d chg: {period_chg:.2f}%  close: {last_c:.2f}  high60: {high_60:.2f}  low60: {low_60:.2f}")
    print(f"    AvgVol: {last60['volume'].mean():,.0f}  LastVol: {int(last60['volume'].iloc[-1]):,}")

    # last 5 trading days
    dates_col = last60["date"] if "date" in last60.columns else last60.index
    print("    Last 5:")
    for i in range(max(0, len(last60)-5), len(last60)):
        row = last60.iloc[i]
        d = str(dates_col.iloc[i] if hasattr(dates_col,'iloc') else dates_col[i])[:10]
        c = float(row.get("close",0))
        ch = float(row.get("pct_chg",0))
        v = int(row.get("volume",0))
        print(f"      {d}  close:{c:.2f}  chg:{ch:.2f}%  vol:{v:,}")

# ── 4. Financials ──
print("\n=== 4. Financials (Latest Quarter) ===")
for code, name, market in STOCKS:
    try:
        fins = agg.get_financials(code, market, count=1)
    except Exception as e:
        print(f"  {code} {name}: [DATA_GAP] {e}")
        continue
    if not fins:
        print(f"  {code} {name}: [DATA_GAP] no data")
        continue
    f = fins[0]
    cit = f.citation
    src_name = cit.provider if cit else "unknown"
    print(f"\n  {code} {name} ({f.report_period}) src={src_name}:")
    print(f"    ROE: {f.roe:.2f}%" if f.roe is not None else "    ROE: [DATA_GAP]")
    print(f"    EPS: {f.eps:.4f}" if f.eps is not None else "    EPS: [DATA_GAP]")
    print(f"    Rev: {f.revenue:,.2f}" if f.revenue is not None else "    Rev: [DATA_GAP]")
    print(f"    NP:  {f.net_profit:,.2f}" if f.net_profit is not None else "    NP: [DATA_GAP]")
    print(f"    Assets: {f.total_assets:,.2f}" if f.total_assets is not None else "    Assets: [DATA_GAP]")
    print(f"    Liab: {f.total_liabilities:,.2f}" if f.total_liabilities is not None else "    Liab: [DATA_GAP]")
    print(f"    OCF: {f.operating_cash_flow:,.2f}" if f.operating_cash_flow is not None else "    OCF: [DATA_GAP]")

# ── 5. Northbound Flow ──
print("\n=== 5. Northbound Flow ===")
try:
    ap = AKShareProvider()
    nf = ap.get_northbound_flow()
    if nf is not None and not nf.empty:
        print(f"  Recent northbound flow (source: akshare/eastmoney):")
        print(f"  {nf.tail(20).to_string()}")
    else:
        print("  [DATA_GAP] Northbound flow unavailable")
except Exception as e:
    print(f"  [DATA_GAP] Northbound flow error: {e}")

# ── 6. Margin Trading ──
print("\n=== 6. Margin Trading ===")
try:
    import akshare as ak
    mt = ak.stock_margin_detail_sse(date=NOW.strftime("%Y%m%d"))
    if mt is not None and not mt.empty:
        print(f"  SSE margin data ({len(mt)} records):")
        for code, name, market in STOCKS:
            if market == "SH":  # SSE only
                row = mt[mt["证券代码"].astype(str) == code]
                if not row.empty:
                    r = row.iloc[0]
                    print(f"    {code} {name}: 融资余额={r.get('融资余额','N/A')}  融券余额={r.get('融券余额','N/A')}")
                else:
                    print(f"    {code} {name}: not in today's SSE margin list")
    else:
        print("  [DATA_GAP] No SSE margin data today")

    # SZ margin via eastmoney
    try:
        sz_margin = ak.stock_margin_szse_summary(date=NOW.strftime("%Y%m%d"))
        if sz_margin is not None and not sz_margin.empty:
            print(f"  SZ margin summary available ({len(sz_margin)} records)")
        else:
            print("  [DATA_GAP] No SZ margin data today")
    except Exception as e:
        print(f"  [DATA_GAP] SZ margin: {e}")
except Exception as e:
    print(f"  [DATA_GAP] Margin trading error: {e}")

print(f"\n=== Done at {FETCH_TS} ===")
