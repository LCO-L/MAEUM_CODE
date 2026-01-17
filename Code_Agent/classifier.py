"""
ActionClassifier - 행동 자동분류 엔진

분류 우선순위(고정): ERROR → PATH → CONTEXT → ARCH → SILENT
LLM 의존 ❌ / 오분류 시 침묵 ⭕
"""

import re
from typing import Tuple, Optional
from dataclasses import dataclass

try:
    from .ARCHITECTURE import (
        ActionType, ActionResult, Phase, Tolerance,
        FileRole, Decision
    )
except ImportError:
    from ARCHITECTURE import (
        ActionType, ActionResult, Phase, Tolerance,
        FileRole, Decision
    )


# -----------------------------------------------------------------------------
# Hard Signal 정규식 패턴
# -----------------------------------------------------------------------------

# ERROR_CUT 신호
ERROR_PATTERNS = [
    re.compile(r'Traceback', re.IGNORECASE),
    re.compile(r'Exception', re.IGNORECASE),
    re.compile(r'Error[:\s]', re.IGNORECASE),  # Error: 또는 Error 뒤 공백
    re.compile(r'TypeError', re.IGNORECASE),
    re.compile(r'ReferenceError', re.IGNORECASE),
    re.compile(r'SyntaxError', re.IGNORECASE),
    re.compile(r'ValueError', re.IGNORECASE),
    re.compile(r'KeyError', re.IGNORECASE),
    re.compile(r'ImportError', re.IGNORECASE),
    re.compile(r'ModuleNotFoundError', re.IGNORECASE),
    re.compile(r'AttributeError', re.IGNORECASE),
    re.compile(r'NameError', re.IGNORECASE),
    re.compile(r'Caused by', re.IGNORECASE),
    re.compile(r'AssertionError', re.IGNORECASE),
    re.compile(r'FAILED', re.IGNORECASE),
    re.compile(r'Cannot read propert', re.IGNORECASE),  # JS 에러
    re.compile(r'is not defined', re.IGNORECASE),
    re.compile(r'is not a function', re.IGNORECASE),
    re.compile(r'undefined', re.IGNORECASE),
    re.compile(r'null pointer', re.IGNORECASE),
    re.compile(r'^\s+at\s+\w+\(', re.MULTILINE),  # 스택 트레이스
    re.compile(r'File ".*", line \d+'),  # Python 스택
    re.compile(r'^\s+File\s+"', re.MULTILINE),
]

# PATH_JUDGE 신호
PATH_PATTERN = re.compile(
    r'^(\.\/|\/|[A-Za-z0-9_-]+\/)*[A-Za-z0-9._-]+\.(ts|js|py|go|java|kt|rs|tsx|jsx|vue|rb|php|swift|c|cpp|h|hpp)$'
)

# ARCH_SNAPSHOT 신호
TREE_PATTERNS = [
    re.compile(r'[├└│]'),           # 트리 기호
    re.compile(r'^\s*(src|app|lib|pkg|cmd|internal)/', re.MULTILINE),
    re.compile(r'\.\/[a-zA-Z]+\/'),  # ./folder/ 패턴
]

# CONTEXT_SET 키워드
CONTEXT_KEYWORDS = [
    '지금', 'MVP', '실험', '임시', '리팩토링', '급함', '나중에',
    '테스트', '프로토타입', '빠르게', '일단', '우선', '당장',
    'now', 'experiment', 'temp', 'refactor', 'urgent', 'later',
    'prototype', 'quick', 'first', 'priority'
]

# 보안 관련 경로 키워드 (NO-GO 판단용)
SECURITY_KEYWORDS = [
    'auth', 'token', 'jwt', 'crypto', 'payment', 'secret',
    'credential', 'password', 'key', 'cert', 'ssl', 'tls'
]


# -----------------------------------------------------------------------------
# Confidence Threshold
# -----------------------------------------------------------------------------
CONFIDENCE_THRESHOLD = 0.6


# -----------------------------------------------------------------------------
# ActionClassifier
# -----------------------------------------------------------------------------
class ActionClassifier:
    """행동 자동분류기 - 결정론적, LLM 없음"""

    def classify(self, input_text: str) -> ActionResult:
        """
        입력을 분류하여 ActionResult 반환

        분류 순서: ERROR → PATH → CONTEXT → ARCH → SILENT
        """
        input_text = input_text.strip()
        if not input_text:
            return ActionResult(ActionType.SILENT, 0.0)

        # 1순위: ERROR_CUT
        error_conf = self._check_error(input_text)
        if error_conf >= CONFIDENCE_THRESHOLD:
            return ActionResult(ActionType.ERROR_CUT, error_conf)

        # 2순위: PATH_JUDGE
        path_conf, path_match = self._check_path(input_text)
        if path_conf >= CONFIDENCE_THRESHOLD:
            return ActionResult(
                ActionType.PATH_JUDGE,
                path_conf,
                {"path": path_match}
            )

        # 3순위: CONTEXT_SET
        ctx_conf, ctx_phase = self._check_context(input_text)
        if ctx_conf >= CONFIDENCE_THRESHOLD:
            return ActionResult(
                ActionType.CONTEXT_SET,
                ctx_conf,
                {"phase": ctx_phase}
            )

        # 4순위: ARCH_SNAPSHOT
        arch_conf = self._check_arch(input_text)
        if arch_conf >= CONFIDENCE_THRESHOLD:
            return ActionResult(ActionType.ARCH_SNAPSHOT, arch_conf)

        # 복수 신호가 약하게 잡히면 CLARIFY
        signals = [error_conf, path_conf, ctx_conf, arch_conf]
        strong_signals = [s for s in signals if s >= 0.3]
        if len(strong_signals) >= 2:
            return ActionResult(ActionType.CLARIFY, max(signals))

        # 분류 실패 → SILENT
        return ActionResult(ActionType.SILENT, 0.0)

    def _check_error(self, text: str) -> float:
        """ERROR_CUT 신호 확인"""
        matches = 0
        for pattern in ERROR_PATTERNS:
            if pattern.search(text):
                matches += 1

        # 스택 트레이스 구조 확인 (여러 줄 + 반복 패턴)
        lines = text.split('\n')
        if len(lines) >= 3:
            matches += 0.5

        # 정규화된 confidence
        return min(matches / 3.0, 1.0)

    def _check_path(self, text: str) -> Tuple[float, Optional[str]]:
        """PATH_JUDGE 신호 확인"""
        lines = text.strip().split('\n')

        # 단일 경로인 경우 높은 신뢰도
        if len(lines) == 1:
            line = lines[0].strip()
            if PATH_PATTERN.match(line):
                return (0.95, line)
            # 슬래시 포함 + 확장자
            if '/' in line and '.' in line and ' ' not in line:
                return (0.7, line)

        return (0.0, None)

    def _check_context(self, text: str) -> Tuple[float, Optional[Phase]]:
        """CONTEXT_SET 신호 확인"""
        lines = text.strip().split('\n')

        # 1~3줄 자연어
        if len(lines) > 3:
            return (0.0, None)

        text_lower = text.lower()
        keyword_count = 0
        detected_phase = Phase.MVP

        for keyword in CONTEXT_KEYWORDS:
            if keyword.lower() in text_lower:
                keyword_count += 1

                # 단계 추론
                if keyword in ['리팩토링', 'refactor']:
                    detected_phase = Phase.REFACTOR
                elif keyword in ['실험', 'experiment', '프로토타입', 'prototype']:
                    detected_phase = Phase.EXPERIMENT
                elif keyword in ['안정', 'stable', '배포', 'deploy']:
                    detected_phase = Phase.STABILIZE

        if keyword_count == 0:
            return (0.0, None)

        # 에러/경로 신호가 없어야 함
        if self._check_error(text) >= 0.3:
            return (0.0, None)
        if self._check_path(text)[0] >= 0.3:
            return (0.0, None)

        confidence = min(keyword_count / 2.0, 1.0)
        return (confidence, detected_phase)

    def _check_arch(self, text: str) -> float:
        """ARCH_SNAPSHOT 신호 확인"""
        matches = 0

        for pattern in TREE_PATTERNS:
            if pattern.search(text):
                matches += 1

        # 여러 줄 + 폴더 구조
        lines = text.strip().split('\n')
        if len(lines) >= 3:
            folder_lines = sum(1 for l in lines if '/' in l or l.strip().endswith('/'))
            if folder_lines >= 2:
                matches += 1

        return min(matches / 2.0, 1.0)


# -----------------------------------------------------------------------------
# PathJudge - 파일 역할 + GO/NO-GO
# -----------------------------------------------------------------------------
class PathJudge:
    """파일 경로 판단기"""

    def judge(self, path: str, tolerance: Tolerance) -> Tuple[FileRole, Decision]:
        """파일 역할 + GO/NO-GO 판정"""
        path_lower = path.lower()

        # Role 분류
        role = self._classify_role(path_lower)

        # Decision 판정
        decision = self._decide(path_lower, role, tolerance)

        return (role, decision)

    def _classify_role(self, path: str) -> FileRole:
        """파일 역할 분류"""
        # entry: controller/route/handler
        if any(k in path for k in ['controller', 'route', 'handler', 'endpoint', 'api']):
            return FileRole.ENTRY

        # core: service/usecase
        if any(k in path for k in ['service', 'usecase', 'domain', 'core', 'logic']):
            return FileRole.CORE

        # infra: repo/dao/db/infra
        if any(k in path for k in ['repo', 'repository', 'dao', 'db', 'database', 'infra', 'storage']):
            return FileRole.INFRA

        # test: test/spec
        if any(k in path for k in ['test', 'spec', '__test__', '.test.', '_test.']):
            return FileRole.TEST

        return FileRole.PERIPHERAL

    def _decide(self, path: str, role: FileRole, tolerance: Tolerance) -> Decision:
        """GO/NO-GO 판정"""
        # 보안 관련 경로 체크
        is_security = any(k in path for k in SECURITY_KEYWORDS)

        if tolerance == Tolerance.HIGH:
            # MVP/실험 - 보안 경로도 경고만 (GO)
            return Decision.GO

        if tolerance == Tolerance.MEDIUM:
            # 보안 경로면 NO-GO
            if is_security:
                return Decision.NO_GO
            return Decision.GO

        # LOW tolerance
        if is_security or role == FileRole.CORE:
            return Decision.NO_GO

        return Decision.GO


# -----------------------------------------------------------------------------
# Clarifier - 애매할 때 1회 되묻기
# -----------------------------------------------------------------------------
class Clarifier:
    """애매할 때 1회 되묻기"""

    PROMPT = """이건 뭐로 볼까?
1) 구조 펼치기
2) 오류 컷
3) 경로 판단
4) 맥락 설정"""

    @staticmethod
    def get_prompt() -> str:
        return Clarifier.PROMPT

    @staticmethod
    def resolve(choice: str) -> Optional[ActionType]:
        """사용자 선택 해석"""
        choice = choice.strip()

        mapping = {
            '1': ActionType.ARCH_SNAPSHOT,
            '2': ActionType.ERROR_CUT,
            '3': ActionType.PATH_JUDGE,
            '4': ActionType.CONTEXT_SET,
        }

        return mapping.get(choice)
