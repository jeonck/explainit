#!/usr/bin/env python3
"""Explain It pipeline — IT/tech term or phrase → ELI5 study post for a 12-year-old.

input/term.md 코드블록에 붙여넣은 기술 용어/문구를 하나의 항목으로 읽어, Claude로
쉬운 비유·단계별 설명·Mermaid 도식·실생활 예시·퀴즈로 구성된 영문 포스트를 생성한다.

코드블록 안에서 `---` 만 있는 줄로 구분하면 용어 여러 개를 각각 별도 포스트로
처리한다. 이미 게시에 사용된 용어(텍스트 해시 기준)는 다시 나타나도 건너뛴다.
후킹 전용 모드 — 크론/폴백이 없으므로 입력이 비어 있으면 이번 실행은 아무것도
하지 않는다.

Usage:
    python pipeline/generate.py [--dry-run]

Env:
    JUDGE_BACKEND            "claude-code" | "api" (기본: 자동 — claude CLI가 있으면
                             claude-code, 없으면 api)
    CLAUDE_CODE_OAUTH_TOKEN  claude-code 백엔드 CI 인증 (claude setup-token으로 발급,
                             로컬은 claude 로그인 세션 사용)
    ANTHROPIC_API_KEY        api 백엔드 필수
    CLAUDE_MODEL             생성 모델 (기본 claude-sonnet-4-6)
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SENTENCE_FILE = ROOT / "input" / "term.md"
STATE_FILE = ROOT / "pipeline" / "state.json"
CONTENT_DIR = ROOT / "content" / "posts"

KST = timezone(timedelta(hours=9))

# ============================== 도메인 설정 =================================
# 이 블록만 새 프로젝트 주제에 맞게 교체한다. 아래 엔진 코드는 건드릴 필요 없다.

# input/term.md 가 비어 있을 때 대신 쓸 항목 풀. 이 사이트는 후킹 전용 모드라 항상
# 비워둔다 — 채우면 daily.yml에 schedule 트리거를 다시 추가해야 실제로 쓰인다.
FALLBACK_QUOTES: list[dict] = []

# Claude에게 부여할 역할/톤
SYSTEM_PROMPT = """You are a warm, patient teacher who explains advanced IT and \
computer-science ideas to a curious 12-year-old. You never drop an unexplained \
technical term — every concept is immediately grounded in one concrete, everyday \
analogy (school, sports, cooking, video games, animals, or similar). Your analogies \
simplify but never mislead about how the technology actually works; you are technically \
accurate underneath the simple language. All output is natural, encouraging, plain \
English."""

# {sentence} / {note} 두 자리를 반드시 유지. JSON 스키마의 이중 중괄호는 str.format()
# 이스케이프이므로 스키마를 고칠 때도 그대로 유지한다.
GENERATE_PROMPT = """A reader typed this IT/tech term or phrase into an "explain this \
simply" box: "{sentence}"{note}

Explain it so a smart, curious 12-year-old fully gets it — what it is, why it exists, \
and roughly how it works — using ONE consistent everyday analogy all the way through. \
Respond ONLY with JSON in exactly this format, no other text:

{{"title": "Short, plain-English title a 12-year-old would click on",
 "eli5": "1-2 sentence summary with zero unexplained jargon",
 "analogy_title": "short punchy label for the central analogy, e.g. 'Like a classroom passing notes'",
 "analogy": "3-6 sentence extended analogy in vivid, concrete, everyday terms — ONE scenario, not a mix of metaphors",
 "how_it_works": [
   {{"step": "short plain-English step label", "text": "1-2 sentences explaining this step, tied back to the analogy"}}
 ],
 "key_terms": [
   {{"term": "a jargon word or short phrase actually used above", "meaning": "one-line plain-English meaning"}}
 ],
 "mermaid": "valid Mermaid flowchart source (no code fences), 4-8 nodes, short plain-English labels that mirror the steps above",
 "why_it_matters": "2-3 sentences on real-world impact, in plain English",
 "real_world_examples": ["short recognizable example 1", "short recognizable example 2", "short recognizable example 3"],
 "quiz": [
   {{"question": "natural sentence containing ____ (a blank) where one key term fits",
     "options": ["key term A", "key term B", "key term C"],
     "answer": "key term B",
     "explanation": "one short line on why it fits the blank and the others don't"}}
 ],
 "fun_fact": "one short, surprising, kid-friendly fact related to the term",
 "tags": ["kebab-case-tag", "max 3"]}}

Requirements: 3-5 "how_it_works" steps in the correct technical order; 3-6 "key_terms"
(every jargon word you used anywhere above must be explained here); 2-4
"real_world_examples" a middle-schooler would recognize (an app, game, or everyday
situation); 3-5 quiz questions.
Mermaid rules: plain "flowchart TD" or "flowchart LR" syntax only, short node labels
(<=6 words) in plain English that echo "how_it_works", no styling/classDef, no markdown
code fences in the value — just the raw Mermaid source.
Quiz rules: every question is FILL-IN-THE-BLANK — a natural sentence with "____" marking
the blank. Every option (3-4 per question) MUST be taken verbatim from this post's
"key_terms" — never invent outside words. Exactly one option fits the blank; the
sentence must be fully grammatical once the correct option is inserted. The same option
set should not repeat across questions.
Accuracy rule: simplify freely, but never state something that is technically wrong —
the analogy must map faithfully onto the real mechanism.

Term or phrase:
{sentence}"""

# 포스트 본문 섹션 제목
HEADING_WHAT = "🤔 What Is It?"
HEADING_HOW = "⚙️ How It Works"
HEADING_DIAGRAM = "🗺️ Picture It"
HEADING_KEY_TERMS = "🔑 Key Words"
HEADING_WHY = "🌍 Why It Matters"
HEADING_EXAMPLES = "🔍 Where You'll See This"
HEADING_QUIZ = "✅ Check Yourself"
HEADING_FUN_FACT = "🎉 Fun Fact"

# ============================ 도메인 설정 끝 =================================


def log(msg: str) -> None:
    print(msg, flush=True)


def sentence_hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title.lower()).strip("-")
    return (slug or "explained")[:60].rstrip("-")


def read_sentences() -> list[str]:
    """input/term.md 코드블록 안의 용어/문구를 읽는다.

    코드블록 전체가 항목 하나. `---` 만 있는 줄로 구분하면 여러 용어를
    각각 별도 항목(= 별도 포스트)으로 처리한다.
    """
    if not SENTENCE_FILE.exists():
        log(f"오류: {SENTENCE_FILE} 파일이 없습니다")
        sys.exit(1)
    text = SENTENCE_FILE.read_text(encoding="utf-8")
    fenced = re.search(r"```[a-zA-Z]*\n(.*?)```", text, re.DOTALL)
    body = fenced.group(1) if fenced else text
    terms = []
    for chunk in re.split(r"^\s*---+\s*$", body, flags=re.MULTILINE):
        chunk = chunk.strip()
        if chunk and not chunk.startswith("<!--"):
            terms.append(chunk)
    return terms


def fallback_quote_item(today) -> dict | None:
    """input이 비어 있을 때 사용할 항목 — 날짜 기준으로 풀을 순환 선택."""
    if not FALLBACK_QUOTES:
        return None
    idx = today.timetuple().tm_yday % len(FALLBACK_QUOTES)
    quote = FALLBACK_QUOTES[idx]
    return {
        "text": quote["text"],
        "source": quote.get("author") or "term",
        "dedup_key": sentence_hash(f"{today.isoformat()}::{quote['text']}"),
    }


def build_queue(sentences: list[str], today) -> list[dict]:
    if sentences:
        return [
            {"text": s, "source": None, "dedup_key": sentence_hash(s)}
            for s in sentences
        ]
    fallback = fallback_quote_item(today)
    return [fallback] if fallback else []


class FatalAPIError(Exception):
    """재시도가 무의미한 오류(크레딧 부족, 인증 실패) — 실행 전체 중단."""


def is_fatal_api_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in (
        "credit balance", "authenticat", "invalid x-api-key",
        "invalid api key", "invalid bearer token", "oauth token", "/login",
        "401",
    ))


def parse_result(text: str) -> dict | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    required = ("title", "eli5", "analogy", "mermaid")
    if not all(isinstance(data.get(k), str) and data.get(k).strip() for k in required):
        return None
    for key in ("how_it_works", "key_terms", "real_world_examples", "quiz"):
        value = data.get(key) or []
        data[key] = value if isinstance(value, list) else []
    if not data["how_it_works"] or not data["quiz"]:
        return None
    data["analogy_title"] = str(data.get("analogy_title") or "The Big Idea").strip()
    data["why_it_matters"] = str(data.get("why_it_matters") or "").strip()
    data["fun_fact"] = str(data.get("fun_fact") or "").strip()
    mermaid = data["mermaid"].strip()
    mermaid = re.sub(r"^```[a-zA-Z]*\n|\n?```$", "", mermaid).strip()
    data["mermaid"] = mermaid
    tags = data.get("tags") or []
    data["tags"] = [slugify(str(t)) for t in tags[:3] if str(t).strip()] or ["explained-simply"]
    return data


def build_prompt(sentence: str, source: str | None) -> str:
    return GENERATE_PROMPT.format(sentence=sentence, note="")


def generate_api(client, model: str, sentence: str, source: str | None = None) -> dict | None:
    prompt = build_prompt(sentence, source)
    for attempt in (1, 2):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=8000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:  # noqa: BLE001
            if is_fatal_api_error(exc):
                raise FatalAPIError(str(exc)) from exc
            log(f"  API 오류 (시도 {attempt}): {exc}")
            if attempt == 2:
                return None
            continue
        text = next((b.text for b in response.content if b.type == "text"), "")
        result = parse_result(text)
        if result:
            return result
        log(f"  JSON 파싱 실패 (시도 {attempt}): {text[:120]!r}")
    return None


def generate_cli(model: str, sentence: str, source: str | None = None) -> dict | None:
    prompt = build_prompt(sentence, source)
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    cmd = ["claude", "-p", "--model", model, "--tools", "",
           "--output-format", "text", "--append-system-prompt", SYSTEM_PROMPT]
    for attempt in (1, 2):
        try:
            result = subprocess.run(cmd, input=prompt, env=env, timeout=360,
                                     capture_output=True, text=True)
        except subprocess.TimeoutExpired:
            log(f"  CLI 타임아웃 (시도 {attempt})")
            continue
        if result.returncode != 0:
            err = (result.stderr or result.stdout).strip()
            if is_fatal_api_error(RuntimeError(err)):
                raise FatalAPIError(err[:300])
            log(f"  CLI 오류 (시도 {attempt}): {err[:200]}")
            if attempt == 2:
                return None
            continue
        parsed = parse_result(result.stdout)
        if parsed:
            return parsed
        log(f"  JSON 파싱 실패 (시도 {attempt}): {result.stdout[:120]!r}")
    return None


def yaml_quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def write_post(sentence: str, result: dict, date: datetime, source: str | None = None) -> Path:
    CONTENT_DIR.mkdir(parents=True, exist_ok=True)
    base = f"{date.date().isoformat()}-{slugify(result['title'])}"
    path = CONTENT_DIR / f"{base}.md"
    n = 2
    while path.exists():
        path = CONTENT_DIR / f"{base}-{n}.md"
        n += 1

    tags_str = ", ".join(yaml_quote(t) for t in result["tags"])

    sections = [f"## {HEADING_WHAT}\n\n> **{sentence}**\n\n{result['eli5']}\n"]

    sections.append(f"## 🧩 {result['analogy_title']}\n\n{result['analogy']}\n")

    if result["how_it_works"]:
        lines = [f"## {HEADING_HOW}\n"]
        for i, item in enumerate(result["how_it_works"], 1):
            step = item.get("step", "")
            text = item.get("text", "")
            lines.append(f"{i}. **{step}** — {text}")
        sections.append("\n".join(lines) + "\n")

    if result["mermaid"]:
        sections.append(f"## {HEADING_DIAGRAM}\n\n```mermaid\n{result['mermaid']}\n```\n")

    if result["key_terms"]:
        lines = [f"## {HEADING_KEY_TERMS}\n"]
        for item in result["key_terms"]:
            term = item.get("term", "")
            meaning = item.get("meaning", "")
            lines.append(f"- **{term}** — {meaning}")
        sections.append("\n".join(lines) + "\n")

    if result["why_it_matters"]:
        sections.append(f"## {HEADING_WHY}\n\n{result['why_it_matters']}\n")

    if result["real_world_examples"]:
        lines = [f"## {HEADING_EXAMPLES}\n"]
        lines.extend(f"- {ex}" for ex in result["real_world_examples"])
        sections.append("\n".join(lines) + "\n")

    if result["quiz"]:
        lines = [f"## {HEADING_QUIZ}\n"]
        for i, item in enumerate(result["quiz"], 1):
            lines.append(f"**Q{i}.** {item.get('question', '')}\n")
            options = item.get("options") or []
            if options:
                lines.append("\n".join(f"- {opt}" for opt in options) + "\n")
            answer = html_escape(str(item.get("answer", "")))
            explanation = html_escape(str(item.get("explanation", "")))
            detail = f"<strong>{answer}</strong>"
            if explanation:
                detail += f" — {explanation}"
            lines.append(
                "<details><summary>Show answer</summary>"
                f"<p>{detail}</p></details>\n"
            )
        sections.append("\n".join(lines))

    if result["fun_fact"]:
        sections.append(f"## {HEADING_FUN_FACT}\n\n> {result['fun_fact']}\n")

    post = f"""---
title: {yaml_quote(result['title'])}
date: {date.isoformat()}
tags: [{tags_str}]
---
""" + "\n".join(sections)
    path.write_text(post, encoding="utf-8")
    return path


def clear_input() -> None:
    """게시가 끝난 뒤 input/term.md 코드블록을 비운다 (안내 주석은 유지)."""
    text = SENTENCE_FILE.read_text(encoding="utf-8")
    cleared = re.sub(r"```[a-zA-Z]*\n.*?```", "```\n```", text, count=1, flags=re.DOTALL)
    if cleared != text:
        SENTENCE_FILE.write_text(cleared, encoding="utf-8")
        log("input/term.md 코드블록을 비웠습니다 (게시 완료)")


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Explain It pipeline")
    parser.add_argument("--dry-run", action="store_true",
                         help="파일 생성/state.json 갱신 없이 결과만 출력")
    args = parser.parse_args()

    backend = os.environ.get("JUDGE_BACKEND", "").strip() or (
        "claude-code" if shutil.which("claude") else "api"
    )
    client = None
    if backend == "api":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            log("오류: api 백엔드에는 ANTHROPIC_API_KEY 환경변수가 필요합니다")
            return 1
        import anthropic  # 지연 임포트

        client = anthropic.Anthropic()
    elif backend == "claude-code":
        if not shutil.which("claude"):
            log("오류: claude-code 백엔드에는 claude CLI가 PATH에 있어야 합니다")
            return 1
    else:
        log(f"오류: 알 수 없는 JUDGE_BACKEND={backend!r} (claude-code | api)")
        return 1

    model = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
    today = datetime.now(KST).date()
    sentences = read_sentences()
    queue = build_queue(sentences, today)
    if sentences:
        log(f"입력된 용어 {len(sentences)}개")
    else:
        log("input/term.md 에 용어가 없습니다 — 후킹 전용 모드라 오늘은 건너뜁니다")
        return 0

    state = load_state()
    processed: dict = state.get("processed", {})

    log(f"=== 생성 시작 (backend={backend}, model={model}, dry_run={args.dry_run}) ===")

    new_count = 0
    skipped_dup = 0
    failed = 0
    fatal_error = None
    for item in queue:
        sentence, source, h = item["text"], item["source"], item["dedup_key"]
        if h in processed:
            skipped_dup += 1
            continue

        preview = sentence if len(sentence) <= 80 else sentence[:80] + "…"
        log(f"\n오늘의 항목 ({len(sentence)}자): {preview}")
        try:
            if backend == "claude-code":
                result = generate_cli(model, sentence, source)
            else:
                result = generate_api(client, model, sentence, source)
        except FatalAPIError as exc:
            fatal_error = exc
            break

        if result is None:
            log("  생성 실패 — 건너뜁니다 (다음 실행에서 재시도)")
            failed += 1
            continue

        now = datetime.now(KST)
        log(f"  → {result['title']}")

        if args.dry_run:
            log(json.dumps(result, ensure_ascii=False, indent=2))
            continue

        path = write_post(sentence, result, now, source)
        log(f"  생성 파일: {path.relative_to(ROOT)}")
        processed[h] = now.date().isoformat()
        new_count += 1

    log(f"\n=== 결과: 신규 {new_count} / 중복 스킵 {skipped_dup} / 생성 실패 {failed} ===")

    if args.dry_run:
        log("(dry-run — 파일 생성/기록 갱신 없음)")
        return 1 if fatal_error else 0

    if new_count:
        state["processed"] = processed
        STATE_FILE.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")

    # 전부 성공했을 때만 입력란 초기화 — 실패분이 있으면 다음 실행 재시도를 위해 남겨둔다
    if sentences and new_count and not failed and fatal_error is None:
        clear_input()

    if fatal_error:
        log(f"\n중단: 복구 불가능한 API 오류 — {fatal_error}")
        log("→ Anthropic 크레딧/API 키(또는 CLAUDE_CODE_OAUTH_TOKEN)를 확인하세요.")
        log("→ 성공한 항목은 이미 게시/기록되었습니다.")
        return 1
    return 1 if failed and not new_count else 0


if __name__ == "__main__":
    sys.exit(main())
