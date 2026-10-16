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

실제 도서관처럼 두 부분으로 이루어집니다. 폴더마다 무엇을 보관하는지 적어 둔 **서가**와, 특정 책을 찾을 때 조회하는 **목록(카탈로그)**입니다.

### 서가: 코드가 있는 폴더마다 `CLAUDE.md` 하나

루트와 코드가 있는 모든 폴더에 `CLAUDE.md`가 있습니다. 문서나 에셋만 있는 폴더에는 만들지 않습니다.

```markdown
# 상위 문서: ../CLAUDE.md

## 이 폴더의 역할
결제·청구 관련 코드를 모아 두는 곳입니다.        ← 에이전트/사람이 작성

## 메모
금액은 원 단위의 정수로 저장합니다.             ← 에이전트/사람이 작성

## 하위 폴더
| 폴더 | 역할 |
|---|---|
| tax/ | 세금 계산 |                              ← 행은 스크립트가 유지, 역할은 에이전트/사람이 작성
```

설치 명령은 가장 먼저 **도서관 언어**를 묻습니다. 폴더 문서를 어떤 언어로 쓸지 정하는 값입니다. 영어와 한국어는 제목이 내장되어 있습니다. 다른 언어도 받으며, 그때는 제목은 영어로 두고 역할만 그 언어로 씁니다. 나중에 `/rebuild-library`를 다시 실행해 언어를 바꿀 수 있고, 이미 쓴 역할은 그대로 남습니다.

- 루트의 하위 폴더 표는 최상위 폴더만, 그 밖의 하위 폴더 표는 바로 아래 폴더만 설명합니다.
- 메모 섹션에는 코드만 봐서는 알 수 없는 맥락과 폴더 작업 규칙을 적습니다.
- Claude Code는 어떤 폴더의 파일을 읽을 때마다 그 폴더와 모든 상위 폴더의 `CLAUDE.md`를 불러옵니다. 그래서 문서를 짧게 유지합니다. `maxDocLines`(기본 60)는 하위 폴더 표의 행을 뺀, 사람이 쓴 글의 길이를 제한합니다.

### 목록: 필요할 때만 조회하는 정의 위치

스크립트가 모든 정의를 `파일 · 항목 · 시작 줄 · 끝 줄` 형태로 `.librarian/catalog.json`에 기록합니다. 목록은 코드에서 다시 만들 수 있는 파생 데이터입니다. `.librarian/.gitignore`로 git에서 제외하고, `CLAUDE.md`에는 쓰지 않습니다. 세션이 시작되면 훅이 에이전트에게 조회 방법을 알려 줍니다.

```text
$ python scripts/librarian.py find '^onscary$'
[src/] The platform-independent C source of the game itself.
src/monmove.c:135-182 onscary
   135	onscary(x, y, mtmp)
   136	int x, y;
   ...

$ python scripts/librarian.py outline src/pray.c
[src/] The platform-independent C source of the game itself.
src/pray.c
  102-141 critically_low_hp
  183-269 in_trouble
  ...

$ python scripts/librarian.py grep 'u\.uluck = 0' src
[src/] The platform-independent C source of the game itself.
src/pray.c:923-1228 pleased
  1117: u.uluck = 0;
src/pray.c:1327-1792 dosacrifice
  1706: u.uluck = 0;
  1740: u.uluck = 0;
  1778: u.uluck = 0;
src/pray.c:1846-1883 dopray
  1862: u.uluck = 0;
```

- 일치하는 정의가 3개 이하이면 `find`가 코드도 함께 보여 줍니다(정의당 최대 60줄). 그래서 조회 한 번이 도구 호출 두 번이 아니라 한 번으로 끝납니다. 그 밖에는 에이전트가 파일 전체 대신 알려 준 줄 범위만 읽습니다. **목록은 함수가 무엇을 하는지 적지 않습니다.** AI가 함수를 잘못 읽고 틀린 설명을 적는 환각을 막기 위해서입니다.
- 결과마다 그 폴더의 역할이 함께 나오므로, 경로에 있는 문서를 모두 불러오지 않아도 서가의 맥락을 알 수 있습니다.
- 목록은 조회할 때 스스로 갱신됩니다. 수정 시각이나 크기가 바뀐 파일만 다시 읽습니다.
- `grep`은 코드 파일에서 정규식에 맞는 줄을 찾아, 각 줄을 그 줄이 들어 있는 정의 아래에 묶어 보여 줍니다. 그래서 어떤 함수를 누가 호출하는지, 어떤 필드를 누가 바꾸는지를 Grep과 추가 읽기 없이 한 번에 찾습니다. 문서처럼 코드가 아닌 파일은 Grep으로 찾습니다. 설계 근거는 [지식 관리 이론 조사](docs/research/knowledge-management.md)에 정리되어 있습니다.

### 훅

- **세션 시작**: 조회 방법을 알려 주고, 목록을 백그라운드에서 갱신하고, `maxDocLines`보다 긴 폴더 문서나 Markdown 규칙 파일을 경고합니다.
- **매 턴 종료**: 새 코드 폴더에 문서를 만들고, 하위 폴더 표를 고치고, 빈 역할을 채우라고 요청합니다. 한 번에 최대 10개 폴더만 나열합니다.

JavaScript/TypeScript 목록에는 리터럴 제목을 쓴 `test`, `it`, `describe`, `test.describe`
호출의 익명 블록 콜백도 들어갑니다. 예를 들어 `test('example')`입니다. 항목은 호출 대상에서
시작해 콜백의 닫는 중괄호에서 끝나며, 스위트 항목은 안쪽 테스트 항목을 포함합니다. 따옴표
문자열과 정적 템플릿 리터럴을 지원하고 `only`, `skip`, `concurrent`, `sequential`도
지원합니다. 테스트는 `fixme`, `fail`, `fails`를, 스위트는 `serial`, `parallel`을 추가로
받습니다. async 화살표 함수, 익명 함수, `test(title, details, callback)` 형식도 지원합니다.
import와 별칭은 해석하지 않고 호출 이름의 문법만 보고 인식합니다. 동적 제목, `each` 팩토리,
표현식 콜백, 콜백 참조, `beforeEach` 같은 훅은 제외합니다.
C 목록에는 `)`와 `{` 사이에 매개변수 선언이 오는 K&R 형식 정의도 들어갑니다.
Python 목록에는 함수 안에 정의된 함수와 클래스도 `outer.inner` 이름으로 들어갑니다. 다른 언어에서는 함수 본문 안의 정의가 목록에 없으므로 `grep` 명령으로 찾습니다. 메서드는 목록에 `Class.name`처럼 클래스 이름이 붙지만 `find '^name$'`로도 찾을 수 있습니다.

도서관을 설치하면 프로젝트에 다음이 추가됩니다.

```
.librarian/config.json      # 도서관 언어, 제외할 경로, 폴더 깊이 경고 기준(maxDepth),
                            # 문서 줄 수 제한(maxDocLines, 기본 60), 플러그인 버전(libraryVersion)
.librarian/.gitignore       # catalog.json을 git에서 제외
.librarian/catalog.json     # 파생 데이터, 자동으로 다시 만들어짐
<코드가 있는 모든 폴더>/CLAUDE.md
```

## 규칙 작성 스킬

`rule-creator` 스킬은 실수가 반복될 것 같을 때 규칙이나 빠진 맥락을 기록합니다. 구체적인 사례 뒤에 있는 일반적인 상황을 찾고, 기존 규칙을 확인한 뒤, 이유가 담긴 실행 가능한 지시 하나를 씁니다. 규칙은 필요할 때 Claude Code가 불러오는 가장 좁은 곳에 둡니다. 루트나 폴더 `CLAUDE.md`의 메모, 또는 `paths` frontmatter를 쓸 수 있는 `.claude/rules/`입니다. 문서가 `maxDocLines`를 넘으면 주제별로 묶어 옮깁니다. 스크립트는 경고만 하고 사람이 쓴 규칙을 고쳐 쓰지 않습니다.

## 요구 사항

- Claude Code
- Python 3.9 이상. 그 밖에 설치할 것은 없습니다. 목록은 Python 표준 라이브러리만으로 만듭니다.
- 지원 언어: Python, JavaScript/TypeScript/TSX, Go, Rust, Java, C/C++(K&R C 포함), C#, CSS. `outline`은 Markdown 파일의 제목도 보여 줍니다.

## 사람을 위한 지침

### 설치

Python 3.9 이상만 있으면 됩니다. Claude Code 안에서 아래 명령어를 입력한 다음 `/reload-plugins`를 실행하세요.

```
/plugin marketplace add j-token/agent-librarian
/plugin install agent-librarian@agent-librarian
```

터미널에서 설치할 수도 있습니다.

```bash
claude plugin marketplace add j-token/agent-librarian
claude plugin install agent-librarian@agent-librarian
```

설치가 끝나면 아래 명령어로 여러분을 위한 "도서관"을 지으세요.

### 기존 코드 베이스가 있는 경우

> 경고! 이 명령어는 플러그인의 Sonnet 에이전트로 코드가 있는 모든 폴더의 역할을 작성합니다. 추가 요금이 발생할 수 있으니 주의하세요!

1. 아래 명령어를 입력합니다.

    `/rebuild-library`

2. 필요한 질문에 응답해주세요. 첫 질문은 도서관 언어입니다.

3. 각 CLAUDE.md에 적힌 폴더 역할이 적절한지 확인하세요.

### 기존 코드 베이스가 없는 경우

1. 아래 명령어를 입력합니다.

    `/build-library`

2. 필요한 질문에 응답해주세요. 첫 질문은 도서관 언어입니다.

3. 루트의 CLAUDE.md와 `.librarian/config.json`의 설정을 확인하세요.

### 플러그인을 업데이트한 뒤

`/plugin update agent-librarian@agent-librarian`을 실행한 뒤 플러그인을 다시 불러오거나 Claude Code를 재시작하세요.

플러그인을 업데이트해도 이미 만든 도서관은 바뀌지 않습니다. 업데이트한 뒤에는 `/update-library`를 실행하세요. 도서관이 예전 버전으로 만들어졌으면 매 턴 종료 훅도 알려 줍니다. 이 스킬은 설정 항목을 현재 버전에 맞추고, 이미 쓴 역할은 그대로 둔 채 모든 폴더 문서를 현재 형식으로 고치고, 목록을 만듭니다.

0.6 이하에서 올라오는 경우, 모든 `CLAUDE.md`에서 생성된 인덱스가 빠지고 생성된 `index.md`, `index/` 파일은 지워집니다. 정의 위치는 목록으로 옮겨 갑니다. `AGENTS.md`에 있던 폴더 문서는 `CLAUDE.md`로 옮겨집니다. 예전 버전이 코드가 없는 폴더에 만든 문서는 지우지 않고 알려만 줍니다. 예전 버전으로 만든 도서관에는 관리지침 스킬(`librarian-guide`)이 있었습니다. `/update-library`는 그 스킬의 연결과 `.gitignore` 항목을 지우고, `.librarian/skills/librarian-guide`는 직접 추가한 내용을 옮긴 뒤 지우라고 알려 줍니다.

## 에이전트를 위한 지침

사용자를 대신해 이 플러그인을 설치하거나 사용하는 AI 에이전트를 위한 절입니다.

### 사용자를 위해 설치할 때

1. `python --version`이 3.9 이상인지 확인합니다. Python이 없으면 사용자에게 설치를 요청합니다. 그 밖의 의존성은 없습니다.
2. 위 "설치"의 `claude plugin …` 터미널 명령으로 플러그인을 설치합니다.
3. 에이전트가 직접 할 수 없어서 사용자에게 요청해야 하는 단계가 있습니다.
   - `/reload-plugins` 실행
   - `/rebuild-library`(기존 코드베이스) 또는 `/build-library`(새 프로젝트) 실행. 이 스킬들은 모델이 호출할 수 없고, 도서관 언어 같은 질문을 사용자에게 합니다.
4. `/rebuild-library`는 코드가 있는 폴더 수에 비례해 토큰 비용이 든다고 사용자에게 알립니다.

### 도서관이 있는 프로젝트에서 작업할 때

루트에 `.librarian/config.json`이 있으면 도서관이 있는 프로젝트입니다. 손볼 곳이 생기면 훅이 알려 줍니다. 핵심은 다음과 같습니다.

- 이름으로 정의를 찾을 때는 세션 시작 안내의 `find` 명령을, 파일이나 폴더에 무엇이 정의되어 있는지 볼 때는 `outline`을 씁니다. 그다음 알려 준 범위를 읽습니다. 함수 이름만 보고 동작을 추측하지 않습니다.
- 코드 안의 호출 위치, 필드 변경, 문자열은 `grep` 명령으로 찾습니다. 일치한 줄마다 그 줄을 담은 함수가 함께 나옵니다. 다른 파일은 Grep으로 찾습니다. 역참조는 어디에도 기록하지 않습니다.
- 문서에 함수나 파일이 무엇을 하는지 적지 않고, `.librarian/catalog.json`은 수정하지 않습니다.
- 코드 폴더를 새로 만들면 그 폴더의 역할 섹션과 부모 문서 하위 폴더 표의 역할 칸을 도서관 언어(`.librarian/config.json`의 `language`)로 채웁니다. 매 턴 종료 훅이 빈 역할을 채우라고 요청하면 코드를 읽고 폴더의 역할만 씁니다.
- 훅이 폴더 깊이 초과를 경고하면 사용자에게 알립니다. 폴더 구조는 임의로 바꾸지 않습니다.
- 훅이 사람이 쓴 문서 본문의 길이를 경고하면 `rule-creator`로 각 규칙의 범위를 지키면서 내용을 묶고 줄입니다.
- 매 턴 종료 훅이 도서관이 예전 플러그인 버전으로 만들어졌다고 알리면 사용자에게 `/update-library` 실행을 요청합니다. 이 스킬은 모델이 호출할 수 없습니다.

## 기여하기

[CONTRIBUTING.md](CONTRIBUTING.md)를 참고하세요. 영어로 작성되어 있습니다.

## 라이선스

[Apache License 2.0](LICENSE)
