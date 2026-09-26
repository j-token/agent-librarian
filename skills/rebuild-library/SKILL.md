---
name: rebuild-library
description: 기존 코드베이스 전체를 스캔해서 claude-librarian 도서관을 만들거나 다시 만든다. 인덱스는 스크립트로 생성하고, 폴더 역할은 에이전트가 가장 깊은 폴더부터 채운다.
disable-model-invocation: true
---

# 도서관 재건 (기존 코드베이스)

`<plugin>`은 이 SKILL.md에서 두 단계 위 폴더, 즉 플러그인 루트다. 명령은 프로젝트 루트에서 실행한다.

## 0. 비용 경고

시작하기 전에 사용자에게 알린다. 코드베이스 전체를 읽고 폴더마다 역할을 작성하므로 폴더 수에 비례해 토큰 비용이 든다. Claude Code에서는 Sonnet 서브에이전트를 쓴다.

## 1. 질문과 의존성

`<plugin>/skills/build-library/SKILL.md`의 1~2단계를 똑같이 진행한다. 이미 `.librarian/config.json`이 있으면 기존 값을 보여 주고, 바꿀지만 묻는다.

## 2. 기계적인 부분 먼저 채우기

```bash
python <plugin>/scripts/librarian.py init --doc <답1> --targets <답2> [--exclude ...]
python <plugin>/scripts/librarian.py scaffold
python <plugin>/scripts/librarian.py index --all
```

이 단계가 끝나면 모든 폴더에 문서가 있고, 인덱스(파일 · 함수 · 줄)가 채워진 상태가 된다.

## 3. 역할 채우기 (가장 깊은 폴더부터)

`python <plugin>/scripts/librarian.py pending`은 역할이 비어 있는 폴더를 가장 깊은 폴더부터 출력한다. 하위 폴더의 역할이 먼저 정해져야 상위 폴더가 그것을 한 줄로 요약할 수 있으므로 **이 순서를 지킨다.**

- **서브에이전트를 쓸 수 있을 때** (Claude Code)
  - 같은 깊이의 폴더들을 묶어 `folder-cataloger` 에이전트에게 병렬로 맡긴다. 에이전트 하나에 폴더 5~10개 정도가 적당하다.
  - 작업 지시에 두 가지를 넣는다: 담당 폴더 문서 경로들, 그리고 규칙 파일 경로 `<plugin>/skills/rebuild-library/references/cataloger.md`.
  - 한 깊이의 작업이 모두 끝난 뒤에 다음(더 얕은) 깊이로 넘어간다.
- **서브에이전트를 쓸 수 없을 때** (Codex 등): `references/cataloger.md`를 읽고, 같은 순서로 직접 하나씩 채운다.

## 4. 검증과 보고

```bash
python <plugin>/scripts/librarian.py check
```

사용자에게 보고할 내용:
- 생성한 문서 수
- 남은 `역할 작성 필요` 항목
- 분리 권고(`경고`) 항목. 폴더 구조는 임의로 바꾸지 않고 사용자에게 제안만 한다.

그리고 build-library의 5단계 안내를 똑같이 한다.
