"""
Tool Base - 도구 기본 클래스

Claude Code 스타일:
- 각 도구는 name, description, parameters를 가짐
- execute()로 실행하고 ToolResult 반환
- 도구는 상태를 가지지 않음 (stateless)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, List
from enum import Enum


class ToolStatus(Enum):
    """도구 실행 상태"""
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class ToolResult:
    """도구 실행 결과"""
    status: ToolStatus
    output: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.status == ToolStatus.SUCCESS

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "output": self.output,
            "error": self.error,
            "metadata": self.metadata
        }


@dataclass
class ToolParameter:
    """도구 파라미터 정의"""
    name: str
    type: str  # "string", "integer", "boolean", "array"
    description: str
    required: bool = True
    default: Any = None


class Tool(ABC):
    """
    도구 기본 클래스

    Claude Code 스타일:
    - 명확한 이름과 설명
    - JSON Schema 기반 파라미터
    - 단일 책임
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """도구 이름"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """도구 설명"""
        pass

    @property
    def parameters(self) -> List[ToolParameter]:
        """도구 파라미터"""
        return []

    @abstractmethod
    def execute(self, **kwargs) -> ToolResult:
        """도구 실행"""
        pass

    def validate_params(self, **kwargs) -> Optional[str]:
        """파라미터 검증"""
        for param in self.parameters:
            if param.required and param.name not in kwargs:
                return f"Missing required parameter: {param.name}"
        return None

    def to_schema(self) -> Dict[str, Any]:
        """JSON Schema 형태로 변환 (AI에게 전달용)"""
        properties = {}
        required = []

        for param in self.parameters:
            properties[param.name] = {
                "type": param.type,
                "description": param.description
            }
            if param.required:
                required.append(param.name)

        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required
            }
        }


class ToolRegistry:
    """도구 레지스트리"""

    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """도구 등록"""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        """도구 조회"""
        return self._tools.get(name)

    def list_all(self) -> List[str]:
        """전체 도구 목록"""
        return list(self._tools.keys())

    def get_schemas(self) -> List[Dict[str, Any]]:
        """전체 도구 스키마"""
        return [tool.to_schema() for tool in self._tools.values()]

    def execute(self, name: str, **kwargs) -> ToolResult:
        """도구 실행"""
        tool = self.get(name)
        if not tool:
            return ToolResult(
                status=ToolStatus.ERROR,
                error=f"Unknown tool: {name}"
            )

        # 파라미터 검증
        error = tool.validate_params(**kwargs)
        if error:
            return ToolResult(
                status=ToolStatus.ERROR,
                error=error
            )

        try:
            return tool.execute(**kwargs)
        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                error=str(e)
            )
