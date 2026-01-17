"""
Bash Tool - 명령어 실행 도구

Claude Code 스타일:
- 타임아웃 지원
- 출력 캡처
- 작업 디렉토리 지정
- 위험 명령 차단
"""

import os
import subprocess
import shlex
from pathlib import Path
from typing import List, Optional

from .base import Tool, ToolResult, ToolStatus, ToolParameter


class BashTool(Tool):
    """
    Bash 명령어 실행 도구

    Claude Code 스타일:
    - 타임아웃 (기본 120초)
    - stdout/stderr 캡처
    - 위험 명령 차단
    """

    # 차단할 위험 명령
    DANGEROUS_COMMANDS = [
        'rm -rf /',
        'rm -rf ~',
        'rm -rf *',
        'mkfs',
        'dd if=',
        ':(){:|:&};:',  # fork bomb
        '> /dev/sda',
        'chmod -R 777 /',
        'chown -R',
    ]

    # 허용하지 않는 패턴
    BLOCKED_PATTERNS = [
        r'rm\s+-rf\s+/',
        r'>\s*/dev/',
        r'sudo\s+rm',
    ]

    @property
    def name(self) -> str:
        return "Bash"

    @property
    def description(self) -> str:
        return "Bash 명령어를 실행합니다."

    @property
    def parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter("command", "string", "실행할 명령어", required=True),
            ToolParameter("cwd", "string", "작업 디렉토리", required=False),
            ToolParameter("timeout", "integer", "타임아웃 (초)", required=False, default=120),
        ]

    def execute(self, command: str, cwd: str = None, timeout: int = 120, **kwargs) -> ToolResult:
        # 위험 명령 체크
        if self._is_dangerous(command):
            return ToolResult(
                status=ToolStatus.ERROR,
                error="Dangerous command blocked"
            )

        # 작업 디렉토리
        work_dir = Path(cwd).resolve() if cwd else Path.cwd()
        if not work_dir.exists():
            return ToolResult(
                status=ToolStatus.ERROR,
                error=f"Working directory not found: {cwd}"
            )

        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=str(work_dir),
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, 'LANG': 'en_US.UTF-8'}
            )

            output = result.stdout
            if result.stderr:
                output += f"\n[stderr]\n{result.stderr}"

            # 출력 truncate
            if len(output) > 30000:
                output = output[:30000] + "\n... (truncated)"

            return ToolResult(
                status=ToolStatus.SUCCESS if result.returncode == 0 else ToolStatus.ERROR,
                output=output,
                error=f"Exit code: {result.returncode}" if result.returncode != 0 else None,
                metadata={
                    "command": command,
                    "cwd": str(work_dir),
                    "exit_code": result.returncode
                }
            )

        except subprocess.TimeoutExpired:
            return ToolResult(
                status=ToolStatus.TIMEOUT,
                error=f"Command timed out after {timeout}s"
            )
        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                error=str(e)
            )

    def _is_dangerous(self, command: str) -> bool:
        """위험 명령 체크"""
        cmd_lower = command.lower()

        for dangerous in self.DANGEROUS_COMMANDS:
            if dangerous.lower() in cmd_lower:
                return True

        import re
        for pattern in self.BLOCKED_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return True

        return False
