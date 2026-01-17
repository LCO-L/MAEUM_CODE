"""
CodeWriter - AI 코드 작성 엔진

MAEUM_CODE가 7860 포트의 AI 서버를 호출하여 코드를 작성한다.

구조:
- AI Server (7860): 이미 실행 중인 AI 서버
- MAEUM_CODE: 코드베이스 분석 + AI 호출 + 결과 적용

API 키 사용 안 함 - 7860 서버만 호출
"""

import os
import re
import json
import requests
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field


# =============================================================================
# AI Server Configuration (7860 - 이미 존재)
# =============================================================================

AI_SERVER_HOST = os.getenv("AI_SERVER_HOST", "localhost")
AI_SERVER_PORT = 7860  # 고정 - 이미 실행 중
AI_SERVER_URL = f"http://{AI_SERVER_HOST}:{AI_SERVER_PORT}"


# =============================================================================
# Data Models
# =============================================================================

@dataclass
class CodeChange:
    """코드 변경 사항"""
    file_path: str
    action: str  # "create", "modify", "delete"
    content: Optional[str] = None
    old_content: Optional[str] = None
    diff: Optional[str] = None


@dataclass
class CodeWriteResult:
    """코드 작성 결과"""
    success: bool
    changes: List[CodeChange] = field(default_factory=list)
    message: str = ""
    error: Optional[str] = None


@dataclass
class CodeContext:
    """코드 작성 컨텍스트"""
    root_path: str
    current_file: Optional[str] = None
    related_files: List[str] = field(default_factory=list)
    structure_summary: str = ""
    pattern: Optional[str] = None


# =============================================================================
# AI Server Client (7860 - 이미 존재하는 서버)
# =============================================================================

class AIServerClient:
    """
    7860 포트 AI 서버 클라이언트

    7860 서버는 이미 실행 중이다.
    API 키 없이 직접 호출한다.
    """

    def __init__(self, base_url: str = None):
        self.base_url = base_url or AI_SERVER_URL
        self.timeout = 25 * 60  # 25분

    def is_available(self) -> bool:
        """AI 서버 사용 가능 여부"""
        try:
            resp = requests.get(f"{self.base_url}/api/health", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    def generate(self, system_prompt: str, user_prompt: str, max_tokens: int = 8192) -> str:
        """
        7860 AI 서버에 코드 생성 요청

        maeum_web_ui.py의 /api/chat 엔드포인트 사용
        """
        try:
            payload = {
                "message": user_prompt,
                "system_prompt": system_prompt,
                "max_tokens": max_tokens,
                "coding_mode": True
            }

            resp = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout
            )

            if resp.status_code == 200:
                data = resp.json()
                return data.get("response", "")
            else:
                return f"[AI Server Error] HTTP {resp.status_code}: {resp.text[:200]}"

        except requests.exceptions.ConnectionError:
            return f"[Error] 7860 AI 서버에 연결할 수 없습니다: {self.base_url}"
        except requests.exceptions.Timeout:
            return "[Error] AI 서버 응답 타임아웃"
        except Exception as e:
            return f"[Error] {str(e)}"

    def chat(self, messages: List[Dict[str, str]], system_prompt: str = None) -> str:
        """
        대화형 요청 - /api/chat 사용
        """
        try:
            # 마지막 user 메시지 추출
            last_message = ""
            for msg in reversed(messages):
                if msg.get("role") == "user":
                    last_message = msg.get("content", "")
                    break

            payload = {
                "message": last_message,
                "system_prompt": system_prompt or "",
                "coding_mode": True
            }
            resp = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout
            )

            if resp.status_code == 200:
                data = resp.json()
                return data.get("response", "")
            else:
                return f"[AI Server Error] HTTP {resp.status_code}"

        except Exception as e:
            return f"[Error] {str(e)}"


# =============================================================================
# LLM Interface (Backward Compatibility)
# =============================================================================

class LLMInterface(AIServerClient):
    """LLM 인터페이스 - AIServerClient의 별칭"""
    pass


# =============================================================================
# Code Writer Engine
# =============================================================================

class CodeWriter:
    """
    코드 작성 엔진

    기능:
    - 코드베이스 분석 후 맥락 파악
    - 7860 AI 서버에 코드 생성 요청
    - 파일 생성/수정/삭제
    - 패턴 일관성 유지
    """

    SYSTEM_PROMPT = """너는 MAEUM_CODE의 코드 작성 AI다.

역할:
1. 코드베이스의 구조와 패턴을 파악한다
2. 요청에 맞는 코드를 작성한다
3. 기존 패턴과 스타일을 따른다
4. 명확하고 유지보수 가능한 코드를 작성한다

규칙:
- 코드 블록은 ```언어 로 감싼다
- 파일 경로는 FILE: path/to/file.ext 형태로 명시한다
- 수정 시 전체 파일 내용을 제공한다
- 설명은 간결하게, 코드가 중심이다
- 기존 프로젝트의 네이밍 컨벤션을 따른다

출력 형식:
FILE: path/to/file.ext
```language
코드 내용
```

여러 파일 수정 시 각각 FILE: 로 구분한다."""

    def __init__(self, root_path: str, ai_server_url: str = None):
        self.root_path = Path(root_path).resolve()
        self.ai_client = AIServerClient(ai_server_url)
        self.context: Optional[CodeContext] = None

    def analyze_context(self) -> CodeContext:
        """코드베이스 컨텍스트 분석"""
        from .graph import CodeTreeParser, SemanticGraphBuilder
        from .patterns import PatternJudge

        # 구조 파싱
        parser = CodeTreeParser(str(self.root_path))
        files = parser.parse()

        # 그래프 빌드
        builder = SemanticGraphBuilder(files)
        graph = builder.build()

        # 패턴 판별
        judge = PatternJudge()
        folders = list(set(str(Path(f.path).parent) for f in files))
        file_paths = [f.path for f in files]
        imports = {f.path: f.imports for f in files}

        pattern_result = judge.judge_structure(folders, file_paths, imports)

        # 구조 요약
        summary_parts = [
            f"Files: {len(files)}",
            f"Entities: {len(graph.entities)}",
        ]
        if pattern_result.dominant_pattern:
            summary_parts.append(f"Pattern: {pattern_result.dominant_pattern}")

        self.context = CodeContext(
            root_path=str(self.root_path),
            structure_summary="\n".join(summary_parts),
            pattern=pattern_result.dominant_pattern,
            related_files=file_paths[:20]
        )

        return self.context

    def write_code(self, request: str, target_file: Optional[str] = None) -> CodeWriteResult:
        """
        코드 작성 요청 처리

        Args:
            request: 사용자 요청
            target_file: 대상 파일 (선택)

        Returns:
            CodeWriteResult
        """
        # 컨텍스트 없으면 분석
        if not self.context:
            self.analyze_context()

        # 프롬프트 구성
        user_prompt = self._build_prompt(request, target_file)

        # 7860 AI 서버 호출
        response = self.ai_client.generate(self.SYSTEM_PROMPT, user_prompt)

        # 에러 체크
        if response.startswith("[Error]") or response.startswith("[AI Server Error]"):
            return CodeWriteResult(
                success=False,
                message="AI 서버 호출 실패",
                error=response
            )

        # 응답 파싱
        changes = self._parse_response(response)

        if not changes:
            return CodeWriteResult(
                success=False,
                message="코드 변경 사항을 파싱할 수 없습니다.",
                error=response[:500]
            )

        return CodeWriteResult(
            success=True,
            changes=changes,
            message=f"{len(changes)}개 파일 변경 준비됨"
        )

    def apply_changes(self, result: CodeWriteResult, dry_run: bool = False) -> Dict[str, Any]:
        """변경 사항 적용"""
        applied = []
        errors = []

        for change in result.changes:
            file_path = self.root_path / change.file_path

            try:
                if change.action == "create":
                    if dry_run:
                        applied.append(f"[DRY] Create: {change.file_path}")
                    else:
                        file_path.parent.mkdir(parents=True, exist_ok=True)
                        file_path.write_text(change.content, encoding='utf-8')
                        applied.append(f"Created: {change.file_path}")

                elif change.action == "modify":
                    if dry_run:
                        applied.append(f"[DRY] Modify: {change.file_path}")
                    else:
                        file_path.write_text(change.content, encoding='utf-8')
                        applied.append(f"Modified: {change.file_path}")

                elif change.action == "delete":
                    if dry_run:
                        applied.append(f"[DRY] Delete: {change.file_path}")
                    else:
                        if file_path.exists():
                            file_path.unlink()
                        applied.append(f"Deleted: {change.file_path}")

            except Exception as e:
                errors.append(f"{change.file_path}: {str(e)}")

        return {
            "applied": applied,
            "errors": errors,
            "dry_run": dry_run
        }

    def _build_prompt(self, request: str, target_file: Optional[str]) -> str:
        """프롬프트 구성"""
        parts = []

        parts.append(f"## 프로젝트 정보")
        parts.append(f"경로: {self.context.root_path}")
        parts.append(f"{self.context.structure_summary}")

        if self.context.pattern:
            parts.append(f"아키텍처: {self.context.pattern}")

        if self.context.related_files:
            parts.append(f"\n## 관련 파일")
            for f in self.context.related_files[:10]:
                parts.append(f"- {f}")

        if target_file:
            target_path = self.root_path / target_file
            if target_path.exists():
                content = target_path.read_text(encoding='utf-8', errors='ignore')
                parts.append(f"\n## 현재 파일: {target_file}")
                parts.append(f"```\n{content[:3000]}\n```")

        parts.append(f"\n## 요청")
        parts.append(request)

        return "\n".join(parts)

    def _parse_response(self, response: str) -> List[CodeChange]:
        """AI 응답에서 코드 변경 파싱"""
        changes = []

        file_pattern = re.compile(r'FILE:\s*(.+?)(?:\n|$)')
        code_pattern = re.compile(r'```(\w+)?\n(.*?)```', re.DOTALL)

        parts = re.split(r'(?=FILE:)', response)

        for part in parts:
            file_match = file_pattern.search(part)
            if not file_match:
                continue

            file_path = file_match.group(1).strip()
            code_match = code_pattern.search(part)

            if code_match:
                content = code_match.group(2).strip()
                full_path = self.root_path / file_path
                action = "modify" if full_path.exists() else "create"

                changes.append(CodeChange(
                    file_path=file_path,
                    action=action,
                    content=content
                ))

        return changes

    def read_file(self, file_path: str) -> Optional[str]:
        """파일 읽기"""
        full_path = self.root_path / file_path
        if full_path.exists():
            return full_path.read_text(encoding='utf-8', errors='ignore')
        return None

    def list_files(self, pattern: str = "**/*.py") -> List[str]:
        """파일 목록"""
        return [str(p.relative_to(self.root_path)) for p in self.root_path.glob(pattern)]

    def check_ai_server(self) -> Dict[str, Any]:
        """AI 서버 상태 확인"""
        return {
            "url": AI_SERVER_URL,
            "port": AI_SERVER_PORT,
            "available": self.ai_client.is_available()
        }


# =============================================================================
# Quick Functions
# =============================================================================

def quick_write(root_path: str, request: str, target_file: str = None) -> CodeWriteResult:
    """빠른 코드 작성"""
    writer = CodeWriter(root_path)
    return writer.write_code(request, target_file)


def quick_apply(root_path: str, request: str, target_file: str = None, dry_run: bool = True):
    """빠른 코드 작성 + 적용"""
    writer = CodeWriter(root_path)
    result = writer.write_code(request, target_file)
    if result.success:
        return writer.apply_changes(result, dry_run=dry_run)
    return {"error": result.error}


def check_ai_status() -> Dict[str, Any]:
    """AI 서버 상태 확인"""
    client = AIServerClient()
    return {
        "server": AI_SERVER_URL,
        "port": AI_SERVER_PORT,
        "status": "online" if client.is_available() else "offline"
    }
