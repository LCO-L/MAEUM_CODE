"""
File Tools - 파일 조작 도구

Claude Code 스타일:
- Read: 파일 읽기 (라인 번호 포함)
- Write: 파일 쓰기 (전체 덮어쓰기)
- Edit: 파일 수정 (old_string → new_string)
"""

import os
from pathlib import Path
from typing import Optional, List
from difflib import unified_diff

from .base import Tool, ToolResult, ToolStatus, ToolParameter


class ReadTool(Tool):
    """
    파일 읽기 도구

    Claude Code 스타일:
    - 라인 번호 포함
    - offset/limit 지원
    - 바이너리 파일 감지
    """

    @property
    def name(self) -> str:
        return "Read"

    @property
    def description(self) -> str:
        return "파일 내용을 읽습니다. 라인 번호와 함께 반환합니다."

    @property
    def parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter("file_path", "string", "읽을 파일의 절대 경로", required=True),
            ToolParameter("offset", "integer", "시작 라인 (0부터)", required=False, default=0),
            ToolParameter("limit", "integer", "읽을 라인 수", required=False, default=2000),
        ]

    def execute(self, file_path: str, offset: int = 0, limit: int = 2000, **kwargs) -> ToolResult:
        path = Path(file_path)

        if not path.exists():
            return ToolResult(
                status=ToolStatus.ERROR,
                error=f"File not found: {file_path}"
            )

        if not path.is_file():
            return ToolResult(
                status=ToolStatus.ERROR,
                error=f"Not a file: {file_path}"
            )

        try:
            # 바이너리 파일 체크
            with open(path, 'rb') as f:
                chunk = f.read(8192)
                if b'\x00' in chunk:
                    return ToolResult(
                        status=ToolStatus.ERROR,
                        error="Binary file - cannot read"
                    )

            # 텍스트로 읽기
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            total_lines = len(lines)
            selected = lines[offset:offset + limit]

            # 라인 번호 포함 포맷
            output_lines = []
            for i, line in enumerate(selected, start=offset + 1):
                # 긴 라인 truncate
                if len(line) > 2000:
                    line = line[:2000] + "... (truncated)"
                output_lines.append(f"{i:6}\t{line.rstrip()}")

            return ToolResult(
                status=ToolStatus.SUCCESS,
                output="\n".join(output_lines),
                metadata={
                    "file_path": str(path),
                    "total_lines": total_lines,
                    "offset": offset,
                    "lines_read": len(selected)
                }
            )

        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                error=str(e)
            )


class WriteTool(Tool):
    """
    파일 쓰기 도구

    Claude Code 스타일:
    - 전체 내용 덮어쓰기
    - 디렉토리 자동 생성
    - 기존 파일 백업 (선택)
    """

    @property
    def name(self) -> str:
        return "Write"

    @property
    def description(self) -> str:
        return "파일에 내용을 씁니다. 기존 파일은 덮어씁니다."

    @property
    def parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter("file_path", "string", "쓸 파일의 절대 경로", required=True),
            ToolParameter("content", "string", "쓸 내용", required=True),
        ]

    def execute(self, file_path: str, content: str, **kwargs) -> ToolResult:
        path = Path(file_path)

        try:
            # 디렉토리 생성
            path.parent.mkdir(parents=True, exist_ok=True)

            # 기존 파일 존재 여부
            existed = path.exists()
            old_content = None
            if existed:
                old_content = path.read_text(encoding='utf-8', errors='replace')

            # 쓰기
            path.write_text(content, encoding='utf-8')

            return ToolResult(
                status=ToolStatus.SUCCESS,
                output=f"{'Modified' if existed else 'Created'}: {file_path}",
                metadata={
                    "file_path": str(path),
                    "action": "modify" if existed else "create",
                    "bytes_written": len(content.encode('utf-8'))
                }
            )

        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                error=str(e)
            )


class EditTool(Tool):
    """
    파일 수정 도구 (Diff 기반)

    Claude Code 스타일:
    - old_string → new_string 치환
    - 유일성 검증 (old_string이 파일에 하나만 있어야 함)
    - replace_all 옵션
    """

    @property
    def name(self) -> str:
        return "Edit"

    @property
    def description(self) -> str:
        return "파일의 특정 부분을 수정합니다. old_string을 new_string으로 치환합니다."

    @property
    def parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter("file_path", "string", "수정할 파일의 절대 경로", required=True),
            ToolParameter("old_string", "string", "치환할 기존 문자열", required=True),
            ToolParameter("new_string", "string", "새 문자열", required=True),
            ToolParameter("replace_all", "boolean", "모든 발생 치환 여부", required=False, default=False),
        ]

    def execute(self, file_path: str, old_string: str, new_string: str, replace_all: bool = False, **kwargs) -> ToolResult:
        path = Path(file_path)

        if not path.exists():
            return ToolResult(
                status=ToolStatus.ERROR,
                error=f"File not found: {file_path}"
            )

        try:
            content = path.read_text(encoding='utf-8', errors='replace')

            # old_string 발생 횟수 확인
            count = content.count(old_string)

            if count == 0:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    error=f"old_string not found in file"
                )

            if count > 1 and not replace_all:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    error=f"old_string found {count} times. Use replace_all=True or provide more context."
                )

            # 치환
            if replace_all:
                new_content = content.replace(old_string, new_string)
            else:
                new_content = content.replace(old_string, new_string, 1)

            # diff 생성
            diff = list(unified_diff(
                content.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=f"a/{path.name}",
                tofile=f"b/{path.name}"
            ))

            # 쓰기
            path.write_text(new_content, encoding='utf-8')

            return ToolResult(
                status=ToolStatus.SUCCESS,
                output=f"Modified: {file_path} ({count} replacement{'s' if count > 1 else ''})",
                metadata={
                    "file_path": str(path),
                    "replacements": count if replace_all else 1,
                    "diff": "".join(diff)
                }
            )

        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                error=str(e)
            )
