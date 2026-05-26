# ⚖️ 法学每日研习系统

每天早上 8 点（北京时间）自动发送 2–3 个深度法学概念到你的邮箱。
法理学 + 国际公法 推完后，自动切换为 国际私法 + 国际经济法。

---

## 文件结构

```
legal-daily/
├── .github/workflows/daily.yml       ← GitHub Actions（每日触发）
├── scripts/
│   ├── daily_generate.py             ← 云端主程序（Actions 调用）
│   └── extract_concepts.py           ← 本地一次性运行，从 PDF 提取概念
├── concepts/
│   ├── jurisprudence.json            ← 法理学概念库（含 48 个种子概念）
│   ├── international_public.json     ← 国际公法概念库（含 44 个种子概念）
│   ├── international_private.json    ← 国际私法概念库（含 28 个种子概念）
│   └── international_economic.json   ← 国际经济法概念库（含 28 个种子概念）
├── progress/progress.json            ← 自动更新的进度文件
└── requirements.txt
```

---

## 阶段规划

| 阶段 | 内容 | 每日推送 |
|------|------|---------|
| Phase 1 | 法理学 + 国际公法 | 各 1 个，共 2 个 |
| Phase 2 | 国际私法 + 国际经济法 | 各 1 个，共 2 个 |

种子概念全部用完后自动重启循环。从 PDF 提取后可支撑 1–2 年。

---

## 快速开始（共 6 步）

### 第 0 步：前置准备

- GitHub 账号
- Anthropic API Key（https://console.anthropic.com）
- Gmail 账号 + 应用专用密码（见第 3 步）

---

### 第 1 步：创建 GitHub 仓库并上传文件

```bash
cd legal-daily
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/你的用户名/legal-daily.git
git push -u origin main
```

---

### 第 2 步：配置 GitHub Secrets

在 GitHub 仓库页面：`Settings → Secrets and variables → Actions → New repository secret`

| Secret 名称 | 填写内容 |
|------------|---------|
| `ANTHROPIC_API_KEY` | sk-ant-... |
| `GMAIL_USER` | 你的Gmail地址（如 xxx@gmail.com） |
| `GMAIL_APP_PASSWORD` | Gmail 应用专用密码（见下方说明） |
| `RECIPIENT_EMAIL` | 收件邮箱（可以是同一个 Gmail） |

---

### 第 3 步：获取 Gmail 应用专用密码

1. 登录 Gmail → 右上角头像 → 管理 Google 账户
2. 安全性 → 两步验证（必须先开启）
3. 安全性 → 搜索"应用专用密码" → 创建
4. 选择"邮件" + 设备类型 → 生成 16 位密码
5. 复制这个密码填入 `GMAIL_APP_PASSWORD`

---

### 第 4 步：手动触发测试

仓库页面 → `Actions → Daily Legal Studies → Run workflow → Run workflow`

约 1–2 分钟后检查邮箱。

---

### 第 5 步（可选但推荐）：从你的 PDF 补充概念

本地安装依赖：
```bash
pip install pdfplumber anthropic
```

按学科运行提取：
```bash
export ANTHROPIC_API_KEY="sk-ant-..."

# 法理学 PDF（可多次运行，--merge 会追加而非覆盖）
python scripts/extract_concepts.py \
  --pdf-dir /path/to/jurisprudence/pdfs \
  --subject jurisprudence \
  --merge

# 国际公法 PDF
python scripts/extract_concepts.py \
  --pdf-dir /path/to/intl_public/pdfs \
  --subject international_public \
  --merge

# 国际私法 PDF（阶段二使用）
python scripts/extract_concepts.py \
  --pdf-dir /path/to/intl_private/pdfs \
  --subject international_private \
  --merge

# 国际经济法 PDF（阶段二使用）
python scripts/extract_concepts.py \
  --pdf-dir /path/to/intl_economic/pdfs \
  --subject international_economic \
  --merge
```

提取完后把更新的 JSON 文件 push 到 GitHub 即可。

**如果文件名包含学科关键词**，可用 `--auto` 自动识别：
```bash
python scripts/extract_concepts.py --pdf-dir /path/to/all/pdfs --auto --merge
```

---

### 第 6 步：确认自动运行

Actions 默认每天 UTC 00:00（北京时间 08:00）运行。
第一次 push 后次日早 8 点会自动发送。

---

## 邮件内容结构

每封邮件包含 2 个概念卡片，每卡包含：

```
[学科标签]
概念名（中文 / English）
简短定义

📖 今日寓言
   故事正文（700-950字，无法律术语）
   ✨ 揭示段落

🔍 概念解析
   中文深度解析（研究生水平）
   English Analysis

🗺️ 故事隐喻对照表（≥6行）

💭 思考题
   Q1 核心理解题（中英双语）
   Q2 概念迁延题（中英双语）
```

---

## 调整每日概念数量

在 `scripts/daily_generate.py` 中，当前每学科各选 1 个（= 每日 2 个）。
若要每日 3 个，可在 Phase 1 的某一学科额外多选 1 个：

修改 `daily_generate.py` 中的 `main()` 函数，在选完 2 个后再调用一次
`select_concept("jurisprudence", used_ids)` 并 append 到 `chosen` 列表即可。

---

## 常见问题

**Q: Actions 运行失败怎么排查？**
仓库 → Actions → 点击失败的 Run → 展开日志查看错误。

**Q: 邮件发送失败但内容生成成功？**
检查 GMAIL_APP_PASSWORD 是否正确，Gmail 账户是否开启了两步验证。

**Q: 种子概念 48 个用完后怎么办？**
运行 `extract_concepts.py --merge` 从 PDF 补充，或系统会从头循环。

**Q: 能否同时推送到多个邮箱？**
将 `RECIPIENT_EMAIL` 改为逗号分隔的多个地址，并在 `send_email()` 中拆分处理。
