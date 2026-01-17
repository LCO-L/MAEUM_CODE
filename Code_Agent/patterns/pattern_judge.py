"""
PatternJudge - 패턴 판별 엔진

핵심:
- LLM은 "검색자"가 아니라 "판별자"로 쓴다
- 0~100 점수
- 위반 지점 리스트업
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set, Tuple
from pathlib import Path
import re

from .pattern_vocabulary import (
    PatternVocabulary,
    PatternDefinition,
    PatternSeverity,
    BUILTIN_PATTERNS,
)


@dataclass
class PatternMatch:
    """패턴 매칭 결과"""
    pattern_name: str
    score: float  # 0.0 ~ 100.0
    matched_signals: List[str]
    missing_signals: List[str]
    violations: List[str]
    severity: PatternSeverity


@dataclass
class JudgementResult:
    """전체 판별 결과"""
    dominant_pattern: Optional[str]
    pattern_scores: Dict[str, float]
    matches: List[PatternMatch]
    all_violations: List[str]
    recommendation: str


class PatternJudge:
    """패턴 판별 엔진"""

    def __init__(self, vocabulary: Optional[PatternVocabulary] = None):
        self.vocabulary = vocabulary or PatternVocabulary()

    def judge_structure(
        self,
        folders: List[str],
        files: List[str],
        imports: Optional[Dict[str, List[str]]] = None
    ) -> JudgementResult:
        """
        구조에서 패턴 판별

        Args:
            folders: 폴더 경로 리스트
            files: 파일 경로 리스트
            imports: 파일별 import 관계 (선택)

        Returns:
            JudgementResult
        """
        # 신호 추출
        signals = self._extract_signals(folders, files)

        # 각 패턴별 매칭
        matches: List[PatternMatch] = []

        for pattern_name, pattern_def in self.vocabulary.patterns.items():
            match = self._match_pattern(pattern_def, signals, imports)
            matches.append(match)

        # 점수순 정렬
        matches.sort(key=lambda m: m.score, reverse=True)

        # 지배적 패턴
        dominant = matches[0].pattern_name if matches and matches[0].score >= 50 else None

        # 전체 위반 수집
        all_violations = []
        for match in matches:
            if match.score >= 30:  # 어느 정도 매칭된 패턴만
                all_violations.extend(match.violations)

        # 권장사항
        recommendation = self._generate_recommendation(matches)

        return JudgementResult(
            dominant_pattern=dominant,
            pattern_scores={m.pattern_name: m.score for m in matches},
            matches=matches[:5],  # 상위 5개만
            all_violations=all_violations,
            recommendation=recommendation
        )

    def _extract_signals(
        self,
        folders: List[str],
        files: List[str]
    ) -> Set[str]:
        """구조에서 신호 추출"""
        signals = set()

        all_paths = folders + files

        # 키워드 기반 신호 추출
        keywords = [
            'controller', 'service', 'model', 'view',
            'api', 'domain', 'infra', 'infrastructure',
            'entity', 'usecase', 'adapter', 'port',
            'repository', 'repo', 'dao', 'store',
            'auth', 'token', 'jwt', 'middleware',
            'command', 'query', 'handler',
            'utils', 'helpers', 'common',
            'test', 'spec',
        ]

        for path in all_paths:
            path_lower = path.lower()
            for keyword in keywords:
                if keyword in path_lower:
                    signals.add(keyword)

        return signals

    def _match_pattern(
        self,
        pattern: PatternDefinition,
        signals: Set[str],
        imports: Optional[Dict[str, List[str]]] = None
    ) -> PatternMatch:
        """단일 패턴 매칭"""
        matched_signals = []
        missing_signals = []
        violations = []

        # 신호 매칭
        for signal in pattern.signals:
            if signal.lower() in signals:
                matched_signals.append(signal)
            else:
                missing_signals.append(signal)

        # 필수 역할 체크
        required_missing = []
        for role in pattern.required_roles:
            if role.lower() not in signals:
                required_missing.append(role)

        # 점수 계산
        if pattern.signals:
            signal_score = (len(matched_signals) / len(pattern.signals)) * 60
        else:
            signal_score = 30

        if pattern.required_roles:
            role_score = ((len(pattern.required_roles) - len(required_missing))
                         / len(pattern.required_roles)) * 40
        else:
            role_score = 40

        score = signal_score + role_score

        # 안티패턴 체크 (imports가 있는 경우)
        if imports:
            for anti in pattern.anti_patterns:
                if self._check_anti_pattern(anti, imports):
                    violations.append(f"Anti-pattern: {anti}")
                    score -= 10

        # 필수 역할 누락 경고
        for role in required_missing:
            violations.append(f"Missing required: {role}")

        score = max(0, min(100, score))

        return PatternMatch(
            pattern_name=pattern.name,
            score=score,
            matched_signals=matched_signals,
            missing_signals=missing_signals,
            violations=violations,
            severity=pattern.severity
        )

    def _check_anti_pattern(
        self,
        anti_pattern: str,
        imports: Dict[str, List[str]]
    ) -> bool:
        """안티패턴 위반 체크"""
        # "A -> B" 형태 파싱
        match = re.match(r'(\w+)\s*->\s*(\w+)', anti_pattern)
        if not match:
            return False

        source, target = match.groups()
        source_lower = source.lower()
        target_lower = target.lower()

        # import 관계에서 위반 확인
        for file_path, import_list in imports.items():
            if source_lower in file_path.lower():
                for imp in import_list:
                    if target_lower in imp.lower():
                        return True

        return False

    def _generate_recommendation(self, matches: List[PatternMatch]) -> str:
        """권장사항 생성"""
        if not matches:
            return "패턴을 식별할 수 없습니다."

        top = matches[0]

        if top.score >= 80:
            return f"{top.pattern_name} 패턴을 잘 따르고 있습니다."
        elif top.score >= 50:
            if top.violations:
                return f"{top.pattern_name} 패턴이나, 일부 위반: {top.violations[0]}"
            else:
                return f"{top.pattern_name} 패턴으로 보이나, 완성도 보완 필요"
        else:
            return "명확한 아키텍처 패턴이 감지되지 않음"

    def format_output(self, result: JudgementResult) -> str:
        """고정 포맷 출력"""
        output_lines = ["[PATTERN JUDGE]"]

        if result.dominant_pattern:
            score = result.pattern_scores.get(result.dominant_pattern, 0)
            output_lines.append(f"Pattern: {result.dominant_pattern} ({score:.0f})")
        else:
            output_lines.append("Pattern: Unknown")

        if result.all_violations:
            output_lines.append(f"Violations: {len(result.all_violations)}")
            for v in result.all_violations[:3]:  # 상위 3개만
                output_lines.append(f"  - {v}")

        output_lines.append(f"Note: {result.recommendation}")

        return "\n".join(output_lines)
