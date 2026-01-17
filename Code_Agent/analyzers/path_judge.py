"""
PathJudgeAnalyzer - 파일 역할 + GO/NO-GO

출력:
    [PATH]
    Role: <entry/core/peripheral/test/infra>
    Decision: GO | NO-GO

Role 분류 v0 룰:
- controller|route|handler → entry
- service|usecase → core
- repo|dao|db|infra → infra
- test|spec → test
- 그 외 → peripheral
"""

from dataclasses import dataclass
from typing import Optional
import os

from ..ARCHITECTURE import FileRole, Decision, Tolerance


@dataclass
class PathResult:
    """경로 판단 결과"""
    path: str
    role: FileRole
    decision: Decision
    reason: Optional[str] = None


class PathJudgeAnalyzer:
    """경로 판단 분석기"""

    # Role 분류 키워드
    ROLE_KEYWORDS = {
        FileRole.ENTRY: [
            'controller', 'route', 'router', 'handler', 'endpoint',
            'api', 'view', 'page', 'screen'
        ],
        FileRole.CORE: [
            'service', 'usecase', 'use_case', 'domain', 'core',
            'logic', 'business', 'interactor'
        ],
        FileRole.INFRA: [
            'repo', 'repository', 'dao', 'db', 'database', 'infra',
            'infrastructure', 'storage', 'cache', 'queue', 'adapter'
        ],
        FileRole.TEST: [
            'test', 'tests', 'spec', 'specs', '__test__', '__tests__',
            '.test.', '.spec.', '_test', '_spec'
        ],
    }

    # 보안 키워드 (주의 필요)
    SECURITY_KEYWORDS = [
        'auth', 'authentication', 'authorization',
        'token', 'jwt', 'oauth', 'session',
        'crypto', 'encrypt', 'decrypt', 'hash',
        'password', 'credential', 'secret', 'key',
        'payment', 'billing', 'charge', 'transaction',
        'admin', 'permission', 'role', 'acl'
    ]

    # 설정 파일 (보통 건드리면 안 됨)
    CONFIG_KEYWORDS = [
        'config', 'settings', 'env', '.env',
        'webpack', 'babel', 'tsconfig', 'eslint',
        'docker', 'kubernetes', 'k8s', 'helm'
    ]

    def analyze(self, path: str, tolerance: Tolerance) -> PathResult:
        """경로 분석 및 판단"""
        path_lower = path.lower()
        filename = os.path.basename(path).lower()

        # Role 분류
        role = self._classify_role(path_lower)

        # Decision 판정
        decision, reason = self._decide(path_lower, filename, role, tolerance)

        return PathResult(
            path=path,
            role=role,
            decision=decision,
            reason=reason
        )

    def _classify_role(self, path: str) -> FileRole:
        """파일 역할 분류"""
        for role, keywords in self.ROLE_KEYWORDS.items():
            for keyword in keywords:
                if keyword in path:
                    return role

        return FileRole.PERIPHERAL

    def _decide(
        self,
        path: str,
        filename: str,
        role: FileRole,
        tolerance: Tolerance
    ) -> tuple[Decision, Optional[str]]:
        """GO/NO-GO 판정"""

        # 보안 관련 체크
        is_security = any(k in path for k in self.SECURITY_KEYWORDS)

        # 설정 파일 체크
        is_config = any(k in path for k in self.CONFIG_KEYWORDS)

        # Tolerance에 따른 판정
        if tolerance == Tolerance.HIGH:
            # MVP/실험 - 거의 다 허용
            if is_security:
                return (Decision.GO, "보안 관련 - 주의 필요")
            return (Decision.GO, None)

        elif tolerance == Tolerance.MEDIUM:
            # 일반
            if is_security:
                return (Decision.NO_GO, "보안 관련 - 리뷰 필요")
            if is_config:
                return (Decision.NO_GO, "설정 파일 - 주의")
            return (Decision.GO, None)

        else:  # LOW
            # 안정화 - 엄격
            if is_security:
                return (Decision.NO_GO, "보안 관련 - 금지")
            if is_config:
                return (Decision.NO_GO, "설정 파일 - 금지")
            if role == FileRole.CORE:
                return (Decision.NO_GO, "핵심 로직 - 리뷰 필요")
            if role == FileRole.INFRA:
                return (Decision.NO_GO, "인프라 - 리뷰 필요")
            return (Decision.GO, None)

    def format_output(self, result: PathResult) -> str:
        """고정 포맷 출력"""
        output = f"""[PATH]
Role: {result.role.value}
Decision: {result.decision.value}"""

        if result.reason:
            output += f"\nNote: {result.reason}"

        return output


# 단독 실행용 (테스트)
if __name__ == "__main__":
    analyzer = PathJudgeAnalyzer()

    test_paths = [
        "/src/controllers/user.controller.ts",
        "/src/services/auth.service.ts",
        "/src/repositories/user.repo.ts",
        "/tests/user.test.ts",
        "/config/database.ts",
        "/src/utils/helpers.ts",
    ]

    for path in test_paths:
        result = analyzer.analyze(path, Tolerance.MEDIUM)
        print(analyzer.format_output(result))
        print()
