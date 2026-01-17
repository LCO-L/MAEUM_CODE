"""
================================================================================
                        MAEUM_CODE 설계도 v0
================================================================================

0) 목표
-------
사용자는 행동만 던진다:
1. 설계도 펼치기(레포/트리)     → ARCH_SNAPSHOT
2. 맥락 선언("지금 MVP", "실험") → CONTEXT_SET
3. 오류 붙여넣기(로그/스택)      → ERROR_CUT
4. 경로 던지기(/src/.../x.ts)   → PATH_JUDGE

MAEUM_CODE는 자동으로 분류해서 정해진 최소 출력만 내고,
애매하면 번호로 1회 되묻는다.


1) 시스템 구성
-------------

1.1 모듈
~~~~~~~~
- InputBuffer: 입력(멀티라인) 수집
- ActionClassifier: 행동 분류 + 신뢰도(confidence)
- Clarifier: 애매할 때 1회 되묻기
- ContextStore: 맥락 상태 저장(세션 단위)
- Analyzers
    - ArchSnapshotAnalyzer: 트리/레포 구조 스냅샷
    - ErrorCutAnalyzer: 에러 원인 1 + 조치 1
    - PathJudgeAnalyzer: 파일 역할 + 지금 만져도 되는지
- Renderer: 출력 포맷 강제(짧게, 고정 틀)


1.2 데이터 모델(필수)
~~~~~~~~~~~~~~~~~~~~
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, List, Dict, Any


# -----------------------------------------------------------------------------
# Action Types
# -----------------------------------------------------------------------------
class ActionType(Enum):
    """행동 분류 타입 - 우선순위 순서대로 정의"""
    ERROR_CUT = auto()      # 1순위: 오류 붙여넣기
    PATH_JUDGE = auto()     # 2순위: 경로 던지기
    CONTEXT_SET = auto()    # 3순위: 맥락 선언
    ARCH_SNAPSHOT = auto()  # 4순위: 설계도 펼치기
    CLARIFY = auto()        # 애매할 때 되묻기
    SILENT = auto()         # 분류 실패 시 침묵


# -----------------------------------------------------------------------------
# Context Store Model
# -----------------------------------------------------------------------------
class Phase(Enum):
    """개발 단계"""
    MVP = "MVP"
    EXPERIMENT = "EXPERIMENT"
    REFACTOR = "REFACTOR"
    STABILIZE = "STABILIZE"


class Tolerance(Enum):
    """허용 수준"""
    HIGH = "HIGH"      # MVP/실험 - 대부분 GO
    MEDIUM = "MEDIUM"  # 일반 - 상황 따라
    LOW = "LOW"        # 안정화 - 엄격


@dataclass
class ContextState:
    """맥락 상태 - 세션 단위로 유지"""
    phase: Phase = Phase.MVP
    tolerance: Tolerance = Tolerance.HIGH
    notes: List[str] = field(default_factory=list)


# -----------------------------------------------------------------------------
# Action Result Model
# -----------------------------------------------------------------------------
@dataclass
class ActionResult:
    """행동 분류 + 분석 결과"""
    action: ActionType
    confidence: float  # 0.0 ~ 1.0
    payload: Dict[str, Any] = field(default_factory=dict)


# -----------------------------------------------------------------------------
# File Role Classification
# -----------------------------------------------------------------------------
class FileRole(Enum):
    """파일 역할 분류"""
    ENTRY = "entry"           # controller/route/handler
    CORE = "core"             # service/usecase
    INFRA = "infra"           # repo/dao/db/infra
    TEST = "test"             # test/spec
    PERIPHERAL = "peripheral" # 그 외


class Decision(Enum):
    """GO/NO-GO 판정"""
    GO = "GO"
    NO_GO = "NO-GO"


# -----------------------------------------------------------------------------
# Pattern Definitions
# -----------------------------------------------------------------------------
@dataclass
class PatternRule:
    """패턴 규칙 정의"""
    name: str
    signals: List[str]
    required_roles: List[str] = field(default_factory=list)
    flow: List[str] = field(default_factory=list)  # e.g., ["controller -> service -> model"]
    max_file_distance: int = 2
    severity: str = "MEDIUM"  # HIGH/MEDIUM/LOW


# -----------------------------------------------------------------------------
# Semantic Graph Models
# -----------------------------------------------------------------------------
@dataclass
class FileNode:
    """파일 노드"""
    path: str
    imports: List[str] = field(default_factory=list)
    exports: List[str] = field(default_factory=list)
    functions: List[str] = field(default_factory=list)
    role: Optional[FileRole] = None


@dataclass
class EntityNode:
    """개념(Entity) 중심 노드"""
    name: str
    roles: Dict[str, str] = field(default_factory=dict)  # role -> file_path
    edges: List[str] = field(default_factory=list)  # 연결된 다른 Entity


@dataclass
class SemanticGraph:
    """의미 그래프"""
    files: List[FileNode] = field(default_factory=list)
    entities: List[EntityNode] = field(default_factory=list)
    pattern_scores: Dict[str, float] = field(default_factory=dict)
    violations: List[str] = field(default_factory=list)


"""
================================================================================
2) 행동 자동분류 로직
================================================================================

2.1 분류 우선순위(고정)
~~~~~~~~~~~~~~~~~~~~~~
ERROR → PATH → CONTEXT → ARCH → UNKNOWN

이 순서가 오분류를 최소화함


2.2 Hard Signal(결정 신호) 규칙
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

ERROR_CUT
---------
- Traceback, Exception, Error:, Caused by, at <func>(...), AssertionError, FAILED
- 스택 형태(여러 줄 + 반복 패턴)

정규식:
    (Traceback|Exception|Error:|Caused by|AssertionError|at \\w+\\()


PATH_JUDGE
----------
- 경로 형태 + 확장자(.ts .js .py .go .java ...)
- / 또는 ./ 포함, 공백 거의 없음

정규식:
    ^(./|/|[A-Za-z0-9_-]+/)+[A-Za-z0-9._-]+.(ts|js|py|go|java|kt|rs)$


CONTEXT_SET
-----------
- 1~3줄 자연어
- 질문/명령형 적음
- 키워드: 지금, MVP, 실험, 임시, 리팩토링, 급함, 나중에

판정:
    키워드 점수 >= 임계치 AND (에러/경로/트리 신호 없음)


ARCH_SNAPSHOT
-------------
- 트리 기호: ├──, └──, │
- 폴더 나열이 다수 줄
- src/, app/ 등 + 여러 엔트리


================================================================================
3) "실수하면 되묻기" 설계 (프로세스 늘리지 않기)
================================================================================

3.1 되묻기 트리거
~~~~~~~~~~~~~~~~
- 두 액션이 동시에 강하게 잡힘 (예: PATH + ERROR 일부)
- confidence < threshold
- UNKNOWN


3.2 되묻기 출력(고정, 1회)
~~~~~~~~~~~~~~~~~~~~~~~~

    이건 뭐로 볼까?
    1) 구조 펼치기
    2) 오류 컷
    3) 경로 판단
    4) 맥락 설정

- 사용자가 1~4 입력하면 즉시 해당 Analyzer 실행
- 추가 질문 금지
- 번호 입력이 아니면: 보류 한 줄 출력 후 종료


================================================================================
4) 각 행동의 "최소 반응" 스펙
================================================================================

4.1 ARCH_SNAPSHOT 출력(4줄 제한 권장)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    [SNAPSHOT]
    Core: <top domains 1~3>
    Flow: <dominant flow>
    State: <phase>

- 설명/개선 제안 금지
- "상태판"만


4.2 CONTEXT_SET 동작(무출력)
~~~~~~~~~~~~~~~~~~~~~~~~~~
- ContextStore 업데이트만 하고 출력 없음
- 다음 ERROR/PATH/ARCH 분석에만 영향

예:
    "지금 MVP, 빨리 돌아가게"
    → phase=MVP, tolerance=HIGH


4.3 ERROR_CUT 출력(원인 1 + 조치 1)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    [ERROR]
    원인: <most likely 1>
    조치: <one action 1>

원인 후보를 나열하지 마라.


4.4 PATH_JUDGE 출력(역할 + GO/NO-GO)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    [PATH]
    Role: <entry/core/peripheral/test/infra>
    Decision: GO | NO-GO

Role 분류 v0 룰:
- 경로에 controller|route|handler → entry
- service|usecase → core logic
- repo|dao|db|infra → infra
- test|spec → test
- 그 외 → peripheral

Decision 룰(맥락 반영):
- tolerance=HIGH면 대부분 GO
- 보안/권한/데이터 경로면 기본 MEDIUM 이상


================================================================================
5) CLI UX 설계
================================================================================

권장 커맨드 최소 3개:
    maeum .                  : 현재 디렉토리 → ARCH_SNAPSHOT
    maeum /path/to/file.ts   : PATH_JUDGE
    maeum + stdin 붙여넣기    : ERROR/CONTEXT 자동분류
    maeum --ctx "지금 MVP"   : CONTEXT_SET (무출력)


================================================================================
6) 구현 순서 (가장 빠른 MVP)
================================================================================

1. Classifier + Clarifier (되묻기까지)
2. ContextStore (phase/tolerance)
3. PATH_JUDGE (룰 기반)
4. ERROR_CUT (시그니처 룰 기반)
5. ARCH_SNAPSHOT (트리 요약 v0)


================================================================================
7) MAEUM 철학 연결
================================================================================

- AI가 코드 위에 군림 ❌
- 인간이 만든 규칙을 AI가 지킴 ⭕
- 주권: 팀
- 실행: MAEUM_CODE
더 똑똑한 LLM 필요 없음, 더 긴 컨텍스트 필요 없음.
"코드를 먼저 구조화하고, LLM은 판사로 쓰는 구조"가 전부다.
"""
