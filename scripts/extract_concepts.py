#!/usr/bin/env python3
"""
法学 PDF 概念提取脚本（本地运行一次）
Legal PDF Concept Extractor — run locally once, upload results to GitHub

Usage:
    export ANTHROPIC_API_KEY="sk-ant-..."
    python scripts/extract_concepts.py --pdf-dir /path/to/your/pdfs --subject jurisprudence
    python scripts/extract_concepts.py --pdf-dir /path/to/your/pdfs --subject international_public
    python scripts/extract_concepts.py --pdf-dir /path/to/your/pdfs --subject international_private
    python scripts/extract_concepts.py --pdf-dir /path/to/your/pdfs --subject international_economic

    # Or auto-detect subject from filename:
    python scripts/extract_concepts.py --pdf-dir /path/to/your/pdfs --auto

    # Merge newly extracted into an existing JSON (safe to re-run):
    python scripts/extract_concepts.py --pdf-dir /path/to/your/pdfs --subject jurisprudence --merge
"""

import os
import re
import sys
import json
import time
import argparse
from pathlib import Path
from typing import List, Dict, Optional

# ── Try to import pdfplumber; give clear install hint if missing ──
try:
    import pdfplumber
except ImportError:
    sys.exit("❌  Please install pdfplumber first:\n    pip install pdfplumber anthropic")

try:
    import anthropic
except ImportError:
    sys.exit("❌  Please install anthropic first:\n    pip install pdfplumber anthropic")

# ── Config ─────────────────────────────────────────────────

SUBJECTS = {
    "jurisprudence": {
        "name_zh": "法理学", "name_en": "Jurisprudence",
        "id_prefix": "jur",
        "keywords": ["法理", "jurisprudence", "法哲学", "法律理论", "法律思想", "法律哲学"],
    },
    "international_public": {
        "name_zh": "国际公法", "name_en": "Public International Law",
        "id_prefix": "ipl",
        "keywords": ["国际公法", "international law", "公法", "国际习惯", "条约法"],
    },
    "international_private": {
        "name_zh": "国际私法", "name_en": "Private International Law",
        "id_prefix": "ipr",
        "keywords": ["国际私法", "conflict of laws", "冲突法", "private international", "涉外民事"],
    },
    "international_economic": {
        "name_zh": "国际经济法", "name_en": "International Economic Law",
        "id_prefix": "iel",
        "keywords": ["国际经济法", "international economic", "贸易法", "wto", "世贸", "国际商"],
    },
}

CHUNK_CHARS = 3500   # characters per API call
OVERLAP     = 300    # overlap between chunks
API_DELAY   = 0.8    # seconds between API calls

OUTPUT_DIR = Path(__file__).parent.parent / "concepts"

# ── Helpers ────────────────────────────────────────────────

def log(msg: str):
    print(msg, flush=True)

def clean_json_response(text: str) -> str:
    """Strip markdown code fences if Claude wrapped the JSON."""
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        # parts[1] starts with optional 'json\n'
        inner = parts[1] if len(parts) > 1 else text
        inner = re.sub(r'^json\s*', '', inner)
        return inner.strip()
    return text

def auto_detect_subject(filename: str) -> Optional[str]:
    name = filename.lower()
    for subj, info in SUBJECTS.items():
        for kw in info["keywords"]:
            if kw.lower() in name:
                return subj
    return None

def chunk_text(text: str) -> List[str]:
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start:start + CHUNK_CHARS])
        start += CHUNK_CHARS - OVERLAP
    return chunks

# ── PDF Text Extraction ────────────────────────────────────

def extract_pdf_text(path: str) -> str:
    log(f"  📄 Extracting: {Path(path).name}")
    pages, total, text = 0, 0, []
    try:
        with pdfplumber.open(path) as pdf:
            total = len(pdf.pages)
            for i, page in enumerate(pdf.pages):
                t = page.extract_text()
                if t:
                    text.append(t)
                if (i + 1) % 100 == 0:
                    log(f"     Page {i+1}/{total}…")
    except Exception as e:
        log(f"  ⚠️  Error opening {Path(path).name}: {e}")
        return ""
    log(f"     Extracted {total} pages, {sum(len(t) for t in text):,} chars")
    return "\n".join(text)

# ── Concept Extraction via Claude ─────────────────────────

EXTRACT_PROMPT = """你是一位专业法学助手。请从以下{subject_zh}（{subject_en}）教材片段中提取所有重要的核心概念。

提取规则：
1. 只提取该学科的抽象理论概念（不要提取：具体案例、条约名称、国家名、历史事件）
2. 每个概念必须有中英文名称
3. 面向研究生水平，提取对法学理论有实质意义的概念
4. 若文本片段中没有符合条件的概念，返回空数组 []

请严格以JSON数组格式返回（不加任何说明或代码块标记），每个元素结构：
{{
  "name_zh": "中文概念名（简洁准确）",
  "name_en": "English Concept Name",
  "brief_definition_zh": "简短中文定义（60字以内，说明核心内涵）",
  "brief_definition_en": "Brief English definition (under 60 words)",
  "key_thinkers": ["学者姓名（英文）"],
  "difficulty": "foundational | intermediate | advanced"
}}

教材文本：
{text}"""

def extract_concepts_from_chunk(
    chunk: str, subject: str, client: anthropic.Anthropic
) -> List[Dict]:
    info = SUBJECTS[subject]
    prompt = EXTRACT_PROMPT.format(
        subject_zh=info["name_zh"],
        subject_en=info["name_en"],
        text=chunk
    )
    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",   # cheaper for bulk extraction
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = clean_json_response(msg.content[0].text)
        result = json.loads(raw)
        return result if isinstance(result, list) else []
    except json.JSONDecodeError:
        return []
    except anthropic.RateLimitError:
        log("     ⏳ Rate limit — waiting 30s…")
        time.sleep(30)
        return []
    except Exception as e:
        log(f"     ⚠️  API error: {e}")
        time.sleep(5)
        return []

# ── Deduplication ─────────────────────────────────────────

def normalise(s: str) -> str:
    return re.sub(r'[\s\-_/（）()（）\u3000]', '', s.lower())

def deduplicate(concepts: List[Dict]) -> List[Dict]:
    seen: Dict[str, bool] = {}
    unique: List[Dict] = []
    for c in concepts:
        key = normalise(c.get("name_en", "") or c.get("name_zh", ""))
        if key and key not in seen:
            seen[key] = True
            unique.append(c)
    return unique

# ── Persistence ───────────────────────────────────────────

def load_existing(subject: str) -> List[Dict]:
    f = OUTPUT_DIR / f"{subject}.json"
    if f.exists():
        data = json.loads(f.read_text(encoding="utf-8"))
        return data.get("concepts", [])
    return []

def assign_ids(concepts: List[Dict], subject: str) -> List[Dict]:
    prefix = SUBJECTS[subject]["id_prefix"]
    for i, c in enumerate(concepts, 1):
        c.setdefault("id", f"{prefix}_{i:03d}")
        c.setdefault("used", False)
        c.setdefault("used_date", None)
        c.setdefault("source", "extracted")
        c["subject"] = subject
    return concepts

def save(concepts: List[Dict], subject: str):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    info = SUBJECTS[subject]
    used = sum(1 for c in concepts if c.get("used"))
    data = {
        "subject":    subject,
        "subject_zh": info["name_zh"],
        "subject_en": info["name_en"],
        "total_count": len(concepts),
        "used_count":  used,
        "concepts":    concepts,
    }
    f = OUTPUT_DIR / f"{subject}.json"
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"  💾 Saved {len(concepts)} concepts → {f}")

# ── Main Processing ────────────────────────────────────────

def process(pdf_paths: List[str], subject: str, merge: bool, client: anthropic.Anthropic):
    info = SUBJECTS[subject]
    log(f"\n{'='*60}")
    log(f"Subject: {info['name_zh']} ({info['name_en']})")
    log(f"PDFs   : {len(pdf_paths)}")
    log(f"{'='*60}")

    all_concepts: List[Dict] = load_existing(subject) if merge else []
    if merge and all_concepts:
        log(f"Loaded {len(all_concepts)} existing concepts (merge mode)")

    for pdf_path in pdf_paths:
        text = extract_pdf_text(pdf_path)
        if not text.strip():
            log("  ⚠️  No text — skipping")
            continue

        chunks = chunk_text(text)
        log(f"  Chunks: {len(chunks)}  Characters: {len(text):,}")
        new_from_pdf: List[Dict] = []

        for i, chunk in enumerate(chunks):
            log(f"  Chunk {i+1:3d}/{len(chunks)}  ", end="")
            extracted = extract_concepts_from_chunk(chunk, subject, client)
            log(f"→ {len(extracted)} concepts found")
            new_from_pdf.extend(extracted)
            time.sleep(API_DELAY)

        all_concepts.extend(new_from_pdf)
        # Incremental save after each PDF
        unique = deduplicate(all_concepts)
        assigned = assign_ids(unique, subject)
        save(assigned, subject)
        log(f"  Running total: {len(assigned)} unique concepts")

    # Final save
    unique   = deduplicate(all_concepts)
    assigned = assign_ids(unique, subject)
    save(assigned, subject)
    log(f"\n✅ Done — {len(assigned)} unique concepts for {info['name_zh']}")
    return assigned

# ── CLI ───────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Extract legal concepts from PDF textbooks.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--pdf-dir",  required=True, help="Folder containing PDF files")
    parser.add_argument("--subject",  choices=list(SUBJECTS.keys()),
                        help="Subject to assign all PDFs in the folder")
    parser.add_argument("--auto",     action="store_true",
                        help="Auto-detect subject from each filename")
    parser.add_argument("--merge",    action="store_true",
                        help="Merge with existing concepts JSON instead of overwriting")
    parser.add_argument("--api-key",  help="Anthropic API key (or set ANTHROPIC_API_KEY env var)")
    args = parser.parse_args()

    # API key
    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("❌  Set ANTHROPIC_API_KEY or pass --api-key")
    client = anthropic.Anthropic(api_key=api_key)

    # Find PDFs
    pdf_dir = Path(args.pdf_dir)
    if not pdf_dir.exists():
        sys.exit(f"❌  Directory not found: {pdf_dir}")
    pdfs = sorted(pdf_dir.rglob("*.pdf"))
    if not pdfs:
        sys.exit(f"❌  No PDF files found in: {pdf_dir}")
    log(f"Found {len(pdfs)} PDF file(s) in {pdf_dir}")

    if args.auto:
        grouped: Dict[str, List[str]] = {s: [] for s in SUBJECTS}
        unmatched: List[str] = []
        for p in pdfs:
            s = auto_detect_subject(p.name)
            if s:
                grouped[s].append(str(p))
            else:
                unmatched.append(p.name)
        for subj, files in grouped.items():
            if files:
                process(files, subj, args.merge, client)
        if unmatched:
            log(f"\n⚠️  {len(unmatched)} PDF(s) not auto-detected — run with --subject to process:")
            for name in unmatched:
                log(f"   • {name}")
    elif args.subject:
        process([str(p) for p in pdfs], args.subject, args.merge, client)
    else:
        parser.print_help()
        sys.exit("\n❌  Specify --subject or use --auto")

if __name__ == "__main__":
    main()
