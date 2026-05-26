# 法学每日研习系统 — Claude Code 项目手册

## 项目用途

每天北京时间 08:00 自动向指定邮箱发送 2 个深度法学概念学习材料（寓言 + 解析 + 思考题，中英双语）。
由 GitHub Actions + Claude API 驱动，无需服务器。

---

## 文件结构

```
legal-daily/
├── CLAUDE.md                          ← 你正在读的这个文件
├── README.md                          ← 用户指南
├── requirements.txt                   ← Python 依赖
├── setup.sh                           ← 一键部署脚本（gh CLI）
├── .github/workflows/daily.yml        ← GitHub Actions 工作流
├── scripts/
│   ├── daily_generate.py              ← 云端主程序（Actions 每日调用）
│   └── extract_concepts.py            ← 本地 PDF 提取脚本（运行一次）
├── concepts/
│   ├── jurisprudence.json             ← 法理学概念库（48 个种子）
│   ├── international_public.json      ← 国际公法概念库（44 个种子）
│   ├── international_private.json     ← 国际私法概念库（28 个种子）
│   └── international_economic.json    ← 国际经济法概念库（28 个种子）
└── progress/
    └── progress.json                  ← 进度追踪（Actions 自动更新）
```

---

## 阶段规划

| 阶段 | 学科 | 每日推送 | 种子天数 |
|------|------|---------|---------|
| Phase 1 | 法理学 + 国际公法 | 各 1 个 | ~92 天 |
| Phase 2 | 国际私法 + 国际经济法 | 各 1 个 | ~56 天 |

Phase 1 全部用完后自动切入 Phase 2，全部完成后重启循环。

---

## 常用任务（Claude Code 直接执行）

### 一键部署到 GitHub

```bash
bash setup.sh
```

脚本会交互式引导：创建仓库 → 配置 4 个 Secrets → push → 触发首次测试。

### 手动触发今日推送

```bash
gh workflow run daily.yml --repo $(gh repo view --json nameWithOwner -q .nameWithOwner)
```

### 从 PDF 提取概念（本地运行，3GB 大文件）

```bash
# 安装依赖
pip install pdfplumber anthropic

# 按学科提取（--merge 追加，不覆盖已有概念）
export ANTHROPIC_API_KEY="sk-ant-..."
python scripts/extract_concepts.py --pdf-dir /path/to/pdfs --subject jurisprudence --merge
python scripts/extract_concepts.py --pdf-dir /path/to/pdfs --subject international_public --merge
python scripts/extract_concepts.py --pdf-dir /path/to/pdfs --subject international_private --merge
python scripts/extract_concepts.py --pdf-dir /path/to/pdfs --subject international_economic --merge

# 提取完成后 push 更新的 JSON
git add concepts/*.json && git commit -m "chore: enrich concepts from PDF" && git push
```

### 查看进度

```bash
cat progress/progress.json | python3 -m json.tool
```

### 查看已用概念数量

```bash
python3 -c "
import json
from pathlib import Path
for f in sorted(Path('concepts').glob('*.json')):
    d = json.loads(f.read_text())
    used = sum(1 for c in d['concepts'] if c.get('used'))
    total = len(d['concepts'])
    print(f\"{d['subject_zh']:10s} {used}/{total} 已用\")
"
```

### 检查 Actions 运行状态

```bash
gh run list --limit 10
gh run view   # 查看最近一次的日志
```

### 重置进度（重新从头开始）

```bash
python3 -c "
import json
p = json.load(open('progress/progress.json'))
p['used_concept_ids'] = []
p['total_concepts_sent'] = 0
p['current_phase'] = 1
p['phases_completed'] = []
json.dump(p, open('progress/progress.json','w'), ensure_ascii=False, indent=2)
print('Progress reset.')
"
git add progress/progress.json && git commit -m "chore: reset progress" && git push
```

---

## 所需环境变量 / Secrets

| 名称 | 用途 |
|------|------|
| `ANTHROPIC_API_KEY` | 内容生成（Claude Sonnet） |
| `GMAIL_USER` | 发件 Gmail 地址 |
| `GMAIL_APP_PASSWORD` | Gmail 应用专用密码（需开两步验证） |
| `RECIPIENT_EMAIL` | 收件邮箱 |

---

## 注意事项

- `progress/progress.json` 由 Actions 自动 commit 回仓库，**不要手动冲突**
- `concepts/*.json` 在提取后 push 一次即可，Actions 只读不写概念文件
- `daily_generate.py` 使用 `claude-sonnet-4-20250514`，每日约消耗 ~4k tokens × 2 概念
- GitHub Actions 免费账户每月有 2000 分钟，本项目每次约 2–3 分钟，**免费额度足够**
