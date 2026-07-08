#!/usr/bin/env bash
# =============================================================================
# 白泽 (Baize) — A 股智能投资决策系统 一键安装脚本
# =============================================================================
# 用法:
#   chmod +x setup.sh && ./setup.sh
#
# 自动完成: 环境检查 → 依赖安装 → .env 配置 → 连接测试
# =============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

echo ""
echo -e "${CYAN}🦄 白泽 (Baize) — A 股智能投资决策系统${NC}"
echo -e "${CYAN}=============================================${NC}"
echo ""

# ---- Step 1: 检查 Python 版本 ----
echo -e "${BOLD}[1/5]${NC} 检查 Python 环境..."

if ! command -v python3 &>/dev/null; then
    echo -e "${RED}❌ 未找到 python3，请先安装 Python 3.11+${NC}"
    echo "   macOS:  brew install python@3.12"
    echo "   Ubuntu: sudo apt install python3.12"
    exit 1
fi

PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)

if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]); then
    echo -e "${RED}❌ Python 版本过低: $PY_VERSION (需要 >= 3.11)${NC}"
    exit 1
fi

echo -e "   ${GREEN}✅ Python $PY_VERSION${NC}"

# ---- Step 2: 安装依赖 ----
echo ""
echo -e "${BOLD}[2/5]${NC} 安装 Python 依赖..."

if command -v uv &>/dev/null; then
    echo "   使用 uv (快速模式)..."
    uv pip install -r requirements.txt --quiet 2>&1 | tail -1
elif command -v pip3 &>/dev/null; then
    echo "   使用 pip3..."
    pip3 install -r requirements.txt --quiet 2>&1 | tail -1
else
    echo -e "${RED}❌ 未找到 pip3 或 uv${NC}"
    exit 1
fi

echo -e "   ${GREEN}✅ 依赖安装完成${NC}"

# ---- Step 3: 配置 .env ----
echo ""
echo -e "${BOLD}[3/5]${NC} 配置环境变量..."

if [ ! -f .env ]; then
    cp .env.example .env
    echo -e "   ${GREEN}✅ 已创建 .env 文件（从 .env.example 复制）${NC}"
else
    echo -e "   ${YELLOW}⏭️  .env 已存在，跳过${NC}"
fi

# ---- Step 4: 检查 API 密钥 ----
echo ""
echo -e "${BOLD}[4/5]${NC} 检查 API 密钥配置..."

HAS_AI_KEY=false
HAS_DATA_KEY=false

# 检查 AI 模型密钥
for var in ANTHROPIC_API_KEY OPENAI_API_KEY DEEPSEEK_API_KEY; do
    val=$(grep -E "^${var}=" .env 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d "'" || true)
    if [ -n "$val" ] && [ "$val" != "your-api-key" ] && [ "$val" != "sk-your-api-key" ] && [ "$val" != "" ]; then
        HAS_AI_KEY=true
        echo -e "   ${GREEN}✅ ${var} 已配置${NC}"
        break
    fi
done

# 检查数据源密钥
for var in MX_APIKEY GS_API_KEY HT_APIKEY; do
    val=$(grep -E "^${var}=" .env 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d "'" || true)
    if [ -n "$val" ] && [ "$val" != "your-api-key" ] && [ "$val" != "" ]; then
        HAS_DATA_KEY=true
        echo -e "   ${GREEN}✅ ${var} 已配置${NC}"
        break
    fi
done

if [ "$HAS_AI_KEY" = false ]; then
    echo -e "   ${YELLOW}⚠️  未检测到 AI 模型密钥（ANTHROPIC_API_KEY / OPENAI_API_KEY）${NC}"
    echo -e "   ${YELLOW}   LLM 分析功能将不可用。编辑 .env 文件配置密钥。${NC}"
fi

if [ "$HAS_DATA_KEY" = false ]; then
    echo -e "   ${CYAN}ℹ️  未检测到付费数据源密钥，将使用免费数据源（mootdx + 腾讯 + AKShare）${NC}"
fi

# ---- Step 5: 连接测试 ----
echo ""
echo -e "${BOLD}[5/5]${NC} 运行连接测试..."

python3 -c "
try:
    import akshare as ak
    df = ak.stock_zh_a_spot_em()
    print(f'   ✅ 数据连接正常（A 股 {len(df)} 只标的可访问）')
except Exception as e:
    print(f'   ⚠️  数据连接测试失败: {e}')
    print('   免费数据源可能暂时不可用，稍后重试')
" 2>&1

# ---- 完成 ----
echo ""
echo -e "${GREEN}${BOLD}=============================================${NC}"
echo -e "${GREEN}${BOLD}  🎉 安装完成！${NC}"
echo -e "${GREEN}${BOLD}=============================================${NC}"
echo ""
echo -e "  快速体验:"
echo -e "    ${CYAN}python -m src diagnose 600519${NC}     # 分析贵州茅台"
echo -e "    ${CYAN}python -m src macro${NC}                 # 宏观快照"
echo -e "    ${CYAN}python -m src sentiment${NC}             # 情绪检测"
echo ""
echo -e "  更多命令:"
echo -e "    ${CYAN}python -m src${NC}                        # 查看所有命令"
echo ""

if [ "$HAS_AI_KEY" = false ]; then
    echo -e "  ${YELLOW}💡 提示: 编辑 .env 文件配置 AI 密钥以启用完整分析功能${NC}"
    echo -e "  ${YELLOW}   详见 SECRET.md 获取注册指引${NC}"
    echo ""
fi
