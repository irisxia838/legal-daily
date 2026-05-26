#!/usr/bin/env python3
"""
每日法学内容生成与发邮件脚本
Daily Legal Studies Generator — runs on GitHub Actions at 08:00 Beijing Time
"""

import os
import json
import smtplib
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Dict, Optional, Tuple
from groq import Groq

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ── Timezone ───────────────────────────────────────────────
BEIJING_TZ = timezone(timedelta(hours=8))

# ── Paths ──────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
CONCEPTS_DIR = ROOT / "concepts"
PROGRESS_FILE = ROOT / "progress" / "progress.json"

# ── Phase Config ───────────────────────────────────────────
PHASES = {
    1: {
        "name_zh": "第一阶段",
        "description": "法理学 · 国际公法",
        "subjects": ["jurisprudence", "international_public"],
    },
    2: {
        "name_zh": "第二阶段",
        "description": "国际私法 · 国际经济法",
        "subjects": ["international_private", "international_economic"],
    },
}

SUBJECT_META = {
    "jurisprudence":         {"name_zh": "法理学",     "name_en": "Jurisprudence",              "emoji": "⚖️"},
    "international_public":  {"name_zh": "国际公法",   "name_en": "Public International Law",   "emoji": "🌐"},
    "international_private": {"name_zh": "国际私法",   "name_en": "Private International Law",  "emoji": "🤝"},
    "international_economic":{"name_zh": "国际经济法", "name_en": "International Economic Law", "emoji": "📈"},
}

SUBJECT_COLORS = {
    "jurisprudence":          {"hdr": "#1e3a5f", "accent": "#3b82f6", "light": "#eff6ff", "border": "#93c5fd", "badge": "#dbeafe", "badge_text": "#1e40af"},
    "international_public":   {"hdr": "#14532d", "accent": "#16a34a", "light": "#f0fdf4", "border": "#86efac", "badge": "#dcfce7", "badge_text": "#166534"},
    "international_private":  {"hdr": "#7c2d12", "accent": "#ea580c", "light": "#fff7ed", "border": "#fdba74", "badge": "#ffedd5", "badge_text": "#9a3412"},
    "international_economic": {"hdr": "#4a1d96", "accent": "#7c3aed", "light": "#f5f3ff", "border": "#c4b5fd", "badge": "#ede9fe", "badge_text": "#5b21b6"},
}

WEEKDAYS_ZH = ["星期一","星期二","星期三","星期四","星期五","星期六","星期日"]

# ══════════════════════════════════════════════════════════
# 1. Progress
# ══════════════════════════════════════════════════════════

def load_progress() -> Dict:
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
    progress = {
        "schema_version": "1.0",
        "created_date": datetime.now(BEIJING_TZ).strftime("%Y-%m-%d"),
        "last_run_date": None,
        "total_concepts_sent": 0,
        "current_phase": 1,
        "phases_completed": [],
        "used_concept_ids": [],
    }
    save_progress(progress)
    return progress

def save_progress(p: Dict):
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_FILE.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")

# ══════════════════════════════════════════════════════════
# 2. Concept Selection
# ══════════════════════════════════════════════════════════

def load_concepts(subject: str) -> Optional[Dict]:
    f = CONCEPTS_DIR / f"{subject}.json"
    if not f.exists():
        logger.warning(f"Concepts file missing: {f}")
        return None
    return json.loads(f.read_text(encoding="utf-8"))

def save_concepts(data: Dict, subject: str):
    f = CONCEPTS_DIR / f"{subject}.json"
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def select_concept(subject: str, used_ids: List[str]) -> Optional[Tuple[Dict, Dict]]:
    data = load_concepts(subject)
    if not data:
        return None
    order = {"foundational": 0, "intermediate": 1, "advanced": 2}
    unused = sorted(
        [c for c in data["concepts"] if c["id"] not in used_ids],
        key=lambda c: order.get(c.get("difficulty", "intermediate"), 1)
    )
    return (unused[0], data) if unused else None

def mark_used(concept_id: str, concepts_data: Dict, subject: str, date: str):
    for c in concepts_data["concepts"]:
        if c["id"] == concept_id:
            c["used"] = True
            c["used_date"] = date
    save_concepts(concepts_data, subject)

def advance_phase_if_needed(progress: Dict) -> Dict:
    phase = progress.get("current_phase", 1)
    if phase > len(PHASES):
        logger.info("All phases done — restarting from Phase 1")
        progress["current_phase"] = 1
        progress["used_concept_ids"] = []
        return progress
    used = progress.get("used_concept_ids", [])
    all_done = all(
        not [c for c in (load_concepts(s) or {}).get("concepts", []) if c["id"] not in used]
        for s in PHASES[phase]["subjects"]
    )
    if all_done:
        logger.info(f"Phase {phase} complete → advancing to Phase {phase+1}")
        progress.setdefault("phases_completed", []).append(phase)
        progress["current_phase"] = phase + 1
    return progress

# ══════════════════════════════════════════════════════════
# 3. Claude Content Generation
# ══════════════════════════════════════════════════════════

SYSTEM_PROMPT = """你是一位精通法学与文学的双栖学者，专门为研究生设计法学概念的寓言教学内容。
你的寓言风格：现代、机智、隐喻精准，让读者在结尾恍然大悟——原来这是在讲某个抽象法学概念。
你的输出必须严格按照JSON格式，不得添加任何说明或代码块标记。"""

def generate_content(concept: Dict, subject: str) -> Optional[Dict]:
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    meta = SUBJECT_META[subject]
    thinkers = "、".join(concept.get("key_thinkers", [])) or "多位法学家"

    prompt = f"""请为以下{meta['name_zh']}概念创作完整学习材料，严格以JSON格式输出（不含代码块标记）：

概念信息
- 中文名：{concept['name_zh']}
- 英文名：{concept['name_en']}
- 中文定义：{concept.get('brief_definition_zh', '')}
- 英文定义：{concept.get('brief_definition_en', '')}
- 关键学者：{thinkers}
- 学科：{meta['name_zh']}（{meta['name_en']}）

输出JSON结构（严格遵守，所有字段必须存在）：
{{
  "fable": {{
    "title_zh": "寓言标题（现代风、不含法律词汇）",
    "title_en": "Fable Title",
    "body_zh": "寓言正文（700-950字，现代白话，绝不出现任何法律术语，场景可以是职场/家庭/社区/网络，故事完整有张力，结尾令人豁然开朗）",
    "reveal_zh": "揭示段落（3-4句话：先点破这个故事对应的法学概念，再精炼说明该概念的核心洞见，最后一句英文点题）"
  }},
  "analysis": {{
    "zh": "概念深度解析（450-550字，研究生水平：①历史渊源与思想背景 ②核心主张与理论结构 ③主要争议与批判 ④当代法学意义）",
    "en": "Graduate-level analysis in English (220-280 words covering: intellectual origins, core thesis, key debates, contemporary significance)"
  }},
  "metaphor_table": [
    {{"story_element": "故事中的具体元素", "legal_concept": "对应法学概念（含英文）", "explanation": "对应逻辑说明（20字内）"}}
  ],
  "questions": {{
    "q1": {{
      "type": "核心理解题 · Core Comprehension",
      "zh": "检验对{concept['name_zh']}核心主张的理解（不是简单复述定义，要有辨析深度）",
      "en": "English version of Q1"
    }},
    "q2": {{
      "type": "概念迁延题 · Conceptual Extension",
      "zh": "将{concept['name_zh']}迁移到新情境或与其他理论对话（如：与XX理论的张力、在XX领域的应用）",
      "en": "English version of Q2"
    }}
  }}
}}

关键约束：
1. 寓言正文中绝对不出现：法律、法规、条约、主权、权利、义务、法院、仲裁、法官、律师、诉讼等任何法律术语
2. 隐喻对照表必须至少6行，每行covering不同层面
3. 概念解析须体现该概念在法学史上的位置，不是百科词条
4. 思考题须有挑战性，引导批判性思维"""

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": prompt},
            ],
            max_tokens=4096,
            temperature=0.9,
        )
        raw = response.choices[0].message.content.strip()
        # Strip code fences if present
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.rsplit("```", 1)[0].strip()
        content = json.loads(raw)
        content["concept"] = concept
        content["subject"] = subject
        return content
    except Exception as e:
        logger.error(f"Generation failed for {concept['name_zh']}: {e}")
        return None

# ══════════════════════════════════════════════════════════
# 4. HTML Email Builder
# ══════════════════════════════════════════════════════════

def _metaphor_rows(rows: List[Dict], colors: Dict) -> str:
    html = ""
    for i, r in enumerate(rows):
        bg = "#f9fafb" if i % 2 else "#ffffff"
        html += f"""<tr style="background:{bg};">
          <td style="padding:10px 14px;border-bottom:1px solid #f0f0f0;color:#374151;font-weight:600;font-size:13px;">{r.get('story_element','')}</td>
          <td style="padding:10px 14px;border-bottom:1px solid #f0f0f0;color:{colors['accent']};font-weight:700;font-size:13px;">{r.get('legal_concept','')}</td>
          <td style="padding:10px 14px;border-bottom:1px solid #f0f0f0;color:#6b7280;font-size:12px;line-height:1.5;">{r.get('explanation','')}</td>
        </tr>"""
    return html

def render_concept_card(content: Dict, idx: int) -> str:
    subject  = content["subject"]
    concept  = content["concept"]
    fable    = content["fable"]
    analysis = content["analysis"]
    table    = content.get("metaphor_table", [])
    qs       = content["questions"]
    c        = SUBJECT_COLORS[subject]
    meta     = SUBJECT_META[subject]

    tag = f"{meta['emoji']} {meta['name_zh']} · {meta['name_en']}"
    body_paragraphs = "".join(
        f'<p style="margin:0 0 14px 0;">{p.strip()}</p>'
        for p in fable.get("body_zh","").split("\n") if p.strip()
    )

    return f"""
<div style="margin:0 0 36px;border-radius:18px;overflow:hidden;box-shadow:0 6px 24px rgba(0,0,0,0.09);background:#fff;">

  <!-- ① Subject Header -->
  <div style="background:{c['hdr']};padding:14px 26px;">
    <span style="background:rgba(255,255,255,0.16);color:#fff;font-size:13px;font-weight:600;padding:5px 14px;border-radius:20px;letter-spacing:0.5px;">{tag}</span>
  </div>

  <!-- ② Concept Title -->
  <div style="padding:24px 28px 18px;border-bottom:2px solid {c['light']};">
    <div style="font-size:28px;font-weight:800;color:#111827;line-height:1.25;letter-spacing:-0.5px;">{concept.get('name_zh','')}</div>
    <div style="font-size:15px;color:#9ca3af;font-style:italic;margin:4px 0 14px;">{concept.get('name_en','')}</div>
    <div style="padding:10px 14px;background:{c['light']};border-left:3px solid {c['accent']};border-radius:0 8px 8px 0;font-size:14px;color:#374151;line-height:1.65;">
      {concept.get('brief_definition_zh','')}
    </div>
    <div style="margin-top:8px;padding:8px 12px;background:#f9fafb;border-radius:6px;font-size:12px;color:#9ca3af;font-style:italic;line-height:1.5;">
      {concept.get('brief_definition_en','')}
    </div>
  </div>

  <!-- ③ Fable -->
  <div style="padding:26px 28px;border-bottom:1px solid #f3f4f6;">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:16px;">
      <span style="font-size:20px;">📖</span>
      <span style="font-size:16px;font-weight:700;color:#111827;">今日寓言</span>
      <span style="font-size:13px;color:#9ca3af;">· Today's Fable</span>
    </div>
    <div style="padding:12px 16px;background:{c['light']};border-radius:8px;margin-bottom:18px;">
      <span style="font-size:16px;font-weight:700;color:#111827;">《{fable.get('title_zh','')}》</span>
      <span style="font-size:14px;color:#6b7280;font-style:italic;margin-left:8px;">{fable.get('title_en','')}</span>
    </div>
    <div style="font-size:15px;color:#1f2937;line-height:1.95;">{body_paragraphs}</div>
    <div style="margin-top:20px;padding:16px 20px;background:linear-gradient(135deg,{c['light']},{c['badge']});border:1.5px solid {c['border']};border-radius:12px;">
      <span style="font-size:17px;vertical-align:middle;margin-right:6px;">✨</span>
      <span style="color:{c['badge_text']};font-size:14px;font-weight:600;line-height:1.75;">{fable.get('reveal_zh','')}</span>
    </div>
  </div>

  <!-- ④ Analysis -->
  <div style="padding:26px 28px;border-bottom:1px solid #f3f4f6;">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:16px;">
      <span style="font-size:20px;">🔍</span>
      <span style="font-size:16px;font-weight:700;color:#111827;">概念解析</span>
      <span style="font-size:13px;color:#9ca3af;">· Concept Analysis</span>
    </div>
    <div style="font-size:14px;color:#374151;line-height:1.9;margin-bottom:16px;">{analysis.get('zh','')}</div>
    <div style="padding:14px 16px;background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;">
      <div style="font-size:11px;color:{c['accent']};font-weight:700;letter-spacing:1.5px;margin-bottom:8px;">ENGLISH ANALYSIS</div>
      <div style="font-size:13px;color:#6b7280;line-height:1.75;font-style:italic;">{analysis.get('en','')}</div>
    </div>
  </div>

  <!-- ⑤ Metaphor Table -->
  <div style="padding:26px 28px;border-bottom:1px solid #f3f4f6;">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:16px;">
      <span style="font-size:20px;">🗺️</span>
      <span style="font-size:16px;font-weight:700;color:#111827;">故事隐喻对照表</span>
      <span style="font-size:13px;color:#9ca3af;">· Metaphor Mapping</span>
    </div>
    <div style="overflow-x:auto;border-radius:10px;border:1px solid #e5e7eb;">
      <table style="width:100%;border-collapse:collapse;font-size:13px;min-width:480px;">
        <thead>
          <tr style="background:{c['hdr']};">
            <th style="padding:11px 14px;text-align:left;color:#fff;font-weight:600;font-size:12px;white-space:nowrap;">故事元素</th>
            <th style="padding:11px 14px;text-align:left;color:#fff;font-weight:600;font-size:12px;white-space:nowrap;">法学对应</th>
            <th style="padding:11px 14px;text-align:left;color:#fff;font-weight:600;font-size:12px;">说明</th>
          </tr>
        </thead>
        <tbody>{_metaphor_rows(table, c)}</tbody>
      </table>
    </div>
  </div>

  <!-- ⑥ Questions -->
  <div style="padding:26px 28px;">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:16px;">
      <span style="font-size:20px;">💭</span>
      <span style="font-size:16px;font-weight:700;color:#111827;">思考题</span>
      <span style="font-size:13px;color:#9ca3af;">· Discussion Questions</span>
    </div>
    <div style="margin-bottom:14px;padding:16px 20px;background:#f9fafb;border-radius:12px;border-left:4px solid {c['accent']};">
      <div style="font-size:11px;color:{c['accent']};font-weight:700;letter-spacing:1px;margin-bottom:8px;">Q1 · {qs['q1'].get('type','')}</div>
      <div style="font-size:14px;color:#111827;font-weight:600;line-height:1.7;margin-bottom:6px;">{qs['q1'].get('zh','')}</div>
      <div style="font-size:12px;color:#9ca3af;line-height:1.6;font-style:italic;">{qs['q1'].get('en','')}</div>
    </div>
    <div style="padding:16px 20px;background:#f9fafb;border-radius:12px;border-left:4px solid {c['border']};">
      <div style="font-size:11px;color:#9ca3af;font-weight:700;letter-spacing:1px;margin-bottom:8px;">Q2 · {qs['q2'].get('type','')}</div>
      <div style="font-size:14px;color:#111827;font-weight:600;line-height:1.7;margin-bottom:6px;">{qs['q2'].get('zh','')}</div>
      <div style="font-size:12px;color:#9ca3af;line-height:1.6;font-style:italic;">{qs['q2'].get('en','')}</div>
    </div>
  </div>

</div>"""

def build_email_html(contents: List[Dict], progress: Dict, today_zh: str, weekday: str) -> str:
    total   = progress.get("total_concepts_sent", 0) + len(contents)
    phase   = progress.get("current_phase", 1)
    p_info  = PHASES.get(phase, PHASES[1])
    cards   = "".join(render_concept_card(c, i+1) for i, c in enumerate(contents))

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>法学每日研习 · {today_zh}</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0;}}
  body{{font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Hiragino Sans GB','Microsoft YaHei','Helvetica Neue',Arial,sans-serif;background:#e8edf5;}}
  @media(max-width:600px){{
    .outer-pad{{padding:12px 8px!important;}}
    .header-box{{border-radius:14px!important;padding:28px 20px!important;}}
    .stat-row{{gap:10px!important;}}
    .stat-box{{padding:10px 14px!important;min-width:80px!important;}}
  }}
</style>
</head>
<body style="background:#e8edf5;padding:24px 0;">
<div class="outer-pad" style="max-width:660px;margin:0 auto;padding:0 16px;">

  <!-- Header -->
  <div class="header-box" style="background:linear-gradient(140deg,#0c1e38 0%,#1a3a5f 55%,#0e2240 100%);border-radius:20px;padding:36px 32px;margin-bottom:28px;text-align:center;">
    <div style="font-size:40px;margin-bottom:10px;">⚖️</div>
    <div style="font-size:28px;font-weight:800;color:#fff;letter-spacing:1px;margin-bottom:4px;">法学每日研习</div>
    <div style="font-size:12px;color:#94a3b8;letter-spacing:3px;margin-bottom:22px;">DAILY LEGAL STUDIES</div>
    <div style="display:inline-block;background:rgba(255,255,255,0.1);border:1px solid rgba(255,255,255,0.2);border-radius:30px;padding:8px 22px;margin-bottom:24px;">
      <span style="color:#e2e8f0;font-size:14px;">{today_zh} &nbsp;{weekday}</span>
    </div>
    <div class="stat-row" style="display:flex;justify-content:center;gap:14px;flex-wrap:wrap;">
      <div class="stat-box" style="background:rgba(255,255,255,0.09);border:1px solid rgba(255,255,255,0.12);border-radius:12px;padding:12px 22px;min-width:90px;text-align:center;">
        <div style="color:#94a3b8;font-size:10px;letter-spacing:1.5px;margin-bottom:3px;">TODAY</div>
        <div style="color:#fff;font-size:26px;font-weight:800;">{len(contents)}</div>
        <div style="color:#94a3b8;font-size:11px;">概念</div>
      </div>
      <div class="stat-box" style="background:rgba(255,255,255,0.09);border:1px solid rgba(255,255,255,0.12);border-radius:12px;padding:12px 22px;min-width:90px;text-align:center;">
        <div style="color:#94a3b8;font-size:10px;letter-spacing:1.5px;margin-bottom:3px;">TOTAL</div>
        <div style="color:#fff;font-size:26px;font-weight:800;">{total}</div>
        <div style="color:#94a3b8;font-size:11px;">已学习</div>
      </div>
      <div class="stat-box" style="background:rgba(255,255,255,0.09);border:1px solid rgba(255,255,255,0.12);border-radius:12px;padding:12px 22px;min-width:90px;text-align:center;">
        <div style="color:#94a3b8;font-size:10px;letter-spacing:1.5px;margin-bottom:3px;">PHASE</div>
        <div style="color:#fff;font-size:26px;font-weight:800;">{phase}</div>
        <div style="color:#94a3b8;font-size:10px;">{p_info['description']}</div>
      </div>
    </div>
  </div>

  <!-- Concept Cards -->
  {cards}

  <!-- Footer -->
  <div style="text-align:center;padding:20px 12px 32px;color:#94a3b8;font-size:13px;">
    <div style="margin-bottom:6px;">📚 法学研究生概念每日研习</div>
    <div style="font-size:12px;margin-bottom:14px;">{p_info['name_zh']} · {p_info['description']}</div>
    <div style="width:48px;height:2px;background:linear-gradient(90deg,#3b82f6,#16a34a,#ea580c);border-radius:2px;margin:0 auto 14px;"></div>
    <div style="font-size:11px;color:#cbd5e1;line-height:1.7;">由 GitHub Actions 每天 08:00（北京时间）自动生成发送</div>
  </div>

</div>
</body>
</html>"""

# ══════════════════════════════════════════════════════════
# 5. Email Sending
# ══════════════════════════════════════════════════════════

def send_email(html: str, subject_line: str) -> bool:
    user      = os.environ.get("GMAIL_USER", "")
    password  = os.environ.get("GMAIL_APP_PASSWORD", "")
    recipient = os.environ.get("RECIPIENT_EMAIL", "")

    if not all([user, password, recipient]):
        logger.error("Missing Gmail env vars (GMAIL_USER / GMAIL_APP_PASSWORD / RECIPIENT_EMAIL)")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject_line
    msg["From"]    = f"法学研习系统 <{user}>"
    msg["To"]      = recipient
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
            srv.login(user, password)
            srv.sendmail(user, recipient, msg.as_bytes())
        logger.info(f"✅ Email sent → {recipient}")
        return True
    except Exception as e:
        logger.error(f"❌ SMTP error: {e}")
        return False

# ══════════════════════════════════════════════════════════
# 6. Main
# ══════════════════════════════════════════════════════════

def main():
    logger.info("=" * 55)
    logger.info("Daily Legal Studies Generator")
    logger.info("=" * 55)

    now      = datetime.now(BEIJING_TZ)
    today_zh = now.strftime("%Y年%m月%d日")
    today_iso= now.strftime("%Y-%m-%d")
    weekday  = WEEKDAYS_ZH[now.weekday()]
    logger.info(f"Date: {today_zh} {weekday}")

    progress = load_progress()
    progress = advance_phase_if_needed(progress)
    save_progress(progress)

    phase   = progress.get("current_phase", 1)
    if phase > len(PHASES):
        logger.warning("All phases completed. Nothing to send today.")
        return

    subjects = PHASES[phase]["subjects"]
    used_ids = progress.get("used_concept_ids", [])
    logger.info(f"Phase {phase}: {PHASES[phase]['description']}")

    # Select one concept per subject
    chosen: List[Tuple[str, Dict, Dict]] = []
    for subj in subjects:
        result = select_concept(subj, used_ids)
        if result:
            concept, cdata = result
            chosen.append((subj, concept, cdata))
            logger.info(f"  [{SUBJECT_META[subj]['name_zh']}] {concept['name_zh']} / {concept['name_en']}")
        else:
            logger.warning(f"  No unused concepts left for {subj}")

    if not chosen:
        logger.error("Nothing to generate. Exiting.")
        return

    # Generate content
    contents: List[Dict] = []
    for subj, concept, cdata in chosen:
        logger.info(f"Generating content for: {concept['name_zh']} ...")
        result = generate_content(concept, subj)
        if result:
            contents.append(result)
            logger.info("  ✅ OK")
        else:
            logger.error(f"  ❌ Failed")

    if not contents:
        logger.error("All generation failed. Exiting.")
        return

    # Build & send email
    html = build_email_html(contents, progress, today_zh, weekday)
    subject_line = f"⚖️ 法学每日研习 · {today_zh}"
    success = send_email(html, subject_line)

    if success:
        new_ids = [c["concept"]["id"] for c in contents]
        progress["used_concept_ids"] = used_ids + new_ids
        progress["total_concepts_sent"] = progress.get("total_concepts_sent", 0) + len(contents)
        progress["last_run_date"] = today_iso

        for subj, concept, cdata in chosen:
            if concept["id"] in new_ids:
                mark_used(concept["id"], cdata, subj, today_iso)

        save_progress(progress)
        logger.info("Progress saved.")

    logger.info("=" * 55)
    logger.info(f"Done — sent {len(contents)} concepts. Total: {progress.get('total_concepts_sent', 0)}")
    logger.info("=" * 55)

if __name__ == "__main__":
    main()
