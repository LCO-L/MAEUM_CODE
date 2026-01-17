# MAEUM_CODE

AI 코딩 어시스턴트

**핵심 철학**: 코드를 토큰으로 읽지 않는다. 구조 → 의미 → 패턴 → 의도 순으로 재조합한다.

---

## 실행

```bash
cd MAEUM_CODE/CUSTOM
python run.py
```

```
  MAEUM_CODE  ─  /path
  (빈 줄로 전송, /q 종료)

> .

[SNAPSHOT]
Core: user, auth, payment
Flow: controller → service → repository
Pattern: MVC

> src/user/user.controller.ts

[PATH]
Role: entry
Decision: GO

> TypeError: Cannot read property 'id' of undefined

[ERROR]
원인: user 객체가 null/undefined 상태에서 .id 접근
조치: user 존재 여부 체크 추가 (if (!user) return)

> 지금 MVP 빨리

(무출력 - 상태만 변경)
```

---

## 행동 자동분류

사용자는 행동만 던진다. MAEUM_CODE가 자동 분류:

| 행동 | 트리거 | 출력 |
|-----|-------|------|
| **ARCH_SNAPSHOT** | `.`, 트리 구조, 폴더 나열 | 구조 스냅샷 4줄 |
| **ERROR_CUT** | Traceback, Error, 스택 | 원인 1 + 조치 1 |
| **PATH_JUDGE** | `/src/.../*.ts` | Role + GO/NO-GO |
| **CONTEXT_SET** | "지금 MVP", "실험" | 무출력 (상태 변경) |
| **CLARIFY** | 애매할 때 | 1회 되묻기 |
| **SILENT** | 분류 실패 | AI에게 전달 |

### 분류 우선순위 (고정)

```
ERROR → PATH → CONTEXT → ARCH → SILENT
```

---

## 되묻기 (CLARIFY)

두 신호가 동시에 잡히면:

```
이건 뭐로 볼까?
1) 구조 펼치기
2) 오류 컷
3) 경로 판단
4) 맥락 설정
```

번호 입력 → 즉시 실행. 추가 질문 없음.

---

## 맥락 상태 (Context)

| Phase | Tolerance | 설명 |
|-------|-----------|------|
| MVP | HIGH | 대부분 GO |
| EXPERIMENT | HIGH | 실험 중 |
| REFACTOR | MEDIUM | 정리 중 |
| STABILIZE | LOW | 엄격 |

```
> 지금 MVP 빠르게
```
→ phase=MVP, tolerance=HIGH (무출력)

---

## PATH_JUDGE 상세

### Role 분류

| Role | 키워드 |
|------|--------|
| entry | controller, route, handler, api |
| core | service, usecase, domain |
| infra | repo, dao, db, storage |
| test | test, spec |
| peripheral | 그 외 |

### Decision 규칙

- `tolerance=HIGH` → 대부분 GO
- 보안 경로 (auth, token, jwt, crypto, payment) → MEDIUM 이상에서 NO-GO

---

## 아키텍처

```
CUSTOM/
├── cli.py              # CLI (행동 던지기)
├── run.py              # 진입점
├── classifier.py       # 행동 자동분류
├── context_store.py    # 맥락 상태
├── code_writer.py      # 7860 AI 클라이언트
├── ARCHITECTURE.py     # 설계 문서 + 데이터 모델
│
├── agent/              # 에이전트 시스템
│   ├── loop.py        # Think → Act → Observe → Reflect
│   ├── memory.py      # 대화/컨텍스트 메모리
│   └── planner.py     # 작업 계획
│
├── tools/              # 도구
│   ├── base.py        # Tool, ToolResult, ToolRegistry
│   ├── file_tools.py  # Read, Write, Edit
│   ├── search_tools.py # Glob, Grep
│   └── bash_tool.py   # Bash
│
├── patterns/           # 패턴 사전
└── graph/              # 시맨틱 그래프
```

---

## 7860 AI 서버

`maeum_web_ui.py`가 7860 포트에서 실행 중이어야 함.

### API

| 엔드포인트 | 용도 |
|-----------|------|
| `POST /api/chat` | 대화 (coding_mode 지원) |
| `GET /api/health` | 상태 확인 |

### /api/chat 요청

```json
{
  "message": "사용자 메시지",
  "system_prompt": "시스템 프롬프트",
  "max_tokens": 4096,
  "coding_mode": true
}
```

---

## 도구

| 도구 | 설명 |
|-----|------|
| Read | 파일 읽기 |
| Write | 파일 쓰기 |
| Edit | 파일 수정 (old_string → new_string) |
| Glob | 파일 패턴 검색 |
| Grep | 내용 검색 |
| Bash | 명령어 실행 |

---

## 패턴 사전 (Pattern Vocabulary)

패턴은 찾는 게 아니라 정의한다:

```python
{
    "MVC": {
        "required_roles": ["controller", "service", "model"],
        "flow": ["controller -> service -> model"],
        "max_file_distance": 2
    },
    "LAYERED": {
        "layers": ["api", "domain", "infra"],
        "no_reverse_dependency": True
    }
}
```

LLM은 "검색자"가 아니라 "판별자":
- ❌ "이 프로젝트 구조 설명해줘"
- ✅ "이 그래프가 MVC_PATTERN을 만족하는지 판단해라"

---

## 시맨틱 그래프

폴더 → 트리 → 그래프 변환:

```
/src
  /api
    user.controller.ts
  /services
    user.service.ts
  /models
    user.model.ts
```

↓

```python
{
    "entity": "User",
    "roles": {
        "controller": "user.controller.ts",
        "service": "user.service.ts",
        "model": "user.model.ts"
    },
    "edges": ["auth", "payment"]
}
```

---

## CI/PR 연동 (확장)

```yaml
- name: MAEUM_CODE PR Review
  run: maeum-code analyze --mode=pr
```

Risk Score 기반 자동 리뷰:
- 0-30: Safe
- 31-60: Review Recommended
- 61-100: Block Suggested

---

## 조직 문화 학습 (확장)

```python
{
    "org": "Acme",
    "culture": {
        "speed_vs_safety": 0.65,
        "rule_strictness": {
            "AUTH_FLOW": "HIGH",
            "MVC_PURITY": "LOW"
        }
    }
}
```

- 문화는 선언이 아니라 행동 로그
- 규칙은 고정, 강도만 학습
- LLM은 입, MAEUM은 뇌

---

## MAEUM 철학

- AI가 코드 위에 군림 ❌
- 인간이 만든 규칙을 AI가 지킴 ⭕
- 주권: 팀
- 실행: MAEUM_CODE

> "MAEUM_CODE는 코드를 관리하지 않습니다. 조직이 일하는 방식을 관리합니다."
