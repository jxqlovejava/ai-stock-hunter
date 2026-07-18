#!/usr/bin/env bash
# 部署白泽哨兵到 Hermes 服务器
# 用法: bash scripts/deploy_sentinel_to_hermes.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PEM="${HERMES_PEM:-$HOME/Documents/hermes.pem}"
HOST="${HERMES_HOST:-ubuntu@124.220.236.129}"
REMOTE_ROOT="${HERMES_BAIZE_ROOT:-/home/ubuntu/ai-stock-hunter}"
REMOTE_POS="${HERMES_POSITIONS:-/home/ubuntu/.hermes/baize/positions.json}"
REMOTE_STATE="${HERMES_STATE:-/home/ubuntu/.hermes/baize/sentinel_state.json}"
REMOTE_CFG="${HERMES_CFG:-/home/ubuntu/.hermes/baize/sentinel_config.json}"

if [[ ! -f "$PEM" ]]; then
  echo "缺少 SSH 密钥: $PEM"
  exit 1
fi

SSH=(ssh -i "$PEM" -o StrictHostKeyChecking=no)
SCP=(scp -i "$PEM" -o StrictHostKeyChecking=no)

echo "==> 创建远程目录"
"${SSH[@]}" "$HOST" "mkdir -p '$REMOTE_ROOT' '$REMOTE_ROOT/src' '$REMOTE_ROOT/scripts' '$(dirname "$REMOTE_POS")'"

echo "==> 同步 sentinel 代码与入口"
"${SCP[@]}" -r \
  "$ROOT/src/sentinel" \
  "$HOST:$REMOTE_ROOT/src/"
# 需要 package 可导入
"${SSH[@]}" "$HOST" "touch '$REMOTE_ROOT/src/__init__.py' 2>/dev/null || true"
"${SCP[@]}" \
  "$ROOT/scripts/baize_sentinel.py" \
  "$ROOT/scripts/hermes_sentinel_config.json" \
  "$HOST:$REMOTE_ROOT/scripts/"

echo "==> 同步 positions.json + portfolio.yaml + watchlist.json"
if [[ -f "$ROOT/data/positions.json" ]]; then
  "${SCP[@]}" "$ROOT/data/positions.json" "$HOST:$REMOTE_POS"
else
  echo "本地无 data/positions.json，跳过持仓同步"
fi
REMOTE_PORTFOLIO="$(dirname "$REMOTE_POS")/portfolio.yaml"
REMOTE_WATCHLIST="$(dirname "$REMOTE_POS")/watchlist.json"
if [[ -f "$ROOT/data/portfolio.yaml" ]]; then
  "${SCP[@]}" "$ROOT/data/portfolio.yaml" "$HOST:$REMOTE_PORTFOLIO"
fi
if [[ -f "$ROOT/data/watchlist.json" ]]; then
  "${SCP[@]}" "$ROOT/data/watchlist.json" "$HOST:$REMOTE_WATCHLIST"
fi

echo "==> 写入默认配置（若不存在）"
"${SSH[@]}" "$HOST" "test -f '$REMOTE_CFG' || cp '$REMOTE_ROOT/scripts/hermes_sentinel_config.json' '$REMOTE_CFG'"

REMOTE_PORTFOLIO="$(dirname "$REMOTE_POS")/portfolio.yaml"
echo "==> 安装薄包装到 ~/.hermes/scripts"
# 注意：外层双引号展开 REMOTE_*；内层 HEREDOC 用 EOF 无引号以便展开变量写入远程文件
"${SSH[@]}" "$HOST" "cat > /home/ubuntu/.hermes/scripts/baize_sentinel.py <<EOF
#!/usr/bin/env python3
import os, sys, json
from pathlib import Path
os.environ.setdefault('BAIZE_ROOT', '${REMOTE_ROOT}')
os.environ.setdefault('BAIZE_POSITIONS', '${REMOTE_POS}')
os.environ.setdefault('BAIZE_SENTINEL_STATE', '${REMOTE_STATE}')
os.environ.setdefault('BAIZE_SENTINEL_CONFIG', '${REMOTE_CFG}')
os.environ.setdefault('BAIZE_WATCHLIST', '$(dirname "$REMOTE_POS")/watchlist.json')
cfg_path = Path(os.environ['BAIZE_SENTINEL_CONFIG'])
try:
    cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
except Exception:
    cfg = {}
cfg['portfolio_path'] = '${REMOTE_PORTFOLIO}'
cfg['positions_path'] = os.environ['BAIZE_POSITIONS']
cfg['state_path'] = os.environ['BAIZE_SENTINEL_STATE']
cfg['watchlist_path'] = os.environ.get('BAIZE_WATCHLIST', '$(dirname "$REMOTE_POS")/watchlist.json')
cfg_path.parent.mkdir(parents=True, exist_ok=True)
cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2))
args = sys.argv[1:]
if '--config' not in args:
    args = ['--config', os.environ['BAIZE_SENTINEL_CONFIG']] + args
sys.argv = [sys.argv[0]] + args
sys.path.insert(0, os.environ['BAIZE_ROOT'])
from src.sentinel.__main__ import main
raise SystemExit(main())
EOF
chmod +x /home/ubuntu/.hermes/scripts/baize_sentinel.py"

# 分频道薄入口（Hermes 只配 script 名、不便带参数时用）
for mode in alert funds open close sentiment watchlist; do
  "${SSH[@]}" "$HOST" "cat > /home/ubuntu/.hermes/scripts/baize_${mode}.py <<EOFMODE
#!/usr/bin/env python3
import os, sys
from pathlib import Path
# 固定 mode，其余环境与主入口一致
sys.argv = [sys.argv[0], '--mode', '${mode}'] + [a for a in sys.argv[1:] if a != '--mode']
# 链式调用主包装
main_py = Path('/home/ubuntu/.hermes/scripts/baize_sentinel.py')
code = main_py.read_text(encoding='utf-8')
# 主包装会再读 sys.argv[1:]，已含 --mode
exec(compile(code, str(main_py), 'exec'), {'__name__': '__main__'})
EOFMODE
chmod +x /home/ubuntu/.hermes/scripts/baize_${mode}.py"
done

echo "==> 试跑 alert / open / funds（--force）"
"${SSH[@]}" "$HOST" "python3 /home/ubuntu/.hermes/scripts/baize_sentinel.py --mode alert --force 2>&1 | head -40"
echo "--- open ---"
"${SSH[@]}" "$HOST" "python3 /home/ubuntu/.hermes/scripts/baize_sentinel.py --mode open --force 2>&1 | head -40"
echo "--- funds ---"
"${SSH[@]}" "$HOST" "python3 /home/ubuntu/.hermes/scripts/baize_sentinel.py --mode funds --force 2>&1 | head -40"

echo ""
echo "✅ 部署完成"
echo "持仓: $REMOTE_POS"
echo "入口: baize_sentinel.py --mode <alert|funds|open|close|sentiment>"
echo "或:   baize_alert.py / baize_funds.py / baize_open.py / baize_close.py / baize_sentiment.py"
echo ""
echo "建议 Hermes cron（人话推送，分频道）:"
echo "  1) 盘中持仓  */2 9-11,13-14 * * 1-5   → baize_alert.py"
echo "  2) 两融+自选  0 10,14 * * 1-5          → baize_funds.py"
echo "  3) 开盘前     15 9 * * 1-5             → baize_open.py"
echo "  4) 收盘后     10 15 * * 1-5            → baize_close.py"
echo "  5) 情绪极端   */15 9-14 * * 1-5        → baize_sentiment.py"
