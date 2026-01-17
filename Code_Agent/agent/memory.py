"""
Memory System - 대화 및 컨텍스트 메모리

Claude Code 스타일:
- ConversationMemory: 대화 히스토리
- ContextMemory: 파일/코드 컨텍스트 추적
- 자동 요약 (컨텍스트 초과 시)
"""

import json
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime
from collections import OrderedDict


@dataclass
class Message:
    """대화 메시지"""
    role: str  # "user", "assistant", "system", "tool"
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata
        }


@dataclass
class FileContext:
    """파일 컨텍스트"""
    path: str
    content: str
    last_read: datetime
    hash: str

    @classmethod
    def from_file(cls, path: str, content: str) -> "FileContext":
        return cls(
            path=path,
            content=content,
            last_read=datetime.now(),
            hash=hashlib.md5(content.encode()).hexdigest()
        )


class ConversationMemory:
    """
    대화 메모리

    Claude Code 스타일:
    - 최근 대화 유지
    - 자동 요약 (토큰 제한 시)
    - 중요 정보 추출
    """

    def __init__(self, max_messages: int = 100, max_tokens: int = 100000):
        self.messages: List[Message] = []
        self.max_messages = max_messages
        self.max_tokens = max_tokens
        self.summaries: List[str] = []  # 요약된 이전 대화

    def add(self, role: str, content: str, metadata: Dict[str, Any] = None) -> Message:
        """메시지 추가"""
        msg = Message(
            role=role,
            content=content,
            metadata=metadata or {}
        )
        self.messages.append(msg)

        # 메시지 수 제한
        if len(self.messages) > self.max_messages:
            self._summarize_old()

        return msg

    def add_user(self, content: str) -> Message:
        return self.add("user", content)

    def add_assistant(self, content: str) -> Message:
        return self.add("assistant", content)

    def add_tool(self, tool_name: str, result: str) -> Message:
        return self.add("tool", result, {"tool": tool_name})

    def add_system(self, content: str) -> Message:
        return self.add("system", content)

    def get_recent(self, n: int = 20) -> List[Message]:
        """최근 n개 메시지"""
        return self.messages[-n:]

    def get_context_window(self, max_chars: int = 50000) -> List[Message]:
        """
        컨텍스트 윈도우에 맞는 메시지 반환

        Claude Code 스타일:
        - 최근 메시지 우선
        - 토큰 제한 내에서 최대한 포함
        """
        result = []
        total_chars = 0

        for msg in reversed(self.messages):
            msg_chars = len(msg.content)
            if total_chars + msg_chars > max_chars:
                break
            result.insert(0, msg)
            total_chars += msg_chars

        return result

    def to_api_format(self) -> List[Dict[str, str]]:
        """API 호출 형식으로 변환"""
        return [
            {"role": msg.role, "content": msg.content}
            for msg in self.messages
            if msg.role in ["user", "assistant"]
        ]

    def _summarize_old(self):
        """오래된 메시지 요약"""
        if len(self.messages) <= self.max_messages // 2:
            return

        # 앞쪽 절반을 요약
        old_messages = self.messages[:len(self.messages) // 2]

        # 간단 요약 (실제로는 AI 호출)
        summary_parts = []
        for msg in old_messages:
            if msg.role == "user":
                summary_parts.append(f"User: {msg.content[:100]}...")
            elif msg.role == "assistant":
                summary_parts.append(f"Assistant: {msg.content[:100]}...")

        summary = "\n".join(summary_parts[:10])
        self.summaries.append(summary)

        # 오래된 메시지 제거
        self.messages = self.messages[len(self.messages) // 2:]

    def clear(self):
        """메모리 초기화"""
        self.messages = []
        self.summaries = []

    def search(self, query: str) -> List[Message]:
        """메시지 검색"""
        query_lower = query.lower()
        return [
            msg for msg in self.messages
            if query_lower in msg.content.lower()
        ]


class ContextMemory:
    """
    컨텍스트 메모리 - 파일/코드 추적

    Claude Code 스타일:
    - 읽은 파일 캐시
    - 수정된 파일 추적
    - 관련 파일 자동 감지
    """

    def __init__(self, max_files: int = 50):
        self.files: OrderedDict[str, FileContext] = OrderedDict()
        self.max_files = max_files
        self.modified_files: Set[str] = set()
        self.created_files: Set[str] = set()
        self.deleted_files: Set[str] = set()

    def track_read(self, path: str, content: str):
        """파일 읽기 추적"""
        ctx = FileContext.from_file(path, content)
        self.files[path] = ctx

        # LRU 제한
        if len(self.files) > self.max_files:
            self.files.popitem(last=False)

    def track_write(self, path: str, content: str):
        """파일 쓰기 추적"""
        if path not in self.files:
            self.created_files.add(path)
        else:
            self.modified_files.add(path)

        self.track_read(path, content)

    def track_delete(self, path: str):
        """파일 삭제 추적"""
        self.deleted_files.add(path)
        if path in self.files:
            del self.files[path]

    def get_file(self, path: str) -> Optional[FileContext]:
        """캐시된 파일 가져오기"""
        return self.files.get(path)

    def has_file(self, path: str) -> bool:
        """파일 캐시 여부"""
        return path in self.files

    def is_modified(self, path: str) -> bool:
        """파일 수정 여부 확인"""
        if path not in self.files:
            return False

        try:
            current_content = Path(path).read_text(encoding='utf-8', errors='ignore')
            current_hash = hashlib.md5(current_content.encode()).hexdigest()
            return current_hash != self.files[path].hash
        except:
            return False

    def get_recent_files(self, n: int = 10) -> List[str]:
        """최근 접근 파일"""
        return list(self.files.keys())[-n:]

    def get_modified_files(self) -> List[str]:
        """수정된 파일 목록"""
        return list(self.modified_files)

    def get_changes_summary(self) -> Dict[str, Any]:
        """변경 사항 요약"""
        return {
            "created": list(self.created_files),
            "modified": list(self.modified_files),
            "deleted": list(self.deleted_files),
            "total_tracked": len(self.files)
        }

    def get_context_for_prompt(self, max_chars: int = 30000) -> str:
        """프롬프트용 컨텍스트 생성"""
        parts = []
        total_chars = 0

        # 최근 파일부터
        for path in reversed(list(self.files.keys())):
            ctx = self.files[path]
            file_section = f"=== {path} ===\n{ctx.content}\n"

            if total_chars + len(file_section) > max_chars:
                break

            parts.insert(0, file_section)
            total_chars += len(file_section)

        return "\n".join(parts)

    def clear(self):
        """메모리 초기화"""
        self.files.clear()
        self.modified_files.clear()
        self.created_files.clear()
        self.deleted_files.clear()


class WorkingMemory:
    """
    작업 메모리 - 현재 작업 상태

    Claude Code 스타일:
    - 현재 작업 목표
    - 진행 상황
    - 다음 단계
    """

    def __init__(self):
        self.current_goal: Optional[str] = None
        self.steps: List[Dict[str, Any]] = []
        self.current_step: int = 0
        self.notes: List[str] = []
        self.errors: List[str] = []

    def set_goal(self, goal: str):
        """목표 설정"""
        self.current_goal = goal
        self.steps = []
        self.current_step = 0

    def add_step(self, description: str, status: str = "pending"):
        """단계 추가"""
        self.steps.append({
            "description": description,
            "status": status,
            "result": None
        })

    def complete_step(self, result: str = None):
        """현재 단계 완료"""
        if self.current_step < len(self.steps):
            self.steps[self.current_step]["status"] = "completed"
            self.steps[self.current_step]["result"] = result
            self.current_step += 1

    def fail_step(self, error: str):
        """현재 단계 실패"""
        if self.current_step < len(self.steps):
            self.steps[self.current_step]["status"] = "failed"
            self.steps[self.current_step]["result"] = error
            self.errors.append(error)

    def add_note(self, note: str):
        """메모 추가"""
        self.notes.append(note)

    def get_progress(self) -> Dict[str, Any]:
        """진행 상황"""
        completed = sum(1 for s in self.steps if s["status"] == "completed")
        return {
            "goal": self.current_goal,
            "total_steps": len(self.steps),
            "completed_steps": completed,
            "current_step": self.current_step,
            "progress_percent": (completed / len(self.steps) * 100) if self.steps else 0
        }

    def to_prompt(self) -> str:
        """프롬프트용 문자열"""
        parts = []

        if self.current_goal:
            parts.append(f"Goal: {self.current_goal}")

        if self.steps:
            parts.append("Steps:")
            for i, step in enumerate(self.steps):
                status_icon = {
                    "pending": "○",
                    "completed": "✓",
                    "failed": "✗"
                }.get(step["status"], "?")

                current = "→ " if i == self.current_step else "  "
                parts.append(f"{current}{status_icon} {step['description']}")

        if self.notes:
            parts.append("\nNotes:")
            for note in self.notes[-5:]:
                parts.append(f"- {note}")

        return "\n".join(parts)

    def clear(self):
        """초기화"""
        self.current_goal = None
        self.steps = []
        self.current_step = 0
        self.notes = []
        self.errors = []
