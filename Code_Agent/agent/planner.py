"""
Task Planner - 작업 계획 수립

Claude Code 스타일:
- 복잡한 요청을 단계별 작업으로 분해
- 우선순위 결정
- 의존성 관리
"""

import re
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime


class TaskStatus(Enum):
    """작업 상태"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


class TaskPriority(Enum):
    """작업 우선순위"""
    CRITICAL = 1
    HIGH = 2
    MEDIUM = 3
    LOW = 4


@dataclass
class Task:
    """작업 단위"""
    id: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.MEDIUM
    dependencies: List[str] = field(default_factory=list)
    tools_needed: List[str] = field(default_factory=list)
    result: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None

    def is_ready(self, completed_tasks: set) -> bool:
        """실행 가능 여부 (의존성 체크)"""
        return all(dep in completed_tasks for dep in self.dependencies)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "status": self.status.value,
            "priority": self.priority.value,
            "dependencies": self.dependencies,
            "tools_needed": self.tools_needed,
            "result": self.result,
            "error": self.error
        }


class TaskPlanner:
    """
    작업 계획 수립기

    Claude Code 스타일:
    - 요청 분석 → 작업 분해
    - 도구 매핑
    - 실행 순서 결정
    """

    # 작업 유형별 도구 매핑
    TOOL_MAPPING = {
        "read": ["Read"],
        "write": ["Write"],
        "edit": ["Edit"],
        "search": ["Glob", "Grep"],
        "execute": ["Bash"],
        "analyze": ["Read", "Glob", "Grep"],
        "create": ["Write"],
        "modify": ["Read", "Edit"],
        "delete": ["Bash"],
        "test": ["Bash"],
        "build": ["Bash"],
    }

    # 작업 키워드
    TASK_PATTERNS = {
        "create": r"(생성|만들|create|add|new|추가)",
        "modify": r"(수정|변경|modify|change|update|edit|고치|바꿔)",
        "delete": r"(삭제|제거|delete|remove)",
        "read": r"(읽|보여|확인|read|show|display|check)",
        "search": r"(찾|검색|search|find|locate)",
        "analyze": r"(분석|파악|analyze|understand|explain)",
        "test": r"(테스트|test|verify|check)",
        "build": r"(빌드|build|compile|package)",
        "run": r"(실행|run|execute|start)",
    }

    def __init__(self):
        self.tasks: Dict[str, Task] = {}
        self.task_counter = 0

    def plan(self, request: str, context: Dict[str, Any] = None) -> List[Task]:
        """
        요청 분석 후 작업 계획 수립

        Args:
            request: 사용자 요청
            context: 컨텍스트 정보

        Returns:
            List[Task]: 작업 목록
        """
        tasks = []

        # 작업 유형 분석
        task_types = self._analyze_request(request)

        # 파일 경로 추출
        file_paths = self._extract_file_paths(request)

        # 작업 생성
        for i, task_type in enumerate(task_types):
            task_id = self._generate_id()

            # 도구 결정
            tools = self.TOOL_MAPPING.get(task_type, ["Read"])

            # 의존성 결정
            dependencies = []
            if task_type in ["modify", "edit"] and i > 0:
                # 수정 작업은 읽기 이후에
                for prev_task in tasks:
                    if "Read" in prev_task.tools_needed:
                        dependencies.append(prev_task.id)

            # 작업 설명 생성
            description = self._generate_description(task_type, file_paths, request)

            task = Task(
                id=task_id,
                description=description,
                priority=self._determine_priority(task_type),
                dependencies=dependencies,
                tools_needed=tools
            )

            tasks.append(task)
            self.tasks[task_id] = task

        return tasks

    def _analyze_request(self, request: str) -> List[str]:
        """요청에서 작업 유형 추출"""
        found_types = []

        for task_type, pattern in self.TASK_PATTERNS.items():
            if re.search(pattern, request, re.IGNORECASE):
                found_types.append(task_type)

        # 기본 작업
        if not found_types:
            found_types = ["analyze"]

        # 순서 정렬 (읽기 → 분석 → 수정 → 테스트)
        order = ["read", "analyze", "search", "create", "modify", "delete", "test", "build", "run"]
        found_types.sort(key=lambda x: order.index(x) if x in order else 99)

        return found_types

    def _extract_file_paths(self, request: str) -> List[str]:
        """파일 경로 추출"""
        paths = []

        # 파일 패턴 매칭
        patterns = [
            r'["\']([^"\']+\.[a-zA-Z]+)["\']',  # "file.ext"
            r'`([^`]+\.[a-zA-Z]+)`',              # `file.ext`
            r'\b([\w/.-]+\.[a-zA-Z]{1,5})\b',     # file.ext
        ]

        for pattern in patterns:
            matches = re.findall(pattern, request)
            paths.extend(matches)

        return list(set(paths))

    def _generate_description(self, task_type: str, file_paths: List[str], request: str) -> str:
        """작업 설명 생성"""
        descriptions = {
            "read": "파일 읽기",
            "write": "파일 작성",
            "edit": "파일 수정",
            "search": "파일/코드 검색",
            "analyze": "코드 분석",
            "create": "새 파일 생성",
            "modify": "기존 파일 수정",
            "delete": "파일 삭제",
            "test": "테스트 실행",
            "build": "빌드 실행",
            "run": "명령 실행",
        }

        base_desc = descriptions.get(task_type, task_type)

        if file_paths:
            return f"{base_desc}: {', '.join(file_paths[:3])}"
        else:
            # 요청에서 핵심 추출
            short_request = request[:50] + "..." if len(request) > 50 else request
            return f"{base_desc} - {short_request}"

    def _determine_priority(self, task_type: str) -> TaskPriority:
        """우선순위 결정"""
        priorities = {
            "read": TaskPriority.HIGH,
            "analyze": TaskPriority.HIGH,
            "search": TaskPriority.HIGH,
            "create": TaskPriority.MEDIUM,
            "modify": TaskPriority.MEDIUM,
            "delete": TaskPriority.LOW,
            "test": TaskPriority.MEDIUM,
            "build": TaskPriority.LOW,
            "run": TaskPriority.MEDIUM,
        }
        return priorities.get(task_type, TaskPriority.MEDIUM)

    def _generate_id(self) -> str:
        """작업 ID 생성"""
        self.task_counter += 1
        return f"task_{self.task_counter:04d}"

    def get_next_task(self) -> Optional[Task]:
        """다음 실행 가능한 작업"""
        completed = {t.id for t in self.tasks.values() if t.status == TaskStatus.COMPLETED}

        # 우선순위 순으로 정렬
        pending_tasks = [
            t for t in self.tasks.values()
            if t.status == TaskStatus.PENDING and t.is_ready(completed)
        ]

        if not pending_tasks:
            return None

        pending_tasks.sort(key=lambda t: t.priority.value)
        return pending_tasks[0]

    def mark_completed(self, task_id: str, result: str = None):
        """작업 완료 표시"""
        if task_id in self.tasks:
            self.tasks[task_id].status = TaskStatus.COMPLETED
            self.tasks[task_id].result = result
            self.tasks[task_id].completed_at = datetime.now()

    def mark_failed(self, task_id: str, error: str):
        """작업 실패 표시"""
        if task_id in self.tasks:
            self.tasks[task_id].status = TaskStatus.FAILED
            self.tasks[task_id].error = error

    def mark_in_progress(self, task_id: str):
        """작업 진행 중 표시"""
        if task_id in self.tasks:
            self.tasks[task_id].status = TaskStatus.IN_PROGRESS

    def get_progress(self) -> Dict[str, Any]:
        """진행 상황"""
        total = len(self.tasks)
        completed = sum(1 for t in self.tasks.values() if t.status == TaskStatus.COMPLETED)
        failed = sum(1 for t in self.tasks.values() if t.status == TaskStatus.FAILED)
        in_progress = sum(1 for t in self.tasks.values() if t.status == TaskStatus.IN_PROGRESS)

        return {
            "total": total,
            "completed": completed,
            "failed": failed,
            "in_progress": in_progress,
            "pending": total - completed - failed - in_progress,
            "percent": (completed / total * 100) if total > 0 else 0
        }

    def to_todo_list(self) -> List[Dict[str, Any]]:
        """Todo 리스트 형식으로 변환"""
        return [
            {
                "content": task.description,
                "status": task.status.value,
                "activeForm": f"{task.description}..."
            }
            for task in self.tasks.values()
        ]

    def clear(self):
        """초기화"""
        self.tasks = {}
        self.task_counter = 0
