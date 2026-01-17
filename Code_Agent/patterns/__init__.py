"""
MAEUM_CODE Patterns - 패턴 사전 및 판별 엔진

핵심:
- 패턴은 찾는 게 아니라 "정의"해야 한다
- LLM에게 "이 프로젝트 구조 설명해줘" ❌
- "이 그래프가 MVC_PATTERN을 만족하는지 판단해라" ⭕
"""

from .pattern_vocabulary import (
    PatternVocabulary,
    BUILTIN_PATTERNS,
)
from .pattern_judge import PatternJudge

__all__ = [
    'PatternVocabulary',
    'BUILTIN_PATTERNS',
    'PatternJudge',
]
