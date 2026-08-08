#!/usr/bin/env bash
# 部署白泽模拟交易监视器到 Hermes 服务器
# 用法: bash scripts/deploy_paper_watcher_to_hermes.sh
# 前提: 本地已配置好 data/paper_trading/ (config/watchlist/state) + src/paper_trading/watcher.py
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PEM="${HERMES_PEM:-$HOME/Documents/hermes.pem}"
HOST="${HERMES_HOST:-ubuntu@124.220.236.129}"
REMOTE_ROOT="${HERMES_BAIZE_ROOT:-/home/ubuntu/ai-stock-hunter}"
REMOTE_PT="${HERMES_PT:-/home/ubuntu/.hermes/baize/paper_trading}"

if [[ ! -f "$PEM" ]]; then
  echo "缺少 SSH 密钥: $PEM"
  exit 1
fi

SSH=(ssh -i "$PEM" -o StrictHostKeyChecking=no)
SCP=(scp -i "$PEM" -o StrictHostKeyChecking=no)

echo "==> 创建远程目录"
"${SSH[@]}" "$HOST" "mkdir -p '$REMOTE_ROOT/src' '$REMOTE_ROOT/data' '$REMOTE_PT'"

echo "==> 同步 src (监视器依赖 paper_trading/routing/data/sentinel/backtest)"
"${SCP[@]}" -r "$ROOT/src" "$HOST:$REMOTE_ROOT/"
"${SSH[@]}" "$HOST" "touch '$REMOTE_ROOT/src/__init__.py' 2>/dev/null || true"

echo "==> 同步 paper_trading 数据 (config/watchlist/state/trades)"
if [[ -d "$ROOT/data/paper_trading" ]]; then
  "${SCP[@]}" -r "$ROOT/data/paper_trading/." "$HOST:$REMOTE_PT/"
else
  echo "  本地无 data/paper_trading, 跳过"
fi
# 也放到项目 data/ 下 (watcher 默认路径 data/paper_trading)
"${SSH[@]}" "$HOST" "mkdir -p '$REMOTE_ROOT/data/paper_trading'"
"${SCP[@]}" -r "$ROOT/data/paper_trading/." "$HOST:$REMOTE_ROOT/data/paper_trading/"

echo "==> 安装包装器 ~/.hermes/scripts/baize_paper.py"
"${SSH[@]}" "$HOST" "cat > /home/ubuntu/.hermes/scripts/baize_paper.py <<'PYEOF'
#!/usr/bin/env python3
# 白泽模拟交易监视器包装器 — stdout 非空=投递微信
import os, sys, subprocess
from pathlib import Path
os.environ.setdefault('BAIZE_ROOT', '$REMOTE_ROOT')
os.environ.setdefault('BAIZE_PT_DEDUP', '$REMOTE_PT/strong_signals.json')
os.environ.setdefault('BAIZE_POSITIONS', '$REMOTE_PT/positions.json')
os.environ.setdefault('BAIZE_WATCHLIST', '$REMOTE_PT/watchlist.json')
root = Path(os.environ['BAIZE_ROOT'])
cmd = [str(root / '.venv' / 'bin' / 'python' if (root / '.venv' / 'bin' / 'python').exists() else 'python3'),
       '-m', 'src.paper_trading.watcher'] + sys.argv[1:]
env = dict(os.environ)
env['PYTHONPATH'] = str(root)
proc = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=str(root), timeout=900)
if proc.stdout and proc.stdout.strip():
    print(proc.stdout, end='')
    sys.exit(0)
if proc.returncode != 0 and proc.stderr:
    print(proc.stderr[-500:], file=sys.stderr)
sys.exit(proc.returncode)
PYEOF
chmod +x /home/ubuntu/.hermes/scripts/baize_paper.py"

echo "==> 安装催化信号包装器 baize_catalyst.py"
"${SSH[@]}" "$HOST" "sed 's/src.paper_trading.watcher/src.paper_trading.catalyst/' /home/ubuntu/.hermes/scripts/baize_paper.py > /home/ubuntu/.hermes/scripts/baize_catalyst.py && chmod +x /home/ubuntu/.hermes/scripts/baize_catalyst.py"

echo "==> 安装 cron (四条路径 + 催化信号)"
"${SSH[@]}" "$HOST" "cat > /home/ubuntu/.hermes/paper_watcher.crontab <<'CEOF'
# 白泽模拟交易监视器 (CST) — 路径 A/B/C/D
# 路径 A: 盘前/盘后
20 9 * * 1-5     cd $REMOTE_ROOT && python3 /home/ubuntu/.hermes/scripts/baize_paper.py --mode premarket >> $REMOTE_ROOT/data/paper_trading/watcher.log 2>&1
5 15 * * 1-5     cd $REMOTE_ROOT && python3 /home/ubuntu/.hermes/scripts/baize_paper.py --mode close >> $REMOTE_ROOT/data/paper_trading/watcher.log 2>&1
# 路径 B: 盘中每30分钟 (09:30-11:30, 13:00-15:00)
30 9 * * 1-5     cd $REMOTE_ROOT && python3 /home/ubuntu/.hermes/scripts/baize_paper.py --mode intraday >> $REMOTE_ROOT/data/paper_trading/watcher.log 2>&1
0,30 10-11 * * 1-5  cd $REMOTE_ROOT && python3 /home/ubuntu/.hermes/scripts/baize_paper.py --mode intraday >> $REMOTE_ROOT/data/paper_trading/watcher.log 2>&1
0,30 13-14 * * 1-5  cd $REMOTE_ROOT && python3 /home/ubuntu/.hermes/scripts/baize_paper.py --mode intraday >> $REMOTE_ROOT/data/paper_trading/watcher.log 2>&1
0 15 * * 1-5     cd $REMOTE_ROOT && python3 /home/ubuntu/.hermes/scripts/baize_paper.py --mode intraday >> $REMOTE_ROOT/data/paper_trading/watcher.log 2>&1
# 路径 C: 强信号轮询 (每2分钟 9-15 点)
*/2 9-14 * * 1-5  cd $REMOTE_ROOT && python3 /home/ubuntu/.hermes/scripts/baize_paper.py --mode strong >> $REMOTE_ROOT/data/paper_trading/watcher.log 2>&1
0-58/2 15 * * 1-5  cd $REMOTE_ROOT && python3 /home/ubuntu/.hermes/scripts/baize_paper.py --mode strong >> $REMOTE_ROOT/data/paper_trading/watcher.log 2>&1
# 催化信号 (价格买点/政策新闻/个股/PMI) — 每30分钟
5,35 9-14 * * 1-5  cd $REMOTE_ROOT && python3 /home/ubuntu/.hermes/scripts/baize_catalyst.py --mode all >> $REMOTE_ROOT/data/paper_trading/catalyst.log 2>&1
5,35 15 * * 1-5    cd $REMOTE_ROOT && python3 /home/ubuntu/.hermes/scripts/baize_catalyst.py --mode all >> $REMOTE_ROOT/data/paper_trading/catalyst.log 2>&1
# 路径 D: 周/月/季复盘 (脚本内部判断是否复盘日)
30 15 * * 5      cd $REMOTE_ROOT && python3 /home/ubuntu/.hermes/scripts/baize_paper.py --mode review --period weekly >> $REMOTE_ROOT/data/paper_trading/watcher.log 2>&1
30 15 28-31 * *  cd $REMOTE_ROOT && python3 /home/ubuntu/.hermes/scripts/baize_paper.py --mode review --period monthly >> $REMOTE_ROOT/data/paper_trading/watcher.log 2>&1
30 15 28-31 3,6,9,12 *  cd $REMOTE_ROOT && python3 /home/ubuntu/.hermes/scripts/baize_paper.py --mode review --period quarterly >> $REMOTE_ROOT/data/paper_trading/watcher.log 2>&1
CEOF
# 追加到现有 crontab (绝不替换, 保留 gold-miner/sentinel 等既有任务)
( crontab -l 2>/dev/null | grep -v 'baize_paper' ; cat /home/ubuntu/.hermes/paper_watcher.crontab ) | crontab -
echo 'cron 已追加安装'"

echo "==> 验证"
"${SSH[@]}" "$HOST" "crontab -l | grep baize_paper | head -4"
echo "✅ 部署完成. 查看: crontab -l | grep baize_paper; 手动测试: python3 /home/ubuntu/.hermes/scripts/baize_paper.py --mode close --force"
