"""
Search Tools - 검색 도구

Claude Code 스타일:
- Glob: 파일 패턴 검색
- Grep: 내용 검색 (정규식)
"""

import os
import re
import fnmatch
from pathlib import Path
from typing import List, Optional

from .base import Tool, ToolResult, ToolStatus, ToolParameter


class GlobTool(Tool):
    """
    파일 패턴 검색 도구

    Claude Code 스타일:
    - glob 패턴 지원 (**, *, ?)
    - 수정 시간순 정렬
    - 무시 패턴 (node_modules 등)
    """

    IGNORE_DIRS = {
        'node_modules', '.git', '__pycache__', '.venv', 'venv',
        'dist', 'build', '.next', '.nuxt', 'coverage', '.idea',
        '.vscode', 'vendor', 'target', 'bin', 'obj', '.cache'
    }

    @property
    def name(self) -> str:
        return "Glob"

    @property
    def description(self) -> str:
        return "glob 패턴으로 파일을 검색합니다. 예: **/*.py, src/**/*.ts"

    @property
    def parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter("pattern", "string", "glob 패턴", required=True),
            ToolParameter("path", "string", "검색 시작 경로", required=False, default="."),
            ToolParameter("limit", "integer", "최대 결과 수", required=False, default=100),
        ]

    def execute(self, pattern: str, path: str = ".", limit: int = 100, **kwargs) -> ToolResult:
        root = Path(path).resolve()

        if not root.exists():
            return ToolResult(
                status=ToolStatus.ERROR,
                error=f"Path not found: {path}"
            )

        try:
            matches = []

            for file_path in root.rglob(pattern.lstrip('/')):
                # 무시 디렉토리 체크
                if any(ignored in file_path.parts for ignored in self.IGNORE_DIRS):
                    continue

                if file_path.is_file():
                    try:
                        rel_path = file_path.relative_to(root)
                        mtime = file_path.stat().st_mtime
                        matches.append((str(rel_path), mtime))
                    except ValueError:
                        continue

                if len(matches) >= limit * 2:  # 정렬 전 여유
                    break

            # 수정 시간순 정렬 (최신 먼저)
            matches.sort(key=lambda x: x[1], reverse=True)
            matches = matches[:limit]

            result_paths = [m[0] for m in matches]

            return ToolResult(
                status=ToolStatus.SUCCESS,
                output="\n".join(result_paths),
                metadata={
                    "pattern": pattern,
                    "root": str(root),
                    "count": len(result_paths)
                }
            )

        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                error=str(e)
            )


class GrepTool(Tool):
    """
    내용 검색 도구

    Claude Code 스타일:
    - 정규식 지원
    - 파일 타입 필터
    - 컨텍스트 라인 (-A, -B, -C)
    """

    IGNORE_DIRS = {
        'node_modules', '.git', '__pycache__', '.venv', 'venv',
        'dist', 'build', '.next', '.nuxt', 'coverage', '.idea',
        '.vscode', 'vendor', 'target', 'bin', 'obj', '.cache'
    }

    @property
    def name(self) -> str:
        return "Grep"

    @property
    def description(self) -> str:
        return "파일 내용을 정규식으로 검색합니다."

    @property
    def parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter("pattern", "string", "검색할 정규식 패턴", required=True),
            ToolParameter("path", "string", "검색 경로", required=False, default="."),
            ToolParameter("glob", "string", "파일 필터 (예: *.py)", required=False),
            ToolParameter("case_insensitive", "boolean", "대소문자 무시", required=False, default=False),
            ToolParameter("context", "integer", "컨텍스트 라인 수", required=False, default=0),
            ToolParameter("limit", "integer", "최대 결과 수", required=False, default=50),
        ]

    def execute(
        self,
        pattern: str,
        path: str = ".",
        glob: str = None,
        case_insensitive: bool = False,
        context: int = 0,
        limit: int = 50,
        **kwargs
    ) -> ToolResult:
        root = Path(path).resolve()

        if not root.exists():
            return ToolResult(
                status=ToolStatus.ERROR,
                error=f"Path not found: {path}"
            )

        try:
            flags = re.IGNORECASE if case_insensitive else 0
            regex = re.compile(pattern, flags)
        except re.error as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                error=f"Invalid regex: {e}"
            )

        try:
            matches = []

            # 파일 목록
            if glob:
                files = root.rglob(glob)
            else:
                files = root.rglob("*")

            for file_path in files:
                if not file_path.is_file():
                    continue

                # 무시 디렉토리 체크
                if any(ignored in file_path.parts for ignored in self.IGNORE_DIRS):
                    continue

                # 바이너리 파일 스킵
                try:
                    with open(file_path, 'rb') as f:
                        if b'\x00' in f.read(8192):
                            continue
                except Exception:
                    continue

                # 내용 검색
                try:
                    content = file_path.read_text(encoding='utf-8', errors='replace')
                    lines = content.splitlines()

                    for i, line in enumerate(lines):
                        if regex.search(line):
                            rel_path = file_path.relative_to(root)

                            # 컨텍스트 포함
                            if context > 0:
                                start = max(0, i - context)
                                end = min(len(lines), i + context + 1)
                                ctx_lines = lines[start:end]
                                match_text = "\n".join(f"{j+1}: {l}" for j, l in enumerate(ctx_lines, start=start))
                            else:
                                match_text = line.strip()

                            matches.append({
                                "file": str(rel_path),
                                "line": i + 1,
                                "match": match_text[:500]  # truncate
                            })

                            if len(matches) >= limit:
                                break

                except Exception:
                    continue

                if len(matches) >= limit:
                    break

            # 출력 포맷
            output_lines = []
            for m in matches:
                output_lines.append(f"{m['file']}:{m['line']}: {m['match']}")

            return ToolResult(
                status=ToolStatus.SUCCESS,
                output="\n".join(output_lines),
                metadata={
                    "pattern": pattern,
                    "root": str(root),
                    "count": len(matches)
                }
            )

        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                error=str(e)
            )
