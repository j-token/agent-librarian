# 이 프로젝트에 대해서

[English](README.md)

이 프로젝트는 도서관에서 영감 받아 코드 베이스,폴더 구조를 도서관처럼 관리할 수 있게 만들어주는 플러그인입니다.

이제 AI가 코드를 생산한다면 인간의 역할은 그 코드를 관리하고 활용하는 것이라고 생각해 만들게 된 플러그인입니다.

## 왜 도서관인가?

인류는 수많은 지식을 생산하고 쌓아올리고 관리를 하였습니다.

수많은 책을 최대한 헷갈리지 않게 분류하고 정리하는게 사서의 역할입니다.

중복된 책이 최대한 없게 하고 비슷한 책들은 분류하고...때로는 분류한 책들을 누군가는 찾을테니 찾기 쉽게 만들어놔야하는 것이 있을껍니다.

이 플러그인은 인간이 세운 도서관의 규칙을 AI가 따르게 만들게 하기위한 플러그인입니다.

## 도서관은 이렇게 생겼습니다

폴더마다 문서(`CLAUDE.md` 또는 `AGENTS.md`)가 하나씩 있습니다.

```markdown
# 상위 문서: ../CLAUDE.md

## 이 폴더의 역할
결제·청구 관련 코드를 모아 두는 곳입니다.        ← 에이전트/사람이 작성

## 하위 폴더
| 폴더 | 역할 |
|---|---|
| tax/ | 세금 계산 |                              ← 에이전트/사람이 작성

<!-- librarian:index:start -->
| 파일 | 함수 | 줄 |
|---|---|---|
| invoice.py | Invoice.total | 2 |              ← 스크립트가 자동 생성
<!-- librarian:index:end -->
```

- 루트 문서에는 최상위 폴더들의 역할만 적습니다. 각 폴더 문서에는 바로 아래 폴더들의 역할만 적습니다.
- 파일 · 함수 · 줄은 tree-sitter 스크립트가 만듭니다. **함수가 무엇을 하는지는 적지 않습니다.** AI가 함수를 잘못 이해해서 틀린 설명을 적는 일(환각)을 막기 위해서입니다.
- 파일을 편집하면 훅이 줄 번호를 바로 갱신합니다. 턴이 끝날 때마다 check 훅이 문서와 코드가 어긋난 곳을 고치고, 역할이 비어 있는 폴더가 있으면 채우라고 요청합니다.
- 설계 근거는 [지식 관리 이론 조사](docs/research/knowledge-management.md)에 정리했습니다.

설치하면 프로젝트에 아래 파일들이 생깁니다.

```
.librarian/config.json                  # 문서 이름, 제외 경로, 분리 기준(maxEntries, maxDepth)
.librarian/skills/librarian-guide/      # 관리지침 스킬 (원본)
.claude/skills/librarian-guide          → 원본에 연결 (Claude Code)
.agents/skills/librarian-guide          → 원본에 연결 (Agent Skills 표준 경로)
.codex/skills/librarian-guide           → 원본에 연결 (Codex)
```

연결은 Windows에서는 정션, 그 외 OS에서는 심볼릭 링크로 만듭니다. 링크를 만들 수 없으면 복사합니다. 연결 경로는 `.gitignore`에 추가되고, 연결이 끊기면 check 훅이 자동으로 복구합니다.

## 요구 사항

- Python 3.9 이상
- `pip install -r requirements.txt` (`tree-sitter-language-pack`)
  - 언어별 파서는 처음 사용할 때 내려받습니다.
- 지원 언어: Python, JavaScript/TypeScript/TSX, Go, Rust, Java, C/C++, C#

이 플러그인은 [Agent Plugins](https://agent-plugins.org/) 규격(루트의 `plugin.json`)을 따릅니다. 그래서 Claude Code와 Codex에서 모두 쓸 수 있습니다.

### Codex에서 쓸 때

- `~/.codex/config.toml`에 `[features] hooks = true`를 켜세요.
- 설치한 뒤 `/hooks`에서 이 플러그인의 훅을 한 번 신뢰(trust)해야 실행됩니다.
- Codex에는 서브에이전트 정의가 없습니다. 그래서 `/rebuild-library`를 실행하면 에이전트가 폴더를 하나씩 순서대로 처리합니다.

## 사람을 위한 지침

먼저 이 플러그인을 설치한 다음 `/reload-plugins` 명령어를 사용하세요.

그러면 여러분을 위한 "도서관"이 지어질껍니다.

### 기존 코드 베이스가 있는 경우

> 주의! 이 명령어를 사용하면 플러그인 내의 sonnet 5 에이전트가 동작하여 코드 베이스를 전체적으로 스캔하여 인덱싱합니다. 이로 인해 추가 요금이 부과될 수 있으니 주의하세요!


1. 아래 명령어를 입력합니다.

    `/rebuild-library`

2. 필요한 질문에 응답해주세요.

3. CLAUDE.md 또는 AGENTS.md에 추가된 지식 관리 규칙이 적절한지 확인하세요.

### 기존 코드 베이스가 없는 경우

1. 아래 명령어를 입력합니다.

    `/build-library`

2. 필요한 질문에 응답해주세요.

3. CLAUDE.md 또는 AGENTS.md에 추가된 지식 관리 규칙이 적절한지 확인하세요.
