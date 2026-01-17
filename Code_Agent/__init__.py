"""
MAEUM_CODE - Claude Code 스타일 AI 코딩 어시스턴트

클로드 코드 수준의 강력한 기능:
- 실시간 스트리밍 응답
- 강화된 검색 (코드/파일/심볼)
- 대규모 코드 작업
- 안전한 파일 조작 (Undo/Redo)
- 프로젝트 인덱싱
- 에이전트 루프 (Think → Act → Observe → Reflect)
- 웹 기반 IDE (로컬 전용)

사용법:
    # CLI 실행 (권장)
    python main.py
    python main.py /path/to/project
    python main.py --status

    # Web IDE 실행
    python -m CUSTOM.ide_server
    python -m CUSTOM.ide_server /path/to/project --port 8880

    # 또는 모듈로 실행
    python -m CUSTOM.main

    # 프로그래밍 방식
    from CUSTOM import SmartClient, SearchEngine, TransactionManager

    # 스트리밍 클라이언트
    client = SmartClient()
    response = client.generate(system_prompt, user_prompt, on_token=print)

    # 검색
    engine = SearchEngine(".")
    engine.index_codebase()
    result = engine.search("def main")

    # 코드 편집
    tx = TransactionManager(".")
    tx.begin("Edit main.py")
    tx.edit("main.py", "old_code", "new_code")
    tx.commit()

    # Web IDE
    from CUSTOM import IDEServer
    server = IDEServer(".")
    server.run(port=8880)
"""

__version__ = "1.1.0"
__ai_server_port__ = 7860

# Core (기존)
from .code_writer import CodeWriter, AIServerClient, check_ai_status
from .classifier import ActionClassifier, ActionType
from .orchestrator import MaeumOrchestrator, create_orchestrator, quick_execute

# Tools (기존)
from .tools.base import Tool, ToolResult, ToolRegistry

# Agent (기존)
from .agent.loop import AgentLoop, AgentState
from .agent.memory import ConversationMemory, ContextMemory
from .agent.planner import TaskPlanner, Task

# 새로운 기능
from .stream_client import (
    SmartClient, StreamClient, FallbackClient,
    StreamResult, StreamStatus, StreamChunk,
    get_client, create_client, check_server,
    quick_generate, quick_stream
)

from .advanced_search import (
    SearchEngine, SearchResult, SearchMatch,
    SearchMode, FileType, FileInfo,
    get_engine, quick_search, quick_find, quick_symbol
)

from .code_tools import (
    TransactionManager, BatchEditor,
    CodeEditor, SafeFileOps, UndoManager,
    FileChange, Transaction, OperationType, OperationStatus,
    get_tx_manager, quick_edit, quick_write, undo, redo
)

# Web IDE
from .ide_server import IDEServer

__all__ = [
    # Core
    'CodeWriter',
    'AIServerClient',
    'check_ai_status',
    'ActionClassifier',
    'ActionType',
    'MaeumOrchestrator',
    'create_orchestrator',
    'quick_execute',

    # Tools
    'Tool',
    'ToolResult',
    'ToolRegistry',

    # Agent
    'AgentLoop',
    'AgentState',
    'ConversationMemory',
    'ContextMemory',
    'TaskPlanner',
    'Task',

    # Streaming
    'SmartClient',
    'StreamClient',
    'FallbackClient',
    'StreamResult',
    'StreamStatus',
    'StreamChunk',
    'get_client',
    'create_client',
    'check_server',
    'quick_generate',
    'quick_stream',

    # Search
    'SearchEngine',
    'SearchResult',
    'SearchMatch',
    'SearchMode',
    'FileType',
    'FileInfo',
    'get_engine',
    'quick_search',
    'quick_find',
    'quick_symbol',

    # Code Tools
    'TransactionManager',
    'BatchEditor',
    'CodeEditor',
    'SafeFileOps',
    'UndoManager',
    'FileChange',
    'Transaction',
    'OperationType',
    'OperationStatus',
    'get_tx_manager',
    'quick_edit',
    'quick_write',
    'undo',
    'redo',

    # Web IDE
    'IDEServer',
]
