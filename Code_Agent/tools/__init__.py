"""
MAEUM_CODE Tools - Claude Code 스타일 도구 시스템

Claude Code가 사용하는 도구들:
- Read: 파일 읽기
- Write: 파일 쓰기
- Edit: 파일 수정 (diff 기반)
- Bash: 명령어 실행
- Glob: 파일 검색
- Grep: 내용 검색

각 도구는 독립적으로 실행되고, 결과를 반환한다.
"""

from .base import Tool, ToolResult, ToolStatus, ToolRegistry, ToolParameter
from .file_tools import ReadTool, WriteTool, EditTool
from .search_tools import GlobTool, GrepTool
from .bash_tool import BashTool


def create_registry() -> ToolRegistry:
    """기본 도구가 등록된 레지스트리 생성"""
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


__all__ = [
    # Base
    'Tool',
    'ToolResult',
    'ToolStatus',
    'ToolRegistry',
    'ToolParameter',
    # File Tools
    'ReadTool',
    'WriteTool',
    'EditTool',
    # Search Tools
    'GlobTool',
    'GrepTool',
    # Bash
    'BashTool',
    # Factory
    'create_registry',
]
