"""
MAEUM_CODE Engine - 메인 엔진

전체 파이프라인:
    [Codebase]
        ↓
    [Structure Parser]
        ↓
    [Semantic Graph Builder]
        ↓
    [Pattern Judge Engine]
        ↓
    [LLM Insight Layer] (1회만)
        ↓
    [Human-readable Output]

AI 포트: 7860 (고정)
"""

from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass

from .classifier import ActionClassifier, PathJudge
from .context_store import ContextStore
from .graph import SemanticGraphBuilder, CodeTreeParser
from .patterns import PatternJudge, PatternVocabulary
from .analyzers import (
    ArchSnapshotAnalyzer,
    ErrorCutAnalyzer,
    PathJudgeAnalyzer,
)
from .ARCHITECTURE import (
    ActionType, ActionResult,
    SemanticGraph, Phase, Tolerance
)


# AI 서버 포트 (고정)
AI_SERVER_PORT = 7860


@dataclass
class CodeWriteRequest:
    """코드 작성 요청"""
    request: str
    target_file: str = None
    root_path: str = "."


@dataclass
class AnalysisResult:
    """전체 분석 결과"""
    graph: Optional[SemanticGraph]
    pattern_result: Optional[Dict]
    summary: str
    recommendations: list


class MaeumEngine:
    """
    MAEUM_CODE 메인 엔진

    핵심 철학:
    - 코드를 토큰으로 읽지 않는다
    - 구조 → 의미 → 패턴 → 의도 순으로 재조합
    - LLM은 "판별자"로만 사용 (요약/해설 1회)
    """

    def __init__(self):
        # 코어 컴포넌트
        self.classifier = ActionClassifier()
        self.context_store = ContextStore()
        self.pattern_vocab = PatternVocabulary()
        self.pattern_judge = PatternJudge(self.pattern_vocab)

        # 분석기
        self.arch_analyzer = ArchSnapshotAnalyzer()
        self.error_analyzer = ErrorCutAnalyzer()
        self.path_analyzer = PathJudgeAnalyzer()

        # 캐시
        self._graph_cache: Dict[str, SemanticGraph] = {}

    def analyze_codebase(self, root_path: str) -> AnalysisResult:
        """
        코드베이스 전체 분석

        Returns:
            AnalysisResult: 구조 + 패턴 + 권장사항
        """
        root = Path(root_path).resolve()

        # 캐시 확인
        cache_key = str(root)
        if cache_key in self._graph_cache:
            graph = self._graph_cache[cache_key]
        else:
            # 1단계: Structure Parser
            parser = CodeTreeParser(str(root))
            files = parser.parse()

            # 2단계: Semantic Graph Builder
            builder = SemanticGraphBuilder(files)
            graph = builder.build()

            self._graph_cache[cache_key] = graph

        # 3단계: Pattern Judge
        folders = list(set(str(Path(f.path).parent) for f in graph.files))
        file_paths = [f.path for f in graph.files]

        # import 관계 구성
        imports = {f.path: f.imports for f in graph.files}

        pattern_result = self.pattern_judge.judge_structure(
            folders=folders,
            files=file_paths,
            imports=imports
        )

        # 결과 구성
        summary = self._generate_summary(graph, pattern_result)
        recommendations = self._generate_recommendations(pattern_result)

        return AnalysisResult(
            graph=graph,
            pattern_result={
                "dominant": pattern_result.dominant_pattern,
                "scores": pattern_result.pattern_scores,
                "violations": pattern_result.all_violations,
            },
            summary=summary,
            recommendations=recommendations
        )

    def quick_analyze(self, input_text: str) -> str:
        """
        빠른 분석 - 입력 자동분류 후 최소 출력

        Args:
            input_text: 사용자 입력 (경로/에러/맥락/트리)

        Returns:
            str: 고정 포맷 출력
        """
        result = self.classifier.classify(input_text)
        tolerance = self.context_store.get_current().tolerance

        if result.action == ActionType.ARCH_SNAPSHOT:
            if Path(input_text).is_dir():
                snap = self.arch_analyzer.analyze_path(input_text)
            else:
                snap = self.arch_analyzer.analyze_tree_text(input_text)
            return self.arch_analyzer.format_output(snap)

        elif result.action == ActionType.ERROR_CUT:
            err = self.error_analyzer.analyze(input_text)
            return self.error_analyzer.format_output(err)

        elif result.action == ActionType.PATH_JUDGE:
            path = result.payload.get('path', input_text)
            judge = self.path_analyzer.analyze(path, tolerance)
            return self.path_analyzer.format_output(judge)

        elif result.action == ActionType.CONTEXT_SET:
            self.context_store.update_from_text(input_text)
            return ""  # 무출력

        elif result.action == ActionType.CLARIFY:
            return """이건 뭐로 볼까?
1) 구조 펼치기
2) 오류 컷
3) 경로 판단
4) 맥락 설정"""

        return ""  # SILENT

    def set_context(self, phase: Phase = None, tolerance: Tolerance = None) -> None:
        """맥락 설정"""
        if phase:
            self.context_store.set_phase(phase)
        if tolerance:
            self.context_store.set_tolerance(tolerance)

    def _generate_summary(self, graph: SemanticGraph, pattern_result) -> str:
        """요약 생성"""
        lines = []

        # 기본 정보
        lines.append(f"Files: {len(graph.files)}")
        lines.append(f"Entities: {len(graph.entities)}")

        # 패턴
        if pattern_result.dominant_pattern:
            score = pattern_result.pattern_scores.get(
                pattern_result.dominant_pattern, 0
            )
            lines.append(f"Pattern: {pattern_result.dominant_pattern} ({score:.0f}%)")

        # 위반
        if pattern_result.all_violations:
            lines.append(f"Violations: {len(pattern_result.all_violations)}")

        return "\n".join(lines)

    def _generate_recommendations(self, pattern_result) -> list:
        """권장사항 생성"""
        recs = []

        # 위반 기반 권장사항
        for violation in pattern_result.all_violations[:3]:
            recs.append(f"Fix: {violation}")

        # 일반 권장사항
        if pattern_result.dominant_pattern:
            recs.append(f"Maintain: {pattern_result.dominant_pattern} structure")

        return recs

    def clear_cache(self) -> None:
        """캐시 초기화"""
        self._graph_cache.clear()

    # =========================================================================
    # 코드 작성 기능 (Claude Code 스타일)
    # =========================================================================

    def write_code(self, request: str, target_file: str = None, root_path: str = ".") -> Dict[str, Any]:
        """
        코드 작성 요청 처리

        Args:
            request: 사용자 요청 (예: "User 모델에 email 추가해줘")
            target_file: 대상 파일 (선택)
            root_path: 프로젝트 루트

        Returns:
            dict: 작성 결과
        """
        from .code_writer import CodeWriter

        writer = CodeWriter(root_path)
        result = writer.write_code(request, target_file)

        return {
            "success": result.success,
            "message": result.message,
            "changes": [
                {
                    "file_path": c.file_path,
                    "action": c.action,
                    "content": c.content
                }
                for c in result.changes
            ],
            "error": result.error
        }

    def apply_code(self, request: str, target_file: str = None, root_path: str = ".", dry_run: bool = False) -> Dict[str, Any]:
        """
        코드 작성 + 적용

        Args:
            request: 사용자 요청
            target_file: 대상 파일
            root_path: 프로젝트 루트
            dry_run: True면 실제 적용 안 함

        Returns:
            dict: 적용 결과
        """
        from .code_writer import CodeWriter

        writer = CodeWriter(root_path)
        result = writer.write_code(request, target_file)

        if not result.success:
            return {"success": False, "error": result.error}

        apply_result = writer.apply_changes(result, dry_run=dry_run)

        return {
            "success": True,
            "dry_run": dry_run,
            "applied": apply_result["applied"],
            "errors": apply_result["errors"],
            "changes": [c.file_path for c in result.changes]
        }

    def chat(self, message: str, root_path: str = ".", history: list = None) -> Dict[str, Any]:
        """
        대화형 코드 작성

        Args:
            message: 사용자 메시지
            root_path: 프로젝트 루트
            history: 대화 히스토리

        Returns:
            dict: 응답
        """
        from .code_writer import CodeWriter, LLMInterface

        history = history or []

        writer = CodeWriter(root_path)
        writer.analyze_context()

        # 히스토리 포함 프롬프트
        history_text = ""
        for h in history[-10:]:
            role = h.get("role", "user")
            content = h.get("content", "")
            history_text += f"\n[{role}]: {content}"

        full_prompt = f"""프로젝트: {root_path}
구조: {writer.context.structure_summary if writer.context else 'unknown'}
패턴: {writer.context.pattern if writer.context else 'unknown'}

대화 히스토리:{history_text}

현재 요청: {message}

코드 작성이 필요하면 FILE: path/to/file 형식으로 제공하세요.
"""

        llm = LLMInterface()
        response = llm.generate(writer.SYSTEM_PROMPT, full_prompt)

        # 코드 변경 파싱
        changes = writer._parse_response(response)

        return {
            "response": response,
            "has_code": len(changes) > 0,
            "changes": [{"file_path": c.file_path, "action": c.action} for c in changes]
        }


# 싱글톤 인스턴스
_engine_instance: Optional[MaeumEngine] = None


def get_engine() -> MaeumEngine:
    """엔진 싱글톤 가져오기"""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = MaeumEngine()
    return _engine_instance
