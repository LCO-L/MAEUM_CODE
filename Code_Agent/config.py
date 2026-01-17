"""
MAEUM_CODE Configuration

AI 포트: 7860 (고정)
"""

from dataclasses import dataclass
from typing import Optional
import os


# =============================================================================
# AI 서버 포트 (고정)
# =============================================================================
AI_SERVER_PORT = 7860


# =============================================================================
# 설정 클래스
# =============================================================================

@dataclass
class MaeumConfig:
    """MAEUM_CODE 설정"""

    # 서버 설정
    port: int = AI_SERVER_PORT  # 7860 고정
    host: str = "0.0.0.0"

    # 분석 설정
    max_files: int = 10000
    max_depth: int = 20
    cache_enabled: bool = True

    # 분류기 설정
    confidence_threshold: float = 0.6

    # 출력 설정
    verbose: bool = False
    color_output: bool = True

    @classmethod
    def from_env(cls) -> "MaeumConfig":
        """환경변수에서 설정 로드"""
        return cls(
            port=AI_SERVER_PORT,  # 환경변수 무시, 7860 고정
            host=os.getenv("MAEUM_HOST", "0.0.0.0"),
            max_files=int(os.getenv("MAEUM_MAX_FILES", "10000")),
            max_depth=int(os.getenv("MAEUM_MAX_DEPTH", "20")),
            cache_enabled=os.getenv("MAEUM_CACHE", "true").lower() == "true",
            confidence_threshold=float(os.getenv("MAEUM_CONFIDENCE", "0.6")),
            verbose=os.getenv("MAEUM_VERBOSE", "false").lower() == "true",
            color_output=os.getenv("MAEUM_COLOR", "true").lower() == "true",
        )


# 기본 설정 인스턴스
DEFAULT_CONFIG = MaeumConfig()


# =============================================================================
# 경로 설정
# =============================================================================

# 무시할 디렉토리
IGNORE_DIRECTORIES = {
    'node_modules',
    '.git',
    '__pycache__',
    '.venv',
    'venv',
    'dist',
    'build',
    '.next',
    '.nuxt',
    'coverage',
    '.idea',
    '.vscode',
    'vendor',
    'target',
    'bin',
    'obj',
    '.cache',
    '.pytest_cache',
    '.mypy_cache',
}

# 코드 파일 확장자
CODE_EXTENSIONS = {
    '.py', '.js', '.ts', '.jsx', '.tsx', '.vue', '.svelte',
    '.java', '.kt', '.scala', '.go', '.rs', '.rb', '.php',
    '.c', '.cpp', '.h', '.hpp', '.cs', '.swift', '.m',
}


# =============================================================================
# 역할 키워드
# =============================================================================

ROLE_KEYWORDS = {
    'entry': [
        'controller', 'route', 'router', 'handler', 'endpoint',
        'api', 'view', 'page', 'screen'
    ],
    'core': [
        'service', 'usecase', 'use_case', 'domain', 'core',
        'logic', 'business', 'interactor'
    ],
    'infra': [
        'repo', 'repository', 'dao', 'db', 'database', 'infra',
        'infrastructure', 'storage', 'cache', 'queue', 'adapter'
    ],
    'test': [
        'test', 'tests', 'spec', 'specs', '__test__', '__tests__',
    ],
}

# 보안 키워드
SECURITY_KEYWORDS = [
    'auth', 'authentication', 'authorization',
    'token', 'jwt', 'oauth', 'session',
    'crypto', 'encrypt', 'decrypt', 'hash',
    'password', 'credential', 'secret', 'key',
    'payment', 'billing', 'charge', 'transaction',
]
