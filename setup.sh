#!/usr/bin/env bash
# ============================================================
# 法学每日研习系统 — 一键部署脚本
# 依赖：git、gh（GitHub CLI）、python3
# 运行：bash setup.sh
# ============================================================
set -euo pipefail

# ── 颜色输出 ────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${BLUE}[•]${NC} $*"; }
success() { echo -e "${GREEN}[✓]${NC} $*"; }
warn()    { echo -e "${YELLOW}[!]${NC} $*"; }
error()   { echo -e "${RED}[✗]${NC} $*"; exit 1; }
prompt()  { echo -e "${CYAN}[?]${NC} $*"; }
header()  { echo -e "\n${BOLD}${BLUE}══ $* ══${NC}\n"; }

# ── 前置检查 ─────────────────────────────────────────────────
header "前置检查"

command -v git  >/dev/null 2>&1 || error "未找到 git，请先安装"
command -v gh   >/dev/null 2>&1 || error "未找到 gh（GitHub CLI），安装：https://cli.github.com"
command -v python3 >/dev/null 2>&1 || error "未找到 python3"

# 检查 gh 登录状态
if ! gh auth status >/dev/null 2>&1; then
    warn "尚未登录 GitHub CLI，正在引导登录..."
    gh auth login
fi

success "依赖检查通过"
GH_USER=$(gh api user --jq .login)
info "当前 GitHub 账号：${BOLD}${GH_USER}${NC}"

# ── 仓库名称 ─────────────────────────────────────────────────
header "GitHub 仓库配置"

DEFAULT_REPO="legal-daily"
prompt "仓库名称 [默认: ${DEFAULT_REPO}]："
read -r REPO_NAME
REPO_NAME="${REPO_NAME:-$DEFAULT_REPO}"

prompt "仓库可见性：(1) Private [推荐]  (2) Public [1/2，默认1]："
read -r VISIBILITY_CHOICE
if [[ "${VISIBILITY_CHOICE}" == "2" ]]; then
    VISIBILITY="--public"
    VISIBILITY_LABEL="Public"
else
    VISIBILITY="--private"
    VISIBILITY_LABEL="Private（推荐）"
fi

info "将创建仓库：${BOLD}${GH_USER}/${REPO_NAME}${NC}（${VISIBILITY_LABEL}）"

# ── Git 初始化 ───────────────────────────────────────────────
header "初始化 Git 仓库"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

if [ ! -d ".git" ]; then
    git init
    git branch -M main
    success "git init 完成"
else
    info "已是 Git 仓库，跳过 init"
fi

# ── 创建 GitHub 仓库 ─────────────────────────────────────────
header "创建 GitHub 仓库"

REPO_FULL="${GH_USER}/${REPO_NAME}"

if gh repo view "${REPO_FULL}" >/dev/null 2>&1; then
    warn "仓库 ${REPO_FULL} 已存在，跳过创建"
else
    gh repo create "${REPO_NAME}" ${VISIBILITY} --description "⚖️ 法学每日研习自动推送系统"
    success "仓库创建成功：https://github.com/${REPO_FULL}"
fi

# 设置远程
REMOTE_URL="https://github.com/${REPO_FULL}.git"
if git remote get-url origin >/dev/null 2>&1; then
    git remote set-url origin "${REMOTE_URL}"
    info "已更新 remote origin → ${REMOTE_URL}"
else
    git remote add origin "${REMOTE_URL}"
    info "已添加 remote origin → ${REMOTE_URL}"
fi

# ── 配置 GitHub Secrets ──────────────────────────────────────
header "配置 GitHub Secrets"
echo -e "需要设置 4 个 Secrets，Actions 每天运行时使用。\n"

set_secret() {
    local NAME="$1"
    local HINT="$2"
    local IS_SENSITIVE="${3:-true}"

    while true; do
        prompt "${NAME}"
        echo -e "  ${YELLOW}说明：${NC}${HINT}"
        if [[ "${IS_SENSITIVE}" == "true" ]]; then
            read -rs VALUE
            echo ""  # 换行（因为 -s 不回显）
        else
            read -r VALUE
        fi
        if [[ -n "${VALUE}" ]]; then
            echo "${VALUE}" | gh secret set "${NAME}" --repo "${REPO_FULL}"
            success "${NAME} 已设置"
            break
        else
            warn "不能为空，请重新输入"
        fi
    done
}

echo ""
set_secret "ANTHROPIC_API_KEY" \
    "Anthropic API 密钥（以 sk-ant- 开头）\n  获取：https://console.anthropic.com/settings/keys"

echo ""
set_secret "GMAIL_USER" \
    "发件 Gmail 地址（例：yourname@gmail.com）" false

echo ""
echo -e "  ${YELLOW}提示：${NC}Gmail 应用专用密码获取方式："
echo    "  1. 登录 Gmail → 账户设置 → 安全性"
echo    "  2. 开启两步验证（必须）"
echo    "  3. 搜索"应用专用密码" → 选择"邮件" → 生成"
echo    "  4. 复制 16 位密码（含空格也可以）"
set_secret "GMAIL_APP_PASSWORD" \
    "Gmail 16 位应用专用密码（不是账户登录密码）"

echo ""
set_secret "RECIPIENT_EMAIL" \
    "收件邮箱（可以是同一个 Gmail）" false

success "全部 4 个 Secrets 已配置完毕"

# ── 首次 Push ────────────────────────────────────────────────
header "推送代码到 GitHub"

git add -A
git diff --cached --quiet || git commit -m "🎉 Initial commit — 法学每日研习系统"

git push -u origin main
success "代码已推送到 https://github.com/${REPO_FULL}"

# ── 触发首次测试 ─────────────────────────────────────────────
header "触发首次测试"

echo ""
prompt "是否立即触发一次邮件发送测试？（推荐，约 1-2 分钟）[Y/n]："
read -r TRIGGER_NOW
if [[ "${TRIGGER_NOW,,}" != "n" ]]; then
    gh workflow run daily.yml --repo "${REPO_FULL}"
    echo ""
    success "已触发 workflow！"
    info "约 1-2 分钟后检查邮箱，也可在此查看进度："
    echo -e "  ${CYAN}https://github.com/${REPO_FULL}/actions${NC}"
    echo ""
    info "正在等待 workflow 启动（10秒）..."
    sleep 10
    gh run list --repo "${REPO_FULL}" --limit 3
else
    info "已跳过。之后可手动触发："
    echo -e "  ${CYAN}gh workflow run daily.yml --repo ${REPO_FULL}${NC}"
fi

# ── 完成 ─────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}${GREEN}  ✅ 部署完成！${NC}"
echo -e "${BOLD}${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  📦 仓库：${CYAN}https://github.com/${REPO_FULL}${NC}"
echo -e "  ⚙️  Actions：${CYAN}https://github.com/${REPO_FULL}/actions${NC}"
echo -e "  🕗  每日自动：北京时间 08:00"
echo ""
echo -e "  ${YELLOW}可选后续步骤（Claude Code 中执行）：${NC}"
echo    "  从你的 3GB PDF 提取更多概念："
echo -e "  ${CYAN}python scripts/extract_concepts.py --pdf-dir /your/pdf/path --subject jurisprudence --merge${NC}"
echo ""
