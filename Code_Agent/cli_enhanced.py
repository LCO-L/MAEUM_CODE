#!/usr/bin/env python3
"""
MAEUM_CODE Enhanced CLI

클로드 코드 수준의 강력한 CLI:
- 실시간 스트리밍 응답
- 강화된 검색 (코드/파일/심볼)
- 대규모 코드 작업
- 안전한 파일 조작
- 실행 취소/다시 실행
- 프로젝트 인덱싱
"""

import os
import sys
import re
import threading
import time
import signal
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any
from datetime import datetime

# 로컬 임포트 (상대/절대 둘 다 지원)
try:
    from .stream_client import SmartClient, StreamStatus, check_server
    from .advanced_search import SearchEngine, SearchMode, FileType, quick_search, quick_find, quick_symbol
    from .code_tools import TransactionManager, BatchEditor, OperationType
    from .classifier import ActionClassifier
    from .context_store import ContextStore
    from .ARCHITECTURE import ActionType, Phase, Tolerance
except ImportError:
    from stream_client import SmartClient, StreamStatus, check_server
    from advanced_search import SearchEngine, SearchMode, FileType, quick_search, quick_find, quick_symbol
    from code_tools import TransactionManager, BatchEditor, OperationType
    from classifier import ActionClassifier
    from context_store import ContextStore
    from ARCHITECTURE import ActionType, Phase, Tolerance


# =============================================================================
# ANSI Colors
# =============================================================================

class Colors:
    """ANSI 색상 코드"""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"

    # 색상
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    GRAY = "\033[90m"

    # 밝은 색상
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"

    # 배경
    BG_BLACK = "\033[40m"
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"
    BG_GRAY = "\033[100m"

    @classmethod
    def rgb(cls, r: int, g: int, b: int) -> str:
        """RGB 색상"""
        return f"\033[38;2;{r};{g};{b}m"

    @classmethod
    def bg_rgb(cls, r: int, g: int, b: int) -> str:
        """RGB 배경"""
        return f"\033[48;2;{r};{g};{b}m"


C = Colors  # 단축


# =============================================================================
# Terminal UI Components
# =============================================================================

def get_terminal_width() -> int:
    """터미널 너비"""
    try:
        import shutil
        return shutil.get_terminal_size().columns
    except:
        return 80


def clear_line():
    """현재 줄 지우기"""
    print(f"\r{' ' * get_terminal_width()}\r", end="", flush=True)


def print_box(title: str, content: List[str], style: str = "single"):
    """박스 출력"""
    width = min(get_terminal_width() - 4, 70)
    border = "─" * (width - 4)

    print(f"{C.DIM}┌─ {title} {border[:width - len(title) - 5]}┐{C.RESET}")
    for line in content:
        truncated = line[:width - 4] + ("..." if len(line) > width - 4 else "")
        print(f"{C.DIM}│{C.RESET} {truncated}")
    print(f"{C.DIM}└{border}─┘{C.RESET}")


def print_diff(old_content: str, new_content: str, max_lines: int = 20):
    """diff 출력"""
    import difflib

    old_lines = old_content.splitlines()
    new_lines = new_content.splitlines()
    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm='', n=2))

    shown = 0
    for line in diff[2:]:  # 헤더 스킵
        if shown >= max_lines:
            print(f"{C.DIM}... (more changes){C.RESET}")
            break

        if line.startswith('+'):
            print(f"{C.GREEN}{line[:70]}{C.RESET}")
            shown += 1
        elif line.startswith('-'):
            print(f"{C.RED}{line[:70]}{C.RESET}")
            shown += 1
        elif line.startswith('@'):
            print(f"{C.BLUE}{line[:70]}{C.RESET}")


# =============================================================================
# Streaming Output
# =============================================================================

class StreamingOutput:
    """
    스트리밍 출력 처리

    실시간 마크다운 렌더링
    """

    def __init__(self):
        self.buffer = ""
        self.in_code_block = False
        self.code_lang = ""
        self.code_path = ""
        self.line_count = 0

    def on_token(self, token: str):
        """토큰 수신 콜백"""
        self.buffer += token

        # 줄바꿈이 있으면 렌더링
        while '\n' in self.buffer:
            line, self.buffer = self.buffer.split('\n', 1)
            self._render_line(line)

        # 버퍼에 남은 내용 (줄바꿈 없는 마지막 부분)
        if self.buffer and '\n' not in self.buffer:
            print(self.buffer, end="", flush=True)

    def _render_line(self, line: str):
        """한 줄 렌더링"""
        self.line_count += 1

        # 코드 블록 시작/끝
        if line.startswith('```'):
            if not self.in_code_block:
                self.in_code_block = True
                rest = line[3:].strip()

                # ```python:path/to/file.py 형식
                if ':' in rest:
                    self.code_lang, self.code_path = rest.split(':', 1)
                    print(f"\n{C.DIM}┌─ {self.code_lang} → {C.CYAN}{self.code_path}{C.RESET}")
                elif rest:
                    self.code_lang = rest
                    print(f"\n{C.DIM}┌─ {self.code_lang}{C.RESET}")
                else:
                    print(f"\n{C.DIM}┌─ code{C.RESET}")
            else:
                self.in_code_block = False
                self.code_lang = ""
                self.code_path = ""
                print(f"{C.DIM}└─{C.RESET}\n")
            return

        # 코드 블록 내부
        if self.in_code_block:
            print(f"{C.GRAY}│{C.RESET} {line}")
            return

        # 헤더
        if line.startswith('### '):
            print(f"\n{C.BOLD}{C.CYAN}   {line[4:]}{C.RESET}")
            return
        if line.startswith('## '):
            print(f"\n{C.BOLD}{C.BLUE}  {line[3:]}{C.RESET}")
            return
        if line.startswith('# '):
            print(f"\n{C.BOLD}{C.MAGENTA} {line[2:]}{C.RESET}")
            print(f"{C.DIM}{'─' * 50}{C.RESET}")
            return

        # 리스트
        if line.strip().startswith('- '):
            indent = len(line) - len(line.lstrip())
            content = line.strip()[2:]
            print(f"{' ' * indent}{C.CYAN}•{C.RESET} {self._inline(content)}")
            return

        # 일반 텍스트
        print(self._inline(line))

    def _inline(self, text: str) -> str:
        """인라인 마크다운"""
        # 굵게 **text**
        text = re.sub(r'\*\*(.+?)\*\*', f'{C.BOLD}\\1{C.RESET}', text)

        # 인라인 코드 `code`
        text = re.sub(r'`([^`]+)`', f'{C.BG_GRAY}{C.WHITE}\\1{C.RESET}', text)

        return text

    def flush(self):
        """버퍼 플러시"""
        if self.buffer:
            print(self.buffer)
            self.buffer = ""

        if self.in_code_block:
            print(f"{C.DIM}└─{C.RESET}")
            self.in_code_block = False


# =============================================================================
# Progress Indicator
# =============================================================================

class ProgressIndicator:
    """진행 표시기"""

    SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, message: str = ""):
        self.message = message
        self.running = False
        self.aborted = False
        self._thread = None
        self._frame = 0
        self._start_time = 0

    def start(self):
        """시작"""
        self.running = True
        self.aborted = False
        self._start_time = time.time()
        self._thread = threading.Thread(target=self._animate, daemon=True)
        self._thread.start()

    def _animate(self):
        """애니메이션"""
        while self.running:
            elapsed = time.time() - self._start_time
            spinner = self.SPINNER_FRAMES[self._frame % len(self.SPINNER_FRAMES)]
            mins, secs = divmod(int(elapsed), 60)

            line = f"\r  {C.CYAN}{spinner}{C.RESET} {self.message} {C.DIM}({mins:02d}:{secs:02d}){C.RESET}"
            print(line + " " * 10, end="", flush=True)

            self._frame += 1
            time.sleep(0.1)

    def update(self, message: str):
        """메시지 업데이트"""
        self.message = message

    def stop(self, final_message: str = ""):
        """정지"""
        self.running = False
        if self._thread:
            self._thread.join(timeout=0.5)
        clear_line()
        if final_message:
            print(f"  {final_message}")

    def cancel(self):
        """취소"""
        self.aborted = True
        self.running = False


# =============================================================================
# Enhanced CLI
# =============================================================================

class EnhancedCLI:
    """
    강화된 CLI

    클로드 코드 수준:
    - 실시간 스트리밍
    - 고급 검색
    - 대규모 코드 작업
    - 프로젝트 인덱싱
    """

    # 시스템 프롬프트
    SYSTEM_PROMPT = """너는 MAEUM_CODE - 프로젝트를 처음부터 완성까지 만들 수 있는 전문 AI 코딩 에이전트다.

## 🎯 핵심 능력
너는 Claude Code Opus처럼 **완전한 프로젝트를 스스로 설계하고 구현**할 수 있다:
- 빈 폴더에서 전체 앱/서비스 구축
- 복잡한 아키텍처 설계 및 구현
- 프론트엔드 + 백엔드 + DB 전체 스택
- 테스트, CI/CD, 배포 설정까지

## 🔧 도구 (정확한 형식으로 사용할 것)

### 탐색 (자동 실행)
```read:경로``` - 파일 읽기
```ls:경로``` - 디렉토리 목록
```grep:패턴:경로``` - 내용 검색
```find:패턴``` - 파일 찾기
```tree:경로``` - 트리 구조

### 코드 작성 (모든 언어 지원)
```언어:경로
코드
```
예: ```python:src/main.py, ```typescript:src/app.ts

### 파일/폴더 조작
```mkdir:경로``` - 디렉토리 생성
```delete:경로``` - 삭제
```move:원본:대상``` - 이동
```copy:원본:대상``` - 복사

### 명령 실행
```bash:설명
명령어
```

### 작업 관리
```todo:add:작업내용```
```todo:done:번호```
```report:메시지```

## ⚡ 중요 원칙
1. **완전한 코드 작성**: 실제 동작하는 전체 코드
2. **한 번에 여러 파일**: 관련 파일들을 모두 생성
3. **실행 가능한 상태 유지**: 매 단계가 끝나면 실행 가능
4. **에러 처리 포함**: 프로덕션 수준
5. **자동 진행**: 사용자 개입 없이 완성

**도구만 사용하라. 설명 없이 바로 실행하라.**"""

    def __init__(self, root_path: str = "."):
        self.root_path = Path(root_path).resolve()

        # 클라이언트
        self.client = SmartClient()

        # 검색 엔진
        self.search_engine = SearchEngine(str(self.root_path))

        # 트랜잭션 매니저
        self.tx_manager = TransactionManager(str(self.root_path))

        # 배치 에디터
        self.batch_editor = BatchEditor(str(self.root_path))

        # 분류기
        self.classifier = ActionClassifier()
        self.context_store = ContextStore()

        # 상태
        self.dir_tree = ""
        self.indexed = False
        self.ai_todos: List[Dict[str, str]] = []
        self.iteration = 0
        self.max_iterations = 48
        self._cancelled = False

    def run(self):
        """메인 루프"""
        self._print_header()
        self._check_server()
        self._index_codebase()

        # Ctrl+C 핸들러
        signal.signal(signal.SIGINT, self._signal_handler)

        while True:
            try:
                user_input = self._read_input()

                if not user_input:
                    continue

                # 명령어 처리
                if user_input.startswith('/'):
                    if self._handle_command(user_input):
                        continue
                    if user_input in ['/q', '/quit', '/exit']:
                        break

                # AI 대화
                self._process(user_input)

            except KeyboardInterrupt:
                print()
                continue
            except EOFError:
                break

        print(f"\n{C.DIM}Goodbye!{C.RESET}\n")

    def _print_header(self):
        """헤더 출력"""
        print()
        print(f"  {C.BOLD}{C.CYAN}╔══════════════════════════════════════════════════════════╗{C.RESET}")
        print(f"  {C.BOLD}{C.CYAN}║{C.RESET}  {C.BOLD}MAEUM_CODE{C.RESET}  ─  AI 코딩 어시스턴트                       {C.BOLD}{C.CYAN}║{C.RESET}")
        print(f"  {C.BOLD}{C.CYAN}╚══════════════════════════════════════════════════════════╝{C.RESET}")
        print(f"  {C.DIM}📁{C.RESET} {self.root_path}")
        print(f"  {C.DIM}💡 빈 줄로 전송 │ /help 도움말 │ /q 종료{C.RESET}")
        print()

    def _check_server(self):
        """서버 상태 확인"""
        status = check_server()

        if status["available"]:
            stream_status = f"{C.GREEN}✓ 스트리밍{C.RESET}" if status.get("stream_support") else f"{C.YELLOW}○ 일반{C.RESET}"
            print(f"  {C.GREEN}●{C.RESET} AI 서버 연결됨 ({status['url']}) {stream_status}")
        else:
            print(f"  {C.RED}○{C.RESET} AI 서버 오프라인 ({status['url']})")
            print(f"  {C.DIM}  7860 포트에서 AI 서버를 실행하세요{C.RESET}")
        print()

    def _index_codebase(self):
        """코드베이스 인덱싱"""
        print(f"  {C.CYAN}⠿{C.RESET} 프로젝트 인덱싱...", end="", flush=True)

        try:
            stats = self.search_engine.index_codebase()
            self.indexed = True
            self.dir_tree = self._scan_directory(self.root_path)

            print(f"\r  {C.GREEN}✓{C.RESET} {stats['indexed_files']}개 파일, {stats['symbols']}개 심볼 ({stats['elapsed_time']:.1f}s)")
        except Exception as e:
            print(f"\r  {C.YELLOW}⚠{C.RESET} 인덱싱 실패: {e}")

        print()

    def _read_input(self) -> str:
        """입력 읽기"""
        lines = []
        print(f"{C.GREEN}>{C.RESET} ", end="", flush=True)

        while True:
            try:
                line = input()
                if line == "" and lines:
                    break
                lines.append(line)
            except EOFError:
                break

        return "\n".join(lines).strip()

    def _handle_command(self, cmd: str) -> bool:
        """명령어 처리"""
        parts = cmd.split(maxsplit=1)
        command = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if command == '/help':
            self._show_help()
            return True

        elif command == '/undo':
            self._undo()
            return True

        elif command == '/redo':
            self._redo()
            return True

        elif command == '/history':
            self._show_history()
            return True

        elif command == '/search' or command == '/s':
            self._search(arg)
            return True

        elif command == '/find' or command == '/f':
            self._find_files(arg)
            return True

        elif command == '/symbol':
            self._find_symbol(arg)
            return True

        elif command == '/index':
            self._index_codebase()
            return True

        elif command == '/status':
            self._show_status()
            return True

        elif command == '/clear':
            os.system('clear' if os.name != 'nt' else 'cls')
            self._print_header()
            return True

        return False

    def _show_help(self):
        """도움말"""
        help_text = [
            f"{C.BOLD}명령어:{C.RESET}",
            f"  /help        - 도움말",
            f"  /search <쿼리> - 코드 검색",
            f"  /find <패턴>   - 파일 찾기",
            f"  /symbol <이름> - 심볼 찾기 (함수, 클래스)",
            f"  /undo        - 마지막 변경 취소",
            f"  /redo        - 다시 실행",
            f"  /history     - 변경 이력",
            f"  /index       - 프로젝트 재인덱싱",
            f"  /status      - 상태 확인",
            f"  /clear       - 화면 지우기",
            f"  /q, /quit    - 종료",
            "",
            f"{C.BOLD}AI 도구:{C.RESET}",
            f"  read:경로     - 파일 읽기",
            f"  ls:경로       - 디렉토리 목록",
            f"  grep:패턴:경로 - 내용 검색",
            f"  find:패턴     - 파일 찾기",
            f"  mkdir:경로    - 디렉토리 생성",
            "",
            f"{C.BOLD}코드 작성:{C.RESET}",
            f"  ```python:경로",
            f"  코드",
            f"  ```",
        ]
        print()
        for line in help_text:
            print(f"  {line}")
        print()

    def _search(self, query: str):
        """코드 검색"""
        if not query:
            print(f"  {C.YELLOW}검색어를 입력하세요{C.RESET}")
            return

        result = self.search_engine.search(query, max_results=20)

        print(f"\n  {C.BOLD}검색 결과:{C.RESET} {query}")
        print(f"  {C.DIM}{result.files_matched}개 파일, {result.total_matches}개 매치 ({result.elapsed_time:.2f}s){C.RESET}")
        print()

        for match in result.matches[:20]:
            print(f"  {C.CYAN}{match.file_path}{C.RESET}:{C.YELLOW}{match.line_number}{C.RESET}")
            print(f"    {match.line_content.strip()[:70]}")
        print()

    def _find_files(self, pattern: str):
        """파일 찾기"""
        if not pattern:
            pattern = "*"

        files = self.search_engine.find_files(pattern, max_results=30)

        print(f"\n  {C.BOLD}파일 찾기:{C.RESET} {pattern}")
        print(f"  {C.DIM}{len(files)}개 발견{C.RESET}")
        print()

        for f in files:
            icon = "📁" if f.extension == "" else "📄"
            print(f"  {icon} {C.CYAN}{f.relative_path}{C.RESET} {C.DIM}({f.file_type.value}){C.RESET}")
        print()

    def _find_symbol(self, name: str):
        """심볼 찾기"""
        if not name:
            print(f"  {C.YELLOW}심볼 이름을 입력하세요{C.RESET}")
            return

        symbols = self.search_engine.find_symbol(name)

        print(f"\n  {C.BOLD}심볼 찾기:{C.RESET} {name}")
        print(f"  {C.DIM}{len(symbols)}개 발견{C.RESET}")
        print()

        for s in symbols[:20]:
            stype = s.get("type", "symbol")
            icon = "🔷" if stype == "class" else ("🔹" if stype == "function" else "○")
            print(f"  {icon} {C.CYAN}{s.get('name')}{C.RESET} ({stype})")
            print(f"    {C.DIM}{s.get('file')}:{s.get('line')}{C.RESET}")
        print()

    def _undo(self):
        """실행 취소"""
        tx = self.tx_manager.undo()
        if tx:
            print(f"\n  {C.GREEN}✓{C.RESET} 취소됨: {tx.description}")
            for change in tx.changes:
                print(f"    - {change.operation.value}: {change.file_path}")
        else:
            print(f"\n  {C.YELLOW}취소할 항목이 없습니다{C.RESET}")
        print()

    def _redo(self):
        """다시 실행"""
        tx = self.tx_manager.redo()
        if tx:
            print(f"\n  {C.GREEN}✓{C.RESET} 다시 실행: {tx.description}")
            for change in tx.changes:
                print(f"    - {change.operation.value}: {change.file_path}")
        else:
            print(f"\n  {C.YELLOW}다시 실행할 항목이 없습니다{C.RESET}")
        print()

    def _show_history(self):
        """변경 이력"""
        history = self.tx_manager.history

        print(f"\n  {C.BOLD}변경 이력:{C.RESET}")
        if not history:
            print(f"  {C.DIM}이력이 없습니다{C.RESET}")
        else:
            for i, h in enumerate(history, 1):
                summary = h['summary']
                ops = ", ".join(f"{k}:{v}" for k, v in summary.items() if v > 0)
                print(f"  {i}. {h['description']} [{ops}]")
                print(f"     {C.DIM}{h['timestamp']}{C.RESET}")
        print()

    def _show_status(self):
        """상태 표시"""
        server = check_server()
        search_stats = self.search_engine.get_stats()
        undo_stats = self.tx_manager.undo_manager.stats

        print(f"\n  {C.BOLD}상태:{C.RESET}")
        print(f"  프로젝트: {self.root_path}")
        print(f"  AI 서버: {'온라인' if server['available'] else '오프라인'} ({server['url']})")
        print(f"  인덱스: {search_stats['indexed_files']}개 파일, {search_stats['total_symbols']}개 심볼")
        print(f"  Undo: {undo_stats['undo_count']}개 / Redo: {undo_stats['redo_count']}개")
        print(f"  메모리: {undo_stats['total_bytes'] / 1024 / 1024:.1f}MB / {undo_stats['max_bytes'] / 1024 / 1024 / 1024:.1f}GB")
        print()

    def _process(self, input_text: str):
        """입력 처리"""
        self._cancelled = False
        self.iteration = 0

        while self.iteration < self.max_iterations and not self._cancelled:
            self.iteration += 1

            # 시스템 프롬프트 구성
            system = self._build_system_prompt()

            # 스트리밍 출력
            output = StreamingOutput()
            progress = ProgressIndicator("AI 응답 대기 중...")

            response_content = ""

            def on_token(token: str):
                nonlocal response_content
                response_content += token
                progress.stop()
                output.on_token(token)

            # 스트리밍 요청
            progress.start()

            try:
                result = self.client.stream(
                    message=input_text,
                    system_prompt=system,
                    on_chunk=on_token
                )

                progress.stop()
                output.flush()

                if result.status == StreamStatus.ERROR:
                    print(f"\n  {C.RED}✗ 오류: {result.error}{C.RESET}\n")
                    break

                if result.status == StreamStatus.CANCELLED:
                    print(f"\n  {C.YELLOW}⚠ 취소됨{C.RESET}\n")
                    break

            except Exception as e:
                progress.stop()
                print(f"\n  {C.RED}✗ 오류: {e}{C.RESET}\n")
                break

            print()

            # 도구 실행
            tool_results = self._execute_tools(response_content)

            if tool_results:
                # 결과를 다음 iteration에 전달
                input_text = f"[이전 요청]\n{input_text}\n\n{tool_results}\n\n위 결과를 바탕으로 계속 진행하세요."
                continue

            break

    def _build_system_prompt(self) -> str:
        """시스템 프롬프트 구성"""
        parts = [self.SYSTEM_PROMPT]

        # 프로젝트 정보
        parts.append(f"\n## 📁 현재 프로젝트")
        parts.append(f"경로: {self.root_path}")
        parts.append(f"Iteration: {self.iteration}/{self.max_iterations}")

        # 디렉토리 구조
        if self.dir_tree:
            parts.append(f"\n{self.dir_tree[:3000]}")

        # 투두 상태
        if self.ai_todos:
            parts.append(f"\n## 현재 작업 계획")
            for i, todo in enumerate(self.ai_todos, 1):
                status = "✓" if todo["status"] == "done" else "○"
                parts.append(f"  {i}. [{status}] {todo['task']}")

        return "\n".join(parts)

    def _execute_tools(self, response: str) -> str:
        """도구 실행"""
        results = []

        # 탐색 도구
        explore_results = self._execute_explore_tools(response)
        if explore_results:
            results.append(explore_results)

        # 파일 조작
        file_results = self._execute_file_tools(response)
        if file_results:
            results.append(file_results)

        # 명령어 실행
        exec_results = self._execute_commands(response)
        if exec_results:
            results.append(exec_results)

        # 코드 블록 저장
        self._save_code_blocks(response)

        # 투두
        self._execute_todos(response)

        return "\n\n".join(results)

    def _execute_explore_tools(self, response: str) -> str:
        """탐색 도구 실행"""
        results = []

        # read:경로
        for match in re.finditer(r'```read:([^\n`]+)\n*```', response):
            path = match.group(1).strip()
            content = self._read_file(path)
            results.append(f"=== read:{path} ===\n{content[:5000]}")
            print(f"  {C.CYAN}📂{C.RESET} read: {path}")

        # ls:경로
        for match in re.finditer(r'```ls:([^\n`]*)\n*```', response):
            path = match.group(1).strip() or '.'
            content = self._list_dir(path)
            results.append(f"=== ls:{path} ===\n{content}")
            print(f"  {C.CYAN}📂{C.RESET} ls: {path}")

        # grep:패턴:경로
        for match in re.finditer(r'```grep:([^:\n`]+):?([^\n`]*)\n*```', response):
            pattern = match.group(1).strip()
            path = match.group(2).strip() or '.'
            result = self.search_engine.search(pattern, max_results=20)
            content = "\n".join(f"{m.file_path}:{m.line_number}: {m.line_content.strip()}" for m in result.matches)
            results.append(f"=== grep:{pattern} ===\n{content}")
            print(f"  {C.CYAN}🔍{C.RESET} grep: {pattern}")

        # find:패턴
        for match in re.finditer(r'```find:([^\n`]+)\n*```', response):
            pattern = match.group(1).strip()
            files = self.search_engine.find_files(pattern, max_results=30)
            content = "\n".join(f.relative_path for f in files)
            results.append(f"=== find:{pattern} ===\n{content}")
            print(f"  {C.CYAN}🔍{C.RESET} find: {pattern}")

        # tree:경로
        for match in re.finditer(r'```tree:([^\n`]*)\n*```', response):
            path = match.group(1).strip() or '.'
            content = self._scan_directory(self.root_path / path if path != '.' else self.root_path)
            results.append(f"=== tree:{path} ===\n{content}")
            print(f"  {C.CYAN}🌳{C.RESET} tree: {path}")

        return "\n\n".join(results)

    def _execute_file_tools(self, response: str) -> str:
        """파일 조작 도구 실행"""
        results = []

        # mkdir:경로
        for match in re.finditer(r'```mkdir:([^\n`]+)\n*```', response):
            path = match.group(1).strip()
            full_path = self.root_path / path
            try:
                full_path.mkdir(parents=True, exist_ok=True)
                results.append(f"✓ mkdir: {path}")
                print(f"  {C.GREEN}✓{C.RESET} mkdir: {path}")
                self.dir_tree = self._scan_directory(self.root_path)
            except Exception as e:
                results.append(f"✗ mkdir failed: {e}")
                print(f"  {C.RED}✗{C.RESET} mkdir failed: {e}")

        return "\n".join(results)

    def _execute_commands(self, response: str) -> str:
        """명령어 실행"""
        import subprocess
        results = []

        for match in re.finditer(r'```bash:([^\n`]*)\n(.*?)```', response, re.DOTALL):
            desc = match.group(1).strip()
            cmd = match.group(2).strip()

            if not cmd:
                continue

            print(f"\n  {C.DIM}┌─ bash: {desc}{C.RESET}")
            print(f"  {C.DIM}│{C.RESET} {C.CYAN}${C.RESET} {cmd[:60]}")

            # 허락 받기
            try:
                choice = input(f"  {C.YELLOW}실행? (y/n):{C.RESET} ").strip().lower()
            except:
                choice = 'n'

            if choice == 'y':
                try:
                    result = subprocess.run(
                        cmd,
                        shell=True,
                        cwd=str(self.root_path),
                        capture_output=True,
                        text=True,
                        timeout=300
                    )
                    output = result.stdout + result.stderr
                    print(f"  {C.DIM}│{C.RESET} {output[:500]}")

                    if result.returncode == 0:
                        print(f"  {C.GREEN}✓ 완료{C.RESET}")
                    else:
                        print(f"  {C.RED}✗ 종료코드 {result.returncode}{C.RESET}")

                    results.append(f"=== bash:{desc} ===\n{output[:2000]}")
                    self.dir_tree = self._scan_directory(self.root_path)

                except subprocess.TimeoutExpired:
                    print(f"  {C.RED}⏱ 타임아웃{C.RESET}")
                    results.append(f"=== bash:{desc} ===\n[타임아웃]")
                except Exception as e:
                    print(f"  {C.RED}✗ {e}{C.RESET}")
                    results.append(f"=== bash:{desc} ===\n[오류: {e}]")
            else:
                print(f"  {C.DIM}건너뜀{C.RESET}")

            print(f"  {C.DIM}└─{C.RESET}\n")

        return "\n\n".join(results)

    def _save_code_blocks(self, response: str):
        """코드 블록 저장"""
        pattern = r'```(\w+):([^\n`]+)\n(.*?)```'

        for match in re.finditer(pattern, response, re.DOTALL):
            lang = match.group(1).lower()
            path = match.group(2).strip()
            code = match.group(3).strip()

            # 특수 블록 제외
            if lang in ('read', 'ls', 'grep', 'find', 'tree', 'mkdir', 'delete', 'move', 'copy', 'bash', 'todo', 'report', 'undo'):
                continue

            if not path or not code:
                continue

            full_path = self.root_path / path
            is_new = not full_path.exists()

            # 출력
            print(f"\n  {C.DIM}┌─ {'Create' if is_new else 'Edit'}{C.RESET}")
            print(f"  {C.DIM}│{C.RESET} {C.CYAN}{path}{C.RESET}")
            print(f"  {C.DIM}│{C.RESET} {len(code.splitlines())} lines │ {lang}")

            # 미리보기
            for i, line in enumerate(code.splitlines()[:5]):
                print(f"  {C.DIM}│{C.RESET} {C.GREEN}+{C.RESET} {line[:60]}")
            if len(code.splitlines()) > 5:
                print(f"  {C.DIM}│{C.RESET} {C.DIM}... (+{len(code.splitlines()) - 5} lines){C.RESET}")

            print(f"  {C.DIM}├─{C.RESET}")

            # 허락 받기
            try:
                choice = input(f"  {C.YELLOW}Apply? (y/n/v):{C.RESET} ").strip().lower()
            except:
                choice = 'n'

            if choice == 'v':
                # 전체 보기
                print(f"\n  {C.DIM}─── Full Content ───{C.RESET}")
                for i, line in enumerate(code.splitlines(), 1):
                    print(f"  {i:4}│ {line}")
                print(f"  {C.DIM}─────────────────────{C.RESET}")

                try:
                    choice = input(f"  {C.YELLOW}Apply? (y/n):{C.RESET} ").strip().lower()
                except:
                    choice = 'n'

            if choice == 'y':
                # 트랜잭션으로 저장
                self.tx_manager.begin(f"{'Create' if is_new else 'Edit'} {path}")
                self.tx_manager.write(path, code)
                tx = self.tx_manager.commit()

                if tx.status.value == "applied":
                    print(f"  {C.GREEN}✓ Applied{C.RESET}")
                    self.dir_tree = self._scan_directory(self.root_path)
                else:
                    print(f"  {C.RED}✗ Failed{C.RESET}")
            else:
                print(f"  {C.DIM}Skipped{C.RESET}")

            print(f"  {C.DIM}└─{C.RESET}\n")

    def _execute_todos(self, response: str):
        """투두 실행"""
        # todo:add:내용
        for match in re.finditer(r'```todo:add:([^\n`]+)\n*```', response):
            task = match.group(1).strip()
            self.ai_todos.append({"task": task, "status": "pending"})
            print(f"  {C.CYAN}📋{C.RESET} 할 일 추가: {task[:50]}")

        # todo:done:번호
        for match in re.finditer(r'```todo:done:(\d+)\n*```', response):
            idx = int(match.group(1)) - 1
            if 0 <= idx < len(self.ai_todos):
                self.ai_todos[idx]["status"] = "done"
                print(f"  {C.GREEN}✓{C.RESET} 완료: {self.ai_todos[idx]['task'][:50]}")

    def _read_file(self, path: str) -> str:
        """파일 읽기"""
        full_path = self.root_path / path if not path.startswith('/') else Path(path)

        if not full_path.exists():
            return f"[파일 없음: {path}]"

        try:
            content = full_path.read_text(encoding='utf-8', errors='ignore')
            lines = content.splitlines()
            numbered = [f"{i+1:4}│ {line}" for i, line in enumerate(lines)]
            return "\n".join(numbered)
        except Exception as e:
            return f"[읽기 실패: {e}]"

    def _list_dir(self, path: str) -> str:
        """디렉토리 목록"""
        target = self.root_path / path if path != '.' else self.root_path

        if not target.exists():
            return f"[경로 없음: {path}]"

        try:
            items = sorted(target.iterdir(), key=lambda x: (x.is_file(), x.name))
            lines = []
            for item in items[:50]:
                if item.is_dir():
                    lines.append(f"  📁 {item.name}/")
                else:
                    size = item.stat().st_size
                    lines.append(f"  📄 {item.name} ({size} bytes)")
            return "\n".join(lines)
        except Exception as e:
            return f"[ls 실패: {e}]"

    def _scan_directory(self, path: Path, max_depth: int = 3) -> str:
        """디렉토리 스캔"""
        lines = []

        def scan(p: Path, prefix: str = "", depth: int = 0):
            if depth > max_depth:
                return

            try:
                items = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name))
            except PermissionError:
                return

            exclude = {'.git', 'node_modules', '__pycache__', '.venv', 'venv'}
            items = [i for i in items if i.name not in exclude and not i.name.startswith('.')]

            for i, item in enumerate(items[:20]):
                is_last = i == len(items) - 1
                connector = "└── " if is_last else "├── "

                if item.is_dir():
                    lines.append(f"{prefix}{connector}{item.name}/")
                    new_prefix = prefix + ("    " if is_last else "│   ")
                    scan(item, new_prefix, depth + 1)
                else:
                    lines.append(f"{prefix}{connector}{item.name}")

        lines.append(f"{path.name}/")
        scan(path)
        return "\n".join(lines)

    def _signal_handler(self, signum, frame):
        """시그널 핸들러"""
        self._cancelled = True
        print(f"\n{C.YELLOW}⚠ 중단됨{C.RESET}")


# =============================================================================
# Entry Point
# =============================================================================

def main():
    """메인 함수"""
    import argparse

    parser = argparse.ArgumentParser(description="MAEUM_CODE Enhanced CLI")
    parser.add_argument("path", nargs="?", default=".", help="프로젝트 경로")
    parser.add_argument("--status", action="store_true", help="서버 상태 확인")

    args = parser.parse_args()

    if args.status:
        status = check_server()
        print(f"""
MAEUM_CODE Status
─────────────────
AI Server: {status['url']} ({'ONLINE' if status['available'] else 'OFFLINE'})
Streaming: {'지원' if status.get('stream_support') else '미지원'}
""")
        return

    cli = EnhancedCLI(args.path)
    cli.run()


if __name__ == "__main__":
    main()
