"""
Main Orchestrator - MAEUM_CODE 메인 오케스트레이터

Claude Code 스타일의 프론티어 아키텍처:
- 요청 분류 → 작업 계획 → 에이전트 실행 → 결과 반환
- 7860 AI 서버 연동
- 도구 통합
"""

import os
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field

from .classifier import ActionClassifier, ActionType, ActionResult
from .code_writer import AIServerClient, CodeWriter, AI_SERVER_URL
from .tools.base import ToolRegistry
from .tools.file_tools import ReadTool, WriteTool, EditTool
from .tools.search_tools import GlobTool, GrepTool
from .tools.bash_tool import BashTool
from .agent.loop import AgentLoop, LoopConfig, SimpleLoop
from .agent.memory import ConversationMemory, ContextMemory


@dataclass
class OrchestratorConfig:
    """오케스트레이터 설정"""
    root_path: str = "."
    ai_server_url: str = AI_SERVER_URL
    max_iterations: int = 50
    max_tool_calls: int = 100
    verbose: bool = True
    auto_apply: bool = False  # 변경 자동 적용


@dataclass
class ExecutionResult:
    """실행 결과"""
    success: bool
    action_type: ActionType
    message: str
    changes: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class MaeumOrchestrator:
    """
    MAEUM_CODE 메인 오케스트레이터

    Claude Code 프론티어 스타일:
    1. 입력 분류 (ERROR_CUT, PATH_JUDGE, CONTEXT_SET, ARCH_SNAPSHOT)
    2. 작업 계획 수립
    3. 에이전트 루프 실행
    4. 결과 반환 및 적용

    7860 AI 서버를 통해 코드 생성/분석 수행
    """

    def __init__(self, config: OrchestratorConfig = None):
        self.config = config or OrchestratorConfig()
        self.root_path = Path(self.config.root_path).resolve()

        # AI 클라이언트
        self.ai_client = AIServerClient(self.config.ai_server_url)

        # 분류기
        self.classifier = ActionClassifier()

        # 도구 레지스트리
        self.tools = self._setup_tools()

        # 에이전트 루프
        self.agent = AgentLoop(
            tool_registry=self.tools,
            ai_client=self.ai_client,
            config=LoopConfig(
                max_iterations=self.config.max_iterations,
                max_tool_calls=self.config.max_tool_calls,
                verbose=self.config.verbose
            )
        )

        # 메모리
        self.conversation = ConversationMemory()
        self.context = ContextMemory()

        # 코드 작성기
        self.code_writer = CodeWriter(str(self.root_path), self.config.ai_server_url)

    def _setup_tools(self) -> ToolRegistry:
        """도구 레지스트리 설정"""
        registry = ToolRegistry()

        # 파일 도구
        registry.register(ReadTool())
        registry.register(WriteTool())
        registry.register(EditTool())

        # 검색 도구
        registry.register(GlobTool())
        registry.register(GrepTool())

        # 실행 도구
        registry.register(BashTool())

        return registry

    def execute(self, input_text: str) -> ExecutionResult:
        """
        요청 실행

        Args:
            input_text: 사용자 입력

        Returns:
            ExecutionResult
        """
        # 1. 입력 분류
        classification = self.classifier.classify(input_text)

        if self.config.verbose:
            print(f"[분류] {classification.action.name} (신뢰도: {classification.confidence:.2f})")

        # 2. 액션별 처리
        if classification.action == ActionType.ERROR_CUT:
            return self._handle_error_cut(input_text, classification)

        elif classification.action == ActionType.PATH_JUDGE:
            return self._handle_path_judge(input_text, classification)

        elif classification.action == ActionType.CONTEXT_SET:
            return self._handle_context_set(input_text, classification)

        elif classification.action == ActionType.ARCH_SNAPSHOT:
            return self._handle_arch_snapshot(input_text, classification)

        else:
            # SILENT 또는 기타
            return self._handle_general(input_text, classification)

    def _handle_error_cut(self, input_text: str, classification: ActionResult) -> ExecutionResult:
        """
        ERROR_CUT 처리 - 에러 분석 및 해결

        Claude Code 스타일:
        - 에러 메시지 파싱
        - 관련 파일 찾기
        - 해결책 제시 또는 적용
        """
        if self.config.verbose:
            print("[ERROR_CUT] 에러 분석 중...")

        # AI에게 에러 분석 요청
        prompt = f"""에러 분석 및 해결책 제시:

{input_text}

1. 에러 원인을 분석하세요
2. 해결을 위해 수정해야 할 파일을 찾으세요
3. 구체적인 코드 수정안을 제시하세요

프로젝트 경로: {self.root_path}"""

        response = self.ai_client.generate(
            "너는 에러 해결 전문가다. 에러 메시지를 분석하고 구체적인 해결책을 제시해라.",
            prompt
        )

        # 코드 수정 요청인 경우
        if "fix" in input_text.lower() or "고쳐" in input_text or "수정" in input_text:
            result = self.code_writer.write_code(input_text)
            if result.success:
                return ExecutionResult(
                    success=True,
                    action_type=ActionType.ERROR_CUT,
                    message=f"에러 수정 준비됨: {result.message}",
                    changes=[c.__dict__ for c in result.changes],
                    metadata={"ai_response": response[:1000]}
                )

        return ExecutionResult(
            success=True,
            action_type=ActionType.ERROR_CUT,
            message="에러 분석 완료",
            metadata={
                "analysis": response,
                "error_type": classification.entity
            }
        )

    def _handle_path_judge(self, input_text: str, classification: ActionResult) -> ExecutionResult:
        """
        PATH_JUDGE 처리 - 파일 경로 분석

        파일을 찾거나 파일 구조를 분석
        """
        if self.config.verbose:
            print("[PATH_JUDGE] 파일 경로 분석 중...")

        # Glob으로 파일 검색
        from .tools.search_tools import GlobTool
        glob_tool = GlobTool()

        # 패턴 추출
        patterns = classification.keywords
        if not patterns:
            patterns = ["**/*.py"]  # 기본

        all_files = []
        for pattern in patterns[:5]:
            result = glob_tool.execute(pattern=pattern, path=str(self.root_path))
            if result.output:
                all_files.extend(result.output.split('\n'))

        return ExecutionResult(
            success=True,
            action_type=ActionType.PATH_JUDGE,
            message=f"{len(all_files)}개 파일 발견",
            metadata={
                "files": all_files[:50],
                "patterns": patterns
            }
        )

    def _handle_context_set(self, input_text: str, classification: ActionResult) -> ExecutionResult:
        """
        CONTEXT_SET 처리 - 컨텍스트 설정

        코드 작성/수정 요청
        """
        if self.config.verbose:
            print("[CONTEXT_SET] 코드 작성 중...")

        # 코드 작성
        result = self.code_writer.write_code(input_text)

        if not result.success:
            return ExecutionResult(
                success=False,
                action_type=ActionType.CONTEXT_SET,
                message="코드 작성 실패",
                errors=[result.error or "Unknown error"]
            )

        # 자동 적용
        if self.config.auto_apply:
            apply_result = self.code_writer.apply_changes(result, dry_run=False)
            return ExecutionResult(
                success=True,
                action_type=ActionType.CONTEXT_SET,
                message=f"코드 작성 및 적용 완료",
                changes=[c.__dict__ for c in result.changes],
                metadata={"applied": apply_result}
            )

        return ExecutionResult(
            success=True,
            action_type=ActionType.CONTEXT_SET,
            message=result.message,
            changes=[c.__dict__ for c in result.changes]
        )

    def _handle_arch_snapshot(self, input_text: str, classification: ActionResult) -> ExecutionResult:
        """
        ARCH_SNAPSHOT 처리 - 아키텍처 분석

        프로젝트 구조 분석
        """
        if self.config.verbose:
            print("[ARCH_SNAPSHOT] 아키텍처 분석 중...")

        # 코드베이스 분석
        context = self.code_writer.analyze_context()

        return ExecutionResult(
            success=True,
            action_type=ActionType.ARCH_SNAPSHOT,
            message="아키텍처 분석 완료",
            metadata={
                "root_path": context.root_path,
                "structure": context.structure_summary,
                "pattern": context.pattern,
                "related_files": context.related_files[:20]
            }
        )

    def _handle_general(self, input_text: str, classification: ActionResult) -> ExecutionResult:
        """
        일반 요청 처리

        에이전트 루프 실행
        """
        if self.config.verbose:
            print("[GENERAL] 에이전트 루프 실행...")

        # 에이전트 실행
        agent_result = self.agent.run(input_text)

        return ExecutionResult(
            success=agent_result.get("success", False),
            action_type=classification.action,
            message=f"에이전트 실행 완료 (iterations: {agent_result.get('iterations', 0)})",
            changes=agent_result.get("changes", {}).get("modified", []),
            errors=agent_result.get("errors", []),
            metadata=agent_result
        )

    def chat(self, message: str) -> str:
        """
        대화형 인터페이스

        Args:
            message: 사용자 메시지

        Returns:
            AI 응답
        """
        self.conversation.add_user(message)

        # AI 호출
        response = self.ai_client.chat(
            self.conversation.to_api_format(),
            system_prompt="너는 MAEUM_CODE의 AI 어시스턴트다. 코드 작성과 분석을 도와준다."
        )

        self.conversation.add_assistant(response)
        return response

    def apply_changes(self, changes: List[Dict[str, Any]], dry_run: bool = True) -> Dict[str, Any]:
        """변경 사항 적용"""
        from .code_writer import CodeChange, CodeWriteResult

        code_changes = [
            CodeChange(
                file_path=c.get("file_path", ""),
                action=c.get("action", "modify"),
                content=c.get("content")
            )
            for c in changes
        ]

        result = CodeWriteResult(success=True, changes=code_changes)
        return self.code_writer.apply_changes(result, dry_run=dry_run)

    def status(self) -> Dict[str, Any]:
        """상태 확인"""
        ai_status = self.ai_client.is_available()

        return {
            "ai_server": {
                "url": self.config.ai_server_url,
                "available": ai_status
            },
            "tools": {
                "registered": list(self.tools._tools.keys()),
                "count": len(self.tools._tools)
            },
            "memory": {
                "conversation_messages": len(self.conversation.messages),
                "context_files": len(self.context.files)
            },
            "root_path": str(self.root_path)
        }


# =============================================================================
# Factory Functions
# =============================================================================

def create_orchestrator(
    root_path: str = ".",
    ai_server_url: str = None,
    verbose: bool = True,
    auto_apply: bool = False
) -> MaeumOrchestrator:
    """오케스트레이터 생성"""
    config = OrchestratorConfig(
        root_path=root_path,
        ai_server_url=ai_server_url or AI_SERVER_URL,
        verbose=verbose,
        auto_apply=auto_apply
    )
    return MaeumOrchestrator(config)


def quick_execute(request: str, root_path: str = ".") -> ExecutionResult:
    """빠른 실행"""
    orchestrator = create_orchestrator(root_path, verbose=False)
    return orchestrator.execute(request)


# =============================================================================
# CLI Interface
# =============================================================================

def main():
    """메인 CLI"""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m CUSTOM.orchestrator <request>")
        print("       python -m CUSTOM.orchestrator --status")
        return

    if sys.argv[1] == "--status":
        orchestrator = create_orchestrator()
        status = orchestrator.status()
        print(f"""
MAEUM_CODE Status
─────────────────
AI Server: {status['ai_server']['url']} ({'ONLINE' if status['ai_server']['available'] else 'OFFLINE'})
Tools: {status['tools']['count']} registered
Root: {status['root_path']}
""")
        return

    request = " ".join(sys.argv[1:])
    orchestrator = create_orchestrator()
    result = orchestrator.execute(request)

    print(f"""
[{result.action_type.name}] {result.message}
Success: {result.success}
""")

    if result.changes:
        print("Changes:")
        for change in result.changes[:10]:
            print(f"  - {change}")

    if result.errors:
        print("Errors:")
        for error in result.errors:
            print(f"  ! {error}")


if __name__ == "__main__":
    main()
