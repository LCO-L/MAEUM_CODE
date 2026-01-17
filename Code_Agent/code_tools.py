"""
Code Tools - 클로드 코드 수준의 대규모 코드 작업 도구

핵심 기능:
- 멀티파일 편집
- 안전한 파일 조작
- 실행 취소/다시 실행
- 트랜잭션 기반 변경
- 대규모 리팩토링
- 코드 생성
"""

import os
import re
import shutil
import difflib
import tempfile
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple, Callable, Union
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import hashlib
import json


# =============================================================================
# Configuration
# =============================================================================

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
MAX_UNDO_STACK = 1000
MAX_UNDO_BYTES = 3 * 1024 * 1024 * 1024  # 3GB
BACKUP_DIR = ".maeum_backup"


class OperationType(Enum):
    """작업 타입"""
    CREATE = "create"
    MODIFY = "modify"
    DELETE = "delete"
    RENAME = "rename"
    MOVE = "move"
    COPY = "copy"


class OperationStatus(Enum):
    """작업 상태"""
    PENDING = "pending"
    APPLIED = "applied"
    FAILED = "failed"
    UNDONE = "undone"


@dataclass
class FileChange:
    """파일 변경"""
    operation: OperationType
    file_path: str
    new_content: Optional[str] = None
    old_content: Optional[str] = None
    new_path: Optional[str] = None  # rename/move용
    diff: Optional[str] = None
    status: OperationStatus = OperationStatus.PENDING
    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def is_new(self) -> bool:
        return self.operation == OperationType.CREATE

    @property
    def is_delete(self) -> bool:
        return self.operation == OperationType.DELETE


@dataclass
class Transaction:
    """트랜잭션 (여러 변경 묶음)"""
    id: str
    description: str
    changes: List[FileChange] = field(default_factory=list)
    status: OperationStatus = OperationStatus.PENDING
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_change(self, change: FileChange):
        self.changes.append(change)

    @property
    def file_count(self) -> int:
        return len(self.changes)

    @property
    def summary(self) -> Dict[str, int]:
        return {
            "create": sum(1 for c in self.changes if c.operation == OperationType.CREATE),
            "modify": sum(1 for c in self.changes if c.operation == OperationType.MODIFY),
            "delete": sum(1 for c in self.changes if c.operation == OperationType.DELETE),
            "rename": sum(1 for c in self.changes if c.operation == OperationType.RENAME),
        }


# =============================================================================
# Safe File Operations
# =============================================================================

class SafeFileOps:
    """
    안전한 파일 작업

    특징:
    - 원자적 쓰기 (atomic write)
    - 자동 백업
    - 실행 취소 지원
    - 바이너리 파일 보호
    """

    def __init__(self, root_path: str, backup_enabled: bool = True):
        self.root_path = Path(root_path).resolve()
        self.backup_enabled = backup_enabled
        self.backup_dir = self.root_path / BACKUP_DIR

        if backup_enabled:
            self.backup_dir.mkdir(exist_ok=True)

    def read_file(self, file_path: str) -> Tuple[Optional[str], Optional[str]]:
        """
        파일 읽기

        Returns:
            (content, error) 튜플
        """
        full_path = self._resolve_path(file_path)

        if not full_path.exists():
            return None, f"파일이 존재하지 않습니다: {file_path}"

        if not full_path.is_file():
            return None, f"파일이 아닙니다: {file_path}"

        # 바이너리 체크
        try:
            with open(full_path, 'rb') as f:
                chunk = f.read(8192)
                if b'\x00' in chunk:
                    return None, "바이너리 파일입니다"

            content = full_path.read_text(encoding='utf-8', errors='replace')
            return content, None

        except Exception as e:
            return None, str(e)

    def write_file(
        self,
        file_path: str,
        content: str,
        create_dirs: bool = True,
        backup: bool = None
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        파일 쓰기 (원자적)

        Returns:
            (success, old_content, error) 튜플
        """
        full_path = self._resolve_path(file_path)
        backup = backup if backup is not None else self.backup_enabled

        old_content = None
        if full_path.exists():
            old_content, err = self.read_file(file_path)
            if err and "바이너리" in err:
                return False, None, "바이너리 파일은 수정할 수 없습니다"

        try:
            # 디렉토리 생성
            if create_dirs:
                full_path.parent.mkdir(parents=True, exist_ok=True)

            # 백업
            if backup and old_content is not None:
                self._backup_file(full_path, old_content)

            # 원자적 쓰기 (임시 파일 → rename)
            temp_path = full_path.with_suffix(full_path.suffix + '.tmp')
            temp_path.write_text(content, encoding='utf-8')
            temp_path.replace(full_path)

            return True, old_content, None

        except Exception as e:
            return False, old_content, str(e)

    def delete_file(
        self,
        file_path: str,
        backup: bool = None
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        파일 삭제

        Returns:
            (success, old_content, error) 튜플
        """
        full_path = self._resolve_path(file_path)
        backup = backup if backup is not None else self.backup_enabled

        if not full_path.exists():
            return False, None, f"파일이 존재하지 않습니다: {file_path}"

        old_content = None
        if full_path.is_file():
            old_content, _ = self.read_file(file_path)

            # 백업
            if backup and old_content is not None:
                self._backup_file(full_path, old_content)

        try:
            if full_path.is_dir():
                shutil.rmtree(full_path)
            else:
                full_path.unlink()

            return True, old_content, None

        except Exception as e:
            return False, old_content, str(e)

    def rename_file(
        self,
        old_path: str,
        new_path: str,
        overwrite: bool = False
    ) -> Tuple[bool, Optional[str]]:
        """
        파일 이름 변경/이동

        Returns:
            (success, error) 튜플
        """
        full_old = self._resolve_path(old_path)
        full_new = self._resolve_path(new_path)

        if not full_old.exists():
            return False, f"원본이 존재하지 않습니다: {old_path}"

        if full_new.exists() and not overwrite:
            return False, f"대상이 이미 존재합니다: {new_path}"

        try:
            full_new.parent.mkdir(parents=True, exist_ok=True)
            full_old.rename(full_new)
            return True, None

        except Exception as e:
            return False, str(e)

    def copy_file(
        self,
        src_path: str,
        dst_path: str,
        overwrite: bool = False
    ) -> Tuple[bool, Optional[str]]:
        """
        파일 복사

        Returns:
            (success, error) 튜플
        """
        full_src = self._resolve_path(src_path)
        full_dst = self._resolve_path(dst_path)

        if not full_src.exists():
            return False, f"원본이 존재하지 않습니다: {src_path}"

        if full_dst.exists() and not overwrite:
            return False, f"대상이 이미 존재합니다: {dst_path}"

        try:
            full_dst.parent.mkdir(parents=True, exist_ok=True)

            if full_src.is_dir():
                shutil.copytree(full_src, full_dst, dirs_exist_ok=overwrite)
            else:
                shutil.copy2(full_src, full_dst)

            return True, None

        except Exception as e:
            return False, str(e)

    def create_directory(self, dir_path: str) -> Tuple[bool, Optional[str]]:
        """디렉토리 생성"""
        full_path = self._resolve_path(dir_path)

        try:
            full_path.mkdir(parents=True, exist_ok=True)
            return True, None
        except Exception as e:
            return False, str(e)

    def get_diff(self, old_content: str, new_content: str, file_path: str = "") -> str:
        """diff 생성"""
        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)

        diff = difflib.unified_diff(
            old_lines, new_lines,
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
            lineterm=''
        )

        return ''.join(diff)

    def _resolve_path(self, file_path: str) -> Path:
        """경로 해석"""
        if file_path.startswith('/'):
            return Path(file_path)
        return self.root_path / file_path

    def _backup_file(self, file_path: Path, content: str):
        """파일 백업"""
        if not self.backup_enabled:
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        rel_path = file_path.relative_to(self.root_path)
        backup_path = self.backup_dir / f"{rel_path}.{timestamp}.bak"

        backup_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path.write_text(content, encoding='utf-8')


# =============================================================================
# Code Editor (Claude Code Style)
# =============================================================================

class CodeEditor:
    """
    코드 에디터

    Claude Code 스타일:
    - Edit: old_string → new_string
    - 유일성 검증
    - 컨텍스트 인식
    """

    def __init__(self, root_path: str):
        self.file_ops = SafeFileOps(root_path)
        self.root_path = Path(root_path).resolve()

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False
    ) -> FileChange:
        """
        파일 편집 (old_string → new_string)

        Args:
            file_path: 파일 경로
            old_string: 기존 문자열
            new_string: 새 문자열
            replace_all: 모든 발생 치환

        Returns:
            FileChange
        """
        content, error = self.file_ops.read_file(file_path)

        if error:
            return FileChange(
                operation=OperationType.MODIFY,
                file_path=file_path,
                status=OperationStatus.FAILED,
                error=error
            )

        # 발생 횟수 확인
        count = content.count(old_string)

        if count == 0:
            return FileChange(
                operation=OperationType.MODIFY,
                file_path=file_path,
                old_content=content,
                status=OperationStatus.FAILED,
                error="old_string을 찾을 수 없습니다"
            )

        if count > 1 and not replace_all:
            return FileChange(
                operation=OperationType.MODIFY,
                file_path=file_path,
                old_content=content,
                status=OperationStatus.FAILED,
                error=f"old_string이 {count}번 발견됨. replace_all=True를 사용하거나 더 구체적인 컨텍스트를 제공하세요."
            )

        # 치환
        if replace_all:
            new_content = content.replace(old_string, new_string)
        else:
            new_content = content.replace(old_string, new_string, 1)

        # diff 생성
        diff = self.file_ops.get_diff(content, new_content, file_path)

        return FileChange(
            operation=OperationType.MODIFY,
            file_path=file_path,
            old_content=content,
            new_content=new_content,
            diff=diff,
            status=OperationStatus.PENDING
        )

    def write(self, file_path: str, content: str) -> FileChange:
        """
        파일 쓰기 (전체 내용)

        Args:
            file_path: 파일 경로
            content: 파일 내용

        Returns:
            FileChange
        """
        full_path = self.root_path / file_path
        operation = OperationType.CREATE if not full_path.exists() else OperationType.MODIFY

        old_content = None
        if full_path.exists():
            old_content, _ = self.file_ops.read_file(file_path)

        diff = None
        if old_content:
            diff = self.file_ops.get_diff(old_content, content, file_path)

        return FileChange(
            operation=operation,
            file_path=file_path,
            old_content=old_content,
            new_content=content,
            diff=diff,
            status=OperationStatus.PENDING
        )

    def delete(self, file_path: str) -> FileChange:
        """
        파일 삭제

        Args:
            file_path: 파일 경로

        Returns:
            FileChange
        """
        old_content, _ = self.file_ops.read_file(file_path)

        return FileChange(
            operation=OperationType.DELETE,
            file_path=file_path,
            old_content=old_content,
            status=OperationStatus.PENDING
        )

    def rename(self, old_path: str, new_path: str) -> FileChange:
        """
        파일 이름 변경

        Args:
            old_path: 기존 경로
            new_path: 새 경로

        Returns:
            FileChange
        """
        return FileChange(
            operation=OperationType.RENAME,
            file_path=old_path,
            new_path=new_path,
            status=OperationStatus.PENDING
        )


# =============================================================================
# Undo Manager
# =============================================================================

class UndoManager:
    """
    실행 취소 관리자

    특징:
    - 무제한 undo 스택 (메모리 허용 범위 내)
    - 트랜잭션 단위 undo/redo
    - 파일별 히스토리
    - 용량 제한 (3GB)
    """

    def __init__(self, root_path: str, max_stack: int = MAX_UNDO_STACK, max_bytes: int = MAX_UNDO_BYTES):
        self.root_path = Path(root_path).resolve()
        self.max_stack = max_stack
        self.max_bytes = max_bytes

        self._undo_stack: List[Transaction] = []
        self._redo_stack: List[Transaction] = []
        self._lock = threading.Lock()

        # 통계
        self._total_bytes = 0

    def push(self, transaction: Transaction):
        """트랜잭션 추가"""
        with self._lock:
            # 용량 계산
            tx_bytes = self._calculate_size(transaction)

            # 용량 초과시 오래된 것 제거
            while self._total_bytes + tx_bytes > self.max_bytes and self._undo_stack:
                removed = self._undo_stack.pop(0)
                self._total_bytes -= self._calculate_size(removed)

            # 개수 제한
            if len(self._undo_stack) >= self.max_stack:
                removed = self._undo_stack.pop(0)
                self._total_bytes -= self._calculate_size(removed)

            self._undo_stack.append(transaction)
            self._total_bytes += tx_bytes

            # redo 스택 클리어
            self._redo_stack.clear()

    def undo(self) -> Optional[Transaction]:
        """실행 취소"""
        with self._lock:
            if not self._undo_stack:
                return None

            transaction = self._undo_stack.pop()
            self._redo_stack.append(transaction)
            self._total_bytes -= self._calculate_size(transaction)

            return transaction

    def redo(self) -> Optional[Transaction]:
        """다시 실행"""
        with self._lock:
            if not self._redo_stack:
                return None

            transaction = self._redo_stack.pop()
            self._undo_stack.append(transaction)
            self._total_bytes += self._calculate_size(transaction)

            return transaction

    def get_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """히스토리 조회"""
        history = []

        for tx in reversed(self._undo_stack[-limit:]):
            history.append({
                "id": tx.id,
                "description": tx.description,
                "files": tx.file_count,
                "summary": tx.summary,
                "timestamp": tx.timestamp
            })

        return history

    def get_file_history(self, file_path: str, limit: int = 10) -> List[Dict[str, Any]]:
        """특정 파일의 히스토리"""
        history = []

        for tx in reversed(self._undo_stack):
            for change in tx.changes:
                if change.file_path == file_path:
                    history.append({
                        "transaction_id": tx.id,
                        "operation": change.operation.value,
                        "timestamp": change.timestamp,
                        "has_old_content": change.old_content is not None
                    })

                    if len(history) >= limit:
                        return history

        return history

    def clear(self):
        """스택 클리어"""
        with self._lock:
            self._undo_stack.clear()
            self._redo_stack.clear()
            self._total_bytes = 0

    @property
    def can_undo(self) -> bool:
        return len(self._undo_stack) > 0

    @property
    def can_redo(self) -> bool:
        return len(self._redo_stack) > 0

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "undo_count": len(self._undo_stack),
            "redo_count": len(self._redo_stack),
            "total_bytes": self._total_bytes,
            "max_bytes": self.max_bytes
        }

    def _calculate_size(self, transaction: Transaction) -> int:
        """트랜잭션 크기 계산"""
        size = len(transaction.id.encode()) + len(transaction.description.encode())

        for change in transaction.changes:
            size += len(change.file_path.encode())
            if change.old_content:
                size += len(change.old_content.encode())
            if change.new_content:
                size += len(change.new_content.encode())

        return size


# =============================================================================
# Transaction Manager (Multi-file Operations)
# =============================================================================

class TransactionManager:
    """
    트랜잭션 관리자

    여러 파일 변경을 하나의 트랜잭션으로 묶어 처리
    """

    def __init__(self, root_path: str):
        self.root_path = Path(root_path).resolve()
        self.file_ops = SafeFileOps(root_path)
        self.editor = CodeEditor(root_path)
        self.undo_manager = UndoManager(root_path)

        self._current_transaction: Optional[Transaction] = None
        self._lock = threading.Lock()

    def begin(self, description: str = "") -> str:
        """트랜잭션 시작"""
        with self._lock:
            if self._current_transaction:
                raise RuntimeError("이미 진행 중인 트랜잭션이 있습니다")

            tx_id = hashlib.md5(f"{datetime.now().isoformat()}".encode()).hexdigest()[:8]
            self._current_transaction = Transaction(
                id=tx_id,
                description=description
            )

            return tx_id

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False
    ) -> FileChange:
        """편집 추가"""
        change = self.editor.edit(file_path, old_string, new_string, replace_all)

        if self._current_transaction:
            self._current_transaction.add_change(change)

        return change

    def write(self, file_path: str, content: str) -> FileChange:
        """쓰기 추가"""
        change = self.editor.write(file_path, content)

        if self._current_transaction:
            self._current_transaction.add_change(change)

        return change

    def delete(self, file_path: str) -> FileChange:
        """삭제 추가"""
        change = self.editor.delete(file_path)

        if self._current_transaction:
            self._current_transaction.add_change(change)

        return change

    def rename(self, old_path: str, new_path: str) -> FileChange:
        """이름 변경 추가"""
        change = self.editor.rename(old_path, new_path)

        if self._current_transaction:
            self._current_transaction.add_change(change)

        return change

    def commit(self, dry_run: bool = False) -> Transaction:
        """
        트랜잭션 커밋 (변경 적용)

        Args:
            dry_run: True면 실제 적용 안 함

        Returns:
            Transaction
        """
        with self._lock:
            if not self._current_transaction:
                raise RuntimeError("진행 중인 트랜잭션이 없습니다")

            tx = self._current_transaction
            errors = []

            if not dry_run:
                for change in tx.changes:
                    success, error = self._apply_change(change)
                    if not success:
                        errors.append(f"{change.file_path}: {error}")
                        change.status = OperationStatus.FAILED
                        change.error = error
                    else:
                        change.status = OperationStatus.APPLIED

                if not errors:
                    tx.status = OperationStatus.APPLIED
                    self.undo_manager.push(tx)
                else:
                    tx.status = OperationStatus.FAILED
            else:
                tx.status = OperationStatus.PENDING

            self._current_transaction = None
            return tx

    def rollback(self):
        """트랜잭션 롤백"""
        with self._lock:
            self._current_transaction = None

    def undo(self) -> Optional[Transaction]:
        """마지막 트랜잭션 실행 취소"""
        tx = self.undo_manager.undo()
        if not tx:
            return None

        # 역순으로 변경 복원
        for change in reversed(tx.changes):
            self._revert_change(change)
            change.status = OperationStatus.UNDONE

        tx.status = OperationStatus.UNDONE
        return tx

    def redo(self) -> Optional[Transaction]:
        """다시 실행"""
        tx = self.undo_manager.redo()
        if not tx:
            return None

        for change in tx.changes:
            self._apply_change(change)
            change.status = OperationStatus.APPLIED

        tx.status = OperationStatus.APPLIED
        return tx

    def quick_edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        description: str = ""
    ) -> Transaction:
        """빠른 편집 (단일 파일)"""
        self.begin(description or f"Edit {file_path}")
        self.edit(file_path, old_string, new_string)
        return self.commit()

    def quick_write(
        self,
        file_path: str,
        content: str,
        description: str = ""
    ) -> Transaction:
        """빠른 쓰기 (단일 파일)"""
        self.begin(description or f"Write {file_path}")
        self.write(file_path, content)
        return self.commit()

    def _apply_change(self, change: FileChange) -> Tuple[bool, Optional[str]]:
        """변경 적용"""
        if change.operation == OperationType.CREATE:
            success, _, error = self.file_ops.write_file(change.file_path, change.new_content)
            return success, error

        elif change.operation == OperationType.MODIFY:
            success, _, error = self.file_ops.write_file(change.file_path, change.new_content)
            return success, error

        elif change.operation == OperationType.DELETE:
            success, _, error = self.file_ops.delete_file(change.file_path)
            return success, error

        elif change.operation == OperationType.RENAME:
            return self.file_ops.rename_file(change.file_path, change.new_path)

        return False, "알 수 없는 작업"

    def _revert_change(self, change: FileChange) -> Tuple[bool, Optional[str]]:
        """변경 복원"""
        if change.operation == OperationType.CREATE:
            # 생성된 파일 삭제
            success, _, error = self.file_ops.delete_file(change.file_path, backup=False)
            return success, error

        elif change.operation == OperationType.MODIFY:
            # 이전 내용으로 복원
            if change.old_content is not None:
                success, _, error = self.file_ops.write_file(
                    change.file_path, change.old_content, backup=False
                )
                return success, error
            return False, "이전 내용이 없습니다"

        elif change.operation == OperationType.DELETE:
            # 삭제된 파일 복원
            if change.old_content is not None:
                success, _, error = self.file_ops.write_file(
                    change.file_path, change.old_content, backup=False
                )
                return success, error
            return False, "이전 내용이 없습니다"

        elif change.operation == OperationType.RENAME:
            # 이름 되돌리기
            return self.file_ops.rename_file(change.new_path, change.file_path)

        return False, "알 수 없는 작업"

    @property
    def history(self) -> List[Dict[str, Any]]:
        return self.undo_manager.get_history()

    @property
    def can_undo(self) -> bool:
        return self.undo_manager.can_undo

    @property
    def can_redo(self) -> bool:
        return self.undo_manager.can_redo


# =============================================================================
# Batch Editor (Multiple Files at Once)
# =============================================================================

class BatchEditor:
    """
    배치 에디터

    대규모 리팩토링을 위한 다중 파일 편집
    """

    def __init__(self, root_path: str):
        self.root_path = Path(root_path).resolve()
        self.tx_manager = TransactionManager(root_path)

    def find_and_replace(
        self,
        pattern: str,
        replacement: str,
        file_pattern: str = "*.py",
        is_regex: bool = False,
        dry_run: bool = True
    ) -> Dict[str, Any]:
        """
        찾아 바꾸기 (다중 파일)

        Args:
            pattern: 찾을 패턴
            replacement: 바꿀 문자열
            file_pattern: 파일 패턴
            is_regex: 정규식 사용
            dry_run: True면 실제 적용 안 함

        Returns:
            결과 딕셔너리
        """
        # 파일 찾기
        files = list(self.root_path.rglob(file_pattern))
        changes = []
        total_replacements = 0

        self.tx_manager.begin(f"Find and Replace: {pattern} → {replacement}")

        for file_path in files:
            try:
                content = file_path.read_text(encoding='utf-8', errors='ignore')
                rel_path = str(file_path.relative_to(self.root_path))

                if is_regex:
                    new_content, count = re.subn(pattern, replacement, content)
                else:
                    count = content.count(pattern)
                    new_content = content.replace(pattern, replacement)

                if count > 0:
                    change = self.tx_manager.write(rel_path, new_content)
                    changes.append({
                        "file": rel_path,
                        "replacements": count
                    })
                    total_replacements += count

            except Exception:
                pass

        if dry_run:
            self.tx_manager.rollback()
        else:
            self.tx_manager.commit()

        return {
            "files_changed": len(changes),
            "total_replacements": total_replacements,
            "changes": changes,
            "dry_run": dry_run
        }

    def rename_symbol(
        self,
        old_name: str,
        new_name: str,
        file_pattern: str = "*.py",
        whole_word: bool = True,
        dry_run: bool = True
    ) -> Dict[str, Any]:
        """
        심볼 이름 변경 (리팩토링)

        Args:
            old_name: 기존 이름
            new_name: 새 이름
            file_pattern: 파일 패턴
            whole_word: 단어 단위 매칭
            dry_run: True면 실제 적용 안 함

        Returns:
            결과 딕셔너리
        """
        if whole_word:
            pattern = r'\b' + re.escape(old_name) + r'\b'
            return self.find_and_replace(pattern, new_name, file_pattern, is_regex=True, dry_run=dry_run)
        else:
            return self.find_and_replace(old_name, new_name, file_pattern, is_regex=False, dry_run=dry_run)


# =============================================================================
# Factory & Singleton
# =============================================================================

_default_tx_manager: Optional[TransactionManager] = None


def get_tx_manager(root_path: str = ".") -> TransactionManager:
    """기본 트랜잭션 매니저"""
    global _default_tx_manager
    if _default_tx_manager is None or str(_default_tx_manager.root_path) != str(Path(root_path).resolve()):
        _default_tx_manager = TransactionManager(root_path)
    return _default_tx_manager


def quick_edit(file_path: str, old_string: str, new_string: str, root_path: str = ".") -> Transaction:
    """빠른 편집"""
    return get_tx_manager(root_path).quick_edit(file_path, old_string, new_string)


def quick_write(file_path: str, content: str, root_path: str = ".") -> Transaction:
    """빠른 쓰기"""
    return get_tx_manager(root_path).quick_write(file_path, content)


def undo(root_path: str = ".") -> Optional[Transaction]:
    """실행 취소"""
    return get_tx_manager(root_path).undo()


def redo(root_path: str = ".") -> Optional[Transaction]:
    """다시 실행"""
    return get_tx_manager(root_path).redo()
