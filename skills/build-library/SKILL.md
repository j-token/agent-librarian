---
name: build-library
description: 새 프로젝트(또는 코드가 거의 없는 프로젝트)에 claude-librarian 도서관을 설치한다. 설정 파일, 관리지침 스킬, 폴더 문서 뼈대를 만든다.
disable-model-invocation: true
---

# 도서관 짓기 (새 프로젝트)

`<plugin>`은 이 SKILL.md에서 두 단계 위 폴더, 즉 플러그인 루트다. 스크립트는 `<plugin>/scripts/librarian.py`에 있다. 명령은 프로젝트 루트에서 실행한다.

## 1. 질문

대화형 질문 도구가 있으면 그것으로 묻고, 없으면 일반 메시지로 묻는다.

1. **폴더 문서 이름**
   - `CLAUDE.md`: Claude Code 전용
   - `AGENTS.md`: Codex 등
   - `both`: 본문은 AGENTS.md에 쓰고, CLAUDE.md에는 `@AGENTS.md` 한 줄만 둔다
2. **관리지침 스킬을 연결할 경로** (복수 선택, 기본값은 전부)
   - `claude` → `.claude/skills`
   - `agents` → `.agents/skills`
   - `codex` → `.codex/skills`
3. **추가로 제외할 경로**
   - 기본 제외: `.gitignore`에 적힌 경로, 점(.)으로 시작하는 폴더, `node_modules`, `dist`, `build` 등

## 2. 의존성 확인

```bash
python -c "import tree_sitter_language_pack"
```

실패하면 사용자에게 `pip install -r <plugin>/requirements.txt`를 안내한다. 사용자가 동의하면 직접 실행한다.

## 3. 설치

```bash
python <plugin>/scripts/librarian.py init --doc <답1> --targets <답2 쉼표구분> [--exclude <답3>...]
python <plugin>/scripts/librarian.py scaffold
```

- `init`이 하는 일:
  - `.librarian/config.json`을 만든다.
  - `.librarian/skills/librarian-guide`를 설치하고 각 경로에 연결한다. Windows에서는 정션, 그 외 OS에서는 심볼릭 링크를 쓰고, 링크가 안 되면 복사한다.
  - 링크 경로를 `.gitignore`에 추가한다.
- `scaffold`는 문서가 없는 폴더에 뼈대를 만든다.

## 4. 역할 채우기

`python <plugin>/scripts/librarian.py pending` 목록에 폴더가 있으면, `<plugin>/skills/rebuild-library/references/cataloger.md`의 규칙에 따라 직접 채운다. 새 프로젝트라 폴더가 적으므로 서브에이전트는 쓰지 않는다.

## 5. 안내

- 루트 문서와 `.librarian/config.json`을 사용자에게 보여 주고, 규칙이 적절한지 확인해 달라고 요청한다.
- 이후 동작을 설명한다.
  - 파일을 편집하면 훅이 인덱스를 갱신한다.
  - 턴이 끝날 때 check 훅이 문서와 코드가 일치하는지 검사한다.
- Codex 사용자에게 두 가지를 안내한다.
  - `~/.codex/config.toml`에 `[features] hooks = true`가 필요하다.
  - Codex는 설치된 플러그인 훅을 `/hooks`에서 한 번 신뢰(trust)해야 실행한다.
