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

echo "==> 同步 positions.json"
if [[ -f "$ROOT/data/positions.json" ]]; then
  "${SCP[@]}" "$ROOT/data/positions.json" "$HOST:$REMOTE_POS"
else
  echo "本地无 data/positions.json，跳过持仓同步"
fi

echo "==> 写入默认配置（若不存在）"
"${SSH[@]}" "$HOST" "test -f '$REMOTE_CFG' || cp '$REMOTE_ROOT/scripts/hermes_sentinel_config.json' '$REMOTE_CFG'"

echo "==> 安装薄包装到 ~/.hermes/scripts"
"${SSH[@]}" "$HOST" "cat > /home/ubuntu/.hermes/scripts/baize_sentinel.py <<'PY'
#!/usr/bin/env python3
import os, sys
os.environ.setdefault('BAIZE_ROOT', '$REMOTE_ROOT')
os.environ.setdefault('BAIZE_POSITIONS', '$REMOTE_POS')
os.environ.setdefault('BAIZE_SENTINEL_STATE', '$REMOTE_STATE')
os.environ.setdefault('BAIZE_SENTINEL_CONFIG', '$REMOTE_CFG')
# 把 config 路径注入 argv
args = sys.argv[1:]
if '--config' not in args:
    args = ['--config', os.environ['BAIZE_SENTINEL_CONFIG']] + args
sys.argv = [sys.argv[0]] + args
sys.path.insert(0, os.environ['BAIZE_ROOT'])
from src.sentinel.__main__ import main
raise SystemExit(main())
PY
chmod +x /home/ubuntu/.hermes/scripts/baize_sentinel.py"

echo "==> 试跑（--force 忽略交易时段）"
"${SSH[@]}" "$HOST" "python3 /home/ubuntu/.hermes/scripts/baize_sentinel.py --force --json 2>&1 | head -80"

echo ""
echo "✅ 部署完成"
echo "持仓: $REMOTE_POS"
echo "入口: /home/ubuntu/.hermes/scripts/baize_sentinel.py"
echo ""
echo "接下来在 Hermes 添加 cron（示例，按你的微信 origin 改 deliver）:"
echo "  hermes cron 相关命令或编辑 ~/.hermes/cron/jobs.json"
echo "  script: baize_sentinel.py"
echo "  schedule: */2 9-11,13-14 * * 1-5"
