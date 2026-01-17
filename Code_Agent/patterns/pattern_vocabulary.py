"""
Pattern Vocabulary - 패턴 사전 정의

패턴은 미리 다 정의할 수 없다 →
"반복 구조를 수집하고, 이름을 붙이고, 재사용"해야 한다

이 파일은 하드코딩된 기본 패턴을 정의한다.
나중에 자동 학습으로 확장 가능.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional
from enum import Enum


class PatternSeverity(Enum):
    """위반 심각도"""
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass
class PatternDefinition:
    """패턴 정의"""
    name: str
    description: str
    signals: List[str]  # 패턴 신호 키워드
    required_roles: List[str] = field(default_factory=list)
    dependency_flow: List[str] = field(default_factory=list)  # "A -> B" 형태
    max_file_distance: int = 2
    severity: PatternSeverity = PatternSeverity.MEDIUM
    anti_patterns: List[str] = field(default_factory=list)  # 이러면 안 됨


# -----------------------------------------------------------------------------
# BUILTIN_PATTERNS - 기본 패턴 사전
# -----------------------------------------------------------------------------

BUILTIN_PATTERNS: Dict[str, PatternDefinition] = {

    # =========================================================================
    # 아키텍처 패턴
    # =========================================================================

    "MVC": PatternDefinition(
        name="MVC",
        description="Model-View-Controller 패턴",
        signals=["controller", "service", "model", "view"],
        required_roles=["controller", "service", "model"],
        dependency_flow=[
            "controller -> service",
            "service -> model",
        ],
        max_file_distance=2,
        severity=PatternSeverity.MEDIUM,
        anti_patterns=[
            "controller -> model",  # 직접 접근 금지
            "view -> model",        # 뷰가 모델 직접 접근 금지
        ]
    ),

    "LAYERED": PatternDefinition(
        name="LAYERED",
        description="계층형 아키텍처 (Presentation-Domain-Infrastructure)",
        signals=["api", "domain", "infra", "presentation", "infrastructure"],
        required_roles=["api", "domain", "infra"],
        dependency_flow=[
            "api -> domain",
            "domain -> infra",
        ],
        max_file_distance=3,
        severity=PatternSeverity.HIGH,
        anti_patterns=[
            "infra -> api",      # 역방향 의존 금지
            "infra -> domain",   # 역방향 의존 금지
        ]
    ),

    "CLEAN_ARCHITECTURE": PatternDefinition(
        name="CLEAN_ARCHITECTURE",
        description="클린 아키텍처 (Entities-UseCases-Adapters-Frameworks)",
        signals=["entity", "usecase", "adapter", "framework", "port"],
        required_roles=["entity", "usecase"],
        dependency_flow=[
            "adapter -> usecase",
            "usecase -> entity",
        ],
        max_file_distance=2,
        severity=PatternSeverity.HIGH,
        anti_patterns=[
            "entity -> usecase",   # 엔티티가 유스케이스 의존 금지
            "entity -> adapter",   # 엔티티가 어댑터 의존 금지
            "usecase -> adapter",  # 유스케이스가 어댑터 의존 금지
        ]
    ),

    "HEXAGONAL": PatternDefinition(
        name="HEXAGONAL",
        description="헥사고날 아키텍처 (Ports and Adapters)",
        signals=["port", "adapter", "domain", "application"],
        required_roles=["port", "adapter", "domain"],
        dependency_flow=[
            "adapter -> port",
            "application -> domain",
        ],
        max_file_distance=2,
        severity=PatternSeverity.HIGH,
        anti_patterns=[
            "domain -> adapter",
        ]
    ),

    # =========================================================================
    # API 패턴
    # =========================================================================

    "CRUD_API": PatternDefinition(
        name="CRUD_API",
        description="표준 CRUD API 패턴",
        signals=["GET", "POST", "PUT", "DELETE", "PATCH"],
        required_roles=[],
        dependency_flow=[],
        max_file_distance=1,
        severity=PatternSeverity.LOW,
        anti_patterns=[]
    ),

    "REST_RESOURCE": PatternDefinition(
        name="REST_RESOURCE",
        description="RESTful 리소스 기반 API",
        signals=["resource", "collection", "endpoint", "route"],
        required_roles=["controller", "service"],
        dependency_flow=[
            "route -> controller",
            "controller -> service",
        ],
        max_file_distance=2,
        severity=PatternSeverity.MEDIUM,
        anti_patterns=[]
    ),

    # =========================================================================
    # 인증 패턴
    # =========================================================================

    "AUTH_FLOW": PatternDefinition(
        name="AUTH_FLOW",
        description="인증/인가 플로우",
        signals=["auth", "token", "jwt", "middleware", "guard", "session"],
        required_roles=["auth", "middleware"],
        dependency_flow=[
            "middleware -> auth",
            "auth -> token",
        ],
        max_file_distance=2,
        severity=PatternSeverity.HIGH,
        anti_patterns=[
            "controller -> token",  # 컨트롤러가 토큰 직접 처리 금지
        ]
    ),

    # =========================================================================
    # 데이터 패턴
    # =========================================================================

    "REPOSITORY": PatternDefinition(
        name="REPOSITORY",
        description="Repository 패턴 (데이터 접근 추상화)",
        signals=["repository", "repo", "dao", "store"],
        required_roles=["repository", "entity"],
        dependency_flow=[
            "service -> repository",
            "repository -> entity",
        ],
        max_file_distance=2,
        severity=PatternSeverity.MEDIUM,
        anti_patterns=[
            "controller -> repository",  # 컨트롤러가 직접 접근 금지
        ]
    ),

    "CQRS": PatternDefinition(
        name="CQRS",
        description="Command Query Responsibility Segregation",
        signals=["command", "query", "handler", "bus"],
        required_roles=["command", "query"],
        dependency_flow=[
            "handler -> command",
            "handler -> query",
        ],
        max_file_distance=2,
        severity=PatternSeverity.HIGH,
        anti_patterns=[]
    ),

    # =========================================================================
    # 경고 패턴 (안티패턴)
    # =========================================================================

    "THIN_SERVICE": PatternDefinition(
        name="THIN_SERVICE",
        description="서비스 레이어 우회 (주의)",
        signals=["controller", "model"],
        required_roles=["controller", "model"],
        dependency_flow=[
            "controller -> model",
        ],
        max_file_distance=1,
        severity=PatternSeverity.HIGH,
        anti_patterns=[]
    ),

    "GOD_OBJECT": PatternDefinition(
        name="GOD_OBJECT",
        description="God Object 안티패턴 (너무 많은 책임)",
        signals=["utils", "helpers", "common", "base"],
        required_roles=[],
        dependency_flow=[],
        max_file_distance=0,
        severity=PatternSeverity.HIGH,
        anti_patterns=[]
    ),

}


# -----------------------------------------------------------------------------
# PatternVocabulary - 패턴 사전 관리
# -----------------------------------------------------------------------------

class PatternVocabulary:
    """패턴 사전 관리자"""

    def __init__(self):
        self.patterns: Dict[str, PatternDefinition] = dict(BUILTIN_PATTERNS)

    def get(self, name: str) -> Optional[PatternDefinition]:
        """패턴 조회"""
        return self.patterns.get(name)

    def add(self, pattern: PatternDefinition) -> None:
        """패턴 추가"""
        self.patterns[pattern.name] = pattern

    def remove(self, name: str) -> bool:
        """패턴 제거"""
        if name in self.patterns:
            del self.patterns[name]
            return True
        return False

    def list_all(self) -> List[str]:
        """전체 패턴 이름 목록"""
        return list(self.patterns.keys())

    def list_by_severity(self, severity: PatternSeverity) -> List[str]:
        """심각도별 패턴 목록"""
        return [
            name for name, p in self.patterns.items()
            if p.severity == severity
        ]

    def get_signals(self) -> Dict[str, List[str]]:
        """전체 패턴의 신호 목록"""
        return {
            name: p.signals
            for name, p in self.patterns.items()
        }
