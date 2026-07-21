# Explain It (explainit)

Paste an IT/tech term or phrase — Claude explains it like you're 12: one clear
everyday analogy, a step-by-step breakdown, a Mermaid diagram, real-world examples,
and a self-check quiz. English site, hook-only (no cron).

사이트: https://explainit.metacog.co.kr/

## 어떻게 동작하나

```
input/term.md (기술 용어/문구를 코드블록에 붙여넣기, GitHub 웹 UI에서 수정)
        │
        ▼  저장(커밋)하는 순간 push 후킹으로 즉시 실행 (크론 없음)
pipeline/generate.py
  - 코드블록 전체를 용어 1개로 읽음 (`---` 구분선으로 여러 개 가능)
  - 이미 게시된 용어(해시 기준)는 건너뜀 — pipeline/state.json 으로 추적
  - 입력이 비어 있으면 아무것도 하지 않고 종료 (폴백 없음, 후킹 전용 모드)
  - Claude가 용어를 분석해 섹션 구성:
      🤔 What Is It? / 🧩 (analogy) / ⚙️ How It Works / 🗺️ Picture It (Mermaid) /
      🔑 Key Words / 🌍 Why It Matters / 🔍 Where You'll See This /
      ✅ Check Yourself (토글 퀴즈) / 🎉 Fun Fact
  - content/posts/YYYY-MM-DD-....md 로 저장
        │
        ▼  변경사항 커밋 & push
Hugo build → GitHub Pages 배포
```

## 사용하는 방법

1. GitHub 저장소에서 [`input/term.md`](input/term.md) 파일을 연다.
   (블로그 상단 "Explain a Term ✏️" 버튼으로 바로 이동 가능)
2. 연필(✏️) 아이콘을 눌러 편집 모드로 들어간다.
3. 코드블록(```) 안에 설명받고 싶은 IT/기술 용어나 문구를 붙여넣는다. 여러 개를
   한꺼번에 처리하려면 `---` 만 있는 줄로 구분한다 — 블록마다 포스트가 하나씩
   생성된다.
4. 우측 상단 "Commit changes"로 저장한다. **저장하는 순간 GitHub Actions가
   후킹되어 즉시 분석·게시가 시작된다** (로컬 git 작업 불필요).
5. 몇 분 뒤 사이트에 새 포스트가 올라온다.

게시가 전부 성공하면 파이프라인이 커밋 시 `input/term.md` 코드블록을 자동으로
비운다 — 다음 용어를 넣을 때 기존 내용을 지울 필요 없이 바로 붙여넣으면 된다.
(일부만 실패하면 재시도할 수 있도록 입력은 그대로 남는다.) 혹시 자동 초기화 전에
같은 용어가 다시 게시판에 남아 있어도, 텍스트 해시 기준 dedup으로 재게시되지
않는다. Actions 탭 → "Explain It Publish" → "Run workflow"로 수동 실행도 가능하다.

### 크론 없음 — 후킹 전용 모드

이 사이트는 매일 자동 게시되는 크론이나 입력 없는 날의 폴백 주제가 없다.
`input/term.md`에 용어를 커밋할 때만 포스트가 생성된다. 크론을 다시 켜려면
`.github/workflows/publish.yml`에 `schedule:` 트리거를 추가하고,
`pipeline/generate.py`의 `FALLBACK_QUOTES` 풀을 채운다.

## 최초 설정 (1회만, 사람이 직접 해야 하는 단계)

자동 생성 단계는 Claude Code CLI를 사용한다. GitHub Actions에서 이 CLI를 인증하려면
Claude 구독 계정으로 발급한 OAuth 토큰을 저장소 Secret으로 등록해야 한다. 이 과정은
브라우저 로그인이 필요해 에이전트가 대신할 수 없다.

```bash
claude setup-token
```

터미널에 표시되는 인증 코드를 브라우저에 붙여넣고 로그인하면, **그 다음에** 터미널에
`sk-ant-oat01-...` 로 시작하는 토큰이 출력된다. (브라우저에 표시된 인증 코드 자체가
아니라, 붙여넣은 뒤 터미널에 최종 출력되는 토큰이어야 한다.)

```bash
gh secret set CLAUDE_CODE_OAUTH_TOKEN --repo jeonck/explainit
# 위 토큰을 붙여넣기
```

등록 후 Actions 탭에서 워크플로를 한 번 수동 실행(`workflow_dispatch`)해 정상 동작을
확인한다.

## 저장소 구조

| 경로 | 역할 |
|---|---|
| `input/term.md` | 설명받을 용어 붙여넣는 곳 (사람이 수정 — 저장 즉시 후킹 실행) |
| `pipeline/generate.py` | 용어 분석 → Hugo 포스트 작성. 도메인 설정은 파일 상단 "도메인 설정" 블록 |
| `pipeline/state.json` | 게시에 사용된 용어 해시 목록 (중복 게시 방지) |
| `content/posts/` | 생성된 ELI5 포스트 |
| `.github/workflows/publish.yml` | push 후킹 전용 생성/배포 워크플로 (크론 없음) |
| `themes/PaperMod` | Hugo 테마 (git submodule) |
| `layouts/_default/_markup/render-codeblock-mermaid.html` | ` ```mermaid ` 코드블록을 `<pre class="mermaid">`로 렌더링하는 훅 |
| `layouts/partials/extend_head.html` | Mermaid.js 로드 + 라이트/다크 테마 동기화 |
| `assets/css/extended/cards.css` | 카드 그리드 레이아웃 + PaperMod 여백 버그 수정 |
| `assets/css/extended/quiz.css` | Check Yourself 토글 스타일 |
| `assets/css/extended/mermaid.css` | Picture It 다이어그램 컨테이너 스타일 |
| `static/CNAME` | 커스텀 도메인 (explainit.metacog.co.kr) |

## 로컬에서 테스트

```bash
hugo server -D                           # http://localhost:1313/
python3 pipeline/generate.py --dry-run   # 파일 생성 없이 결과만 확인
```

로컬에는 `claude` CLI 로그인 세션이 있으면 그대로 사용되고(`JUDGE_BACKEND=claude-code`),
없으면 `ANTHROPIC_API_KEY` 를 설정해 `JUDGE_BACKEND=api` 로 실행할 수 있다.
