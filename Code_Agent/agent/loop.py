"""
Agent Loop - 핵심 에이전트 실행 루프

Claude Code 스타일:
- Think → Act → Observe → Reflect
- 도구 실행 + 결과 반영
- 자동 복구 (에러 시)
"""

import json
import re
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

from ..tools.base import ToolRegistry, ToolResult, ToolStatus
from .memory import ConversationMemory, ContextMemory, WorkingMemory
from .planner import TaskPlanner, Task, TaskStatus


class AgentState(Enum):
    """에이전트 상태"""
    IDLE = "idle"
    THINKING = "thinking"
    ACTING = "acting"
    OBSERVING = "observing"
    REFLECTING = "reflecting"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class AgentAction:
    """에이전트 액션"""
    tool: str
    params: Dict[str, Any]
    reasoning: str = ""


@dataclass
class AgentObservation:
    """에이전트 관찰 결과"""
    tool: str
    result: ToolResult
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class LoopConfig:
    """루프 설정"""
    max_iterations: int = 50
    max_tool_calls: int = 100
    reflection_interval: int = 5  # N번 액션마다 반성
    auto_recover: bool = True
    verbose: bool = True


class AgentLoop:
    """
    에이전트 실행 루프

    Claude Code 스타일:
    1. Think: 상황 분석, 다음 액션 결정
    2. Act: 도구 실행
    3. Observe: 결과 확인
    4. Reflect: 진행 상황 평가, 전략 수정

    AI 서버 (7860)와 통신하여 결정 수행
    """

    SYSTEM_PROMPT = """너는 MAEUM_CODE의 실행 에이전트다.

역할:
1. 사용자 요청을 분석하고 작업을 계획한다
2. 도구를 사용하여 작업을 수행한다
3. 결과를 확인하고 다음 단계를 결정한다
4. 문제 발생 시 복구를 시도한다

사용 가능한 도구:
- Read: 파일 읽기 (file_path)
- Write: 파일 쓰기 (file_path, content)
- Edit: 파일 수정 (file_path, old_string, new_string)
- Glob: 파일 검색 (pattern, path)
- Grep: 내용 검색 (pattern, path)
- Bash: 명령 실행 (command, cwd, timeout)

응답 형식 (JSON):
{
    "thinking": "현재 상황 분석...",
    "action": {
        "tool": "도구명",
        "params": {"param1": "value1"}
    },
    "reasoning": "이 도구를 선택한 이유"
}

작업 완료 시:
{
    "thinking": "완료 분석...",
    "action": null,
    "result": "최종 결과 요약"
}"""

    def __init__(
        self,
        tool_registry: ToolRegistry,
        ai_client: Any,  # AIServerClient
        config: LoopConfig = None
    ):
        self.tools = tool_registry
        self.ai_client = ai_client
        self.config = config or LoopConfig()

        # 메모리
        self.conversation = ConversationMemory()
        self.context = ContextMemory()
        self.working = WorkingMemory()

        # 플래너
        self.planner = TaskPlanner()

        # 상태
        self.state = AgentState.IDLE
        self.iteration = 0
        self.tool_calls = 0
        self.observations: List[AgentObservation] = []
        self.errors: List[str] = []

        # 콜백
        self.on_action: Optional[Callable] = None
        self.on_observe: Optional[Callable] = None
        self.on_reflect: Optional[Callable] = None

    def run(self, request: str) -> Dict[str, Any]:
        """
        에이전트 루프 실행

        Args:
            request: 사용자 요청

        Returns:
            실행 결과
        """
        self._reset()
        self.working.set_goal(request)
        self.conversation.add_user(request)

        # 작업 계획
        tasks = self.planner.plan(request)
        for task in tasks:
            self.working.add_step(task.description)

        if self.config.verbose:
            print(f"[Agent] 계획 수립: {len(tasks)}개 작업")

        # 메인 루프
        while self.iteration < self.config.max_iterations:
            self.iteration += 1

            # 1. Think
            self.state = AgentState.THINKING
            action = self._think()

            if action is None:
                # 완료
                self.state = AgentState.COMPLETED
                break

            # 2. Act
            self.state = AgentState.ACTING
            observation = self._act(action)

            # 3. Observe
            self.state = AgentState.OBSERVING
            self._observe(observation)

            # 4. Reflect (주기적)
            if self.iteration % self.config.reflection_interval == 0:
                self.state = AgentState.REFLECTING
                self._reflect()

            # 도구 호출 제한 체크
            if self.tool_calls >= self.config.max_tool_calls:
                self.errors.append("Tool call limit reached")
                break

        return self._build_result()

    def _think(self) -> Optional[AgentAction]:
        """
        현재 상황 분석 후 다음 액션 결정

        AI 서버에 컨텍스트 전달 → 액션 결정
        """
        # 프롬프트 구성
        prompt = self._build_think_prompt()

        # AI 호출
        response = self.ai_client.generate(self.SYSTEM_PROMPT, prompt)

        if self.config.verbose:
            print(f"[Think] {response[:200]}...")

        # 응답 파싱
        return self._parse_action(response)

    def _act(self, action: AgentAction) -> AgentObservation:
        """도구 실행"""
        self.tool_calls += 1

        if self.config.verbose:
            print(f"[Act] {action.tool}({action.params})")

        if self.on_action:
            self.on_action(action)

        # 도구 실행
        result = self.tools.execute(action.tool, **action.params)

        # 컨텍스트 업데이트
        self._update_context(action, result)

        return AgentObservation(
            tool=action.tool,
            result=result
        )

    def _observe(self, observation: AgentObservation):
        """결과 관찰 및 기록"""
        self.observations.append(observation)

        # 대화 메모리에 추가
        result_summary = self._summarize_result(observation.result)
        self.conversation.add_tool(observation.tool, result_summary)

        if self.on_observe:
            self.on_observe(observation)

        # 에러 처리
        if observation.result.status == ToolStatus.ERROR:
            self.errors.append(observation.result.error or "Unknown error")

            if self.config.auto_recover:
                self._try_recover(observation)

    def _reflect(self):
        """진행 상황 평가"""
        if self.config.verbose:
            progress = self.planner.get_progress()
            print(f"[Reflect] 진행률: {progress['percent']:.1f}%")

        if self.on_reflect:
            self.on_reflect(self.planner.get_progress())

        # 작업 상태 업데이트
        self.working.add_note(f"Iteration {self.iteration}: {len(self.errors)} errors")

    def _try_recover(self, observation: AgentObservation):
        """에러 복구 시도"""
        if self.config.verbose:
            print(f"[Recover] Attempting recovery from: {observation.result.error}")

        # 간단한 복구 전략
        # 실제로는 AI에게 복구 방법 질의

    def _build_think_prompt(self) -> str:
        """Think 단계 프롬프트 구성"""
        parts = []

        # 목표
        parts.append(f"## 목표\n{self.working.current_goal}")

        # 진행 상황
        parts.append(f"\n## 진행 상황\n{self.working.to_prompt()}")

        # 최근 관찰
        if self.observations:
            parts.append("\n## 최근 결과")
            for obs in self.observations[-3:]:
                status = "✓" if obs.result.status == ToolStatus.SUCCESS else "✗"
                output = (obs.result.output or "")[:500]
                parts.append(f"{status} {obs.tool}: {output}")

        # 에러
        if self.errors:
            parts.append(f"\n## 에러\n" + "\n".join(self.errors[-3:]))

        # 컨텍스트 (읽은 파일)
        if self.context.files:
            parts.append(f"\n## 파일 컨텍스트")
            for path in list(self.context.files.keys())[-5:]:
                parts.append(f"- {path}")

        parts.append("\n## 지시\n다음 액션을 결정하세요. JSON 형식으로 응답하세요.")

        return "\n".join(parts)

    def _parse_action(self, response: str) -> Optional[AgentAction]:
        """AI 응답에서 액션 파싱"""
        try:
            # JSON 추출
            json_match = re.search(r'\{[\s\S]*\}', response)
            if not json_match:
                return None

            data = json.loads(json_match.group())

            # 완료 체크
            if data.get("action") is None:
                self.working.add_note(f"완료: {data.get('result', '')}")
                return None

            action_data = data["action"]
            return AgentAction(
                tool=action_data.get("tool", ""),
                params=action_data.get("params", {}),
                reasoning=data.get("reasoning", "")
            )

        except json.JSONDecodeError:
            # JSON 파싱 실패 - 직접 추출 시도
            return self._extract_action_fallback(response)

    def _extract_action_fallback(self, response: str) -> Optional[AgentAction]:
        """폴백: 텍스트에서 액션 추출"""
        # 도구 이름 패턴
        tool_pattern = r'(Read|Write|Edit|Glob|Grep|Bash)\s*[:\(]'
        match = re.search(tool_pattern, response)

        if match:
            tool = match.group(1)
            # 간단한 파라미터 추출
            return AgentAction(
                tool=tool,
                params={},
                reasoning="Fallback extraction"
            )

        return None

    def _update_context(self, action: AgentAction, result: ToolResult):
        """컨텍스트 업데이트"""
        if action.tool == "Read" and result.status == ToolStatus.SUCCESS:
            file_path = action.params.get("file_path", "")
            self.context.track_read(file_path, result.output or "")

        elif action.tool == "Write" and result.status == ToolStatus.SUCCESS:
            file_path = action.params.get("file_path", "")
            content = action.params.get("content", "")
            self.context.track_write(file_path, content)

        elif action.tool == "Edit" and result.status == ToolStatus.SUCCESS:
            file_path = action.params.get("file_path", "")
            self.context.modified_files.add(file_path)

    def _summarize_result(self, result: ToolResult) -> str:
        """결과 요약"""
        status = "SUCCESS" if result.status == ToolStatus.SUCCESS else str(result.status.value)
        output = (result.output or "")[:1000]
        error = result.error or ""

        return f"[{status}] {output}\n{error}".strip()

    def _build_result(self) -> Dict[str, Any]:
        """최종 결과 구성"""
        return {
            "success": self.state == AgentState.COMPLETED and len(self.errors) == 0,
            "state": self.state.value,
            "iterations": self.iteration,
            "tool_calls": self.tool_calls,
            "errors": self.errors,
            "changes": self.context.get_changes_summary(),
            "progress": self.planner.get_progress(),
            "observations_count": len(self.observations)
        }

    def _reset(self):
        """상태 초기화"""
        self.state = AgentState.IDLE
        self.iteration = 0
        self.tool_calls = 0
        self.observations = []
        self.errors = []
        self.working.clear()
        self.planner.clear()

    def get_state(self) -> Dict[str, Any]:
        """현재 상태"""
        return {
            "state": self.state.value,
            "iteration": self.iteration,
            "tool_calls": self.tool_calls,
            "errors": len(self.errors),
            "progress": self.planner.get_progress()
        }


class SimpleLoop:
    """
    간단한 에이전트 루프 (AI 없이)

    테스트/디버깅용
    """

    def __init__(self, tool_registry: ToolRegistry):
        self.tools = tool_registry
        self.history: List[AgentObservation] = []

    def execute(self, tool: str, **params) -> ToolResult:
        """단일 도구 실행"""
        result = self.tools.execute(tool, **params)

        self.history.append(AgentObservation(
            tool=tool,
            result=result
        ))

        return result

    def get_history(self) -> List[Dict[str, Any]]:
        """실행 히스토리"""
        return [
            {
                "tool": obs.tool,
                "status": obs.result.status.value,
                "output": obs.result.output[:200] if obs.result.output else None,
                "timestamp": obs.timestamp.isoformat()
            }
            for obs in self.history
        ]
