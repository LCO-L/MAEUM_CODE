"""
Advanced Search - 클로드 코드 수준의 강력한 검색 시스템

핵심 기능:
- 시맨틱 검색 (코드 의미 기반)
- 멀티 패턴 검색
- 대규모 코드베이스 최적화
- 증분 인덱싱
- 퍼지 매칭
- 컨텍스트 인식 검색
"""

import os
import re
import ast
import fnmatch
import hashlib
import threading
from pathlib import Path
from typing import (
    Optional, List, Dict, Any, Set, Tuple,
    Generator, Callable, Union
)
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import time


# =============================================================================
# Configuration
# =============================================================================

# 무시할 디렉토리
IGNORE_DIRS = {
    '.git', 'node_modules', '__pycache__', '.venv', 'venv', 'env',
    'dist', 'build', '.next', '.nuxt', 'coverage', '.idea', '.vscode',
    'vendor', 'target', 'bin', 'obj', '.cache', '.pytest_cache',
    '.mypy_cache', '.tox', 'eggs', '*.egg-info', '.eggs',
    'htmlcov', '.hypothesis', '.nox', '.ruff_cache'
}

# 무시할 파일 패턴
IGNORE_FILES = {
    '*.pyc', '*.pyo', '*.pyd', '*.so', '*.dylib', '*.dll',
    '*.class', '*.jar', '*.war', '*.ear',
    '*.min.js', '*.min.css', '*.map',
    '*.lock', 'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml',
    '*.log', '*.tmp', '*.temp', '*.swp', '*.swo',
    '.DS_Store', 'Thumbs.db', '*.ico', '*.icns',
    '*.png', '*.jpg', '*.jpeg', '*.gif', '*.bmp', '*.svg', '*.webp',
    '*.mp3', '*.mp4', '*.wav', '*.avi', '*.mov',
    '*.pdf', '*.doc', '*.docx', '*.xls', '*.xlsx',
    '*.zip', '*.tar', '*.gz', '*.rar', '*.7z',
    '*.exe', '*.bin', '*.o', '*.a',
    '*.woff', '*.woff2', '*.ttf', '*.eot', '*.otf'
}

# 검색 가능한 파일 확장자
SEARCHABLE_EXTENSIONS = {
    # 프로그래밍 언어
    '.py', '.js', '.ts', '.jsx', '.tsx', '.mjs', '.cjs',
    '.java', '.kt', '.scala', '.groovy',
    '.c', '.cpp', '.cc', '.cxx', '.h', '.hpp', '.hxx',
    '.cs', '.fs', '.vb',
    '.go', '.rs', '.swift', '.m', '.mm',
    '.rb', '.php', '.pl', '.pm', '.lua',
    '.r', '.R', '.jl', '.m', '.mat',
    '.sh', '.bash', '.zsh', '.fish', '.ps1', '.bat', '.cmd',
    '.sql', '.graphql', '.gql',
    '.hs', '.elm', '.clj', '.cljs', '.erl', '.ex', '.exs',
    '.dart', '.v', '.zig', '.nim', '.cr',

    # 마크업/스타일
    '.html', '.htm', '.xhtml', '.xml', '.xsl', '.xslt',
    '.css', '.scss', '.sass', '.less', '.styl',
    '.vue', '.svelte', '.astro',

    # 데이터/설정
    '.json', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf',
    '.env', '.env.local', '.env.development', '.env.production',
    '.properties', '.plist',

    # 문서
    '.md', '.markdown', '.rst', '.txt', '.text',
    '.adoc', '.asciidoc', '.org',

    # 기타
    '.dockerfile', '.containerfile',
    '.tf', '.hcl',  # Terraform
    '.prisma', '.proto',  # Schema
    '.sol',  # Solidity
}

# 우선순위 높은 파일
HIGH_PRIORITY_FILES = {
    'main.py', 'app.py', 'index.py', '__init__.py', 'cli.py', 'server.py',
    'main.ts', 'main.js', 'index.ts', 'index.js', 'app.ts', 'app.js',
    'main.go', 'main.rs', 'main.java', 'Main.java',
    'setup.py', 'setup.cfg', 'pyproject.toml',
    'package.json', 'tsconfig.json', 'vite.config.ts', 'webpack.config.js',
    'Cargo.toml', 'go.mod', 'pom.xml', 'build.gradle',
    'Makefile', 'CMakeLists.txt', 'Dockerfile', 'docker-compose.yml',
    'README.md', 'README.rst', 'CHANGELOG.md',
}


class SearchMode(Enum):
    """검색 모드"""
    EXACT = "exact"           # 정확히 일치
    FUZZY = "fuzzy"           # 퍼지 매칭
    REGEX = "regex"           # 정규식
    SEMANTIC = "semantic"     # 의미 기반
    SYMBOL = "symbol"         # 심볼 (함수, 클래스)


class FileType(Enum):
    """파일 타입"""
    SOURCE = "source"
    CONFIG = "config"
    DOC = "doc"
    TEST = "test"
    DATA = "data"
    OTHER = "other"


@dataclass
class SearchMatch:
    """검색 결과 매치"""
    file_path: str
    line_number: int
    column: int
    line_content: str
    match_text: str
    context_before: List[str] = field(default_factory=list)
    context_after: List[str] = field(default_factory=list)
    score: float = 1.0
    file_type: FileType = FileType.SOURCE
    symbol_type: Optional[str] = None  # function, class, variable


@dataclass
class SearchResult:
    """검색 결과"""
    query: str
    mode: SearchMode
    matches: List[SearchMatch] = field(default_factory=list)
    files_searched: int = 0
    files_matched: int = 0
    total_matches: int = 0
    elapsed_time: float = 0.0
    truncated: bool = False
    error: Optional[str] = None


@dataclass
class FileInfo:
    """파일 정보 (인덱싱용)"""
    path: str
    relative_path: str
    name: str
    extension: str
    size: int
    modified_time: float
    file_type: FileType
    priority: int = 0  # 높을수록 우선
    content_hash: Optional[str] = None
    symbols: List[Dict[str, Any]] = field(default_factory=list)


# =============================================================================
# File Type Detection
# =============================================================================

def detect_file_type(file_path: str) -> FileType:
    """파일 타입 감지"""
    path_lower = file_path.lower()
    name = Path(file_path).name.lower()

    # 테스트 파일
    if 'test' in name or 'spec' in name or '/tests/' in path_lower or '/test/' in path_lower:
        return FileType.TEST

    # 설정 파일
    config_patterns = [
        'config', 'settings', '.env', '.rc', '.conf',
        'setup.py', 'setup.cfg', 'pyproject.toml',
        'package.json', 'tsconfig', 'webpack', 'vite',
        'dockerfile', 'docker-compose', 'makefile',
        '.yaml', '.yml', '.toml', '.ini'
    ]
    for pattern in config_patterns:
        if pattern in path_lower:
            return FileType.CONFIG

    # 문서 파일
    doc_patterns = ['.md', '.rst', '.txt', 'readme', 'changelog', 'license', 'contributing']
    for pattern in doc_patterns:
        if pattern in path_lower:
            return FileType.DOC

    # 데이터 파일
    if path_lower.endswith(('.json', '.csv', '.xml')) and 'config' not in path_lower:
        return FileType.DATA

    return FileType.SOURCE


def get_file_priority(file_path: str) -> int:
    """파일 우선순위 계산"""
    name = Path(file_path).name

    if name in HIGH_PRIORITY_FILES:
        return 100

    # 진입점 파일
    if name in ('main.py', 'app.py', 'index.py', 'cli.py'):
        return 90
    if name in ('main.ts', 'main.js', 'index.ts', 'index.js', 'app.ts', 'app.js'):
        return 90

    # __init__.py
    if name == '__init__.py':
        return 80

    # 루트 레벨 파일
    if len(Path(file_path).parts) <= 2:
        return 70

    # 소스 디렉토리
    if '/src/' in file_path or '/lib/' in file_path:
        return 60

    # API/핵심 로직
    if any(x in file_path.lower() for x in ['api', 'core', 'service', 'util', 'helper']):
        return 50

    return 10


# =============================================================================
# Advanced Search Engine
# =============================================================================

class SearchEngine:
    """
    고급 검색 엔진

    특징:
    - 병렬 검색
    - 증분 인덱싱
    - 캐싱
    - 우선순위 기반 결과
    - 대규모 코드베이스 최적화
    """

    def __init__(
        self,
        root_path: str,
        max_workers: int = None,
        max_file_size: int = 10 * 1024 * 1024,  # 10MB
        cache_enabled: bool = True
    ):
        self.root_path = Path(root_path).resolve()
        self.max_workers = max_workers or min(32, (os.cpu_count() or 1) + 4)
        self.max_file_size = max_file_size
        self.cache_enabled = cache_enabled

        # 인덱스
        self._file_index: Dict[str, FileInfo] = {}
        self._symbol_index: Dict[str, List[Dict]] = {}
        self._content_cache: Dict[str, str] = {}
        self._index_lock = threading.Lock()

        # 캐시
        self._search_cache: Dict[str, SearchResult] = {}
        self._cache_max_size = 100

    def index_codebase(
        self,
        force: bool = False,
        on_progress: Optional[Callable[[int, int, str], None]] = None
    ) -> Dict[str, Any]:
        """
        코드베이스 인덱싱

        Args:
            force: 강제 재인덱싱
            on_progress: 진행 콜백 (current, total, file_path)

        Returns:
            인덱싱 통계
        """
        start_time = time.time()

        # 파일 목록 수집
        all_files = list(self._walk_files())
        total_files = len(all_files)

        indexed_count = 0
        symbol_count = 0
        errors = []

        def index_file(file_path: Path) -> Optional[FileInfo]:
            nonlocal symbol_count
            try:
                rel_path = str(file_path.relative_to(self.root_path))
                stat = file_path.stat()

                # 크기 체크
                if stat.st_size > self.max_file_size:
                    return None

                # 기존 인덱스 확인
                if not force and rel_path in self._file_index:
                    existing = self._file_index[rel_path]
                    if existing.modified_time == stat.st_mtime:
                        return existing

                file_info = FileInfo(
                    path=str(file_path),
                    relative_path=rel_path,
                    name=file_path.name,
                    extension=file_path.suffix,
                    size=stat.st_size,
                    modified_time=stat.st_mtime,
                    file_type=detect_file_type(rel_path),
                    priority=get_file_priority(rel_path)
                )

                # 심볼 추출 (Python, JavaScript만)
                if file_path.suffix in ('.py', '.js', '.ts', '.jsx', '.tsx'):
                    try:
                        content = file_path.read_text(encoding='utf-8', errors='ignore')
                        symbols = self._extract_symbols(content, file_path.suffix)
                        file_info.symbols = symbols
                        symbol_count += len(symbols)
                    except Exception:
                        pass

                return file_info

            except Exception as e:
                errors.append((str(file_path), str(e)))
                return None

        # 병렬 인덱싱
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(index_file, f): f for f in all_files}

            for i, future in enumerate(as_completed(futures)):
                file_path = futures[future]
                file_info = future.result()

                if file_info:
                    with self._index_lock:
                        self._file_index[file_info.relative_path] = file_info
                    indexed_count += 1

                if on_progress and i % 100 == 0:
                    on_progress(i + 1, total_files, str(file_path))

        # 심볼 인덱스 구축
        self._build_symbol_index()

        elapsed = time.time() - start_time

        return {
            "total_files": total_files,
            "indexed_files": indexed_count,
            "symbols": symbol_count,
            "errors": len(errors),
            "elapsed_time": elapsed
        }

    def search(
        self,
        query: str,
        mode: SearchMode = SearchMode.REGEX,
        file_pattern: str = None,
        file_types: List[FileType] = None,
        max_results: int = 100,
        context_lines: int = 2,
        case_sensitive: bool = False,
        whole_word: bool = False,
        include_hidden: bool = False
    ) -> SearchResult:
        """
        검색 실행

        Args:
            query: 검색 쿼리
            mode: 검색 모드
            file_pattern: 파일 패턴 (glob)
            file_types: 파일 타입 필터
            max_results: 최대 결과 수
            context_lines: 컨텍스트 라인 수
            case_sensitive: 대소문자 구분
            whole_word: 단어 단위 매칭
            include_hidden: 숨김 파일 포함

        Returns:
            SearchResult
        """
        start_time = time.time()

        # 캐시 확인
        cache_key = f"{query}:{mode.value}:{file_pattern}:{case_sensitive}:{whole_word}"
        if self.cache_enabled and cache_key in self._search_cache:
            cached = self._search_cache[cache_key]
            cached.elapsed_time = time.time() - start_time
            return cached

        # 검색 대상 파일 선택
        target_files = self._select_files(file_pattern, file_types, include_hidden)

        # 검색 실행
        if mode == SearchMode.SYMBOL:
            matches = self._search_symbols(query, case_sensitive)
        else:
            matches = self._search_content(
                query, target_files, mode,
                context_lines, case_sensitive, whole_word, max_results
            )

        # 결과 정렬 (우선순위, 점수)
        matches.sort(key=lambda m: (-self._file_index.get(m.file_path, FileInfo(
            path="", relative_path="", name="", extension="",
            size=0, modified_time=0, file_type=FileType.OTHER, priority=0
        )).priority, -m.score))

        # 결과 제한
        truncated = len(matches) > max_results
        matches = matches[:max_results]

        result = SearchResult(
            query=query,
            mode=mode,
            matches=matches,
            files_searched=len(target_files),
            files_matched=len(set(m.file_path for m in matches)),
            total_matches=len(matches),
            elapsed_time=time.time() - start_time,
            truncated=truncated
        )

        # 캐시 저장
        if self.cache_enabled:
            self._cache_result(cache_key, result)

        return result

    def find_files(
        self,
        pattern: str,
        file_types: List[FileType] = None,
        max_results: int = 100,
        sort_by: str = "priority"  # priority, modified, name
    ) -> List[FileInfo]:
        """
        파일 찾기 (glob 패턴)

        Args:
            pattern: glob 패턴
            file_types: 파일 타입 필터
            max_results: 최대 결과
            sort_by: 정렬 기준

        Returns:
            List[FileInfo]
        """
        results = []

        for rel_path, file_info in self._file_index.items():
            # 패턴 매칭
            if not fnmatch.fnmatch(file_info.name, pattern) and \
               not fnmatch.fnmatch(rel_path, pattern):
                continue

            # 타입 필터
            if file_types and file_info.file_type not in file_types:
                continue

            results.append(file_info)

        # 정렬
        if sort_by == "priority":
            results.sort(key=lambda f: (-f.priority, f.relative_path))
        elif sort_by == "modified":
            results.sort(key=lambda f: -f.modified_time)
        elif sort_by == "name":
            results.sort(key=lambda f: f.name.lower())

        return results[:max_results]

    def find_symbol(
        self,
        name: str,
        symbol_type: str = None,  # function, class, variable
        exact: bool = False
    ) -> List[Dict[str, Any]]:
        """
        심볼 찾기 (함수, 클래스, 변수)

        Args:
            name: 심볼 이름
            symbol_type: 심볼 타입
            exact: 정확히 일치

        Returns:
            List[Dict]
        """
        results = []
        name_lower = name.lower()

        for rel_path, file_info in self._file_index.items():
            for symbol in file_info.symbols:
                symbol_name = symbol.get("name", "")

                # 이름 매칭
                if exact:
                    if symbol_name != name:
                        continue
                else:
                    if name_lower not in symbol_name.lower():
                        continue

                # 타입 필터
                if symbol_type and symbol.get("type") != symbol_type:
                    continue

                results.append({
                    "file": rel_path,
                    "line": symbol.get("line", 0),
                    **symbol
                })

        # 정확 매치 우선
        results.sort(key=lambda s: (s["name"] != name, s.get("line", 0)))

        return results

    def find_references(
        self,
        symbol_name: str,
        definition_file: str = None
    ) -> List[SearchMatch]:
        """
        참조 찾기

        심볼이 사용된 모든 위치 찾기

        Args:
            symbol_name: 심볼 이름
            definition_file: 정의 파일 (제외)

        Returns:
            List[SearchMatch]
        """
        # 단어 단위 검색
        result = self.search(
            query=symbol_name,
            mode=SearchMode.REGEX,
            whole_word=True,
            max_results=500
        )

        # 정의 파일 제외
        if definition_file:
            result.matches = [m for m in result.matches if m.file_path != definition_file]

        return result.matches

    def find_definition(self, symbol_name: str) -> Optional[Dict[str, Any]]:
        """
        정의 찾기

        심볼이 정의된 위치 찾기

        Args:
            symbol_name: 심볼 이름

        Returns:
            정의 위치 또는 None
        """
        symbols = self.find_symbol(symbol_name, exact=True)

        if symbols:
            # 클래스/함수 정의 우선
            for symbol in symbols:
                if symbol.get("type") in ("class", "function"):
                    return symbol
            return symbols[0]

        return None

    # =========================================================================
    # Private Methods
    # =========================================================================

    def _walk_files(self) -> Generator[Path, None, None]:
        """파일 순회"""
        for root, dirs, files in os.walk(self.root_path):
            # 무시할 디렉토리 제거
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith('.')]

            for file in files:
                # 무시할 파일 체크
                if any(fnmatch.fnmatch(file, pattern) for pattern in IGNORE_FILES):
                    continue

                # 확장자 체크
                file_path = Path(root) / file
                if file_path.suffix.lower() not in SEARCHABLE_EXTENSIONS:
                    continue

                yield file_path

    def _select_files(
        self,
        file_pattern: str = None,
        file_types: List[FileType] = None,
        include_hidden: bool = False
    ) -> List[str]:
        """검색 대상 파일 선택"""
        results = []

        for rel_path, file_info in self._file_index.items():
            # 패턴 필터
            if file_pattern:
                if not fnmatch.fnmatch(file_info.name, file_pattern) and \
                   not fnmatch.fnmatch(rel_path, file_pattern):
                    continue

            # 타입 필터
            if file_types and file_info.file_type not in file_types:
                continue

            # 숨김 파일
            if not include_hidden and file_info.name.startswith('.'):
                continue

            results.append(rel_path)

        # 우선순위순 정렬
        results.sort(key=lambda p: -self._file_index[p].priority)

        return results

    def _search_content(
        self,
        query: str,
        target_files: List[str],
        mode: SearchMode,
        context_lines: int,
        case_sensitive: bool,
        whole_word: bool,
        max_results: int
    ) -> List[SearchMatch]:
        """내용 검색"""
        matches = []

        # 정규식 컴파일
        if mode == SearchMode.REGEX:
            pattern = query
        elif mode == SearchMode.EXACT:
            pattern = re.escape(query)
        elif mode == SearchMode.FUZZY:
            # 퍼지: 각 문자 사이에 .* 삽입
            pattern = '.*'.join(re.escape(c) for c in query)
        else:
            pattern = re.escape(query)

        if whole_word:
            pattern = r'\b' + pattern + r'\b'

        flags = 0 if case_sensitive else re.IGNORECASE

        try:
            regex = re.compile(pattern, flags)
        except re.error:
            return []

        def search_file(rel_path: str) -> List[SearchMatch]:
            file_matches = []
            file_info = self._file_index.get(rel_path)
            if not file_info:
                return file_matches

            try:
                file_path = self.root_path / rel_path
                content = file_path.read_text(encoding='utf-8', errors='ignore')
                lines = content.splitlines()

                for i, line in enumerate(lines):
                    for match in regex.finditer(line):
                        # 컨텍스트
                        ctx_before = lines[max(0, i - context_lines):i]
                        ctx_after = lines[i + 1:i + 1 + context_lines]

                        file_matches.append(SearchMatch(
                            file_path=rel_path,
                            line_number=i + 1,
                            column=match.start() + 1,
                            line_content=line,
                            match_text=match.group(),
                            context_before=ctx_before,
                            context_after=ctx_after,
                            file_type=file_info.file_type,
                            score=1.0 if mode == SearchMode.EXACT else 0.9
                        ))

                        if len(file_matches) >= max_results // 10:
                            break

            except Exception:
                pass

            return file_matches

        # 병렬 검색
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(search_file, f): f for f in target_files}

            for future in as_completed(futures):
                file_matches = future.result()
                matches.extend(file_matches)

                if len(matches) >= max_results:
                    break

        return matches

    def _search_symbols(self, query: str, case_sensitive: bool) -> List[SearchMatch]:
        """심볼 검색"""
        matches = []
        query_lower = query.lower() if not case_sensitive else query

        for rel_path, file_info in self._file_index.items():
            for symbol in file_info.symbols:
                name = symbol.get("name", "")
                name_check = name if case_sensitive else name.lower()

                if query_lower in name_check:
                    matches.append(SearchMatch(
                        file_path=rel_path,
                        line_number=symbol.get("line", 1),
                        column=1,
                        line_content=f"{symbol.get('type', 'symbol')}: {name}",
                        match_text=name,
                        file_type=file_info.file_type,
                        symbol_type=symbol.get("type"),
                        score=1.0 if name_check == query_lower else 0.8
                    ))

        return matches

    def _extract_symbols(self, content: str, extension: str) -> List[Dict[str, Any]]:
        """심볼 추출"""
        symbols = []

        if extension == '.py':
            symbols = self._extract_python_symbols(content)
        elif extension in ('.js', '.ts', '.jsx', '.tsx'):
            symbols = self._extract_js_symbols(content)

        return symbols

    def _extract_python_symbols(self, content: str) -> List[Dict[str, Any]]:
        """Python 심볼 추출"""
        symbols = []

        try:
            tree = ast.parse(content)

            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    symbols.append({
                        "type": "class",
                        "name": node.name,
                        "line": node.lineno,
                        "decorators": [self._get_decorator_name(d) for d in node.decorator_list]
                    })
                elif isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                    symbols.append({
                        "type": "function",
                        "name": node.name,
                        "line": node.lineno,
                        "async": isinstance(node, ast.AsyncFunctionDef),
                        "args": [a.arg for a in node.args.args],
                        "decorators": [self._get_decorator_name(d) for d in node.decorator_list]
                    })
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            # 상수 (대문자)
                            if target.id.isupper():
                                symbols.append({
                                    "type": "constant",
                                    "name": target.id,
                                    "line": node.lineno
                                })

        except SyntaxError:
            pass

        return symbols

    def _extract_js_symbols(self, content: str) -> List[Dict[str, Any]]:
        """JavaScript/TypeScript 심볼 추출 (정규식 기반)"""
        symbols = []

        # 클래스
        for match in re.finditer(r'class\s+(\w+)', content):
            line = content[:match.start()].count('\n') + 1
            symbols.append({
                "type": "class",
                "name": match.group(1),
                "line": line
            })

        # 함수
        patterns = [
            r'function\s+(\w+)\s*\(',
            r'(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(',
            r'(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?function',
            r'(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>',
        ]

        for pattern in patterns:
            for match in re.finditer(pattern, content):
                line = content[:match.start()].count('\n') + 1
                symbols.append({
                    "type": "function",
                    "name": match.group(1),
                    "line": line
                })

        return symbols

    def _get_decorator_name(self, decorator) -> str:
        """데코레이터 이름 추출"""
        if isinstance(decorator, ast.Name):
            return decorator.id
        elif isinstance(decorator, ast.Attribute):
            return decorator.attr
        elif isinstance(decorator, ast.Call):
            return self._get_decorator_name(decorator.func)
        return ""

    def _build_symbol_index(self):
        """심볼 인덱스 구축"""
        self._symbol_index.clear()

        for rel_path, file_info in self._file_index.items():
            for symbol in file_info.symbols:
                name = symbol.get("name", "")
                if name:
                    if name not in self._symbol_index:
                        self._symbol_index[name] = []
                    self._symbol_index[name].append({
                        "file": rel_path,
                        **symbol
                    })

    def _cache_result(self, key: str, result: SearchResult):
        """결과 캐싱"""
        if len(self._search_cache) >= self._cache_max_size:
            # LRU 방식으로 오래된 것 제거
            oldest = next(iter(self._search_cache))
            del self._search_cache[oldest]

        self._search_cache[key] = result

    def clear_cache(self):
        """캐시 초기화"""
        self._search_cache.clear()
        self._content_cache.clear()

    def get_stats(self) -> Dict[str, Any]:
        """통계"""
        return {
            "indexed_files": len(self._file_index),
            "total_symbols": sum(len(f.symbols) for f in self._file_index.values()),
            "cache_size": len(self._search_cache),
            "file_types": {
                ft.value: sum(1 for f in self._file_index.values() if f.file_type == ft)
                for ft in FileType
            }
        }


# =============================================================================
# Quick Search Functions
# =============================================================================

_default_engine: Optional[SearchEngine] = None


def get_engine(root_path: str = ".") -> SearchEngine:
    """기본 검색 엔진"""
    global _default_engine
    if _default_engine is None or str(_default_engine.root_path) != str(Path(root_path).resolve()):
        _default_engine = SearchEngine(root_path)
    return _default_engine


def quick_search(query: str, root_path: str = ".", **kwargs) -> SearchResult:
    """빠른 검색"""
    engine = get_engine(root_path)
    if not engine._file_index:
        engine.index_codebase()
    return engine.search(query, **kwargs)


def quick_find(pattern: str, root_path: str = ".") -> List[FileInfo]:
    """빠른 파일 찾기"""
    engine = get_engine(root_path)
    if not engine._file_index:
        engine.index_codebase()
    return engine.find_files(pattern)


def quick_symbol(name: str, root_path: str = ".") -> List[Dict]:
    """빠른 심볼 찾기"""
    engine = get_engine(root_path)
    if not engine._file_index:
        engine.index_codebase()
    return engine.find_symbol(name)
