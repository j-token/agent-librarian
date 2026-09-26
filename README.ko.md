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
| 파일 | 함수 | 시작 줄 | 끝 줄 |
|---|---|---|---|
| invoice.py | Invoice.total | 2 | 9 |          ← 스크립트가 자동 생성
<!-- librarian:index:end -->
```

설치 명령은 가장 먼저 **도서관 언어**를 묻습니다. 폴더 문서를 어떤 언어로 쓸지 정하는 질문입니다.
- 영어와 한국어는 제목이 내장되어 있습니다. 위 예시는 한국어를 골랐을 때의 모습입니다.
- 다른 언어도 고를 수 있습니다. 이때 제목은 영어로 두고, 역할은 그 언어로 씁니다.
- 언어는 나중에 `/rebuild-library`를 다시 실행해서 바꿀 수 있습니다. 이미 쓴 역할은 그대로 유지됩니다.

- 루트 문서에는 최상위 폴더들의 역할만 적습니다. 각 폴더 문서에는 바로 아래 폴더들의 역할만 적습니다.
- 파일 · 함수 · 시작 줄 · 끝 줄은 스크립트가 만듭니다. 에이전트는 함수가 어디서 끝나는지 짐작하지 않고, 파일을 시작 줄부터 끝 줄까지 열어서 읽습니다. **함수가 무엇을 하는지는 적지 않습니다.** AI가 함수를 잘못 이해해서 틀린 설명을 적는 일(환각)을 막기 위해서입니다.
- 파일을 편집하면 훅이 줄 번호를 바로 갱신합니다. 턴이 끝날 때마다 check 훅이 문서와 코드가 어긋난 곳을 고치고, 역할이 비어 있는 폴더가 있으면 채우라고 요청합니다.
- 설계 근거는 [지식 관리 이론 조사](docs/research/knowledge-management.md)에 정리했습니다.

설치하면 프로젝트에 아래 파일들이 생깁니다.

```
.librarian/config.json                  # 도서관 언어, 문서 이름, 제외 경로, 폴더 깊이 경고 기준(maxDepth),
                                        # 도서관을 만든 플러그인 버전(libraryVersion)
<모든 폴더>/CLAUDE.md 또는 AGENTS.md    # 폴더 문서
```

## 요구 사항

- Python 3.9 이상. 그 밖에 설치할 것은 없습니다. 인덱스는 Python 표준 라이브러리만으로 만듭니다.
- 지원 언어: Python, JavaScript/TypeScript/TSX, Go, Rust, Java, C/C++, C#

이 플러그인은 [Agent Plugins](https://agent-plugins.org/) 규격(루트의 `plugin.json`)을 따릅니다. 그래서 Claude Code와 Codex에서 모두 쓸 수 있습니다.

### Codex에서 쓸 때

- `~/.codex/config.toml`에 `[features] hooks = true`를 켜세요.
- 설치한 뒤 `/hooks`에서 이 플러그인의 훅을 한 번 신뢰(trust)해야 실행됩니다.
- Codex에는 서브에이전트 정의가 없습니다. 그래서 `/rebuild-library`를 실행하면 에이전트가 폴더를 하나씩 순서대로 처리합니다.

## 사람을 위한 지침

### 설치

Python 3.9 이상만 있으면 됩니다.

**Claude Code**: Claude Code 안에서 아래 명령어를 입력한 다음 `/reload-plugins`를 실행하세요.

```
/plugin marketplace add j-token/agent-librarian
/plugin install agent-librarian@agent-librarian
```

터미널에서 설치할 수도 있습니다.

```bash
claude plugin marketplace add j-token/agent-librarian
claude plugin install agent-librarian@agent-librarian
```

**Codex**: 터미널에서 아래 명령어를 입력하세요.

```bash
codex plugin marketplace add j-token/agent-librarian
codex plugin add agent-librarian@agent-librarian
```

그다음 `~/.codex/config.toml`에 `[features] hooks = true`를 켜고, Codex를 실행해서 `/hooks`에서 이 플러그인의 훅을 신뢰(trust)하세요.

설치가 끝나면 아래 명령어로 여러분을 위한 "도서관"을 지으세요.

### 기존 코드 베이스가 있는 경우

> 주의! 이 명령어를 사용하면 플러그인 내의 sonnet 5 에이전트가 동작하여 코드 베이스를 전체적으로 스캔하여 인덱싱합니다. 이로 인해 추가 요금이 부과될 수 있으니 주의하세요!


1. 아래 명령어를 입력합니다.

    `/rebuild-library`

2. 필요한 질문에 응답해주세요. 첫 질문은 도서관 언어입니다.

3. 각 CLAUDE.md 또는 AGENTS.md에 적힌 폴더 역할이 적절한지 확인하세요.

### 기존 코드 베이스가 없는 경우

1. 아래 명령어를 입력합니다.

    `/build-library`

2. 필요한 질문에 응답해주세요. 첫 질문은 도서관 언어입니다.

3. 루트의 CLAUDE.md 또는 AGENTS.md와 `.librarian/config.json`의 설정을 확인하세요.

### 플러그인을 업데이트한 뒤

플러그인을 업데이트해도(`/plugin update`) 이미 만든 도서관은 바뀌지 않습니다. check 훅이 도서관이 예전 버전으로 만들어졌다고 알려 주면 `/update-library`를 실행하세요. 설정 항목을 현재 버전에 맞추고, 이미 쓴 역할은 그대로 둔 채 모든 폴더 문서를 현재 형식으로 고칩니다. 예전 버전으로 만든 도서관에는 관리지침 스킬(`librarian-guide`)이 있었습니다. `/update-library`(`/rebuild-library`도 마찬가지)는 그 스킬의 연결과 `.gitignore` 항목을 지우고, `.librarian/skills/librarian-guide`는 직접 추가한 내용을 옮긴 뒤 지우라고 알려 줍니다.

## 에이전트를 위한 지침

사용자를 대신해 이 플러그인을 설치하거나 사용하는 AI 에이전트를 위한 절입니다.

### 사용자를 위해 설치할 때

1. `python --version`이 3.9 이상인지 확인합니다. Python이 없으면 사용자에게 설치를 요청합니다. 그 밖의 의존성은 없습니다.
2. 위 "설치"의 터미널 명령으로 플러그인을 설치합니다. Claude Code는 `claude plugin …` 명령을, Codex는 `codex plugin …` 명령을 씁니다.
3. 에이전트가 직접 할 수 없어서 사용자에게 요청해야 하는 단계가 있습니다.
   - Claude Code에서 `/reload-plugins` 실행
   - Codex에서 `[features] hooks = true` 설정, `/hooks`에서 이 플러그인의 훅 신뢰
   - `/rebuild-library`(기존 코드베이스) 또는 `/build-library`(새 프로젝트) 실행. 이 스킬들은 모델이 호출할 수 없고, 도서관 언어 같은 질문을 사용자에게 합니다.
4. `/rebuild-library`는 코드베이스 전체를 읽으므로 폴더 수에 비례해 토큰 비용이 든다고 사용자에게 알립니다.

### 도서관이 있는 프로젝트에서 작업할 때

루트에 `.librarian/config.json`이 있으면 도서관이 있는 프로젝트입니다. 손볼 곳이 생기면 훅이 알려 줍니다. 핵심은 다음과 같습니다.

- 폴더 문서에는 폴더의 역할과, 코드에 대해서는 `파일 · 함수 · 시작 줄 · 끝 줄`만 적혀 있습니다. 무언가에 의존하기 전에 그 파일을 시작 줄부터 끝 줄까지 직접 열어서 읽습니다. 함수 이름만 보고 동작을 추측하지 않습니다.
- 함수나 파일이 무엇을 하는지 적지 않습니다. `<!-- librarian:index:start/end -->` 블록은 수정하지 않습니다. 훅이 최신 상태로 유지합니다.
- 폴더를 새로 만들면 그 폴더의 역할 섹션과 부모 문서 하위 폴더 표의 역할 칸을 도서관 언어(`.librarian/config.json`의 `language`)로 채웁니다.
- Stop 훅이 빈 역할을 채우라고 요청하면 코드를 읽고 채웁니다. 폴더의 역할만 씁니다.
- 역참조(누가 무엇을 호출하는지)는 grep이나 LSP로 조회합니다. 문서에는 기록하지 않습니다.
- 훅이 폴더 깊이 초과를 경고하면 사용자에게 알립니다. 폴더 구조는 임의로 바꾸지 않습니다.
- Stop 훅이 도서관이 예전 플러그인 버전으로 만들어졌다고 알리면 사용자에게 `/update-library` 실행을 요청합니다. 이 스킬은 모델이 호출할 수 없습니다.

## 기여하기

[CONTRIBUTING.md](CONTRIBUTING.md)를 참고하세요. 영어로 작성되어 있습니다.

## 라이선스

[Apache License 2.0](LICENSE)
