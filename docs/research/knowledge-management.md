# 지식 관리 이론 조사: 미국 도서관학 · 위키피디아 · 나무위키

> 조사일: 2026-09-26
> 목적: agent-librarian의 "폴더별 CLAUDE.md/AGENTS.md 계층 문서" 설계에 쓸 이론적 근거 수집

## 대상 설계 요약

- 루트 문서: 최상위 폴더 각각의 역할만 적음
- 중간 폴더 문서: 바로 아래 하위 폴더의 역할만 적음
- 말단 폴더 문서: `파일명 · 함수명 · 줄 번호`만 적고, 함수가 하는 일은 적지 않음 (환각 방지)
- 에이전트는 위에서 아래로 한 단계씩 내려가며 필요한 문서만 읽음 (컨텍스트 관리)

---

## 1. 설계 원칙별 근거 매핑

| 설계 원칙 | 도서관학 | 위키피디아 | 나무위키 |
|---|---|---|---|
| 각 계층은 자기 바로 아래만 기술하고, 계층 사이에 정보를 반복하지 않는다 | DACS / ISAD(G) 다계층 기술 규칙 | WP:SUMMARY (상위 문서는 요약 + `{{Main}}` 포인터) | 하위 문서(`/`) 구조 |
| 말단 문서는 위치만 적고 설명은 적지 않는다 | 청구기호는 주소이지 설명이 아님, 대리물(surrogate)과 원본 구분, Cutter의 finding/choice 목적 구분 | WP:V (검증 가능성), WP:NOR (독자연구 금지) | 독자연구 금지 규정이 없어 생긴 문제를 스스로 비판함 (반면교사) |
| 파일은 가장 가까운 폴더 문서에만 기록한다 | LCSH 특정 표목(specific entry) 원칙 | WP:SUBCAT (상위와 하위 분류에 중복 등록 금지) | 나무위키:분류 (가장 좁은 분류에만 넣음) |
| 문서가 너무 커지면 나눈다 | Ranganathan 제5법칙 (도서관은 성장하는 유기체) | WP:SIZERULE, WP:DIFFUSE | 문서 분리 기준 (150자 이상 문단 5개 이상 등) |
| 같은 대상을 두 곳에서 기술하지 않는다 | 전거통제 (한 개념에 승인된 표목 하나) | WP:MERGE, WP:CFORK, Wikidata의 단일 진실 원천 | 문서 병합 규정 |
| 문서 구조는 실제 폴더 구조를 그대로 따른다 | 출처 존중(respect des fonds), 원질서 존중 | (본문 이름공간에서 하위 문서 금지. 설계 방향이 다름) | 하위 문서 계층을 공식 규정으로 둠 |
| 낡은 문서는 없는 문서보다 나쁘다 | CREW / MUSTIE의 Misleading, Superseded | Link rot 대응 봇, 유지보수 틀 | 깨진 링크는 3시간 안에 고쳐야 함 |
| 역참조는 문서에 적지 않고 실시간으로 조회한다 | — | Special:WhatLinksHere (소프트웨어 기능) | 역링크 (엔진이 자동 계산) |
| 처리는 최소로, 제공 범위는 넓게 | MPLP (Greene & Meissner 2005) | 스텁 (일단 만들고 점진적으로 보강) | — |
| 읽는 사람의 시간을 아낀다 | Ranganathan 제4법칙 (독자의 시간을 절약하라) | MOS:LEAD | — |

---

## 2. 미국/영미권 도서관학 · 기록관리학

### 2.1 Ranganathan의 도서관학 5법칙 (1931)
1. 책은 이용하기 위한 것이다
2. 모든 독자에게 그의 책을
3. 모든 책에게 그 독자를
4. **독자의 시간을 절약하라**
5. **도서관은 성장하는 유기체다**

- 제4법칙은 "필요한 문서만 읽는다"는 이 설계의 목표 그 자체입니다.
- 제5법칙에 따라 구조는 자라는 것을 전제로 설계해야 합니다. 분리 기준과 재편 절차가 필요합니다.
- 패싯 분류(PMEST)는 직접 적용하지 않습니다. 다만 폴더 이름을 지을 때 "무엇에 관한 것인가"와 "무엇을 하는가"를 분리해서 생각하는 데 참고할 수 있습니다.
- 출처: https://en.wikipedia.org/wiki/Five_laws_of_library_science , https://en.wikipedia.org/wiki/Faceted_classification

### 2.2 Cutter의 목록의 목적 (1876)
- **Finding**(찾기), **Collocating**(모으기), **Choice**(고르기)
- 목록은 찾기와 모으기를 맡습니다. 무엇을 고를지는 이용자가 원본을 직접 보고 판단합니다.
- 이 설계에 대응시키면, 문서가 finding/collocating을 맡고, "이 함수가 무엇을 하는가"(choice)는 에이전트가 코드를 직접 열어 판단합니다.
- 출처: https://www.librarianshipstudies.com/2020/03/charles-ammi-cutters-objects-catalogue-objectives-library-catalog.html

### 2.3 DDC / LCC와 청구기호
- 분류 기호의 자릿수가 곧 계층 깊이입니다 (500 과학 → 530 물리학).
- **청구기호는 서가에서의 주소이지 내용 설명이 아닙니다.** 청구기호만 보고는 책의 내용을 알 수 없습니다.
- 말단 문서의 줄 번호도 같은 역할입니다. 위치를 가리킬 뿐 내용을 설명하지 않습니다.
- 출처: https://www.oclc.org/content/dam/oclc/dewey/versions/print/intro.pdf , https://unitproj.library.ucla.edu/cataloging/callnumbers/callpt21.htm

### 2.4 LCSH: 통제어휘와 전거통제
- 한 개념에는 승인된 표목 하나만 씁니다. 동의어는 "see" 참조로 안내합니다.
- 관계는 BT(상위어), NT(하위어), RT(관련어)로 표시합니다. NT는 BT를 뒤집어 자동으로 생성합니다.
  - 이 설계에 대응시키면, 하위 목록은 실제 폴더 구조에서 자동으로 나와야 합니다.
- **문헌적 근거(literary warrant)**: 표목은 실제 자료에 근거해야만 추가합니다.
- **특정 표목(specific entry)**: 내용과 정확히 일치하는 가장 구체적인 표목을 씁니다.
- 출처: https://www.loc.gov/catworkshop/lcsh/PDF%20scripts/2-1-Structural-Overview.pdf , https://www.isko.org/cyclo/literary_warrant

### 2.5 기록물 정리: DACS / ISAD(G) — 이 설계에 가장 직접적으로 대응하는 이론
- 계층: **fonds(전체) > series > file > item**
- **다계층 기술(multilevel description) 규칙**
  1. 일반에서 구체로 기술한다
  2. 각 계층에는 그 계층에 해당하는 정보만 적는다
  3. 계층을 서로 연결한다
  4. **상위 계층에 적은 정보를 하위 계층에서 반복하지 않는다**
- **출처 존중(respect des fonds)과 원질서 존중**: 생산자가 만든 원래 구조를 유지합니다. 이 설계에 대응시키면, 문서가 실제 폴더 구조를 그대로 따르고 가상의 분류를 덧씌우지 않는 것입니다.
- **MPLP(More Product, Less Process, 2005)**: 모든 항목을 정밀하게 기술하려다 적체가 생깁니다. 최소한으로 처리하고 빠르게 접근할 수 있게 하라는 주장입니다. 말단 문서에서 설명을 생략하는 것과 같은 판단입니다.
- 출처: https://www2.archivists.org/standards/DACS/part_I/chapter_1 , https://en.wikipedia.org/wiki/ISAD(G) , https://en.wikipedia.org/wiki/Respect_des_fonds , https://www2.archivists.org/sites/all/files/MPLP-AmericanArchivist-2005.pdf
- 한계: ISAD(G) 원문 PDF는 직접 확인하지 못했고, 2차 출처로 확인했습니다.

### 2.6 CREW / MUSTIE (장서 폐기)
- **M**isleading(내용이 틀림), **U**gly(훼손), **S**uperseded(더 나은 자료로 대체됨), **T**rivial(가치 없음), **I**rrelevant(수요와 무관), **E**lsewhere(다른 곳에서 구할 수 있음)
- 문서에 적용하면 이렇습니다. 코드와 어긋난 문서는 Misleading이고, 리팩터링으로 사라진 함수는 Superseded입니다. 정기적으로 다시 검증하는 절차가 필요합니다.
- 출처: https://www.tsl.texas.gov/ld/pubs/crew/index.html

### 2.7 메타데이터 유형 (NISO)
- 기술(descriptive), 구조(structural), 관리(administrative) 메타데이터
- 이 설계에 대응시키면, 폴더 역할은 기술 메타데이터이고, 하위 목록과 파일·함수·줄 번호는 구조 메타데이터입니다.
- 출처: https://groups.niso.org/higherlogic/ws/public/download/17446/Understanding%20Metadata.pdf , https://www.dublincore.org/specifications/dublin-core/dces/

### 2.8 대리물(surrogate)과 원본
- 목록 레코드는 자료의 대리물입니다. **무엇이 참인지는 항상 원자료가 정합니다.**
- 대리물에 요약을 넣으면 두 가지 위험이 생깁니다. 요약이 원본과 어긋날 수 있고, 대리물을 원본처럼 믿게 됩니다.
- 출처: https://www.loc.gov/catdir/catmodes.html

---

## 3. 위키피디아

### 3.1 분류 (WP:CAT, WP:SUBCAT, WP:DIFFUSE)
- 문서는 **가장 구체적인 분류에만** 넣습니다. 상위 분류와 하위 분류에 동시에 넣지 않습니다.
- 분류가 너무 커지면 하위 분류로 분산(diffuse)합니다. 분산된 분류는 하위 분류만 갖습니다.
- 출처: https://en.wikipedia.org/wiki/Wikipedia:Categorization

### 3.2 요약 양식과 분리 (WP:SUMMARY, WP:SIZERULE)
- 상위 문서는 하위 문서를 요약하고 `{{Main}}`으로 가리킵니다.
- 분량 기준(읽을 수 있는 본문 기준): 6,000단어 미만은 분리 불필요, 8,000단어 초과는 검토, 9,000단어 초과는 대체로 분리, 15,000단어 초과는 거의 확실히 분리
- 출처: https://en.wikipedia.org/wiki/Wikipedia:Summary_style , https://en.wikipedia.org/wiki/Wikipedia:Article_size

### 3.3 병합과 콘텐츠 포크 (WP:MERGE, WP:CFORK)
- 같은 범위를 다루는 문서가 둘이면 병합합니다. 콘텐츠 포크는 금지입니다.
- 출처: https://en.wikipedia.org/wiki/Wikipedia:Merging , https://en.wikipedia.org/wiki/Wikipedia:Content_forking

### 3.4 동음이의어, 넘겨주기, 제목 규칙 (WP:DAB, WP:REDIRECT, WP:AT)
- 제목 기준 다섯 가지: 인식 가능성, 자연스러움, 정확성, 간결성, 일관성
- 같은 이름의 함수가 여러 폴더에 있을 때는 경로와 이름을 함께 써서 구분합니다.
- 출처: https://en.wikipedia.org/wiki/Wikipedia:Disambiguation , https://en.wikipedia.org/wiki/Wikipedia:Article_titles

### 3.5 검증 가능성과 독자연구 금지 (WP:V, WP:NOR)
- "포함 기준은 진실이 아니라 검증 가능성이다." 입증 책임은 내용을 추가하는 편집자에게 있습니다.
- 출처에 명시되지 않은 결론을 조합해서 만들어내는 것(synthesis)도 금지합니다.
- 이 설계에 대응시키면, 함수 설명은 에이전트의 독자연구입니다. 줄 번호는 누구나 검증할 수 있는 사실입니다.
- 출처: https://en.wikipedia.org/wiki/Wikipedia:Verifiability , https://en.wikipedia.org/wiki/Wikipedia:No_original_research

### 3.6 도입부, 내비박스, 관련 항목, 목록, 스텁
- MOS:LEAD: 도입부는 그 자체로 완결된 개요여야 합니다.
- WP:CLN: 분류, 목록, 내비박스는 **서로 중복이 아니라 보완 관계**입니다. 폴더를 가로지르는 인덱스를 따로 두어도 된다는 근거가 됩니다.
- 스텁: 일단 만들고 점진적으로 보강합니다.
- 출처: https://en.wikipedia.org/wiki/Wikipedia:Manual_of_Style/Lead_section , https://en.wikipedia.org/wiki/Wikipedia:Categories,_lists,_and_navigation_templates , https://en.wikipedia.org/wiki/Wikipedia:Stub

### 3.7 유지보수: 토론 문서, 유지보수 틀, 봇
- InternetArchiveBot 같은 봇이 링크 부패(link rot)를 자동으로 처리합니다.
- 이 설계에 대응시키면, 줄 번호가 코드와 어긋나는 문제를 스크립트나 훅으로 자동 검증하고 갱신해야 합니다.
- 출처: https://en.wikipedia.org/wiki/Wikipedia:Link_rot , https://en.wikipedia.org/wiki/Wikipedia:WikiProject

### 3.8 Wikidata: 단일 진실 원천
- 구조화된 사실은 한 곳에서만 관리하고, 각 위키는 그것을 불러다 씁니다.
- 이 설계에 대응시키면, 파일·함수·줄 번호는 코드에서 기계적으로 추출해서 생성해야 합니다.
- 출처: https://www.wikidata.org/wiki/Wikidata:Introduction

### 3.9 Special:WhatLinksHere
- 역참조는 문서가 아니라 소프트웨어 기능입니다.
- 이 설계에 대응시키면, "누가 이 함수를 쓰는가"는 문서에 적지 않고 grep이나 LSP로 실시간 조회합니다.
- 출처: https://en.wikipedia.org/wiki/Help:What_links_here

---

## 4. 나무위키

### 4.1 하위 문서 (`/`)
- `문서명/하위 특성` 형식입니다. **상위 문서는 최대 6단계까지** 허용합니다.
- 출처: https://namu.wiki/w/나무위키:편집지침/표제어

### 4.2 문서 분리 기준
- 개요, 여담, 관련 문서 문단을 빼고 **150자 이상 하위 문단이 5개 이상**이면 분리 대상입니다. 분리하면 문단 단계가 2단계 이상 줄어드는 경우도 해당합니다.
- 문서 전체에서 150자 이상 문단이 20개 이상이거나, 한 문단이 1,000자 이상이면 분량이 많다고 봅니다.
- **앞으로 내용이 크게 늘어날 것으로 예상되는 경우**도 분리 판단 요소입니다.
- 출처: https://namu.wiki/w/나무위키:기본방침/토론%20관리%20방침 (절 번호는 재확인 필요)

### 4.3 병합과 깨진 링크 처리
- 이동이나 병합으로 깨진 링크가 생기면 **3시간 안에** 역링크를 고치거나 넘겨주기를 만들어야 합니다.
- 1개월 이상 유지된 문서를 옮기면 옛 이름을 최소 1개월 동안 새 문서로 안내해야 합니다.
- 출처: https://namu.wiki/w/나무위키:기본방침/문서%20관리%20방침

### 4.4 분류
- **가장 좁은 분류에만** 넣습니다.
- 하위 문서가 늘어나면 중간 분류를 새로 만들어 재편합니다.
- 출처: https://namu.wiki/w/나무위키:분류

### 4.5 틀과 상위 문서 표시
- 하위 문서 최상단에 `틀:상위 문서`를 넣어 부모 문서로 가는 링크를 둡니다.
- 이 설계에 대응시키면, 각 CLAUDE.md 첫 줄에 부모 문서 경로를 적습니다. 정적 마크다운이라 자동 갱신이 안 되므로 스크립트로 생성해야 합니다.
- 출처: https://namu.wiki/w/나무위키:틀

### 4.6 동음이의어와 넘겨주기
- 괄호 구분자를 씁니다 (예: `배(과일)`, `배(탈것)`). 가장 널리 알려진 뜻은 구분자 없이 씁니다.
- 출처: https://namu.wiki/w/나무위키:편집지침/표제어

### 4.7 서술 원칙: 반면교사
- 나무위키 기본방침에는 "검증 가능성"이나 "독자연구 금지" 조항이 **확인되지 않았습니다.**
- 나무위키 스스로 `나무위키/비판 및 문제점/문서 서술 관련` 문서에서 "출처 없이 뇌피셜로 작성되는 부정확한 정보" 문제를 인정합니다.
- 이 설계는 위키피디아(출처를 강제)보다 더 엄격합니다. 서술 자체를 금지하는 방식입니다.
- 출처: https://namu.wiki/w/나무위키:기본방침 , https://namu.wiki/w/나무위키/비판%20및%20문제점/문서%20서술%20관련

### 4.8 나무위키와 위키피디아의 차이
- 위키피디아는 **본문 이름공간에서 하위 문서 기능을 꺼 두었습니다.** 엄격한 계층 조직을 지양하기 때문입니다. (https://en.wikipedia.org/wiki/Wikipedia:Subpages)
- 나무위키는 계층적 하위 문서를 규정으로 공식화했습니다.
- 폴더 구조는 원래 강한 계층이므로, 이 설계는 **나무위키 모델과 기록관리학의 다계층 기술**을 기본 뼈대로 삼는 것이 타당합니다. 위키피디아에서는 분류, 검증 가능성, 유지보수 원칙을 가져옵니다.

---

## 5. 설계에 대한 시사점

1. **줄 번호는 사람이나 LLM이 쓰지 말고 스크립트로 생성한다.**
   줄 번호는 코드를 한 줄만 고쳐도 어긋납니다(CREW의 Misleading, 위키피디아의 link rot).
   ctags나 tree-sitter 같은 파서로 추출하면 줄 번호 자체를 환각할 위험도 없습니다(Wikidata의 단일 진실 원천).
   검증 훅(pre-commit 등)으로 문서와 코드가 일치하는지 확인합니다.
2. **폴더 설명(기술 메타데이터)만 LLM이나 사람이 쓴다.** 폴더 역할 설명은 코드 내용이 조금 바뀌어도 거의 달라지지 않아서 쉽게 낡지 않습니다.
3. **각 문서 첫 줄에 상위 문서 경로를 적는다** (나무위키 `틀:상위 문서`, DACS의 계층 연결).
4. **파일은 가장 가까운 폴더 문서에만 적는다** (WP:SUBCAT, 나무위키:분류, LCSH 특정 표목).
5. **분리 기준을 둔다.** 예: 말단 문서의 항목이 N개를 넘으면 하위 폴더로 분리하도록 권고합니다 (WP:SIZERULE, 나무위키 분리 기준). 깊이는 6단계 안팎으로 제한하는 것을 검토합니다(나무위키의 6단계 제한).
6. **역참조는 적지 않는다.** grep이나 LSP로 대체합니다 (WhatLinksHere, 역링크).
7. **폴더를 이동하거나 이름을 바꾸면 해당 문서와 부모 문서를 즉시 갱신한다** (나무위키의 3시간 규정을 커밋 단위의 무결성 검사로 옮긴 것).
8. **폴더를 가로지르는 인덱스가 필요하면 별도 문서로 두어도 된다** (WP:CLN). 다만 필수는 아닙니다.

## 6. 조사 한계

- 나무위키 문서는 WebFetch 요약을 거쳐 인용했으므로 원문 문구와 조금 다를 수 있습니다. 문서 분리 기준의 절 번호도 불확실합니다.
- ISAD(G)는 원문 PDF가 아니라 2차 출처로 확인했습니다.
- 위키피디아의 See also, Stub, Citation needed 관련 내용은 검색 결과 발췌로만 확인했습니다.
- 5장의 코드 대응(매핑)은 이론을 코드에 적용한 **유추**이며, 각 원전이 직접 주장하는 내용이 아닙니다.
