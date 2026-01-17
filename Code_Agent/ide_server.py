#!/usr/bin/env python3
"""
MAEUM_CODE Web IDE - Backend Server
===================================

로컬 전용 웹 기반 IDE 백엔드
- FastAPI 기반 비동기 서버
- WebSocket 실시간 AI 스트리밍
- 파일 시스템 작업
- 검색 엔진 통합
- Undo/Redo 지원

포트: 8880 (AI 서버 7860과 분리)
"""

import os
import sys
import json
import asyncio
import mimetypes
import httpx
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

# FastAPI
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# 경로 설정
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

# MAEUM_CODE 모듈
try:
    from .stream_client import SmartClient, check_server
    from .advanced_search import SearchEngine, SearchMode, SearchResult
    from .code_tools import TransactionManager, get_tx_manager, BatchEditor, CodeEditor
    from .classifier import ActionClassifier, ActionType
    from .code_writer import CodeWriter, check_ai_status
except ImportError:
    from stream_client import SmartClient, check_server
    from advanced_search import SearchEngine, SearchMode, SearchResult
    from code_tools import TransactionManager, get_tx_manager, BatchEditor, CodeEditor
    from classifier import ActionClassifier, ActionType
    from code_writer import CodeWriter, check_ai_status


# ============================================================
# Pydantic Models
# ============================================================

class FileContent(BaseModel):
    path: str
    content: str

class FileCreate(BaseModel):
    path: str
    content: str = ""
    is_directory: bool = False

class FileRename(BaseModel):
    old_path: str
    new_path: str

class FileDelete(BaseModel):
    path: str

class SearchQuery(BaseModel):
    query: str
    mode: str = "content"  # content, file, symbol

class EditOperation(BaseModel):
    path: str
    old_text: str
    new_text: str

class BatchEditOperation(BaseModel):
    operations: List[EditOperation]
    description: str = "Batch edit"

class CodeWriteRequest(BaseModel):
    request: str
    target_file: Optional[str] = None
    auto_apply: bool = False

class ChatMessage(BaseModel):
    message: str
    context: Optional[str] = None


# ============================================================
# Tool Definitions (Agentic Loop)
# ============================================================

TOOLS = [
    {
        "name": "bash",
        "description": "Execute bash commands. Use for system operations, file listing, git commands, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The bash command to execute"
                }
            },
            "required": ["command"]
        }
    },
    {
        "name": "read_file",
        "description": "Read file with line numbers. Supports line range selection (e.g., lines 100-200). Reads up to 30000 chars per call. If 'has_more' is true, continue reading with next_offset.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to file (relative to workspace)"
                },
                "start_line": {
                    "type": "integer",
                    "description": "Start line number (1-based, default: 1)"
                },
                "end_line": {
                    "type": "integer",
                    "description": "End line number (inclusive). If omitted, reads up to 30000 chars from start_line."
                },
                "offset": {
                    "type": "integer",
                    "description": "Alias for start_line (for compatibility)"
                }
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "write_file",
        "description": "Write content to a file. Creates new file or overwrites existing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to write"
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file"
                }
            },
            "required": ["file_path", "content"]
        }
    },
    {
        "name": "edit_file",
        "description": "Edit file by replacing old_text with new_text, OR replace lines in a range. Use old_text/new_text for precise edits, or start_line/end_line/new_content to replace a line range.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to edit"
                },
                "old_text": {
                    "type": "string",
                    "description": "Text to find and replace (for text-based edit)"
                },
                "new_text": {
                    "type": "string",
                    "description": "Text to replace with (for text-based edit)"
                },
                "start_line": {
                    "type": "integer",
                    "description": "Start line number for range-based edit (1-based)"
                },
                "end_line": {
                    "type": "integer",
                    "description": "End line number for range-based edit (inclusive)"
                },
                "new_content": {
                    "type": "string",
                    "description": "New content to replace the line range with"
                }
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "list_dir",
        "description": "List contents of a directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path (relative to workspace, empty for root)"
                }
            },
            "required": []
        }
    },
    {
        "name": "search_code",
        "description": "Search for code patterns in the codebase.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (regex supported)"
                },
                "file_pattern": {
                    "type": "string",
                    "description": "File pattern to search (e.g., '*.py')"
                }
            },
            "required": ["query"]
        }
    },
    # ========== 핵심 검색 도구 (Claude Code 수준) ==========
    {
        "name": "grep",
        "description": "파일 내용 검색 (정규식 지원). ripgrep 스타일. 코드에서 패턴을 찾을 때 사용.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "검색 패턴 (정규식 지원)"
                },
                "path": {
                    "type": "string",
                    "description": "검색 경로 (기본값: 전체)"
                },
                "file_pattern": {
                    "type": "string",
                    "description": "파일 패턴 (예: '*.py', '*.ts')"
                },
                "case_sensitive": {
                    "type": "boolean",
                    "description": "대소문자 구분 (기본값: false)"
                },
                "whole_word": {
                    "type": "boolean",
                    "description": "단어 단위 매칭 (기본값: false)"
                },
                "context_lines": {
                    "type": "integer",
                    "description": "컨텍스트 라인 수 (기본값: 2)"
                },
                "max_results": {
                    "type": "integer",
                    "description": "최대 결과 수 (기본값: 50)"
                }
            },
            "required": ["pattern"]
        }
    },
    {
        "name": "glob",
        "description": "파일 이름/경로 패턴 검색. 파일을 찾을 때 사용.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "glob 패턴 (예: '**/*.py', 'src/**/*.ts', 'test_*.py')"
                },
                "max_results": {
                    "type": "integer",
                    "description": "최대 결과 수 (기본값: 50)"
                }
            },
            "required": ["pattern"]
        }
    },
    {
        "name": "find_symbol",
        "description": "심볼(함수, 클래스, 변수) 찾기. 정의를 찾을 때 사용.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "심볼 이름"
                },
                "symbol_type": {
                    "type": "string",
                    "enum": ["function", "class", "variable", "constant"],
                    "description": "심볼 타입 필터"
                },
                "exact": {
                    "type": "boolean",
                    "description": "정확히 일치 (기본값: false)"
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "find_references",
        "description": "심볼이 사용된 모든 위치 찾기. 영향 범위 파악에 사용.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol_name": {
                    "type": "string",
                    "description": "찾을 심볼 이름"
                },
                "definition_file": {
                    "type": "string",
                    "description": "정의 파일 (제외)"
                }
            },
            "required": ["symbol_name"]
        }
    },
    {
        "name": "find_definition",
        "description": "심볼의 정의 위치 찾기. Go to Definition.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol_name": {
                    "type": "string",
                    "description": "심볼 이름"
                }
            },
            "required": ["symbol_name"]
        }
    },
    # ========== Claude Code 패턴: 작업 관리 도구 ==========
    {
        "name": "todo_write",
        "description": "작업 목록을 관리합니다. 복잡한 작업을 단계별로 계획하고 진행 상황을 추적합니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "description": "작업 목록 배열",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string", "description": "작업 내용"},
                            "status": {"type": "string", "enum": ["pending", "in_progress", "completed"], "description": "상태"},
                            "priority": {"type": "string", "enum": ["high", "medium", "low"], "description": "우선순위"}
                        },
                        "required": ["content", "status"]
                    }
                }
            },
            "required": ["todos"]
        }
    },
    {
        "name": "read_project_memory",
        "description": "MAEUM.md 프로젝트 메모리 파일을 읽습니다. 프로젝트의 맥락, 아키텍처, 규칙을 파악합니다.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "update_project_memory",
        "description": "MAEUM.md 프로젝트 메모리를 업데이트합니다. 중요한 결정, 패턴, 규칙을 기록합니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "enum": ["architecture", "patterns", "rules", "context", "decisions"],
                    "description": "업데이트할 섹션"
                },
                "content": {
                    "type": "string",
                    "description": "추가할 내용"
                }
            },
            "required": ["section", "content"]
        }
    },
    {
        "name": "plan_task",
        "description": "복잡한 작업을 실행하기 전에 계획을 세웁니다. 코드 수정 전 전체 구조를 파악합니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "수행할 작업"
                },
                "files_to_examine": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "검토해야 할 파일 목록"
                },
                "considerations": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "고려해야 할 사항들"
                }
            },
            "required": ["task"]
        }
    },
    # ========== 웹 검색 도구 (7860 서버 연동) ==========
    {
        "name": "web_search",
        "description": "웹 검색을 수행합니다. 최신 정보, 문서, 라이브러리 사용법 등을 검색할 때 사용합니다. Serper/Brave/Tavily 지원.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "검색 쿼리"
                },
                "max_results": {
                    "type": "integer",
                    "description": "최대 결과 수 (기본값: 5)"
                },
                "search_type": {
                    "type": "string",
                    "enum": ["general", "news", "code", "docs"],
                    "description": "검색 유형 (기본값: general)"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "web_fetch",
        "description": "URL에서 웹 페이지 내용을 가져옵니다. 문서, API 레퍼런스 등을 읽을 때 사용합니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "가져올 URL"
                },
                "extract_code": {
                    "type": "boolean",
                    "description": "코드 블록만 추출할지 (기본값: false)"
                }
            },
            "required": ["url"]
        }
    },
    # ========== 멀티 편집 도구 (Claude Code 스타일) ==========
    {
        "name": "multi_edit",
        "description": "여러 파일을 동시에 편집합니다. 리팩토링, 이름 변경 등에 사용합니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "edits": {
                    "type": "array",
                    "description": "편집 목록",
                    "items": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string", "description": "파일 경로"},
                            "old_text": {"type": "string", "description": "찾을 텍스트"},
                            "new_text": {"type": "string", "description": "바꿀 텍스트"}
                        },
                        "required": ["file_path", "old_text", "new_text"]
                    }
                },
                "description": {
                    "type": "string",
                    "description": "편집 설명"
                }
            },
            "required": ["edits"]
        }
    },
    # ========== Git 통합 도구 ==========
    {
        "name": "git_status",
        "description": "Git 저장소 상태를 확인합니다. 변경된 파일, 스테이지된 파일 등을 보여줍니다.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "git_diff",
        "description": "Git diff를 보여줍니다. 변경 내용을 확인할 때 사용합니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "특정 파일만 볼 경우 (선택사항)"
                },
                "staged": {
                    "type": "boolean",
                    "description": "스테이지된 변경만 볼지 (기본값: false)"
                }
            },
            "required": []
        }
    },
    {
        "name": "git_log",
        "description": "Git 커밋 히스토리를 보여줍니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "표시할 커밋 수 (기본값: 10)"
                },
                "file_path": {
                    "type": "string",
                    "description": "특정 파일의 히스토리만 볼 경우"
                }
            },
            "required": []
        }
    },
    {
        "name": "git_commit",
        "description": "변경사항을 커밋합니다. 스테이지된 파일이 있어야 합니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "커밋 메시지"
                },
                "add_all": {
                    "type": "boolean",
                    "description": "모든 변경사항 자동 스테이지 (기본값: false)"
                }
            },
            "required": ["message"]
        }
    },
    # ========== 사용자 상호작용 도구 ==========
    {
        "name": "ask_user",
        "description": "사용자에게 질문하여 입력을 받습니다. 중요한 결정, 확인이 필요할 때 사용합니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "사용자에게 할 질문"
                },
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "선택지 (선택사항)"
                },
                "default": {
                    "type": "string",
                    "description": "기본값 (선택사항)"
                }
            },
            "required": ["question"]
        }
    },
    # ========== 코드 분석 도구 ==========
    {
        "name": "analyze_code",
        "description": "코드를 분석하여 구조, 의존성, 잠재적 문제를 파악합니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "분석할 파일 경로"
                },
                "analysis_type": {
                    "type": "string",
                    "enum": ["structure", "dependencies", "complexity", "security", "all"],
                    "description": "분석 유형 (기본값: all)"
                }
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "explain_code",
        "description": "코드를 설명합니다. 특정 함수나 클래스의 동작을 이해할 때 사용합니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "파일 경로"
                },
                "line_start": {
                    "type": "integer",
                    "description": "시작 라인"
                },
                "line_end": {
                    "type": "integer",
                    "description": "끝 라인"
                },
                "symbol_name": {
                    "type": "string",
                    "description": "설명할 심볼 이름 (함수, 클래스 등)"
                }
            },
            "required": ["file_path"]
        }
    },
    # ========== 프로젝트 탐색 도구 ==========
    {
        "name": "project_structure",
        "description": "프로젝트 전체 구조를 트리 형태로 보여줍니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "max_depth": {
                    "type": "integer",
                    "description": "최대 깊이 (기본값: 4)"
                },
                "show_hidden": {
                    "type": "boolean",
                    "description": "숨김 파일 표시 (기본값: false)"
                },
                "include_patterns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "포함할 패턴 (예: ['*.py', '*.ts'])"
                }
            },
            "required": []
        }
    },
    {
        "name": "find_files_by_content",
        "description": "특정 내용을 포함한 파일들을 찾습니다. grep과 유사하지만 파일 목록만 반환합니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "찾을 내용"
                },
                "file_pattern": {
                    "type": "string",
                    "description": "파일 패턴 (예: '*.py')"
                }
            },
            "required": ["content"]
        }
    }
]


class ToolExecutor:
    """도구 실행기 (maeum_code.py 스타일)"""

    def __init__(self, workspace: str, tx_manager: TransactionManager, symbol_index: dict = None, search_engine: SearchEngine = None):
        self.workspace = workspace
        self.tx_manager = tx_manager
        self.symbol_index = symbol_index if symbol_index is not None else {}
        self.search_engine = search_engine or SearchEngine(workspace)

    def _extract_file_symbols(self, file_path: str, content: str) -> dict:
        """파일에서 심볼(함수, 클래스, 변수 등) 추출 - AST 파싱"""
        import ast
        import re

        ext = os.path.splitext(file_path)[1].lower()
        symbols = {
            "file": file_path,
            "lines": content.count('\n') + 1,
            "imports": [],
            "classes": [],
            "functions": [],
            "variables": []
        }

        try:
            # Python
            if ext == '.py':
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            symbols["imports"].append({"name": alias.name, "line": node.lineno})
                    elif isinstance(node, ast.ImportFrom):
                        module = node.module or ""
                        for alias in node.names:
                            symbols["imports"].append({"name": f"{module}.{alias.name}", "line": node.lineno})
                    elif isinstance(node, ast.ClassDef):
                        methods = [{"name": m.name, "line": m.lineno}
                                   for m in node.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))]
                        symbols["classes"].append({
                            "name": node.name, "line": node.lineno, "methods": methods
                        })
                    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        symbols["functions"].append({
                            "name": node.name, "line": node.lineno,
                            "args": [arg.arg for arg in node.args.args]
                        })

            # JavaScript / TypeScript
            elif ext in ['.js', '.ts', '.jsx', '.tsx']:
                for i, line in enumerate(content.split('\n'), 1):
                    if re.match(r'import\s+', line):
                        symbols["imports"].append({"name": line.strip()[:50], "line": i})
                    if match := re.match(r'(?:export\s+)?class\s+(\w+)', line):
                        symbols["classes"].append({"name": match.group(1), "line": i})
                    if match := re.match(r'(?:export\s+)?(?:async\s+)?function\s+(\w+)', line):
                        symbols["functions"].append({"name": match.group(1), "line": i})
                    if match := re.match(r'(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s+)?\(', line):
                        symbols["functions"].append({"name": match.group(1), "line": i})

            # 기타
            else:
                for i, line in enumerate(content.split('\n'), 1):
                    if match := re.match(r'\s*(?:def|func|function|fn)\s+(\w+)', line):
                        symbols["functions"].append({"name": match.group(1), "line": i})
                    if match := re.match(r'\s*(?:class|struct|interface)\s+(\w+)', line):
                        symbols["classes"].append({"name": match.group(1), "line": i})

        except Exception as e:
            symbols["error"] = str(e)

        return symbols

    def execute(self, tool_name: str, tool_input: dict) -> dict:
        """도구 실행 및 결과 반환"""
        import subprocess

        try:
            if tool_name == "bash":
                cmd = tool_input.get("command", "")
                # 안전한 명령어만 허용 (rm -rf 등 위험 명령어 차단)
                dangerous = ["rm -rf", "rm -r /", "sudo rm", "> /dev", "mkfs", "dd if="]
                if any(d in cmd for d in dangerous):
                    return {"success": False, "error": f"위험한 명령어 차단됨: {cmd}"}

                result = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=self.workspace
                )
                output = result.stdout + result.stderr
                return {
                    "success": result.returncode == 0,
                    "output": output[:5000] if output else f"(exit code: {result.returncode})",
                    "exit_code": result.returncode
                }

            elif tool_name == "read_file":
                file_path = tool_input.get("file_path", "")
                # start_line 또는 offset 지원 (호환성)
                start_line = tool_input.get("start_line") or tool_input.get("offset", 1)
                end_line = tool_input.get("end_line")  # 명시적 종료 라인
                max_chars = 30000  # 3만자 제한
                full_path = os.path.join(self.workspace, file_path)

                if not os.path.exists(full_path):
                    return {"success": False, "error": f"File not found: {file_path}"}

                if not os.path.isfile(full_path):
                    return {"success": False, "error": f"Not a file: {file_path}"}

                try:
                    with open(full_path, 'r', encoding='utf-8') as f:
                        full_content = f.read()

                    total_chars = len(full_content)
                    all_lines = full_content.split('\n')
                    total_lines = len(all_lines)

                    # 시작/종료 인덱스 계산 (1-based to 0-based)
                    start_idx = max(0, start_line - 1)

                    # end_line이 지정되면 해당 범위만 읽기
                    if end_line is not None:
                        end_idx = min(end_line, total_lines)
                        # 지정된 범위 읽기 (max_chars 무시)
                        numbered_lines = []
                        for i in range(start_idx, end_idx):
                            line_num = i + 1
                            line_content = all_lines[i].rstrip('\r')
                            numbered_lines.append(f"{line_num}: {line_content}")

                        content = '\n'.join(numbered_lines)
                        has_more = end_idx < total_lines

                    else:
                        # end_line 없으면 max_chars까지 읽기
                        numbered_lines = []
                        char_count = 0
                        end_idx = start_idx

                        for i in range(start_idx, total_lines):
                            line_num = i + 1
                            line_content = all_lines[i].rstrip('\r')
                            line_with_num = f"{line_num}: {line_content}\n"

                            if char_count + len(line_with_num) > max_chars and numbered_lines:
                                break

                            numbered_lines.append(f"{line_num}: {line_content}")
                            char_count += len(line_with_num)
                            end_idx = i + 1

                        content = '\n'.join(numbered_lines)
                        has_more = end_idx < total_lines

                    remaining_lines = total_lines - end_idx

                    # 심볼 추출 및 인덱싱 (처음 읽을 때만)
                    symbols = None
                    if file_path not in self.symbol_index:
                        symbols = self._extract_file_symbols(file_path, full_content)
                        self.symbol_index[file_path] = symbols

                    result = {
                        "success": True,
                        "content": content,
                        "file_path": file_path,
                        "total_lines": total_lines,
                        "total_chars": total_chars,
                        "showing": f"{start_idx + 1}-{end_idx}",
                        "chars_read": len(content),
                        "has_more": has_more,
                        "symbols": symbols
                    }

                    # 더 읽어야 할 내용이 있으면 안내
                    if has_more:
                        result["next_offset"] = end_idx + 1
                        result["remaining_lines"] = remaining_lines
                        result["CONTINUE"] = f"File has {remaining_lines} more lines. Use start_line={end_idx + 1} to continue."

                    return result

                except UnicodeDecodeError:
                    return {"success": False, "error": "Binary file, cannot read as text"}

            elif tool_name == "write_file":
                file_path = tool_input.get("file_path", "")
                content = tool_input.get("content", "")
                full_path = os.path.join(self.workspace, file_path)

                # 부모 디렉토리 생성
                os.makedirs(os.path.dirname(full_path), exist_ok=True)

                # 트랜잭션으로 파일 생성/수정
                exists = os.path.exists(full_path)
                with open(full_path, 'w', encoding='utf-8') as f:
                    f.write(content)

                return {
                    "success": True,
                    "action": "overwritten" if exists else "created",
                    "path": file_path,
                    "size": len(content)
                }

            elif tool_name == "edit_file":
                file_path = tool_input.get("file_path", "")
                old_text = tool_input.get("old_text", "")
                new_text = tool_input.get("new_text", "")
                start_line = tool_input.get("start_line")
                end_line = tool_input.get("end_line")
                new_content_input = tool_input.get("new_content", "")
                full_path = os.path.join(self.workspace, file_path)

                if not os.path.exists(full_path):
                    return {"success": False, "error": f"File not found: {file_path}"}

                with open(full_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                # 라인 범위 편집 모드
                if start_line is not None and end_line is not None:
                    all_lines = content.split('\n')
                    total_lines = len(all_lines)

                    if start_line < 1 or end_line > total_lines or start_line > end_line:
                        return {"success": False, "error": f"Invalid line range: {start_line}-{end_line} (file has {total_lines} lines)"}

                    # 라인 범위 교체 (1-based to 0-based)
                    start_idx = start_line - 1
                    end_idx = end_line

                    # 새 내용을 라인으로 분할
                    new_lines = new_content_input.split('\n') if new_content_input else []

                    # 교체
                    result_lines = all_lines[:start_idx] + new_lines + all_lines[end_idx:]
                    new_content = '\n'.join(result_lines)

                    with open(full_path, 'w', encoding='utf-8') as f:
                        f.write(new_content)

                    lines_removed = end_line - start_line + 1
                    lines_added = len(new_lines)

                    return {
                        "success": True,
                        "path": file_path,
                        "edit_type": "line_range",
                        "range": f"{start_line}-{end_line}",
                        "lines_removed": lines_removed,
                        "lines_added": lines_added,
                        "new_total_lines": len(result_lines)
                    }

                # 텍스트 교체 모드
                elif old_text:
                    if old_text not in content:
                        return {"success": False, "error": "Text not found in file"}

                    new_content = content.replace(old_text, new_text, 1)

                    with open(full_path, 'w', encoding='utf-8') as f:
                        f.write(new_content)

                    return {
                        "success": True,
                        "path": file_path,
                        "edit_type": "text_replace",
                        "changes": 1
                    }

                else:
                    return {"success": False, "error": "Provide old_text/new_text OR start_line/end_line/new_content"}

            elif tool_name == "list_dir":
                path = tool_input.get("path", "")
                full_path = os.path.join(self.workspace, path)

                if not os.path.exists(full_path):
                    return {"success": False, "error": f"경로 없음: {path}"}

                items = []
                for name in sorted(os.listdir(full_path)):
                    if name.startswith('.'):
                        continue
                    item_path = os.path.join(full_path, name)
                    is_dir = os.path.isdir(item_path)
                    items.append({
                        "name": name,
                        "type": "directory" if is_dir else "file",
                        "size": os.path.getsize(item_path) if not is_dir else 0
                    })

                return {"success": True, "path": path, "items": items[:50]}

            elif tool_name == "search_code":
                query = tool_input.get("query", "")
                file_pattern = tool_input.get("file_pattern", "*")

                import re
                import fnmatch

                results = []
                for root, dirs, files in os.walk(self.workspace):
                    # 숨김 폴더 제외
                    dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['node_modules', '__pycache__', 'venv']]

                    for f in files:
                        if not fnmatch.fnmatch(f, file_pattern):
                            continue
                        if f.startswith('.'):
                            continue

                        file_path = os.path.join(root, f)
                        rel_path = os.path.relpath(file_path, self.workspace)

                        try:
                            with open(file_path, 'r', encoding='utf-8') as fp:
                                lines = fp.readlines()

                            for i, line in enumerate(lines, 1):
                                if re.search(query, line, re.IGNORECASE):
                                    results.append({
                                        "file": rel_path,
                                        "line": i,
                                        "content": line.strip()[:100]
                                    })

                                if len(results) >= 50:
                                    break
                        except:
                            pass

                        if len(results) >= 50:
                            break

                return {"success": True, "query": query, "matches": results}

            # ========== Claude Code 패턴: 새 도구들 ==========

            elif tool_name == "todo_write":
                todos = tool_input.get("todos", [])
                # 작업 목록을 .maeum_todos.json에 저장
                todo_file = os.path.join(self.workspace, ".maeum_todos.json")

                # 기존 목록 로드
                existing = []
                if os.path.exists(todo_file):
                    try:
                        with open(todo_file, 'r', encoding='utf-8') as f:
                            existing = json.load(f)
                    except:
                        pass

                # 새 목록으로 업데이트
                with open(todo_file, 'w', encoding='utf-8') as f:
                    json.dump(todos, f, ensure_ascii=False, indent=2)

                # 통계 계산
                pending = sum(1 for t in todos if t.get("status") == "pending")
                in_progress = sum(1 for t in todos if t.get("status") == "in_progress")
                completed = sum(1 for t in todos if t.get("status") == "completed")

                return {
                    "success": True,
                    "message": f"작업 목록 업데이트됨",
                    "stats": {
                        "total": len(todos),
                        "pending": pending,
                        "in_progress": in_progress,
                        "completed": completed
                    },
                    "todos": todos
                }

            elif tool_name == "read_project_memory":
                # MAEUM.md 파일 읽기
                memory_file = os.path.join(self.workspace, "MAEUM.md")

                if not os.path.exists(memory_file):
                    # 기본 템플릿 생성
                    default_template = """# MAEUM 프로젝트 메모리

## Architecture (아키텍처)
<!-- 프로젝트 구조, 핵심 컴포넌트 -->

## Patterns (패턴)
<!-- 코드 패턴, 컨벤션 -->

## Rules (규칙)
<!-- 코딩 규칙, 금지사항 -->

## Context (맥락)
<!-- 현재 작업 맥락, 진행 상황 -->

## Decisions (결정)
<!-- 중요한 기술적 결정 사항 -->

---
*이 파일은 MAEUM_CODE AI가 프로젝트를 이해하는 데 사용됩니다.*
"""
                    with open(memory_file, 'w', encoding='utf-8') as f:
                        f.write(default_template)
                    return {
                        "success": True,
                        "content": default_template,
                        "created": True,
                        "message": "MAEUM.md 파일이 생성되었습니다."
                    }

                with open(memory_file, 'r', encoding='utf-8') as f:
                    content = f.read()

                return {
                    "success": True,
                    "content": content,
                    "created": False
                }

            elif tool_name == "update_project_memory":
                section = tool_input.get("section", "context")
                new_content = tool_input.get("content", "")

                memory_file = os.path.join(self.workspace, "MAEUM.md")

                # 파일 읽기 (없으면 기본 템플릿)
                if os.path.exists(memory_file):
                    with open(memory_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                else:
                    content = "# MAEUM 프로젝트 메모리\n\n"

                # 섹션 매핑
                section_headers = {
                    "architecture": "## Architecture (아키텍처)",
                    "patterns": "## Patterns (패턴)",
                    "rules": "## Rules (규칙)",
                    "context": "## Context (맥락)",
                    "decisions": "## Decisions (결정)"
                }

                header = section_headers.get(section, f"## {section.title()}")
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                entry = f"\n- [{timestamp}] {new_content}"

                # 섹션 찾아서 내용 추가
                if header in content:
                    # 해당 섹션 다음에 추가
                    parts = content.split(header)
                    if len(parts) >= 2:
                        # 다음 ## 전까지가 섹션 내용
                        section_content = parts[1]
                        next_section_idx = section_content.find("\n##")
                        if next_section_idx > 0:
                            insert_pos = next_section_idx
                        else:
                            insert_pos = len(section_content)

                        new_section = section_content[:insert_pos].rstrip() + entry + "\n" + section_content[insert_pos:]
                        content = parts[0] + header + new_section
                else:
                    # 섹션이 없으면 새로 추가
                    content += f"\n{header}\n{entry}\n"

                with open(memory_file, 'w', encoding='utf-8') as f:
                    f.write(content)

                return {
                    "success": True,
                    "section": section,
                    "added": new_content,
                    "message": f"MAEUM.md의 {section} 섹션이 업데이트되었습니다."
                }

            elif tool_name == "plan_task":
                task = tool_input.get("task", "")
                files_to_examine = tool_input.get("files_to_examine", [])
                considerations = tool_input.get("considerations", [])

                # 계획서 생성
                plan = {
                    "task": task,
                    "status": "planning",
                    "files_to_examine": files_to_examine,
                    "considerations": considerations,
                    "created_at": datetime.now().isoformat(),
                    "steps": []
                }

                # .maeum_plan.json에 저장
                plan_file = os.path.join(self.workspace, ".maeum_plan.json")
                with open(plan_file, 'w', encoding='utf-8') as f:
                    json.dump(plan, f, ensure_ascii=False, indent=2)

                return {
                    "success": True,
                    "plan": plan,
                    "message": f"작업 계획 생성됨: {task}",
                    "next_action": "검토할 파일들을 순서대로 read_file로 확인하세요."
                }

            # ========== 검색 도구 (grep, glob, find_symbol 등) ==========

            elif tool_name == "grep":
                pattern = tool_input.get("pattern", "")
                path = tool_input.get("path", ".")
                file_pattern = tool_input.get("file_pattern", None)
                max_results = tool_input.get("max_results", 50)
                context_lines = tool_input.get("context_lines", 2)

                if not pattern:
                    return {"success": False, "error": "검색 패턴이 필요합니다"}

                # 인덱스가 없으면 생성
                if not self.search_engine._file_index:
                    self.search_engine.index_codebase()

                result = self.search_engine.search(
                    query=pattern,
                    mode=SearchMode.REGEX,
                    file_pattern=file_pattern,
                    max_results=max_results,
                    context_lines=context_lines
                )

                matches = []
                for m in result.matches:
                    match_info = {
                        "file": m.file_path,
                        "line": m.line_number,
                        "column": m.column,
                        "content": m.line_content.strip()[:200],
                        "match": m.match_text
                    }
                    if m.context_before:
                        match_info["context_before"] = m.context_before
                    if m.context_after:
                        match_info["context_after"] = m.context_after
                    matches.append(match_info)

                return {
                    "success": True,
                    "pattern": pattern,
                    "files_searched": result.files_searched,
                    "files_matched": result.files_matched,
                    "total_matches": result.total_matches,
                    "elapsed_time": f"{result.elapsed_time:.2f}s",
                    "matches": matches
                }

            elif tool_name == "glob":
                pattern = tool_input.get("pattern", "*")
                max_results = tool_input.get("max_results", 100)

                # 인덱스가 없으면 생성
                if not self.search_engine._file_index:
                    self.search_engine.index_codebase()

                files = self.search_engine.find_files(pattern, max_results=max_results)

                file_list = []
                for f in files:
                    file_list.append({
                        "path": f.relative_path,
                        "name": f.name,
                        "type": f.file_type.value if hasattr(f.file_type, 'value') else str(f.file_type),
                        "size": f.size,
                        "priority": f.priority
                    })

                return {
                    "success": True,
                    "pattern": pattern,
                    "count": len(file_list),
                    "files": file_list
                }

            elif tool_name == "find_symbol":
                name = tool_input.get("name", "")
                symbol_type = tool_input.get("symbol_type", None)  # function, class, variable
                exact = tool_input.get("exact", False)

                if not name:
                    return {"success": False, "error": "심볼 이름이 필요합니다"}

                # 인덱스가 없으면 생성
                if not self.search_engine._file_index:
                    self.search_engine.index_codebase()

                symbols = self.search_engine.find_symbol(name, symbol_type=symbol_type, exact=exact)

                return {
                    "success": True,
                    "name": name,
                    "count": len(symbols),
                    "symbols": symbols[:50]  # 최대 50개
                }

            elif tool_name == "find_references":
                symbol_name = tool_input.get("symbol_name", "")
                definition_file = tool_input.get("definition_file", None)

                if not symbol_name:
                    return {"success": False, "error": "심볼 이름이 필요합니다"}

                # 인덱스가 없으면 생성
                if not self.search_engine._file_index:
                    self.search_engine.index_codebase()

                matches = self.search_engine.find_references(symbol_name, definition_file=definition_file)

                references = []
                for m in matches[:100]:  # 최대 100개
                    references.append({
                        "file": m.file_path,
                        "line": m.line_number,
                        "column": m.column,
                        "content": m.line_content.strip()[:200]
                    })

                return {
                    "success": True,
                    "symbol_name": symbol_name,
                    "count": len(references),
                    "references": references
                }

            elif tool_name == "find_definition":
                symbol_name = tool_input.get("symbol_name", "")

                if not symbol_name:
                    return {"success": False, "error": "심볼 이름이 필요합니다"}

                # 인덱스가 없으면 생성
                if not self.search_engine._file_index:
                    self.search_engine.index_codebase()

                definition = self.search_engine.find_definition(symbol_name)

                if definition:
                    return {
                        "success": True,
                        "symbol_name": symbol_name,
                        "found": True,
                        "definition": definition
                    }
                else:
                    return {
                        "success": True,
                        "symbol_name": symbol_name,
                        "found": False,
                        "message": f"'{symbol_name}'의 정의를 찾을 수 없습니다"
                    }

            # ========== 웹 검색 도구 (7860 서버 연동) ==========

            elif tool_name == "web_search":
                query = tool_input.get("query", "")
                max_results = tool_input.get("max_results", 5)
                search_type = tool_input.get("search_type", "general")

                if not query:
                    return {"success": False, "error": "검색 쿼리가 필요합니다"}

                import requests
                try:
                    # 7860 서버의 웹 검색 API 호출
                    response = requests.post(
                        "http://localhost:7860/api/chat",
                        json={
                            "message": f"[웹 검색 요청] {query}",
                            "system_prompt": "웹 검색 결과를 요약해서 제공해주세요.",
                            "web_search": True,
                            "max_results": max_results
                        },
                        timeout=30
                    )

                    if response.status_code == 200:
                        data = response.json()
                        return {
                            "success": True,
                            "query": query,
                            "search_type": search_type,
                            "results": data.get("response", "검색 결과 없음"),
                            "sources": data.get("sources", [])
                        }
                    else:
                        return {"success": False, "error": f"웹 검색 실패: HTTP {response.status_code}"}

                except requests.exceptions.ConnectionError:
                    return {"success": False, "error": "7860 서버에 연결할 수 없습니다. 서버가 실행 중인지 확인하세요."}
                except Exception as e:
                    return {"success": False, "error": f"웹 검색 오류: {str(e)}"}

            elif tool_name == "web_fetch":
                url = tool_input.get("url", "")
                extract_code = tool_input.get("extract_code", False)

                if not url:
                    return {"success": False, "error": "URL이 필요합니다"}

                import requests
                try:
                    # Jina Reader를 사용하거나 직접 fetch
                    jina_url = f"https://r.jina.ai/{url}"
                    response = requests.get(jina_url, timeout=30, headers={"Accept": "text/markdown"})

                    if response.status_code == 200:
                        content = response.text

                        if extract_code:
                            # 코드 블록만 추출
                            import re
                            code_blocks = re.findall(r'```[\w]*\n(.*?)```', content, re.DOTALL)
                            content = "\n\n---\n\n".join(code_blocks) if code_blocks else "코드 블록을 찾을 수 없습니다."

                        return {
                            "success": True,
                            "url": url,
                            "content": content[:10000],  # 최대 10000자
                            "truncated": len(content) > 10000
                        }
                    else:
                        return {"success": False, "error": f"페이지 가져오기 실패: HTTP {response.status_code}"}

                except Exception as e:
                    return {"success": False, "error": f"웹 페이지 가져오기 오류: {str(e)}"}

            # ========== 멀티 편집 도구 ==========

            elif tool_name == "multi_edit":
                edits = tool_input.get("edits", [])
                description = tool_input.get("description", "Multi-edit")

                if not edits:
                    return {"success": False, "error": "편집 목록이 필요합니다"}

                results = []
                success_count = 0
                fail_count = 0

                self.tx_manager.begin(description)

                for edit in edits:
                    file_path = edit.get("file_path", "")
                    old_text = edit.get("old_text", "")
                    new_text = edit.get("new_text", "")

                    full_path = os.path.join(self.workspace, file_path)

                    if not os.path.exists(full_path):
                        results.append({"file": file_path, "success": False, "error": "파일 없음"})
                        fail_count += 1
                        continue

                    try:
                        with open(full_path, 'r', encoding='utf-8') as f:
                            content = f.read()

                        if old_text not in content:
                            results.append({"file": file_path, "success": False, "error": "텍스트를 찾을 수 없음"})
                            fail_count += 1
                            continue

                        new_content = content.replace(old_text, new_text, 1)
                        self.tx_manager.write(file_path, new_content)
                        results.append({"file": file_path, "success": True})
                        success_count += 1

                    except Exception as e:
                        results.append({"file": file_path, "success": False, "error": str(e)})
                        fail_count += 1

                if fail_count == 0:
                    self.tx_manager.commit()
                    return {
                        "success": True,
                        "description": description,
                        "total": len(edits),
                        "succeeded": success_count,
                        "failed": fail_count,
                        "results": results
                    }
                else:
                    self.tx_manager.rollback()
                    return {
                        "success": False,
                        "error": f"{fail_count}개 파일 편집 실패",
                        "results": results
                    }

            # ========== Git 도구 ==========

            elif tool_name == "git_status":
                result = subprocess.run(
                    ["git", "status", "--porcelain", "-b"],
                    cwd=self.workspace,
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                if result.returncode == 0:
                    lines = result.stdout.strip().split('\n')
                    branch = lines[0] if lines else "unknown"
                    changes = []

                    for line in lines[1:]:
                        if line:
                            status = line[:2]
                            file_path = line[3:]
                            status_map = {
                                'M': 'modified', 'A': 'added', 'D': 'deleted',
                                'R': 'renamed', 'C': 'copied', '?': 'untracked',
                                'U': 'unmerged', ' M': 'modified (unstaged)',
                                ' D': 'deleted (unstaged)'
                            }
                            changes.append({
                                "file": file_path,
                                "status": status_map.get(status.strip(), status)
                            })

                    return {
                        "success": True,
                        "branch": branch.replace("## ", ""),
                        "changes": changes,
                        "clean": len(changes) == 0
                    }
                else:
                    return {"success": False, "error": result.stderr or "Git 저장소가 아닙니다"}

            elif tool_name == "git_diff":
                file_path = tool_input.get("file_path", "")
                staged = tool_input.get("staged", False)

                cmd = ["git", "diff"]
                if staged:
                    cmd.append("--cached")
                if file_path:
                    cmd.append(file_path)

                result = subprocess.run(
                    cmd,
                    cwd=self.workspace,
                    capture_output=True,
                    text=True,
                    timeout=30
                )

                return {
                    "success": True,
                    "diff": result.stdout[:20000] if result.stdout else "(변경 없음)",
                    "truncated": len(result.stdout) > 20000 if result.stdout else False
                }

            elif tool_name == "git_log":
                count = tool_input.get("count", 10)
                file_path = tool_input.get("file_path", "")

                cmd = ["git", "log", f"-{count}", "--oneline", "--decorate"]
                if file_path:
                    cmd.extend(["--", file_path])

                result = subprocess.run(
                    cmd,
                    cwd=self.workspace,
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                if result.returncode == 0:
                    commits = []
                    for line in result.stdout.strip().split('\n'):
                        if line:
                            parts = line.split(' ', 1)
                            commits.append({
                                "hash": parts[0],
                                "message": parts[1] if len(parts) > 1 else ""
                            })

                    return {"success": True, "commits": commits}
                else:
                    return {"success": False, "error": result.stderr}

            elif tool_name == "git_commit":
                message = tool_input.get("message", "")
                add_all = tool_input.get("add_all", False)

                if not message:
                    return {"success": False, "error": "커밋 메시지가 필요합니다"}

                if add_all:
                    subprocess.run(["git", "add", "-A"], cwd=self.workspace, timeout=10)

                result = subprocess.run(
                    ["git", "commit", "-m", message],
                    cwd=self.workspace,
                    capture_output=True,
                    text=True,
                    timeout=30
                )

                if result.returncode == 0:
                    return {"success": True, "message": message, "output": result.stdout}
                else:
                    return {"success": False, "error": result.stderr or "커밋 실패"}

            # ========== 프로젝트 구조 도구 ==========

            elif tool_name == "project_structure":
                max_depth = tool_input.get("max_depth", 4)
                show_hidden = tool_input.get("show_hidden", False)
                include_patterns = tool_input.get("include_patterns", [])

                def build_tree(path, prefix="", depth=0):
                    if depth > max_depth:
                        return []

                    items = []
                    try:
                        entries = sorted(os.listdir(path))
                    except PermissionError:
                        return []

                    # 숨김 파일 필터링
                    if not show_hidden:
                        entries = [e for e in entries if not e.startswith('.')]

                    # 무시할 디렉토리
                    ignore_dirs = {'node_modules', '__pycache__', '.git', 'venv', '.venv', 'dist', 'build'}
                    entries = [e for e in entries if e not in ignore_dirs]

                    for i, entry in enumerate(entries):
                        full_path = os.path.join(path, entry)
                        is_last = i == len(entries) - 1
                        connector = "└── " if is_last else "├── "
                        extension = "    " if is_last else "│   "

                        if os.path.isdir(full_path):
                            items.append(f"{prefix}{connector}📁 {entry}/")
                            items.extend(build_tree(full_path, prefix + extension, depth + 1))
                        else:
                            # 패턴 필터링
                            if include_patterns:
                                import fnmatch
                                if not any(fnmatch.fnmatch(entry, p) for p in include_patterns):
                                    continue
                            items.append(f"{prefix}{connector}📄 {entry}")

                    return items

                tree = build_tree(self.workspace)

                return {
                    "success": True,
                    "workspace": self.workspace,
                    "structure": "\n".join(tree[:500]),  # 최대 500줄
                    "truncated": len(tree) > 500
                }

            elif tool_name == "find_files_by_content":
                content = tool_input.get("content", "")
                file_pattern = tool_input.get("file_pattern", "*")

                if not content:
                    return {"success": False, "error": "검색할 내용이 필요합니다"}

                # 인덱스 사용
                if not self.search_engine._file_index:
                    self.search_engine.index_codebase()

                result = self.search_engine.search(
                    query=content,
                    mode=SearchMode.CONTENT,
                    file_pattern=file_pattern,
                    max_results=50
                )

                files = list(set([m.file_path for m in result.matches]))

                return {
                    "success": True,
                    "content": content,
                    "file_count": len(files),
                    "files": files
                }

            elif tool_name == "analyze_code":
                file_path = tool_input.get("file_path", "")
                analysis_type = tool_input.get("analysis_type", "all")

                full_path = os.path.join(self.workspace, file_path)
                if not os.path.exists(full_path):
                    return {"success": False, "error": f"파일을 찾을 수 없음: {file_path}"}

                with open(full_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                analysis = {
                    "file": file_path,
                    "lines": len(content.split('\n')),
                    "size": len(content),
                }

                # Python 분석
                if file_path.endswith('.py'):
                    import ast
                    try:
                        tree = ast.parse(content)
                        classes = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
                        functions = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
                        imports = []
                        for node in ast.walk(tree):
                            if isinstance(node, ast.Import):
                                imports.extend([alias.name for alias in node.names])
                            elif isinstance(node, ast.ImportFrom):
                                imports.append(node.module or '')

                        analysis["classes"] = classes
                        analysis["functions"] = functions
                        analysis["imports"] = list(set(imports))
                        analysis["complexity"] = "high" if len(functions) > 20 else "medium" if len(functions) > 10 else "low"

                    except SyntaxError as e:
                        analysis["syntax_error"] = str(e)

                return {"success": True, "analysis": analysis}

            elif tool_name == "ask_user":
                # 이 도구는 특별 처리 필요 - WebSocket으로 사용자에게 질문
                question = tool_input.get("question", "")
                options = tool_input.get("options", [])

                return {
                    "success": True,
                    "type": "user_input_required",
                    "question": question,
                    "options": options,
                    "message": "사용자 입력 대기 중..."
                }

            elif tool_name == "explain_code":
                file_path = tool_input.get("file_path", "")
                line_start = tool_input.get("line_start", 1)
                line_end = tool_input.get("line_end", None)
                symbol_name = tool_input.get("symbol_name", "")

                full_path = os.path.join(self.workspace, file_path)
                if not os.path.exists(full_path):
                    return {"success": False, "error": f"파일을 찾을 수 없음: {file_path}"}

                with open(full_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()

                if line_end:
                    code = ''.join(lines[line_start-1:line_end])
                elif symbol_name:
                    # 심볼 찾기
                    code = ''.join(lines)  # 전체 코드 반환, AI가 심볼 찾아서 설명
                else:
                    code = ''.join(lines)

                return {
                    "success": True,
                    "file": file_path,
                    "code": code[:5000],
                    "line_start": line_start,
                    "line_end": line_end or len(lines),
                    "symbol_name": symbol_name,
                    "message": "코드를 분석하고 설명해주세요."
                }

            else:
                return {"success": False, "error": f"알 수 없는 도구: {tool_name}"}

        except subprocess.TimeoutExpired:
            return {"success": False, "error": "명령어 시간 초과 (30초)"}
        except Exception as e:
            return {"success": False, "error": str(e)}


# ============================================================
# IDE Server
# ============================================================

class IDEServer:
    """MAEUM_CODE Web IDE 서버"""

    def __init__(self, workspace: str = "."):
        self.workspace = os.path.abspath(workspace)
        print(f"🏠 워크스페이스 설정: {self.workspace}")
        print(f"   경로 존재 여부: {os.path.exists(self.workspace)}")
        print(f"   디렉토리 여부: {os.path.isdir(self.workspace)}")

        self.app = self._create_app()

        # 모듈 초기화
        self.client = SmartClient()
        self.search_engine = SearchEngine(self.workspace)
        self.tx_manager = get_tx_manager(self.workspace)
        self.classifier = ActionClassifier()
        self.code_writer = CodeWriter(self.workspace)
        self.batch_editor = BatchEditor(self.workspace)
        self.code_editor = CodeEditor(self.workspace)

        # 코드 심볼 인덱스 (파일별 함수/클래스/변수 등) - ToolExecutor보다 먼저 초기화
        self.symbol_index: Dict[str, dict] = {}  # {file_path: {symbols...}}

        # ToolExecutor에 symbol_index와 search_engine 전달
        self.tool_executor = ToolExecutor(self.workspace, self.tx_manager, self.symbol_index, self.search_engine)

        # WebSocket 연결 관리
        self.active_connections: List[WebSocket] = []
        self.abort_requested = False  # 생성 중단 플래그

        # 대화 이력
        self.conversation_history: List[Dict[str, str]] = []

        # 컨텍스트 압축 설정 (Claude Code 패턴) - 30K 토큰 초과 시 압축
        self.context_token_limit = 30000
        self.compressed_summary = ""  # 압축된 이전 대화 요약

        # Agentic Loop 상태
        self.pending_tool_confirmations: Dict[str, dict] = {}  # {confirmation_id: tool_info}

        # 인덱싱
        self._index_workspace()

        # 워크스페이스 파일 개수 확인
        try:
            file_count = len(os.listdir(self.workspace))
            print(f"   파일/폴더 개수: {file_count}")
        except Exception as e:
            print(f"   ⚠️ 디렉토리 읽기 오류: {e}")

    def _index_workspace(self):
        """워크스페이스 인덱싱"""
        try:
            self.search_engine.index_codebase()
        except Exception as e:
            print(f"인덱싱 오류: {e}")

    def _extract_symbols(self, file_path: str, content: str) -> dict:
        """파일에서 심볼(함수, 클래스, 변수 등) 추출 - AST 파싱"""
        import ast
        import re

        ext = os.path.splitext(file_path)[1].lower()
        symbols = {
            "file": file_path,
            "lines": content.count('\n') + 1,
            "imports": [],
            "classes": [],
            "functions": [],
            "variables": [],
            "exports": []  # JS/TS용
        }

        try:
            # ========== Python ==========
            if ext == '.py':
                tree = ast.parse(content)

                for node in ast.walk(tree):
                    # Import
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            symbols["imports"].append({
                                "name": alias.name,
                                "line": node.lineno
                            })
                    elif isinstance(node, ast.ImportFrom):
                        module = node.module or ""
                        for alias in node.names:
                            symbols["imports"].append({
                                "name": f"{module}.{alias.name}",
                                "line": node.lineno
                            })

                    # Class
                    elif isinstance(node, ast.ClassDef):
                        methods = []
                        class_vars = []
                        for item in node.body:
                            if isinstance(item, ast.FunctionDef) or isinstance(item, ast.AsyncFunctionDef):
                                methods.append({
                                    "name": item.name,
                                    "line": item.lineno,
                                    "args": [arg.arg for arg in item.args.args]
                                })
                            elif isinstance(item, ast.Assign):
                                for target in item.targets:
                                    if isinstance(target, ast.Name):
                                        class_vars.append(target.id)

                        symbols["classes"].append({
                            "name": node.name,
                            "line": node.lineno,
                            "bases": [self._get_name(base) for base in node.bases],
                            "methods": methods,
                            "variables": class_vars
                        })

                    # Top-level Function
                    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        # 클래스 내부 함수는 제외 (이미 위에서 처리)
                        if not any(isinstance(parent, ast.ClassDef) for parent in ast.walk(tree)):
                            pass  # 복잡해서 일단 모든 함수 추가
                        symbols["functions"].append({
                            "name": node.name,
                            "line": node.lineno,
                            "args": [arg.arg for arg in node.args.args],
                            "is_async": isinstance(node, ast.AsyncFunctionDef),
                            "decorators": [self._get_name(d) for d in node.decorator_list]
                        })

                    # Top-level Variable
                    elif isinstance(node, ast.Assign):
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                symbols["variables"].append({
                                    "name": target.id,
                                    "line": node.lineno
                                })

            # ========== JavaScript / TypeScript ==========
            elif ext in ['.js', '.ts', '.jsx', '.tsx']:
                # 정규식 기반 파싱 (AST 없이)
                lines = content.split('\n')

                for i, line in enumerate(lines, 1):
                    # import
                    import_match = re.match(r'import\s+.*?from\s+[\'"](.+?)[\'"]', line)
                    if import_match:
                        symbols["imports"].append({"name": import_match.group(1), "line": i})

                    # class
                    class_match = re.match(r'(?:export\s+)?class\s+(\w+)', line)
                    if class_match:
                        symbols["classes"].append({"name": class_match.group(1), "line": i})

                    # function (여러 형태)
                    func_patterns = [
                        r'(?:export\s+)?(?:async\s+)?function\s+(\w+)',
                        r'(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s+)?\(',
                        r'(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s+)?\w+\s*=>'
                    ]
                    for pattern in func_patterns:
                        func_match = re.match(pattern, line)
                        if func_match:
                            symbols["functions"].append({"name": func_match.group(1), "line": i})
                            break

                    # export
                    export_match = re.match(r'export\s+(?:default\s+)?(\w+)', line)
                    if export_match:
                        symbols["exports"].append({"name": export_match.group(1), "line": i})

            # ========== 기타 언어 ==========
            else:
                # 간단한 정규식으로 함수/클래스 추출
                lines = content.split('\n')
                for i, line in enumerate(lines, 1):
                    # def, func, function
                    func_match = re.match(r'\s*(?:def|func|function|fn)\s+(\w+)', line)
                    if func_match:
                        symbols["functions"].append({"name": func_match.group(1), "line": i})

                    # class, struct, interface
                    class_match = re.match(r'\s*(?:class|struct|interface|type)\s+(\w+)', line)
                    if class_match:
                        symbols["classes"].append({"name": class_match.group(1), "line": i})

        except Exception as e:
            symbols["parse_error"] = str(e)

        return symbols

    def _get_name(self, node) -> str:
        """AST 노드에서 이름 추출"""
        import ast
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._get_name(node.value)}.{node.attr}"
        elif isinstance(node, ast.Call):
            return self._get_name(node.func)
        return str(node)

    def _get_symbol_summary(self) -> str:
        """인덱싱된 심볼 요약 (LLM 컨텍스트용)"""
        if not self.symbol_index:
            return ""

        summary_lines = ["## 📚 확인한 코드 심볼"]

        for file_path, symbols in self.symbol_index.items():
            file_name = os.path.basename(file_path)
            summary_lines.append(f"\n### {file_name} ({symbols.get('lines', '?')}줄)")

            # Classes
            if symbols.get("classes"):
                for cls in symbols["classes"]:
                    methods = ", ".join([m["name"] for m in cls.get("methods", [])[:5]])
                    if methods:
                        summary_lines.append(f"  - class **{cls['name']}** (line {cls['line']}): {methods}")
                    else:
                        summary_lines.append(f"  - class **{cls['name']}** (line {cls['line']})")

            # Functions
            if symbols.get("functions"):
                funcs = symbols["functions"][:10]  # 최대 10개
                func_list = ", ".join([f"{f['name']}:{f['line']}" for f in funcs])
                summary_lines.append(f"  - functions: {func_list}")

            # Imports
            if symbols.get("imports"):
                imports = [imp["name"].split(".")[-1] for imp in symbols["imports"][:10]]
                summary_lines.append(f"  - imports: {', '.join(imports)}")

        return "\n".join(summary_lines)

    def _estimate_tokens(self, text: str) -> int:
        """토큰 수 추정 (한글은 1.5배, 영문은 0.25배)"""
        korean_chars = sum(1 for c in text if '\uac00' <= c <= '\ud7a3')
        other_chars = len(text) - korean_chars
        return int(korean_chars * 1.5 + other_chars * 0.25)

    def _get_conversation_tokens(self) -> int:
        """현재 대화의 총 토큰 수 계산"""
        total = 0
        for msg in self.conversation_history:
            total += self._estimate_tokens(msg.get("content", ""))
        if self.compressed_summary:
            total += self._estimate_tokens(self.compressed_summary)
        return total

    async def _compress_context_if_needed(self) -> bool:
        """30K 토큰 초과 시 컨텍스트 압축 (Qwen 7860 포트 사용)"""
        import httpx

        current_tokens = self._get_conversation_tokens()
        if current_tokens <= self.context_token_limit:
            return False

        print(f"🗜️ 컨텍스트 압축 시작 (현재: {current_tokens} 토큰)")

        # 압축할 대화 선택 (최근 10개는 유지)
        if len(self.conversation_history) <= 10:
            return False

        to_compress = self.conversation_history[:-10]
        to_keep = self.conversation_history[-10:]

        # 압축용 텍스트 생성
        compress_text = "\n".join([
            f"{msg['role']}: {msg['content'][:500]}"
            for msg in to_compress
        ])

        # Qwen에게 요약 요청
        summary_prompt = f"""다음 대화를 5-10줄로 핵심만 요약해주세요.
중요한 결정, 수정된 파일, 해결된 문제를 중심으로:

{compress_text[:8000]}

JSON 형식으로 답변: {{"summary": "요약 내용", "key_files": ["파일1", "파일2"], "decisions": ["결정1"]}}"""

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "http://localhost:7860/api/chat/stream",
                    json={
                        "message": summary_prompt,
                        "system_prompt": "너는 대화 요약 전문가다. 핵심만 간결하게 요약한다.",
                        "stream": False
                    },
                    timeout=30
                )

                if response.status_code == 200:
                    result = response.json()
                    summary = result.get("content", "")

                    # 이전 요약과 합치기
                    if self.compressed_summary:
                        self.compressed_summary = f"[이전 요약]\n{self.compressed_summary}\n\n[새 요약]\n{summary}"
                    else:
                        self.compressed_summary = summary

                    # 압축된 대화 제거, 최근 10개만 유지
                    self.conversation_history = to_keep

                    new_tokens = self._get_conversation_tokens()
                    print(f"✅ 컨텍스트 압축 완료: {current_tokens} → {new_tokens} 토큰")
                    return True

        except Exception as e:
            print(f"❌ 컨텍스트 압축 실패: {e}")

        return False

    def _create_app(self) -> FastAPI:
        """FastAPI 앱 생성"""
        app = FastAPI(
            title="MAEUM_CODE IDE",
            description="로컬 전용 웹 기반 AI 코딩 IDE",
            version="1.0.0"
        )

        # CORS (로컬 전용)
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:8880", "http://127.0.0.1:8880"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # 라우트 등록
        self._register_routes(app)

        return app

    def _register_routes(self, app: FastAPI):
        """라우트 등록"""

        # ========== 정적 파일 (오프라인 지원) ==========
        static_dir = Path(__file__).parent / "static"
        print(f"📁 Static 디렉토리: {static_dir}")
        print(f"📁 Static 존재 여부: {static_dir.exists()}")
        if static_dir.exists():
            app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
            print(f"✅ Static 파일 마운트 완료: /static -> {static_dir}")
        else:
            print(f"⚠️ Static 디렉토리 없음! 마크다운 렌더링 안 될 수 있음")

        @app.get("/", response_class=HTMLResponse)
        async def get_index():
            """메인 IDE 페이지"""
            return self._get_ide_html()

        # ========== 워크스페이스 정보 ==========

        @app.get("/api/workspace")
        async def get_workspace():
            """워크스페이스 정보"""
            return {
                "path": self.workspace,
                "name": os.path.basename(self.workspace) or self.workspace
            }

        # ========== 파일 시스템 API ==========

        @app.get("/api/files")
        async def list_files(path: str = ""):
            """디렉토리 내용 조회"""
            try:
                full_path = os.path.join(self.workspace, path)
                print(f"📁 [/api/files] 요청 경로: {path}")
                print(f"   전체 경로: {full_path}")
                print(f"   워크스페이스: {self.workspace}")

                if not os.path.exists(full_path):
                    print(f"   ❌ 경로 없음: {full_path}")
                    raise HTTPException(status_code=404, detail="경로를 찾을 수 없습니다")

                if not os.path.isdir(full_path):
                    print(f"   ❌ 디렉토리 아님: {full_path}")
                    raise HTTPException(status_code=400, detail="디렉토리가 아닙니다")

                items = []
                for name in sorted(os.listdir(full_path)):
                    item_path = os.path.join(full_path, name)
                    rel_path = os.path.relpath(item_path, self.workspace)

                    # 숨김 파일/디렉토리 제외 (선택적)
                    if name.startswith('.') and name not in ['.gitignore', '.env.example']:
                        continue

                    is_dir = os.path.isdir(item_path)
                    stat = os.stat(item_path)

                    items.append({
                        "name": name,
                        "path": rel_path,
                        "is_directory": is_dir,
                        "size": stat.st_size if not is_dir else 0,
                        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        "extension": Path(name).suffix.lower() if not is_dir else None
                    })

                # 디렉토리 먼저, 그 다음 파일
                items.sort(key=lambda x: (not x["is_directory"], x["name"].lower()))

                print(f"   ✅ 파일 목록: {len(items)}개")
                return {"path": path, "items": items}

            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.get("/api/file")
        async def read_file(path: str):
            """파일 내용 읽기"""
            try:
                full_path = os.path.join(self.workspace, path)
                if not os.path.exists(full_path):
                    raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다")

                if os.path.isdir(full_path):
                    raise HTTPException(status_code=400, detail="디렉토리는 읽을 수 없습니다")

                # 파일 크기 제한 (10MB)
                if os.path.getsize(full_path) > 10 * 1024 * 1024:
                    raise HTTPException(status_code=400, detail="파일이 너무 큽니다 (최대 10MB)")

                # 바이너리 파일 감지
                mime_type, _ = mimetypes.guess_type(full_path)
                is_binary = mime_type and not mime_type.startswith('text') and \
                           mime_type not in ['application/json', 'application/javascript',
                                            'application/xml', 'application/x-python']

                if is_binary:
                    return {
                        "path": path,
                        "content": None,
                        "is_binary": True,
                        "mime_type": mime_type,
                        "size": os.path.getsize(full_path)
                    }

                # 텍스트 파일 읽기
                try:
                    with open(full_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                except UnicodeDecodeError:
                    # 다른 인코딩 시도
                    try:
                        with open(full_path, 'r', encoding='cp949') as f:
                            content = f.read()
                    except:
                        with open(full_path, 'r', encoding='latin-1') as f:
                            content = f.read()

                return {
                    "path": path,
                    "content": content,
                    "is_binary": False,
                    "language": self._detect_language(path)
                }

            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.post("/api/file")
        async def save_file(file_data: FileContent):
            """파일 저장"""
            try:
                full_path = os.path.join(self.workspace, file_data.path)

                # 트랜잭션으로 저장
                self.tx_manager.begin(f"Save {file_data.path}")

                if os.path.exists(full_path):
                    # 기존 파일 수정
                    with open(full_path, 'r', encoding='utf-8') as f:
                        old_content = f.read()
                    self.tx_manager.write(file_data.path, file_data.content)
                else:
                    # 새 파일 생성
                    os.makedirs(os.path.dirname(full_path), exist_ok=True)
                    self.tx_manager.write(file_data.path, file_data.content)

                self.tx_manager.commit()

                return {"success": True, "path": file_data.path}

            except Exception as e:
                self.tx_manager.rollback()
                raise HTTPException(status_code=500, detail=str(e))

        @app.post("/api/file/create")
        async def create_file(file_data: FileCreate):
            """파일/디렉토리 생성"""
            try:
                full_path = os.path.join(self.workspace, file_data.path)

                if os.path.exists(full_path):
                    raise HTTPException(status_code=400, detail="이미 존재합니다")

                if file_data.is_directory:
                    os.makedirs(full_path, exist_ok=True)
                else:
                    os.makedirs(os.path.dirname(full_path), exist_ok=True)
                    with open(full_path, 'w', encoding='utf-8') as f:
                        f.write(file_data.content)

                return {"success": True, "path": file_data.path}

            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.post("/api/file/rename")
        async def rename_file(data: FileRename):
            """파일/디렉토리 이름 변경"""
            try:
                old_full = os.path.join(self.workspace, data.old_path)
                new_full = os.path.join(self.workspace, data.new_path)

                if not os.path.exists(old_full):
                    raise HTTPException(status_code=404, detail="원본을 찾을 수 없습니다")

                if os.path.exists(new_full):
                    raise HTTPException(status_code=400, detail="대상이 이미 존재합니다")

                os.makedirs(os.path.dirname(new_full), exist_ok=True)
                os.rename(old_full, new_full)

                return {"success": True, "old_path": data.old_path, "new_path": data.new_path}

            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.delete("/api/file")
        async def delete_file(path: str):
            """파일/디렉토리 삭제"""
            try:
                full_path = os.path.join(self.workspace, path)

                if not os.path.exists(full_path):
                    raise HTTPException(status_code=404, detail="찾을 수 없습니다")

                if os.path.isdir(full_path):
                    import shutil
                    shutil.rmtree(full_path)
                else:
                    os.remove(full_path)

                return {"success": True, "path": path}

            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        # ========== 검색 API ==========

        @app.get("/api/search")
        async def search(q: str, mode: str = "content"):
            """코드/파일/심볼 검색"""
            try:
                if mode == "file":
                    results = self.search_engine.find_files(q)
                elif mode == "symbol":
                    results = self.search_engine.find_symbol(q)
                else:
                    results = self.search_engine.search(q)

                return {
                    "query": q,
                    "mode": mode,
                    "count": len(results.matches) if hasattr(results, 'matches') else len(results),
                    "results": self._format_search_results(results)
                }

            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        # ========== Undo/Redo API ==========

        @app.post("/api/undo")
        async def undo(confirm: bool = True):
            """실행 취소 - confirm=False면 미리보기만"""
            try:
                # 미리보기: 무엇이 취소될지 확인
                if not confirm:
                    if not self.tx_manager.undo_manager.can_undo:
                        return {"success": False, "message": "실행 취소할 항목이 없습니다"}

                    last_tx = self.tx_manager.undo_manager._undo_stack[-1]
                    return {
                        "success": True,
                        "preview": True,
                        "transaction": {
                            "id": last_tx.id,
                            "description": last_tx.description,
                            "files": [c.file_path for c in last_tx.changes],
                            "operations": [c.operation.value for c in last_tx.changes],
                            "timestamp": last_tx.timestamp
                        }
                    }

                # 실제 실행
                tx = self.tx_manager.undo()
                if tx:
                    return {
                        "success": True,
                        "message": f"실행 취소됨: {tx.description}",
                        "files": [c.file_path for c in tx.changes]
                    }
                return {"success": False, "message": "실행 취소할 항목이 없습니다"}
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.post("/api/redo")
        async def redo(confirm: bool = True):
            """다시 실행 - confirm=False면 미리보기만"""
            try:
                # 미리보기
                if not confirm:
                    if not self.tx_manager.undo_manager.can_redo:
                        return {"success": False, "message": "다시 실행할 항목이 없습니다"}

                    last_tx = self.tx_manager.undo_manager._redo_stack[-1]
                    return {
                        "success": True,
                        "preview": True,
                        "transaction": {
                            "id": last_tx.id,
                            "description": last_tx.description,
                            "files": [c.file_path for c in last_tx.changes],
                            "operations": [c.operation.value for c in last_tx.changes],
                            "timestamp": last_tx.timestamp
                        }
                    }

                # 실제 실행
                tx = self.tx_manager.redo()
                if tx:
                    return {
                        "success": True,
                        "message": f"다시 실행됨: {tx.description}",
                        "files": [c.file_path for c in tx.changes]
                    }
                return {"success": False, "message": "다시 실행할 항목이 없습니다"}
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.get("/api/history")
        async def get_history():
            """변경 이력"""
            try:
                history = self.tx_manager.undo_manager.get_history()
                return {"history": history}
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        # ========== 코드 편집 API ==========

        @app.post("/api/edit")
        async def edit_code(op: EditOperation):
            """코드 편집 (old_text -> new_text 치환)"""
            try:
                self.tx_manager.begin(f"Edit {op.path}")
                success = self.tx_manager.edit(op.path, op.old_text, op.new_text)
                if success:
                    self.tx_manager.commit()
                    return {"success": True, "path": op.path}
                else:
                    self.tx_manager.rollback()
                    raise HTTPException(status_code=400, detail="편집 실패: 텍스트를 찾을 수 없습니다")
            except HTTPException:
                raise
            except Exception as e:
                self.tx_manager.rollback()
                raise HTTPException(status_code=500, detail=str(e))

        @app.post("/api/edit/batch")
        async def batch_edit(batch: BatchEditOperation):
            """일괄 코드 편집"""
            try:
                edits = [(op.path, op.old_text, op.new_text) for op in batch.operations]
                result = self.batch_editor.batch_edit(edits, batch.description)
                return {
                    "success": result.get("success", False),
                    "applied": result.get("applied", []),
                    "errors": result.get("errors", [])
                }
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.post("/api/code/write")
        async def ai_write_code(req: CodeWriteRequest):
            """AI 코드 작성 요청"""
            try:
                result = self.code_writer.write_code(req.request, req.target_file)

                if not result.success:
                    return {
                        "success": False,
                        "error": result.error,
                        "message": result.message
                    }

                # 자동 적용
                if req.auto_apply:
                    apply_result = self.code_writer.apply_changes(result, dry_run=False)
                    return {
                        "success": True,
                        "message": result.message,
                        "changes": [c.__dict__ for c in result.changes],
                        "applied": apply_result
                    }

                return {
                    "success": True,
                    "message": result.message,
                    "changes": [c.__dict__ for c in result.changes]
                }
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.post("/api/code/apply")
        async def apply_code_changes(changes: List[Dict[str, Any]]):
            """코드 변경 적용"""
            try:
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
                apply_result = self.code_writer.apply_changes(result, dry_run=False)
                return apply_result
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        # ========== 분류기 API ==========

        @app.post("/api/classify")
        async def classify_input(message: ChatMessage):
            """입력 분류 (ERROR_CUT, PATH_JUDGE, CONTEXT_SET, ARCH_SNAPSHOT)"""
            try:
                result = self.classifier.classify(message.message)
                return {
                    "action": result.action.name,
                    "confidence": result.confidence,
                    "metadata": result.metadata
                }
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        # ========== 인덱싱 API ==========

        @app.post("/api/index/refresh")
        async def refresh_index():
            """검색 인덱스 새로고침"""
            try:
                self.search_engine.index_codebase()
                return {"success": True, "message": "인덱스 갱신 완료"}
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.get("/api/index/stats")
        async def index_stats():
            """인덱스 통계"""
            try:
                return {
                    "workspace": self.workspace,
                    "file_count": len(self.search_engine.file_index) if hasattr(self.search_engine, 'file_index') else 0,
                    "symbol_count": len(self.search_engine.symbol_index) if hasattr(self.search_engine, 'symbol_index') else 0
                }
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        # ========== 대화 이력 API ==========

        @app.get("/api/chat/history")
        async def get_chat_history():
            """대화 이력 조회"""
            return {"history": self.conversation_history[-50:]}  # 최근 50개

        @app.delete("/api/chat/history")
        async def clear_chat_history():
            """대화 이력 삭제"""
            self.conversation_history.clear()
            return {"success": True}

        # ========== 파일 분석 API ==========

        @app.get("/api/analyze/file")
        async def analyze_file(path: str):
            """파일 분석"""
            try:
                full_path = os.path.join(self.workspace, path)
                if not os.path.exists(full_path):
                    raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다")

                # 파일 정보
                stat = os.stat(full_path)

                # 심볼 검색
                symbols = []
                try:
                    result = self.search_engine.find_symbol("", file_filter=path)
                    if hasattr(result, 'matches'):
                        symbols = [{"name": m.content, "line": m.line} for m in result.matches[:20]]
                except:
                    pass

                return {
                    "path": path,
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "language": self._detect_language(path),
                    "symbols": symbols
                }
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.get("/api/analyze/workspace")
        async def analyze_workspace():
            """워크스페이스 분석"""
            try:
                # 코드베이스 컨텍스트 분석
                try:
                    context = self.code_writer.analyze_context()
                    return {
                        "root_path": context.root_path,
                        "structure_summary": context.structure_summary,
                        "pattern": context.pattern,
                        "related_files": context.related_files[:30]
                    }
                except:
                    # 간단한 분석
                    file_count = 0
                    ext_counts = {}
                    for root, dirs, files in os.walk(self.workspace):
                        # 숨김 폴더 제외
                        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['node_modules', '__pycache__', 'venv']]
                        for f in files:
                            if not f.startswith('.'):
                                file_count += 1
                                ext = Path(f).suffix.lower()
                                ext_counts[ext] = ext_counts.get(ext, 0) + 1

                    return {
                        "root_path": self.workspace,
                        "file_count": file_count,
                        "extensions": dict(sorted(ext_counts.items(), key=lambda x: -x[1])[:10])
                    }
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        # ========== AI 상태 API ==========

        @app.get("/api/ai/status")
        async def ai_status():
            """AI 서버 상태"""
            try:
                status = check_server()
                return status
            except Exception as e:
                return {"available": False, "error": str(e)}

        @app.post("/api/abort")
        async def abort_generation():
            """AI 생성 중단"""
            try:
                self.abort_requested = True
                await self._send_abort_signal()
                return {"success": True, "message": "Abort signal sent"}
            except Exception as e:
                return {"success": False, "error": str(e)}

        # ========== WebSocket (AI 채팅 + Agentic Loop) ==========

        @app.websocket("/ws/chat")
        async def websocket_chat(websocket: WebSocket):
            """AI 채팅 WebSocket with Agentic Loop"""
            await websocket.accept()
            self.active_connections.append(websocket)
            cancelled = False  # ESC 취소 플래그

            try:
                while True:
                    # 메시지 수신
                    data = await websocket.receive_text()
                    message_data = json.loads(data)

                    msg_type = message_data.get("type", "chat")

                    # ESC 취소 처리
                    if msg_type == "cancel":
                        cancelled = True
                        print("⚠️ 사용자가 작업을 취소했습니다")
                        await websocket.send_json({
                            "type": "cancelled",
                            "content": "작업이 취소되었습니다"
                        })
                        continue

                    # 도구 확인 응답 처리
                    if msg_type == "tool_confirm":
                        confirmation_id = message_data.get("confirmation_id")
                        approved = message_data.get("approved", False)

                        if confirmation_id in self.pending_tool_confirmations:
                            tool_info = self.pending_tool_confirmations.pop(confirmation_id)

                            if approved:
                                # 도구 실행
                                tool_name = tool_info["tool_name"]
                                tool_input = tool_info["tool_input"]

                                result = self.tool_executor.execute(tool_name, tool_input)

                                await websocket.send_json({
                                    "type": "tool_result",
                                    "tool_name": tool_name,
                                    "result": result
                                })

                                # 파일 수정 도구면 에디터 새로고침 요청
                                file_path = tool_input.get("file_path") or tool_input.get("path")
                                if tool_name in ["edit_file", "write_file"] and result.get("success"):
                                    await websocket.send_json({
                                        "type": "file_modified",
                                        "file_path": file_path,
                                        "action": result.get("action", "modified")
                                    })
                                    print(f"✅ 파일 수정 완료: {file_path}")

                                # 🔥 핵심: 승인 후 Agentic Loop 재시작 (연속 작업 가능)
                                # 저장된 맥락으로 루프 계속
                                if hasattr(self, '_pending_loop_context'):
                                    ctx = self._pending_loop_context
                                    tool_result_str = json.dumps(result, ensure_ascii=False, indent=2)
                                    continue_message = f"""
도구 실행 결과:
```json
{tool_result_str[:2000]}
```

위 결과를 바탕으로 다음 작업을 계속하세요. 추가 수정이 필요하면 edit_file을, 완료됐으면 사용자에게 결과를 설명하세요.
"""
                                    # Agentic Loop 재시작
                                    await self._run_agentic_loop(
                                        websocket,
                                        continue_message,
                                        ctx.get('system_prompt', ''),
                                        ctx.get('stream', False)
                                    )
                                    del self._pending_loop_context
                            else:
                                # 거부됨 - 결과 전송 후 done으로 종료
                                await websocket.send_json({
                                    "type": "tool_result",
                                    "tool_name": tool_info["tool_name"],
                                    "result": {"success": False, "error": "사용자가 거부함"}
                                })
                                await websocket.send_json({
                                    "type": "done",
                                    "content": "도구 실행이 거부되어 작업을 중단합니다."
                                })
                                # 거부 시 대기 컨텍스트 정리
                                if hasattr(self, '_pending_loop_context'):
                                    del self._pending_loop_context
                        continue

                    # 일반 채팅 메시지
                    user_message = message_data.get("message", "")
                    context = message_data.get("context", "")
                    current_file = message_data.get("currentFile")  # 현재 열린 파일 정보
                    open_tabs = message_data.get("openTabs", [])  # 열린 탭 목록
                    cancelled = False

                    # 디버그 로그
                    print(f"\n📨 사용자 메시지: {user_message[:100]}...")
                    print(f"📎 컨텍스트 길이: {len(context)} chars")
                    if current_file:
                        print(f"📄 현재 파일: {current_file.get('path')} (줄 {current_file.get('cursorLine')})")
                    if open_tabs:
                        print(f"📑 열린 탭: {len(open_tabs)}개")

                    # 현재 파일 정보를 인스턴스에 저장 (시스템 프롬프트에서 사용)
                    self.current_file_info = current_file
                    self.open_tabs_info = open_tabs

                    # 입력 분류
                    classification = self.classifier.classify(user_message)
                    print(f"🏷️ 분류: {classification.action.name} (신뢰도: {classification.confidence:.2f})")

                    # 대화 이력에 추가
                    self.conversation_history.append({
                        "role": "user",
                        "content": user_message,
                        "timestamp": datetime.now().isoformat()
                    })

                    # 컨텍스트 압축 체크 (30K 토큰 초과 시)
                    compressed = await self._compress_context_if_needed()
                    if compressed:
                        await websocket.send_json({
                            "type": "system",
                            "content": "🗜️ 대화 컨텍스트가 압축되었습니다."
                        })

                    # 시스템 프롬프트 구성
                    system_prompt = self._build_system_prompt(context, classification)

                    # ========== Agentic Loop ==========
                    try:
                        await self._run_agentic_loop(
                            websocket,
                            user_message,
                            system_prompt,
                            max_iterations=99
                        )
                    except Exception as e:
                        await websocket.send_json({
                            "type": "error",
                            "content": str(e)
                        })

            except WebSocketDisconnect:
                if websocket in self.active_connections:
                    self.active_connections.remove(websocket)
            except Exception as e:
                print(f"WebSocket 오류: {e}")
                if websocket in self.active_connections:
                    self.active_connections.remove(websocket)

    async def _run_agentic_loop(
        self,
        websocket: WebSocket,
        user_message: str,
        system_prompt: str,
        max_iterations: int = 99
    ):
        """Agentic Loop 실행 (maeum_code.py 스타일)"""
        import httpx
        import uuid

        full_response = ""
        iteration = 0
        exploration_count = 0  # 탐색 도구 카운터
        max_exploration = 20  # 탐색 도구 최대 횟수
        exploration_tools = {"list_dir", "read_file", "search_code"}  # 탐색 도구 목록

        self.abort_requested = False  # 새 대화 시작 시 리셋

        while iteration < max_iterations:
            # 중단 요청 체크
            if self.abort_requested:
                print("🛑 사용자에 의해 중단됨")
                self.abort_requested = False
                break

            iteration += 1
            print(f"🔄 Agentic Loop 반복 {iteration}/{max_iterations} (탐색: {exploration_count}/{max_exploration})")

            # AI 호출
            try:
                full_message = f"{system_prompt}\n\n사용자: {user_message}"

                if full_response:
                    full_message += f"\n\n이전 응답:\n{full_response[-2000:]}"

                token_queue = asyncio.Queue()

                async def generate():
                    try:
                        async with httpx.AsyncClient(timeout=120.0) as client:
                            async with client.stream(
                                "POST",
                                "http://localhost:7860/api/chat/stream",
                                json={"message": full_message}
                            ) as response:
                                async for line in response.aiter_lines():
                                    if line.startswith("data: "):
                                        try:
                                            chunk = json.loads(line[6:])
                                            token = chunk.get("token") or chunk.get("content", "")
                                            if token:
                                                await token_queue.put(("token", token))
                                        except:
                                            pass
                        await token_queue.put(("done", None))
                    except Exception as e:
                        await token_queue.put(("error", str(e)))

                gen_task = asyncio.create_task(generate())

                # ========== 구조화된 Tool Use 패턴 ==========
                # [TOOL:xxx] 감지 시 즉시 중단 → 도구 실행 → 결과로 다음 턴
                current_response = ""
                display_buffer = ""
                tool_detected = None  # 감지된 도구 정보
                tool_block_buffer = ""
                in_tool_block = False

                while True:
                    msg_type, content = await token_queue.get()

                    if msg_type == "token":
                        current_response += content

                        # 도구 블록 내부라면 버퍼에만 추가
                        if in_tool_block:
                            tool_block_buffer += content
                            # 도구 블록 완료 확인 (``` 열고 닫힘)
                            backtick_count = tool_block_buffer.count("```")
                            if backtick_count >= 2:
                                # 도구 파싱 시도
                                tool_detected = self._parse_tool_block(tool_block_buffer)
                                if tool_detected:
                                    # 도구 감지됨 - 즉시 스트리밍 중단!
                                    print(f"🔧 Tool detected: {tool_detected['name']}")

                                    # KoboldCpp abort 신호 전송
                                    await self._send_abort_signal()
                                    gen_task.cancel()
                                    try:
                                        await gen_task
                                    except asyncio.CancelledError:
                                        pass

                                    # 사용자에게 도구 감지 알림
                                    await websocket.send_json({
                                        "type": "tool_detected",
                                        "tool_name": tool_detected["name"],
                                        "tool_input": tool_detected["input"]
                                    })
                                    break
                                else:
                                    # 파싱 실패 - 일반 텍스트로 처리
                                    print(f"⚠️ Tool parse failed, treating as text")
                                    in_tool_block = False
                                    # 버퍼링된 텍스트 표시
                                    await websocket.send_json({
                                        "type": "token",
                                        "content": tool_block_buffer
                                    })
                                    display_buffer += tool_block_buffer
                                    tool_block_buffer = ""
                        else:
                            # [TOOL: 시작 감지
                            if "[TOOL:" in current_response and not in_tool_block:
                                in_tool_block = True
                                # [TOOL: 이전 텍스트만 표시
                                before_tool = current_response.split("[TOOL:")[0]
                                if before_tool and before_tool.strip() and before_tool not in display_buffer:
                                    new_text = before_tool[len(display_buffer):]
                                    if new_text:
                                        await websocket.send_json({
                                            "type": "token",
                                            "content": new_text
                                        })
                                display_buffer = before_tool
                                tool_block_buffer = "[TOOL:" + current_response.split("[TOOL:", 1)[1]
                            else:
                                # 일반 텍스트 표시
                                await websocket.send_json({
                                    "type": "token",
                                    "content": content
                                })
                                display_buffer += content

                    elif msg_type == "done":
                        break
                    elif msg_type == "error":
                        await websocket.send_json({
                            "type": "error",
                            "content": content
                        })
                        try:
                            await gen_task
                        except:
                            pass
                        return

                # 스트리밍 완료 또는 도구 감지로 중단됨
                if not tool_detected:
                    try:
                        await gen_task
                    except:
                        pass

                full_response += current_response

                # 도구 감지 확인
                if not tool_detected:
                    tool_calls = self._detect_tool_calls(current_response)
                    if tool_calls:
                        tool_detected = tool_calls[0]

                # 도구가 없으면 - 첫 번째만 사용
                tool_calls = [tool_detected] if tool_detected else []

                if not tool_calls:
                    # 도구 호출 없음 → 완료
                    self.conversation_history.append({
                        "role": "assistant",
                        "content": full_response[:500],
                        "timestamp": datetime.now().isoformat()
                    })
                    await websocket.send_json({
                        "type": "done",
                        "content": full_response
                    })
                    return

                # 도구 실행
                for tool_call in tool_calls:
                    tool_name = tool_call["name"]
                    tool_input = tool_call["input"]

                    # 위험한 도구는 확인 요청
                    needs_confirm = tool_name in ["write_file", "edit_file", "bash"]

                    if needs_confirm:
                        confirm_id = str(uuid.uuid4())[:8]
                        self.pending_tool_confirmations[confirm_id] = {
                            "tool_name": tool_name,
                            "tool_input": tool_input
                        }

                        # 🔥 루프 컨텍스트 저장 (승인 후 재개용)
                        self._pending_loop_context = {
                            "system_prompt": system_prompt,
                            "stream": stream,
                            "user_message": user_message,
                            "full_response": full_response
                        }

                        await websocket.send_json({
                            "type": "tool_confirm_request",
                            "confirmation_id": confirm_id,
                            "tool_name": tool_name,
                            "tool_input": tool_input,
                            "description": self._get_tool_description(tool_name, tool_input)
                        })

                        # 확인 대기 (타임아웃 30초)
                        # 실제로는 별도 메시지로 처리됨
                        await websocket.send_json({
                            "type": "waiting_confirmation",
                            "confirmation_id": confirm_id
                        })
                        return  # 확인 대기 중 루프 종료
                    else:
                        # 자동 실행 (read_file, list_dir, search_code)

                        # 탐색 도구 카운터 체크
                        if tool_name in exploration_tools:
                            exploration_count += 1
                            if exploration_count > max_exploration:
                                # 탐색 제한 도달 - 부드럽게 안내
                                await websocket.send_json({
                                    "type": "token",
                                    "content": f"\n\n---\n충분히 탐색했습니다. 이제 파악한 내용을 정리해드리겠습니다.\n\n"
                                })
                                # 도구 실행 없이 다음 턴으로 - LLM에게 부드럽게 안내
                                user_message += f"""

---
[시스템 안내]
탐색을 충분히 진행했습니다 ({max_exploration}회).
지금까지 수집한 정보를 바탕으로 사용자의 질문에 답변해주세요.
추가 탐색 없이, 파악한 내용을 명확하게 정리해서 설명해주세요.
"""
                                continue

                        # Step 1: 실행 시작 알림
                        await websocket.send_json({
                            "type": "tool_executing",
                            "tool_name": tool_name,
                            "tool_input": tool_input,
                            "exploration_count": exploration_count if tool_name in exploration_tools else None,
                            "max_exploration": max_exploration
                        })

                        # Step-by-step: 0.5초 대기 (사용자가 볼 수 있도록)
                        await asyncio.sleep(0.5)

                        # Step 2: 파일 관련 도구는 에디터에서 열기
                        file_path = tool_input.get("path") or tool_input.get("file_path")
                        if file_path and tool_name in ["read_file", "edit_file", "write_file", "search_code"]:
                            await websocket.send_json({
                                "type": "open_in_editor",
                                "file_path": file_path,
                                "tool_name": tool_name,
                                "line": tool_input.get("line", 1)  # 특정 라인으로 이동
                            })
                            await asyncio.sleep(0.3)  # 에디터 열릴 시간

                        result = self.tool_executor.execute(tool_name, tool_input)

                        # Step 3: 결과 전송
                        await asyncio.sleep(0.3)
                        await websocket.send_json({
                            "type": "tool_result",
                            "tool_name": tool_name,
                            "result": result,
                            "file_path": file_path  # 에디터 업데이트용
                        })

                        # Step 4: 파일 수정 도구면 에디터 새로고침 요청
                        if tool_name in ["edit_file", "write_file"] and result.get("success"):
                            await websocket.send_json({
                                "type": "file_modified",
                                "file_path": file_path,
                                "action": result.get("action", "modified")
                            })

                        # 결과를 컨텍스트에 추가 (맥락 유지)
                        tool_result_str = json.dumps(result, ensure_ascii=False, indent=2)

                        # 탐색 횟수 안내 추가
                        remaining = max_exploration - exploration_count
                        exploration_hint = f"\n(탐색 {exploration_count}/{max_exploration}회 사용)" if tool_name in exploration_tools else ""

                        # AI에게 도구 결과와 다음 행동 지시
                        context_update = f"""

---
## [도구 실행 결과: {tool_name}]{exploration_hint}
{tool_result_str[:3000]}
---

위 결과를 바탕으로 계속 진행하세요.
- 더 궁금한 파일이 있으면 read_file로 읽으세요.
- 연관된 코드를 찾으려면 search_code를 사용하세요.
- 충분히 이해했으면 사용자에게 설명하세요.
"""
                        user_message = f"{user_message}{context_update}"

            except Exception as e:
                print(f"❌ Agentic Loop 오류: {e}")
                await websocket.send_json({
                    "type": "error",
                    "content": str(e)
                })
                return

        # 최대 반복 도달
        await websocket.send_json({
            "type": "done",
            "content": full_response + "\n\n[최대 반복 횟수 도달]"
        })

    async def _send_abort_signal(self):
        """KoboldCpp에 abort 신호 전송 (Qwen 12345, Gemma 12346)"""
        try:
            async with httpx.AsyncClient() as client:
                # Qwen (12345) abort
                try:
                    await client.post(
                        "http://localhost:12345/api/extra/abort",
                        timeout=2.0
                    )
                    print("🛑 KoboldCpp (Qwen 12345) abort signal sent")
                except:
                    pass

                # 7860 포트도 시도 (통합 서버)
                try:
                    await client.post(
                        "http://localhost:7860/api/extra/abort",
                        timeout=2.0
                    )
                    print("🛑 KoboldCpp (7860) abort signal sent")
                except:
                    pass
        except Exception as e:
            print(f"⚠️ Abort signal failed: {e}")

    def _parse_tool_block(self, tool_block: str) -> Optional[dict]:
        """
        [TOOL:xxx]```json {...} ``` 형식의 도구 블록 파싱

        Args:
            tool_block: [TOOL:name]```json ... ``` 형식의 문자열

        Returns:
            {"name": "tool_name", "input": {...}} 또는 None
        """
        import re

        # 패턴: [TOOL:tool_name]```json? {...} ```
        pattern = r'\[TOOL:(\w+)\]\s*```(?:json)?\s*(.*?)\s*```'
        match = re.search(pattern, tool_block, re.DOTALL | re.IGNORECASE)

        if match:
            tool_name = match.group(1)
            json_str = match.group(2).strip()

            try:
                tool_input = json.loads(json_str)
                return {
                    "name": tool_name,
                    "input": tool_input
                }
            except json.JSONDecodeError as e:
                print(f"⚠️ Tool JSON parse error: {e}")
                print(f"   Raw JSON: {json_str[:100]}...")
                return None

        # 대체 패턴: ```tool:name {...} ```
        alt_pattern = r'```tool:(\w+)\s*(.*?)\s*```'
        alt_match = re.search(alt_pattern, tool_block, re.DOTALL | re.IGNORECASE)

        if alt_match:
            tool_name = alt_match.group(1)
            json_str = alt_match.group(2).strip()

            try:
                tool_input = json.loads(json_str)
                return {
                    "name": tool_name,
                    "input": tool_input
                }
            except:
                return None

        return None

    def _detect_tool_calls(self, response: str) -> List[dict]:
        """AI 응답에서 도구 호출 감지"""
        import re

        tool_calls = []

        # 패턴: [TOOL:tool_name]{json_input}
        pattern = r'\[TOOL:(\w+)\]\s*```json?\s*(.*?)\s*```'
        matches = re.findall(pattern, response, re.DOTALL | re.IGNORECASE)

        for tool_name, json_str in matches:
            try:
                tool_input = json.loads(json_str)
                tool_calls.append({
                    "name": tool_name,
                    "input": tool_input
                })
            except:
                pass

        # 대체 패턴: ```tool:name ... ```
        alt_pattern = r'```tool:(\w+)\s*(.*?)\s*```'
        alt_matches = re.findall(alt_pattern, response, re.DOTALL | re.IGNORECASE)

        for tool_name, json_str in alt_matches:
            try:
                tool_input = json.loads(json_str)
                if {"name": tool_name, "input": tool_input} not in tool_calls:
                    tool_calls.append({
                        "name": tool_name,
                        "input": tool_input
                    })
            except:
                pass

        return tool_calls

    def _get_tool_description(self, tool_name: str, tool_input: dict) -> str:
        """도구 실행 설명 생성"""
        if tool_name == "bash":
            return f"명령어 실행: {tool_input.get('command', '')}"
        elif tool_name == "write_file":
            path = tool_input.get('file_path', '')
            size = len(tool_input.get('content', ''))
            return f"파일 작성: {path} ({size}자)"
        elif tool_name == "edit_file":
            path = tool_input.get('file_path', '')
            return f"파일 수정: {path}"
        elif tool_name == "read_file":
            return f"파일 읽기: {tool_input.get('file_path', '')}"
        elif tool_name == "list_dir":
            return f"디렉토리 목록: {tool_input.get('path', '/')}"
        elif tool_name == "search_code":
            return f"코드 검색: {tool_input.get('query', '')}"
        return f"{tool_name}: {json.dumps(tool_input)}"

    def _detect_language(self, path: str) -> str:
        """파일 확장자로 언어 감지"""
        ext_map = {
            '.py': 'python',
            '.js': 'javascript',
            '.ts': 'typescript',
            '.tsx': 'typescript',
            '.jsx': 'javascript',
            '.html': 'html',
            '.css': 'css',
            '.scss': 'scss',
            '.json': 'json',
            '.md': 'markdown',
            '.yaml': 'yaml',
            '.yml': 'yaml',
            '.xml': 'xml',
            '.sql': 'sql',
            '.sh': 'shell',
            '.bash': 'shell',
            '.zsh': 'shell',
            '.c': 'c',
            '.cpp': 'cpp',
            '.h': 'c',
            '.hpp': 'cpp',
            '.java': 'java',
            '.go': 'go',
            '.rs': 'rust',
            '.rb': 'ruby',
            '.php': 'php',
            '.swift': 'swift',
            '.kt': 'kotlin',
            '.scala': 'scala',
            '.r': 'r',
            '.R': 'r',
            '.lua': 'lua',
            '.pl': 'perl',
            '.dockerfile': 'dockerfile',
            '.toml': 'toml',
            '.ini': 'ini',
            '.cfg': 'ini',
            '.env': 'shell',
        }
        ext = Path(path).suffix.lower()
        name = Path(path).name.lower()

        if name == 'dockerfile':
            return 'dockerfile'
        if name == 'makefile':
            return 'makefile'

        return ext_map.get(ext, 'plaintext')

    def _format_search_results(self, results) -> List[Dict]:
        """검색 결과 포맷팅"""
        if hasattr(results, 'matches'):
            return [
                {
                    "file": m.file,
                    "line": m.line,
                    "content": m.content,
                    "context": getattr(m, 'context', None)
                }
                for m in results.matches[:100]  # 최대 100개
            ]
        elif isinstance(results, list):
            return [
                {
                    "file": str(r) if isinstance(r, (str, Path)) else r.get('file', str(r)),
                    "line": r.get('line', 0) if isinstance(r, dict) else 0,
                    "content": r.get('content', '') if isinstance(r, dict) else ''
                }
                for r in results[:100]
            ]
        return []

    def _get_directory_tree(self, max_depth: int = 3, max_files: int = 100) -> str:
        """디렉토리 트리 생성"""
        tree_lines = []
        file_count = 0

        def walk_dir(path: str, prefix: str = "", depth: int = 0):
            nonlocal file_count
            if depth > max_depth or file_count > max_files:
                return

            try:
                items = sorted(os.listdir(path))
                # 숨김 파일/폴더 제외
                items = [i for i in items if not i.startswith('.') and i not in ['__pycache__', 'node_modules', 'venv', '.git']]

                dirs = [i for i in items if os.path.isdir(os.path.join(path, i))]
                files = [i for i in items if os.path.isfile(os.path.join(path, i))]

                # 파일 먼저
                for f in files[:20]:  # 폴더당 최대 20개 파일
                    if file_count > max_files:
                        break
                    tree_lines.append(f"{prefix}📄 {f}")
                    file_count += 1

                if len(files) > 20:
                    tree_lines.append(f"{prefix}   ... 그 외 {len(files) - 20}개 파일")

                # 디렉토리
                for d in dirs[:10]:  # 최대 10개 하위 디렉토리
                    if file_count > max_files:
                        break
                    tree_lines.append(f"{prefix}📁 {d}/")
                    walk_dir(os.path.join(path, d), prefix + "  ", depth + 1)

            except PermissionError:
                pass

        tree_lines.append(f"📁 {os.path.basename(self.workspace)}/")
        walk_dir(self.workspace, "  ")

        return "\n".join(tree_lines[:150])  # 최대 150줄

    def _read_file_content(self, file_path: str, max_lines: int = 100) -> str:
        """파일 내용 읽기 (AI용)"""
        full_path = os.path.join(self.workspace, file_path)
        if not os.path.exists(full_path) or not os.path.isfile(full_path):
            return f"[파일을 찾을 수 없음: {file_path}]"

        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()[:max_lines]
                content = ''.join(lines)
                if len(lines) == max_lines:
                    content += f"\n... (이하 생략, 총 {sum(1 for _ in open(full_path))}줄)"
                return content
        except Exception as e:
            return f"[파일 읽기 오류: {e}]"

    def _build_system_prompt(self, context: str = "", classification=None) -> str:
        """Build Qwen-optimized system prompt for MAEUM_CODE"""
        # Generate directory tree
        dir_tree = self._get_directory_tree()

        # Task mode based on classification
        task_mode = ""
        if classification:
            action_name = classification.action.name
            task_modes = {
                "ERROR_CUT": "ERROR_FIX",
                "PATH_JUDGE": "FILE_ANALYZE",
                "CONTEXT_SET": "CODE_WRITE",
                "ARCH_SNAPSHOT": "ARCHITECTURE"
            }
            task_mode = task_modes.get(action_name, "")

        # Qwen-optimized System Prompt
        # Qwen responds well to: clear role, structured instructions, explicit tool format
        base_prompt = f"""# Role: MAEUM_CODE Assistant - The Curious Code Explorer

You are MAEUM_CODE, an expert coding assistant with INFINITE CURIOSITY.
Your core trait: You are OBSESSIVELY CURIOUS about every piece of code.

## 🔍 CURIOSITY-DRIVEN PHILOSOPHY

You have an insatiable desire to UNDERSTAND code deeply:
- "이 함수는 왜 이렇게 작성됐을까?" → 관련 파일 더 읽어보기
- "이 변수는 어디서 사용될까?" → search_code로 추적
- "이 구조가 최선일까?" → 비슷한 패턴 찾아보기
- "연결된 다른 코드는?" → import/require 따라가기

**절대 추측하지 마라. 호기심을 가지고 직접 확인하라.**

## Core Rules
1. **EXPLORE EVERYTHING**: 코드에 대해 물으면, 호기심을 가지고 관련 파일들을 적극적으로 탐색하라
2. **FOLLOW THE TRAIL**: 하나를 읽으면 연결된 것들이 궁금해져야 한다. import, 함수 호출, 변수 사용처를 따라가라
3. **NEVER GUESS**: "아마도", "것 같습니다"는 금지. 모르면 읽어보고, 읽어도 모르면 더 읽어라
4. **DEEP DIVE**: 표면적 답변 금지. 근본 원인, 전체 맥락을 파악할 때까지 탐구하라
5. **Code First**: 설명보다 코드. 간결하게.
6. **Same Language**: 사용자 언어로 답변 (한국어→한국어)

## Environment
- Working Directory: {self.workspace}
- Platform: MAEUM_CODE IDE (Local Web)

## Directory Structure
```
{dir_tree}
```

## Available Tools
You can use these tools by outputting the exact format:

### 1. read_file - Read file content
```
[TOOL:read_file]
```json
{{"file_path": "path/to/file.py"}}
```
```

### 2. list_dir - List directory contents
```
[TOOL:list_dir]
```json
{{"path": "src/"}}
```
```

### 3. search_code - Search code pattern
```
[TOOL:search_code]
```json
{{"query": "def main", "file_pattern": "*.py"}}
```
```

### 4. write_file - Write file (requires user approval)
```
[TOOL:write_file]
```json
{{"file_path": "new_file.py", "content": "# code here"}}
```
```

### 5. edit_file - Edit file (requires user approval)
```
[TOOL:edit_file]
```json
{{"file_path": "file.py", "old_text": "old code", "new_text": "new code"}}
```
```

### 6. bash - Run command (requires user approval)
```
[TOOL:bash]
```json
{{"command": "ls -la"}}
```
```

### 7. todo_write - 작업 계획 및 추적 (Claude Code 패턴)
```
[TOOL:todo_write]
```json
{{"todos": [
  {{"content": "파일 구조 분석", "status": "completed", "priority": "high"}},
  {{"content": "핵심 함수 수정", "status": "in_progress", "priority": "high"}},
  {{"content": "테스트 실행", "status": "pending", "priority": "medium"}}
]}}
```
```

### 8. read_project_memory - MAEUM.md 프로젝트 메모리 읽기
```
[TOOL:read_project_memory]
```json
{{}}
```
```

### 9. update_project_memory - 프로젝트 메모리 업데이트
```
[TOOL:update_project_memory]
```json
{{"section": "decisions", "content": "API 응답 형식을 JSON으로 통일하기로 결정"}}
```
```

### 10. plan_task - 복잡한 작업 계획 수립
```
[TOOL:plan_task]
```json
{{"task": "인증 시스템 리팩토링", "files_to_examine": ["auth.py", "models.py", "routes.py"], "considerations": ["하위 호환성 유지", "테스트 커버리지 확인"]}}
```
```

## 🎯 CLAUDE CODE METHODOLOGY: 먼저 파악, 후에 행동

### ⚠️ 중요: 코드 수정 전 반드시 지켜야 할 순서

1. **MAEUM.md 확인** (프로젝트 메모리)
   - 프로젝트 규칙, 패턴, 이전 결정사항 파악
   - `read_project_memory` 도구 사용

2. **작업 계획 수립** (복잡한 작업일 경우)
   - `plan_task` 도구로 검토할 파일 목록 정리
   - `todo_write`로 단계별 작업 계획

3. **충분한 탐색**
   - 수정 대상 파일 읽기
   - 연관 파일들 추적 (import, 호출처)
   - 영향 범위 파악

4. **코드 수정**
   - 계획에 따라 순차적 수정
   - 각 수정마다 todo 상태 업데이트

5. **결과 기록**
   - 중요 결정은 `update_project_memory`로 기록
   - 다음 세션을 위한 맥락 보존

## 🧭 Exploration Guidelines (탐구 가이드)

### 탐색 원칙
- **호기심을 가지고** 코드를 깊이 파악하세요
- 하지만 **충분하다 싶으면 멈춰도 됩니다**
- 질문에 답할 수 있을 만큼 파악했으면 정리를 시작하세요

### 프로젝트/디렉토리 질문 시:
1. `list_dir` → 전체 구조 파악
2. `read_file` → 핵심 파일 (main.py, index.js, package.json 등)
3. 🔍 **호기심**: 궁금한 import나 모듈이 있으면 더 읽기
4. 🔍 **깊이 파기**: 필요하면 search_code로 추적
5. **충분하면 멈추고** 이해한 내용을 정리해서 설명

### 코드 수정 요청 시:
1. `read_file` → 현재 코드 확인
2. 🔍 **연관 파일 확인**: 필요하면 search_code
3. 영향 범위가 명확하면 바로 수정
4. `edit_file` → 정확한 old_text, new_text로 수정

### 버그/에러 질문 시:
1. 에러 발생 파일 `read_file`
2. 🔍 **원인 추적**: 관련 함수, 클래스 정의 찾기
3. 원인이 파악되면 바로 해결책 제시
4. 필요시에만 추가 탐색

### Example: 호기심 있는 탐구
```
흥미롭네요! 이 프로젝트를 깊이 파보겠습니다.

[TOOL:list_dir]
```json
{{"path": ""}}
```

main.py가 있네요. 어떤 구조인지 궁금합니다.

[TOOL:read_file]
```json
{{"file_path": "main.py"}}
```

utils를 import 하네요. 이것도 봐야겠습니다.

[TOOL:read_file]
```json
{{"file_path": "utils.py"}}
```
```

### ❌ BAD: 게으른 추측
"이 프로젝트는 아마도 웹 앱일 것 같습니다..." → 틀림! 읽어보면 CLI 도구임

### ✅ GOOD: 호기심 있는 탐구
"main.py를 읽어보니 argparse를 사용하네요. CLI 도구입니다. 어떤 커맨드가 있는지 더 살펴보겠습니다."
"""
        if task_mode:
            base_prompt += f"\n## Current Task Mode: {task_mode}\n"

        # 현재 열린 파일 정보 추가
        if hasattr(self, 'current_file_info') and self.current_file_info:
            cf = self.current_file_info
            base_prompt += f"""
## 📄 Currently Open File
- **Path**: `{cf.get('path', 'unknown')}`
- **Language**: {cf.get('language', 'unknown')}
- **Total Lines**: {cf.get('totalLines', 0)}
- **Cursor at Line**: {cf.get('cursorLine', 1)}

**Important**: When the user says "이 파일", "여기", "이 코드" they mean THIS file.
"""

        # 열린 탭 목록 추가
        if hasattr(self, 'open_tabs_info') and self.open_tabs_info:
            tabs_list = ", ".join([f"`{t}`" for t in self.open_tabs_info[:10]])
            base_prompt += f"\n## 📑 Open Tabs\n{tabs_list}\n"

        if context:
            base_prompt += f"\n## Current Code Context (around cursor)\n```\n{context[:3000]}\n```\n"

        # Add recent conversation for continuity
        # 압축된 이전 대화 요약 추가
        if self.compressed_summary:
            base_prompt += f"\n## 이전 대화 요약 (압축됨)\n{self.compressed_summary[:2000]}\n"

        # 최근 대화 추가
        if self.conversation_history:
            recent = self.conversation_history[-4:]
            if recent:
                base_prompt += "\n## Recent Conversation\n"
                for msg in recent:
                    role = "User" if msg["role"] == "user" else "Assistant"
                    content = msg["content"][:200]
                    base_prompt += f"**{role}**: {content}\n"

        # 확인한 코드 심볼 정보 추가 (AST 파싱 결과)
        symbol_summary = self._get_symbol_summary()
        if symbol_summary:
            base_prompt += f"\n{symbol_summary}\n"

        return base_prompt

    def _get_ide_html(self) -> str:
        """IDE HTML 반환"""
        # 외부 템플릿 파일 사용
        template_path = os.path.join(os.path.dirname(__file__), 'ide_template.html')
        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            return IDE_HTML  # 폴백

    def run(self, host: str = "127.0.0.1", port: int = 8880, auto_shutdown: bool = True):
        """서버 실행

        Args:
            host: 호스트 주소
            port: 포트 번호
            auto_shutdown: 브라우저 닫으면 자동 종료
        """
        import webbrowser
        import threading
        import time

        # 워크스페이스 경로 표시 (긴 경로는 축약)
        ws_display = self.workspace
        if len(ws_display) > 50:
            ws_display = "..." + ws_display[-47:]

        print(f"""
╔══════════════════════════════════════════════════════════════╗
║                    MAEUM_CODE Web IDE                        ║
╠══════════════════════════════════════════════════════════════╣
║  🌐 URL: http://{host}:{port}                              ║
║  📁 Workspace: {ws_display}
║  🤖 AI Server: http://localhost:7860                        ║
║  ⏹️  Ctrl+C 또는 브라우저 닫으면 종료                        ║
╚══════════════════════════════════════════════════════════════╝
""")

        # 자동 종료 설정
        if auto_shutdown:
            self._setup_auto_shutdown()

        # 브라우저 자동 열기
        def open_browser():
            time.sleep(0.8)
            webbrowser.open(f"http://{host}:{port}")

        threading.Thread(target=open_browser, daemon=True).start()

        # 서버 실행
        uvicorn.run(self.app, host=host, port=port, log_level="warning")

    def _setup_auto_shutdown(self):
        """브라우저 닫으면 자동 종료 설정"""
        import threading
        import time

        self._last_activity = time.time()
        self._shutdown_timeout = 10  # 10초 후 종료
        self._initial_grace_period = 15  # 시작 후 15초 동안은 종료 안함
        self._server_start_time = time.time()
        self._had_connection = False  # 한 번이라도 연결된 적 있는지

        # 연결 감시 스레드
        def monitor_connections():
            while True:
                time.sleep(3)

                # 초기 대기 시간 (브라우저 열릴 때까지)
                if time.time() - self._server_start_time < self._initial_grace_period:
                    continue

                # 현재 연결 상태 확인
                if len(self.active_connections) > 0:
                    self._had_connection = True
                    self._last_activity = time.time()
                else:
                    # 한 번이라도 연결된 적 있고, 지금 연결이 없으면 종료 체크
                    if self._had_connection:
                        if time.time() - self._last_activity > self._shutdown_timeout:
                            print("\n🛑 브라우저 연결 종료됨. 서버를 종료합니다...")
                            os._exit(0)

        monitor_thread = threading.Thread(target=monitor_connections, daemon=True)
        monitor_thread.start()


# ============================================================
# IDE Frontend (HTML/CSS/JS)
# ============================================================

IDE_HTML = '''<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MAEUM_CODE IDE</title>

    <!-- Monaco Editor -->
    <script src="https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs/loader.min.js"></script>

    <!-- Marked (Markdown) -->
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>

    <!-- Highlight.js -->
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>

    <style>
        :root {
            --bg-primary: #1e1e1e;
            --bg-secondary: #252526;
            --bg-tertiary: #2d2d30;
            --bg-hover: #3c3c3c;
            --text-primary: #cccccc;
            --text-secondary: #969696;
            --text-highlight: #ffffff;
            --accent: #0078d4;
            --accent-hover: #1a8cff;
            --border: #3c3c3c;
            --success: #4caf50;
            --warning: #ff9800;
            --error: #f44336;
            --sidebar-width: 280px;
            --panel-height: 300px;
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            height: 100vh;
            overflow: hidden;
        }

        /* Layout */
        .container {
            display: flex;
            height: 100vh;
        }

        /* Sidebar */
        .sidebar {
            width: var(--sidebar-width);
            background: var(--bg-secondary);
            border-right: 1px solid var(--border);
            display: flex;
            flex-direction: column;
            flex-shrink: 0;
        }

        .sidebar-header {
            padding: 12px 16px;
            background: var(--bg-tertiary);
            border-bottom: 1px solid var(--border);
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .sidebar-header h1 {
            font-size: 14px;
            font-weight: 600;
            color: var(--text-highlight);
        }

        .sidebar-header .logo {
            font-size: 20px;
        }

        /* File Explorer */
        .file-explorer {
            flex: 1;
            overflow-y: auto;
            padding: 8px 0;
        }

        .file-item {
            padding: 6px 16px;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 13px;
            color: var(--text-primary);
            user-select: none;
        }

        .file-item:hover {
            background: var(--bg-hover);
        }

        .file-item.active {
            background: var(--accent);
            color: white;
        }

        .file-item.directory {
            font-weight: 500;
        }

        .file-item .icon {
            width: 16px;
            text-align: center;
        }

        .file-item .name {
            flex: 1;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .file-item .indent {
            width: 16px;
            flex-shrink: 0;
        }

        /* Main Content */
        .main {
            flex: 1;
            display: flex;
            flex-direction: column;
            min-width: 0;
        }

        /* Tabs */
        .tabs {
            display: flex;
            background: var(--bg-tertiary);
            border-bottom: 1px solid var(--border);
            overflow-x: auto;
            flex-shrink: 0;
        }

        .tab {
            padding: 10px 16px;
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 13px;
            cursor: pointer;
            border-right: 1px solid var(--border);
            background: var(--bg-secondary);
            color: var(--text-secondary);
            white-space: nowrap;
        }

        .tab.active {
            background: var(--bg-primary);
            color: var(--text-highlight);
        }

        .tab:hover {
            background: var(--bg-hover);
        }

        .tab .close {
            opacity: 0;
            font-size: 16px;
            padding: 2px;
            border-radius: 3px;
        }

        .tab:hover .close {
            opacity: 1;
        }

        .tab .close:hover {
            background: var(--bg-hover);
        }

        .tab.modified .name::after {
            content: ' •';
            color: var(--accent);
        }

        /* Editor Container */
        .editor-container {
            flex: 1;
            display: flex;
            flex-direction: column;
            min-height: 0;
        }

        #editor {
            flex: 1;
            min-height: 0;
        }

        /* Bottom Panel */
        .bottom-panel {
            height: var(--panel-height);
            background: var(--bg-secondary);
            border-top: 1px solid var(--border);
            display: flex;
            flex-direction: column;
            flex-shrink: 0;
        }

        .panel-tabs {
            display: flex;
            background: var(--bg-tertiary);
            border-bottom: 1px solid var(--border);
        }

        .panel-tab {
            padding: 8px 16px;
            font-size: 12px;
            cursor: pointer;
            color: var(--text-secondary);
            border-bottom: 2px solid transparent;
        }

        .panel-tab.active {
            color: var(--text-highlight);
            border-bottom-color: var(--accent);
        }

        .panel-tab:hover {
            color: var(--text-primary);
        }

        .panel-content {
            flex: 1;
            overflow-y: auto;
            padding: 12px;
        }

        /* AI Chat */
        .chat-container {
            display: flex;
            flex-direction: column;
            height: 100%;
        }

        .chat-messages {
            flex: 1;
            overflow-y: auto;
            padding: 8px;
        }

        .chat-message {
            margin-bottom: 12px;
            padding: 8px 12px;
            border-radius: 8px;
            font-size: 13px;
            line-height: 1.5;
        }

        .chat-message.user {
            background: var(--accent);
            color: white;
            margin-left: 20%;
        }

        .chat-message.assistant {
            background: var(--bg-tertiary);
            margin-right: 20%;
        }

        .chat-message.assistant pre {
            background: var(--bg-primary);
            padding: 8px;
            border-radius: 4px;
            overflow-x: auto;
            margin: 8px 0;
        }

        .chat-message.assistant code {
            font-family: 'Consolas', 'Monaco', monospace;
            font-size: 12px;
        }

        .chat-input-container {
            display: flex;
            gap: 8px;
            padding: 8px;
            background: var(--bg-tertiary);
        }

        .chat-input {
            flex: 1;
            padding: 10px 14px;
            border: 1px solid var(--border);
            border-radius: 20px;
            background: var(--bg-primary);
            color: var(--text-primary);
            font-size: 13px;
            outline: none;
        }

        .chat-input:focus {
            border-color: var(--accent);
        }

        .chat-send {
            padding: 10px 20px;
            background: var(--accent);
            color: white;
            border: none;
            border-radius: 20px;
            cursor: pointer;
            font-size: 13px;
            font-weight: 500;
        }

        .chat-send:hover {
            background: var(--accent-hover);
        }

        .chat-send:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        /* Search */
        .search-container {
            padding: 8px;
        }

        .search-input {
            width: 100%;
            padding: 8px 12px;
            border: 1px solid var(--border);
            border-radius: 4px;
            background: var(--bg-primary);
            color: var(--text-primary);
            font-size: 13px;
            outline: none;
        }

        .search-input:focus {
            border-color: var(--accent);
        }

        .search-results {
            margin-top: 8px;
        }

        .search-result {
            padding: 8px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 12px;
        }

        .search-result:hover {
            background: var(--bg-hover);
        }

        .search-result .file {
            color: var(--accent);
        }

        .search-result .line {
            color: var(--text-secondary);
        }

        .search-result .content {
            font-family: monospace;
            margin-top: 4px;
            padding: 4px;
            background: var(--bg-primary);
            border-radius: 2px;
            overflow-x: auto;
        }

        /* Status Bar */
        .status-bar {
            height: 24px;
            background: var(--accent);
            display: flex;
            align-items: center;
            padding: 0 12px;
            font-size: 12px;
            color: white;
            justify-content: space-between;
        }

        .status-bar .left,
        .status-bar .right {
            display: flex;
            align-items: center;
            gap: 16px;
        }

        /* Toolbar */
        .toolbar {
            display: flex;
            gap: 4px;
            padding: 4px 8px;
            background: var(--bg-secondary);
            border-bottom: 1px solid var(--border);
        }

        .toolbar button {
            padding: 4px 8px;
            background: transparent;
            border: none;
            color: var(--text-primary);
            cursor: pointer;
            border-radius: 4px;
            font-size: 12px;
            display: flex;
            align-items: center;
            gap: 4px;
        }

        .toolbar button:hover {
            background: var(--bg-hover);
        }

        /* Context Menu */
        .context-menu {
            position: fixed;
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 4px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            z-index: 1000;
            min-width: 150px;
            display: none;
        }

        .context-menu.show {
            display: block;
        }

        .context-menu-item {
            padding: 8px 16px;
            cursor: pointer;
            font-size: 13px;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .context-menu-item:hover {
            background: var(--bg-hover);
        }

        .context-menu-item.separator {
            border-top: 1px solid var(--border);
            margin: 4px 0;
            padding: 0;
        }

        /* Loading */
        .loading {
            display: inline-block;
            width: 16px;
            height: 16px;
            border: 2px solid var(--text-secondary);
            border-radius: 50%;
            border-top-color: var(--accent);
            animation: spin 1s linear infinite;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        /* Welcome Screen */
        .welcome {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 100%;
            color: var(--text-secondary);
        }

        .welcome h2 {
            font-size: 24px;
            margin-bottom: 16px;
            color: var(--text-primary);
        }

        .welcome p {
            margin-bottom: 8px;
        }

        .welcome kbd {
            background: var(--bg-tertiary);
            padding: 2px 6px;
            border-radius: 3px;
            font-size: 12px;
        }

        /* Scrollbar */
        ::-webkit-scrollbar {
            width: 10px;
            height: 10px;
        }

        ::-webkit-scrollbar-track {
            background: var(--bg-primary);
        }

        ::-webkit-scrollbar-thumb {
            background: var(--bg-hover);
            border-radius: 5px;
        }

        ::-webkit-scrollbar-thumb:hover {
            background: #555;
        }

        /* Resize handle */
        .resize-handle {
            height: 4px;
            background: var(--border);
            cursor: ns-resize;
        }

        .resize-handle:hover {
            background: var(--accent);
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Sidebar -->
        <div class="sidebar">
            <div class="sidebar-header">
                <span class="logo">🧠</span>
                <h1>MAEUM_CODE</h1>
            </div>
            <div class="toolbar">
                <button onclick="createFile()" title="새 파일">📄 새 파일</button>
                <button onclick="createFolder()" title="새 폴더">📁 새 폴더</button>
                <button onclick="refreshFiles()" title="새로고침">🔄</button>
            </div>
            <div class="file-explorer" id="fileExplorer">
                <!-- 파일 목록 -->
            </div>
        </div>

        <!-- Main Content -->
        <div class="main">
            <!-- Tabs -->
            <div class="tabs" id="tabs">
                <!-- 탭 목록 -->
            </div>

            <!-- Editor -->
            <div class="editor-container">
                <div id="editor">
                    <div class="welcome">
                        <h2>🧠 MAEUM_CODE IDE</h2>
                        <p>왼쪽 파일 탐색기에서 파일을 선택하세요</p>
                        <p><kbd>Ctrl+S</kbd> 저장 | <kbd>Ctrl+Z</kbd> 실행 취소 | <kbd>Ctrl+F</kbd> 찾기</p>
                        <p><kbd>Ctrl+P</kbd> 빠른 열기 | <kbd>Ctrl+Shift+F</kbd> 전체 검색</p>
                    </div>
                </div>
            </div>

            <!-- Resize Handle -->
            <div class="resize-handle" id="resizeHandle"></div>

            <!-- Bottom Panel -->
            <div class="bottom-panel" id="bottomPanel">
                <div class="panel-tabs">
                    <div class="panel-tab active" data-panel="chat">🤖 AI 채팅</div>
                    <div class="panel-tab" data-panel="search">🔍 검색</div>
                    <div class="panel-tab" data-panel="problems">⚠️ 문제</div>
                    <div class="panel-tab" data-panel="output">📋 출력</div>
                </div>
                <div class="panel-content" id="panelContent">
                    <!-- Chat Panel -->
                    <div class="chat-container" id="chatPanel">
                        <div class="chat-messages" id="chatMessages">
                            <div class="chat-message assistant">
                                안녕하세요! MAEUM_CODE AI 어시스턴트입니다. 코딩에 대해 무엇이든 물어보세요.
                            </div>
                        </div>
                        <div class="chat-input-container">
                            <input type="text" class="chat-input" id="chatInput"
                                   placeholder="메시지를 입력하세요..."
                                   onkeypress="if(event.key==='Enter') sendMessage()">
                            <button class="chat-send" id="chatSend" onclick="sendMessage()">전송</button>
                        </div>
                    </div>

                    <!-- Search Panel (hidden by default) -->
                    <div class="search-container" id="searchPanel" style="display:none">
                        <input type="text" class="search-input" id="searchInput"
                               placeholder="검색어 입력 (Enter로 검색)"
                               onkeypress="if(event.key==='Enter') performSearch()">
                        <div class="search-results" id="searchResults"></div>
                    </div>

                    <!-- Problems Panel -->
                    <div id="problemsPanel" style="display:none">
                        <p style="color: var(--text-secondary);">문제 없음</p>
                    </div>

                    <!-- Output Panel -->
                    <div id="outputPanel" style="display:none">
                        <pre style="font-family: monospace; font-size: 12px;" id="outputContent"></pre>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- Context Menu -->
    <div class="context-menu" id="contextMenu">
        <div class="context-menu-item" onclick="renameItem()">✏️ 이름 변경</div>
        <div class="context-menu-item" onclick="deleteItem()">🗑️ 삭제</div>
        <div class="context-menu-item separator"></div>
        <div class="context-menu-item" onclick="copyPath()">📋 경로 복사</div>
    </div>

    <!-- Status Bar -->
    <div class="status-bar">
        <div class="left">
            <span id="aiStatus">🤖 AI 연결 중...</span>
            <span id="fileStatus"></span>
        </div>
        <div class="right">
            <span id="cursorPos">Ln 1, Col 1</span>
            <span id="language">Plain Text</span>
            <span>UTF-8</span>
        </div>
    </div>

    <script>
        // Monaco Editor 초기화
        let editor = null;
        let openFiles = new Map(); // path -> { content, modified, model }
        let activeFile = null;
        let ws = null;
        let contextMenuTarget = null;

        // Monaco 로드
        require.config({ paths: { vs: 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs' }});
        require(['vs/editor/editor.main'], function() {
            console.log('Monaco Editor 로드 완료');

            // 테마 설정
            monaco.editor.defineTheme('maeum-dark', {
                base: 'vs-dark',
                inherit: true,
                rules: [],
                colors: {
                    'editor.background': '#1e1e1e',
                }
            });

            // 파일 목록 로드
            loadFiles('');

            // AI 상태 확인
            checkAIStatus();

            // WebSocket 연결
            connectWebSocket();
        });

        // 파일 목록 로드
        async function loadFiles(path) {
            try {
                const response = await fetch(`/api/files?path=${encodeURIComponent(path)}`);
                const data = await response.json();

                const explorer = document.getElementById('fileExplorer');
                explorer.innerHTML = '';

                // 상위 디렉토리
                if (path) {
                    const parentPath = path.split('/').slice(0, -1).join('/');
                    const item = createFileItem('..', parentPath, true, 0);
                    explorer.appendChild(item);
                }

                // 파일/폴더 목록
                data.items.forEach(item => {
                    const el = createFileItem(item.name, item.path, item.is_directory, 0);
                    explorer.appendChild(el);
                });

            } catch (error) {
                console.error('파일 목록 로드 실패:', error);
            }
        }

        // 파일 아이템 생성
        function createFileItem(name, path, isDirectory, indent) {
            const item = document.createElement('div');
            item.className = `file-item${isDirectory ? ' directory' : ''}`;
            item.dataset.path = path;
            item.dataset.isDirectory = isDirectory;

            const icon = isDirectory ? '📁' : getFileIcon(name);

            item.innerHTML = `
                <span class="indent" style="width: ${indent * 16}px"></span>
                <span class="icon">${icon}</span>
                <span class="name">${name}</span>
            `;

            item.onclick = (e) => {
                e.stopPropagation();
                if (isDirectory) {
                    loadFiles(path);
                } else {
                    openFile(path);
                }
            };

            item.oncontextmenu = (e) => {
                e.preventDefault();
                showContextMenu(e, path, isDirectory);
            };

            return item;
        }

        // 파일 아이콘
        function getFileIcon(name) {
            const ext = name.split('.').pop().toLowerCase();
            const icons = {
                'py': '🐍', 'js': '📜', 'ts': '📘', 'tsx': '⚛️', 'jsx': '⚛️',
                'html': '🌐', 'css': '🎨', 'scss': '🎨', 'json': '📋',
                'md': '📝', 'txt': '📄', 'yaml': '⚙️', 'yml': '⚙️',
                'sh': '💻', 'bash': '💻', 'sql': '🗃️',
                'png': '🖼️', 'jpg': '🖼️', 'gif': '🖼️', 'svg': '🖼️',
                'pdf': '📕', 'doc': '📘', 'xls': '📗',
            };
            return icons[ext] || '📄';
        }

        // 파일 열기
        async function openFile(path) {
            try {
                // 이미 열려있으면 활성화만
                if (openFiles.has(path)) {
                    activateTab(path);
                    return;
                }

                const response = await fetch(`/api/file?path=${encodeURIComponent(path)}`);
                const data = await response.json();

                if (data.is_binary) {
                    alert('바이너리 파일은 열 수 없습니다.');
                    return;
                }

                // 에디터 생성 (처음인 경우)
                if (!editor) {
                    document.getElementById('editor').innerHTML = '';
                    editor = monaco.editor.create(document.getElementById('editor'), {
                        value: data.content,
                        language: data.language,
                        theme: 'maeum-dark',
                        fontSize: 14,
                        fontFamily: "'Fira Code', Consolas, 'Courier New', monospace",
                        minimap: { enabled: true },
                        automaticLayout: true,
                        wordWrap: 'on',
                        scrollBeyondLastLine: false,
                        lineNumbers: 'on',
                        renderWhitespace: 'selection',
                        tabSize: 4,
                    });

                    // 변경 감지
                    editor.onDidChangeModelContent(() => {
                        if (activeFile) {
                            const fileData = openFiles.get(activeFile);
                            if (fileData) {
                                fileData.modified = editor.getValue() !== fileData.originalContent;
                                updateTab(activeFile, fileData.modified);
                            }
                        }
                    });

                    // 커서 위치
                    editor.onDidChangeCursorPosition((e) => {
                        document.getElementById('cursorPos').textContent =
                            `Ln ${e.position.lineNumber}, Col ${e.position.column}`;
                    });

                    // 키보드 단축키
                    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
                        saveCurrentFile();
                    });
                }

                // 모델 생성
                const model = monaco.editor.createModel(data.content, data.language);

                openFiles.set(path, {
                    content: data.content,
                    originalContent: data.content,
                    modified: false,
                    model: model,
                    language: data.language
                });

                // 탭 추가
                addTab(path);

                // 활성화
                activateTab(path);

                // 언어 표시
                document.getElementById('language').textContent = data.language;

            } catch (error) {
                console.error('파일 열기 실패:', error);
                alert('파일을 열 수 없습니다: ' + error.message);
            }
        }

        // 탭 추가
        function addTab(path) {
            const tabs = document.getElementById('tabs');
            const name = path.split('/').pop();

            const tab = document.createElement('div');
            tab.className = 'tab';
            tab.dataset.path = path;
            tab.innerHTML = `
                <span class="icon">${getFileIcon(name)}</span>
                <span class="name">${name}</span>
                <span class="close" onclick="closeTab(event, '${path}')">×</span>
            `;

            tab.onclick = () => activateTab(path);
            tabs.appendChild(tab);
        }

        // 탭 활성화
        function activateTab(path) {
            // 이전 탭 비활성화
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.file-item').forEach(f => f.classList.remove('active'));

            // 현재 탭 활성화
            const tab = document.querySelector(`.tab[data-path="${path}"]`);
            if (tab) tab.classList.add('active');

            const fileItem = document.querySelector(`.file-item[data-path="${path}"]`);
            if (fileItem) fileItem.classList.add('active');

            // 에디터 모델 변경
            const fileData = openFiles.get(path);
            if (fileData && editor) {
                editor.setModel(fileData.model);
            }

            activeFile = path;
            document.getElementById('fileStatus').textContent = path;
        }

        // 탭 닫기
        function closeTab(event, path) {
            event.stopPropagation();

            const fileData = openFiles.get(path);
            if (fileData && fileData.modified) {
                if (!confirm('저장하지 않은 변경사항이 있습니다. 닫으시겠습니까?')) {
                    return;
                }
            }

            // 모델 삭제
            if (fileData && fileData.model) {
                fileData.model.dispose();
            }

            openFiles.delete(path);

            // 탭 제거
            const tab = document.querySelector(`.tab[data-path="${path}"]`);
            if (tab) tab.remove();

            // 다른 탭 활성화
            if (activeFile === path) {
                const remainingTabs = document.querySelectorAll('.tab');
                if (remainingTabs.length > 0) {
                    activateTab(remainingTabs[0].dataset.path);
                } else {
                    activeFile = null;
                    document.getElementById('editor').innerHTML = `
                        <div class="welcome">
                            <h2>🧠 MAEUM_CODE IDE</h2>
                            <p>왼쪽 파일 탐색기에서 파일을 선택하세요</p>
                        </div>
                    `;
                    editor = null;
                }
            }
        }

        // 탭 상태 업데이트
        function updateTab(path, modified) {
            const tab = document.querySelector(`.tab[data-path="${path}"]`);
            if (tab) {
                if (modified) {
                    tab.classList.add('modified');
                } else {
                    tab.classList.remove('modified');
                }
            }
        }

        // 현재 파일 저장
        async function saveCurrentFile() {
            if (!activeFile || !editor) return;

            const content = editor.getValue();

            try {
                const response = await fetch('/api/file', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ path: activeFile, content: content })
                });

                if (response.ok) {
                    const fileData = openFiles.get(activeFile);
                    if (fileData) {
                        fileData.originalContent = content;
                        fileData.modified = false;
                        updateTab(activeFile, false);
                    }
                    addOutput('✅ 저장됨: ' + activeFile);
                } else {
                    throw new Error('저장 실패');
                }
            } catch (error) {
                console.error('저장 실패:', error);
                alert('저장 실패: ' + error.message);
            }
        }

        // WebSocket 연결
        function connectWebSocket() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${window.location.host}/ws/chat`);

            ws.onopen = () => {
                console.log('WebSocket 연결됨');
                document.getElementById('aiStatus').textContent = '🤖 AI 연결됨';
            };

            ws.onclose = () => {
                console.log('WebSocket 연결 끊김');
                document.getElementById('aiStatus').textContent = '🤖 AI 연결 끊김';
                // 재연결 시도
                setTimeout(connectWebSocket, 3000);
            };

            ws.onerror = (error) => {
                console.error('WebSocket 오류:', error);
            };

            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                handleChatResponse(data);
            };
        }

        // 채팅 응답 처리
        let currentAssistantMessage = null;

        function handleChatResponse(data) {
            const messages = document.getElementById('chatMessages');

            if (data.type === 'token') {
                // 스트리밍 토큰
                if (!currentAssistantMessage) {
                    currentAssistantMessage = document.createElement('div');
                    currentAssistantMessage.className = 'chat-message assistant';
                    currentAssistantMessage.innerHTML = '';
                    messages.appendChild(currentAssistantMessage);
                }
                currentAssistantMessage.innerHTML += data.content;
                messages.scrollTop = messages.scrollHeight;

            } else if (data.type === 'done') {
                // 완료
                if (currentAssistantMessage) {
                    // Markdown 렌더링
                    currentAssistantMessage.innerHTML = marked.parse(currentAssistantMessage.innerHTML);
                    // 코드 하이라이팅
                    currentAssistantMessage.querySelectorAll('pre code').forEach(block => {
                        hljs.highlightElement(block);
                    });
                }
                currentAssistantMessage = null;
                document.getElementById('chatSend').disabled = false;
                document.getElementById('chatInput').disabled = false;

            } else if (data.type === 'error') {
                // 오류
                const errorMsg = document.createElement('div');
                errorMsg.className = 'chat-message assistant';
                errorMsg.style.borderLeft = '3px solid var(--error)';
                errorMsg.textContent = '오류: ' + data.content;
                messages.appendChild(errorMsg);

                currentAssistantMessage = null;
                document.getElementById('chatSend').disabled = false;
                document.getElementById('chatInput').disabled = false;
            }
        }

        // 메시지 전송
        function sendMessage() {
            const input = document.getElementById('chatInput');
            const message = input.value.trim();

            if (!message || !ws || ws.readyState !== WebSocket.OPEN) return;

            // 사용자 메시지 표시
            const messages = document.getElementById('chatMessages');
            const userMsg = document.createElement('div');
            userMsg.className = 'chat-message user';
            userMsg.textContent = message;
            messages.appendChild(userMsg);

            // 현재 파일 컨텍스트
            let context = '';
            if (activeFile && editor) {
                const selection = editor.getModel().getValueInRange(editor.getSelection());
                context = selection || editor.getValue().substring(0, 2000);
            }

            // 전송
            ws.send(JSON.stringify({
                message: message,
                context: context
            }));

            // 입력 초기화
            input.value = '';
            document.getElementById('chatSend').disabled = true;
            document.getElementById('chatInput').disabled = true;

            messages.scrollTop = messages.scrollHeight;
        }

        // 검색
        async function performSearch() {
            const query = document.getElementById('searchInput').value.trim();
            if (!query) return;

            try {
                const response = await fetch(`/api/search?q=${encodeURIComponent(query)}&mode=content`);
                const data = await response.json();

                const results = document.getElementById('searchResults');
                results.innerHTML = '';

                if (data.results.length === 0) {
                    results.innerHTML = '<p style="color: var(--text-secondary);">결과 없음</p>';
                    return;
                }

                data.results.forEach(r => {
                    const item = document.createElement('div');
                    item.className = 'search-result';
                    item.innerHTML = `
                        <span class="file">${r.file}</span>
                        <span class="line">:${r.line}</span>
                        <div class="content">${escapeHtml(r.content)}</div>
                    `;
                    item.onclick = () => {
                        openFile(r.file);
                        if (editor && r.line) {
                            setTimeout(() => {
                                editor.revealLineInCenter(r.line);
                                editor.setPosition({ lineNumber: r.line, column: 1 });
                            }, 100);
                        }
                    };
                    results.appendChild(item);
                });

            } catch (error) {
                console.error('검색 실패:', error);
            }
        }

        // HTML 이스케이프
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        // 패널 전환
        document.querySelectorAll('.panel-tab').forEach(tab => {
            tab.onclick = () => {
                // 탭 활성화
                document.querySelectorAll('.panel-tab').forEach(t => t.classList.remove('active'));
                tab.classList.add('active');

                // 패널 표시
                const panelId = tab.dataset.panel;
                ['chatPanel', 'searchPanel', 'problemsPanel', 'outputPanel'].forEach(id => {
                    document.getElementById(id).style.display = id === panelId + 'Panel' ? '' : 'none';
                });
            };
        });

        // AI 상태 확인
        async function checkAIStatus() {
            try {
                const response = await fetch('/api/ai/status');
                const data = await response.json();

                if (data.available) {
                    document.getElementById('aiStatus').textContent = '🤖 AI 온라인';
                } else {
                    document.getElementById('aiStatus').textContent = '🤖 AI 오프라인';
                }
            } catch (error) {
                document.getElementById('aiStatus').textContent = '🤖 AI 상태 확인 실패';
            }
        }

        // 컨텍스트 메뉴
        function showContextMenu(event, path, isDirectory) {
            const menu = document.getElementById('contextMenu');
            menu.style.left = event.pageX + 'px';
            menu.style.top = event.pageY + 'px';
            menu.classList.add('show');
            contextMenuTarget = { path, isDirectory };
        }

        document.onclick = () => {
            document.getElementById('contextMenu').classList.remove('show');
        };

        // 이름 변경
        async function renameItem() {
            if (!contextMenuTarget) return;

            const newName = prompt('새 이름:', contextMenuTarget.path.split('/').pop());
            if (!newName) return;

            const newPath = contextMenuTarget.path.split('/').slice(0, -1).concat(newName).join('/');

            try {
                const response = await fetch('/api/file/rename', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ old_path: contextMenuTarget.path, new_path: newPath })
                });

                if (response.ok) {
                    refreshFiles();
                } else {
                    throw new Error('이름 변경 실패');
                }
            } catch (error) {
                alert('오류: ' + error.message);
            }
        }

        // 삭제
        async function deleteItem() {
            if (!contextMenuTarget) return;

            if (!confirm(`정말 삭제하시겠습니까?\n${contextMenuTarget.path}`)) return;

            try {
                const response = await fetch(`/api/file?path=${encodeURIComponent(contextMenuTarget.path)}`, {
                    method: 'DELETE'
                });

                if (response.ok) {
                    refreshFiles();
                } else {
                    throw new Error('삭제 실패');
                }
            } catch (error) {
                alert('오류: ' + error.message);
            }
        }

        // 경로 복사
        function copyPath() {
            if (!contextMenuTarget) return;
            navigator.clipboard.writeText(contextMenuTarget.path);
        }

        // 새 파일
        async function createFile() {
            const name = prompt('파일 이름:');
            if (!name) return;

            try {
                const response = await fetch('/api/file/create', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ path: name, content: '', is_directory: false })
                });

                if (response.ok) {
                    refreshFiles();
                    openFile(name);
                }
            } catch (error) {
                alert('오류: ' + error.message);
            }
        }

        // 새 폴더
        async function createFolder() {
            const name = prompt('폴더 이름:');
            if (!name) return;

            try {
                const response = await fetch('/api/file/create', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ path: name, is_directory: true })
                });

                if (response.ok) {
                    refreshFiles();
                }
            } catch (error) {
                alert('오류: ' + error.message);
            }
        }

        // 새로고침
        function refreshFiles() {
            loadFiles('');
        }

        // 출력 추가
        function addOutput(text) {
            const output = document.getElementById('outputContent');
            const time = new Date().toLocaleTimeString();
            output.textContent += `[${time}] ${text}\n`;
        }

        // 패널 크기 조절
        const resizeHandle = document.getElementById('resizeHandle');
        let isResizing = false;

        resizeHandle.onmousedown = (e) => {
            isResizing = true;
            document.body.style.cursor = 'ns-resize';
        };

        document.onmousemove = (e) => {
            if (!isResizing) return;

            const container = document.querySelector('.main');
            const containerRect = container.getBoundingClientRect();
            const newHeight = containerRect.bottom - e.clientY;

            if (newHeight >= 100 && newHeight <= 600) {
                document.getElementById('bottomPanel').style.height = newHeight + 'px';
                if (editor) editor.layout();
            }
        };

        document.onmouseup = () => {
            isResizing = false;
            document.body.style.cursor = '';
        };

        // 윈도우 리사이즈
        window.onresize = () => {
            if (editor) editor.layout();
        };
    </script>
</body>
</html>
'''


# ============================================================
# Entry Point
# ============================================================

def main():
    """IDE 서버 실행"""
    import argparse

    parser = argparse.ArgumentParser(description="MAEUM_CODE Web IDE")
    parser.add_argument("path", nargs="?", default=".", help="워크스페이스 경로")
    parser.add_argument("--port", "-p", type=int, default=8880, help="포트 (기본: 8880)")
    parser.add_argument("--host", default="127.0.0.1", help="호스트 (기본: 127.0.0.1, 로컬 전용)")

    args = parser.parse_args()

    workspace = os.path.abspath(args.path)
    if not os.path.isdir(workspace):
        print(f"오류: 디렉토리가 아닙니다: {workspace}")
        sys.exit(1)

    server = IDEServer(workspace)
    server.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
