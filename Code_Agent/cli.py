#!/usr/bin/env python3
"""
MAEUM_CODE CLI

Claude Code 스타일:
- 디렉토리 자동 스캔
- AI가 코드 작성
- 파일 수정 전 허락 받기 (위험도 기반)
- AI 자율 파일 탐색
- 진행 표시
- 의미론적 분석
"""

import os
import sys
import re
import ast
import threading
import time
import subprocess
import fnmatch
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any, Set
from datetime import datetime

from .code_writer import AIServerClient
from .classifier import ActionClassifier, PathJudge, Clarifier
from .context_store import ContextStore
from .ARCHITECTURE import ActionType, Phase, Tolerance, FileRole


# =============================================================================
# 의미론적 분석기 (Semantic Analyzer)
# =============================================================================
class SemanticAnalyzer:
    """코드의 의미론적 분석 - 파일명, 변수, 함수, 클래스 등"""

    # 네이밍 컨벤션 패턴
    PATTERNS = {
        'snake_case': re.compile(r'^[a-z][a-z0-9]*(_[a-z0-9]+)*$'),
        'camelCase': re.compile(r'^[a-z][a-zA-Z0-9]*$'),
        'PascalCase': re.compile(r'^[A-Z][a-zA-Z0-9]*$'),
        'SCREAMING_SNAKE': re.compile(r'^[A-Z][A-Z0-9]*(_[A-Z0-9]+)*$'),
        'kebab-case': re.compile(r'^[a-z][a-z0-9]*(-[a-z0-9]+)*$'),
    }

    # 의미 있는 접두사/접미사
    PREFIXES = {
        'is_': '불리언 체크',
        'has_': '소유 여부',
        'can_': '가능 여부',
        'should_': '권장 여부',
        'get_': '값 획득',
        'set_': '값 설정',
        'create_': '생성',
        'delete_': '삭제',
        'update_': '수정',
        'fetch_': '데이터 가져오기',
        'load_': '로드',
        'save_': '저장',
        'parse_': '파싱',
        'validate_': '검증',
        'handle_': '핸들러',
        'on_': '이벤트 핸들러',
        '_': '프라이빗',
        '__': '매직/던더',
    }

    SUFFIXES = {
        '_id': '식별자',
        '_list': '목록',
        '_dict': '딕셔너리',
        '_map': '매핑',
        '_set': '집합',
        '_count': '개수',
        '_index': '인덱스',
        '_path': '경로',
        '_url': 'URL',
        '_name': '이름',
        '_type': '타입',
        '_config': '설정',
        '_handler': '핸들러',
        '_callback': '콜백',
        '_factory': '팩토리',
        '_manager': '관리자',
        '_service': '서비스',
        '_controller': '컨트롤러',
        '_repository': '저장소',
        '_model': '모델',
        '_view': '뷰',
        '_test': '테스트',
        '_spec': '스펙',
    }

    # 파일 역할 추론
    FILE_PATTERNS = {
        r'test_.*\.py$': ('테스트', 'test'),
        r'.*_test\.py$': ('테스트', 'test'),
        r'.*\.test\.[jt]sx?$': ('테스트', 'test'),
        r'.*\.spec\.[jt]sx?$': ('스펙 테스트', 'test'),
        r'__init__\.py$': ('패키지 초기화', 'init'),
        r'main\.py$': ('진입점', 'entry'),
        r'index\.[jt]sx?$': ('진입점', 'entry'),
        r'app\.[jt]sx?$': ('앱 메인', 'entry'),
        r'config.*\.(py|js|ts|json|ya?ml)$': ('설정', 'config'),
        r'settings.*\.py$': ('설정', 'config'),
        r'\.env.*$': ('환경변수', 'env'),
        r'requirements.*\.txt$': ('의존성', 'deps'),
        r'package\.json$': ('패키지 설정', 'deps'),
        r'Dockerfile$': ('도커 설정', 'docker'),
        r'docker-compose.*\.ya?ml$': ('도커 컴포즈', 'docker'),
        r'README.*\.md$': ('문서', 'docs'),
        r'.*\.md$': ('문서', 'docs'),
        r'models?\.py$': ('데이터 모델', 'model'),
        r'schemas?\.py$': ('스키마', 'schema'),
        r'views?\.py$': ('뷰', 'view'),
        r'controllers?\.py$': ('컨트롤러', 'controller'),
        r'routes?\.py$': ('라우트', 'route'),
        r'api\.py$': ('API', 'api'),
        r'utils?\.py$': ('유틸리티', 'util'),
        r'helpers?\.py$': ('헬퍼', 'util'),
        r'constants?\.py$': ('상수', 'const'),
        r'types?\.py$': ('타입 정의', 'type'),
        r'interfaces?\.ts$': ('인터페이스', 'type'),
        r'hooks?\.tsx?$': ('React 훅', 'hook'),
        r'components?/.*\.tsx?$': ('React 컴포넌트', 'component'),
        r'services?\.py$': ('서비스', 'service'),
        r'repositories?\.py$': ('저장소', 'repository'),
        r'migrations?/.*\.py$': ('DB 마이그레이션', 'migration'),
    }

    @classmethod
    def analyze_file(cls, file_path: str, content: str = None) -> Dict[str, Any]:
        """파일 전체 의미론적 분석"""
        result = {
            'path': file_path,
            'filename': Path(file_path).name,
            'role': cls.infer_file_role(file_path),
            'naming_convention': None,
            'symbols': {
                'classes': [],
                'functions': [],
                'variables': [],
                'imports': [],
                'constants': [],
            },
            'metrics': {
                'lines': 0,
                'classes_count': 0,
                'functions_count': 0,
                'complexity_hint': 'low',
            },
            'suggestions': [],
        }

        if content:
            result['metrics']['lines'] = len(content.splitlines())

            # Python 파일 분석
            if file_path.endswith('.py'):
                cls._analyze_python(content, result)
            # JavaScript/TypeScript 분석
            elif file_path.endswith(('.js', '.jsx', '.ts', '.tsx')):
                cls._analyze_javascript(content, result)

        return result

    @classmethod
    def infer_file_role(cls, file_path: str) -> Tuple[str, str]:
        """파일 역할 추론"""
        filename = Path(file_path).name
        full_path = file_path.lower()

        for pattern, (desc, role) in cls.FILE_PATTERNS.items():
            if re.search(pattern, full_path, re.IGNORECASE):
                return (desc, role)

        # 확장자 기반 기본 추론
        ext = Path(file_path).suffix.lower()
        ext_roles = {
            '.py': ('Python 소스', 'source'),
            '.js': ('JavaScript 소스', 'source'),
            '.ts': ('TypeScript 소스', 'source'),
            '.jsx': ('React 컴포넌트', 'component'),
            '.tsx': ('React TSX 컴포넌트', 'component'),
            '.css': ('스타일시트', 'style'),
            '.scss': ('SCSS 스타일', 'style'),
            '.html': ('HTML 문서', 'markup'),
            '.json': ('JSON 데이터', 'data'),
            '.yaml': ('YAML 설정', 'config'),
            '.yml': ('YAML 설정', 'config'),
            '.sql': ('SQL 쿼리', 'query'),
            '.sh': ('셸 스크립트', 'script'),
        }
        return ext_roles.get(ext, ('일반 파일', 'other'))

    @classmethod
    def analyze_name(cls, name: str) -> Dict[str, Any]:
        """이름 의미 분석"""
        result = {
            'name': name,
            'convention': cls.detect_convention(name),
            'parts': cls.split_name(name),
            'prefix_meaning': None,
            'suffix_meaning': None,
            'inferred_type': None,
            'suggestions': [],
        }

        # 접두사 분석
        for prefix, meaning in cls.PREFIXES.items():
            if name.startswith(prefix):
                result['prefix_meaning'] = meaning
                break

        # 접미사 분석
        for suffix, meaning in cls.SUFFIXES.items():
            if name.endswith(suffix):
                result['suffix_meaning'] = meaning
                break

        # 타입 추론
        result['inferred_type'] = cls._infer_type_from_name(name)

        return result

    @classmethod
    def detect_convention(cls, name: str) -> str:
        """네이밍 컨벤션 감지"""
        for conv_name, pattern in cls.PATTERNS.items():
            if pattern.match(name):
                return conv_name
        return 'mixed'

    @classmethod
    def split_name(cls, name: str) -> List[str]:
        """이름을 단어로 분리"""
        # snake_case, SCREAMING_SNAKE
        if '_' in name:
            return [p.lower() for p in name.split('_') if p]

        # kebab-case
        if '-' in name:
            return [p.lower() for p in name.split('-') if p]

        # camelCase, PascalCase
        parts = re.findall(r'[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|\W|$)|\d+', name)
        return [p.lower() for p in parts]

    @classmethod
    def _infer_type_from_name(cls, name: str) -> str:
        """이름에서 타입 추론"""
        name_lower = name.lower()

        if name_lower.startswith(('is_', 'has_', 'can_', 'should_', 'was_', 'will_')):
            return 'bool'
        if name_lower.endswith(('_count', '_num', '_index', '_size', '_length', '_id')):
            return 'int'
        if name_lower.endswith(('_list', '_items', '_array', '_collection')):
            return 'list'
        if name_lower.endswith(('_dict', '_map', '_mapping', '_hash')):
            return 'dict'
        if name_lower.endswith(('_set',)):
            return 'set'
        if name_lower.endswith(('_str', '_name', '_text', '_message', '_path', '_url')):
            return 'str'
        if name_lower.endswith(('_date', '_time', '_timestamp', '_at')):
            return 'datetime'
        if name_lower.endswith(('_callback', '_handler', '_func', '_fn')):
            return 'callable'

        return 'unknown'

    @classmethod
    def _analyze_python(cls, content: str, result: Dict):
        """Python 코드 분석"""
        try:
            tree = ast.parse(content)

            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    cls_info = {
                        'name': node.name,
                        'line': node.lineno,
                        'analysis': cls.analyze_name(node.name),
                        'methods': [],
                        'bases': [cls._get_name(b) for b in node.bases],
                    }
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef):
                            cls_info['methods'].append(item.name)
                    result['symbols']['classes'].append(cls_info)

                elif isinstance(node, ast.FunctionDef) and not isinstance(node, ast.AsyncFunctionDef):
                    if not any(node.name in c.get('methods', []) for c in result['symbols']['classes']):
                        func_info = {
                            'name': node.name,
                            'line': node.lineno,
                            'analysis': cls.analyze_name(node.name),
                            'args': [a.arg for a in node.args.args],
                            'decorators': [cls._get_name(d) for d in node.decorator_list],
                        }
                        result['symbols']['functions'].append(func_info)

                elif isinstance(node, ast.AsyncFunctionDef):
                    func_info = {
                        'name': node.name,
                        'line': node.lineno,
                        'analysis': cls.analyze_name(node.name),
                        'args': [a.arg for a in node.args.args],
                        'async': True,
                    }
                    result['symbols']['functions'].append(func_info)

                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        result['symbols']['imports'].append(alias.name)

                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ''
                    for alias in node.names:
                        result['symbols']['imports'].append(f"{module}.{alias.name}")

                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            name = target.id
                            # 상수 감지 (대문자)
                            if cls.PATTERNS['SCREAMING_SNAKE'].match(name):
                                result['symbols']['constants'].append({
                                    'name': name,
                                    'line': node.lineno,
                                })
                            else:
                                result['symbols']['variables'].append({
                                    'name': name,
                                    'line': node.lineno,
                                    'analysis': cls.analyze_name(name),
                                })

            # 메트릭 업데이트
            result['metrics']['classes_count'] = len(result['symbols']['classes'])
            result['metrics']['functions_count'] = len(result['symbols']['functions'])

            # 복잡도 힌트
            total = result['metrics']['classes_count'] + result['metrics']['functions_count']
            if total > 20:
                result['metrics']['complexity_hint'] = 'high'
            elif total > 10:
                result['metrics']['complexity_hint'] = 'medium'

        except SyntaxError:
            result['suggestions'].append('구문 오류가 있습니다')

    @classmethod
    def _analyze_javascript(cls, content: str, result: Dict):
        """JavaScript/TypeScript 기본 분석 (정규식 기반)"""
        # 클래스
        for match in re.finditer(r'class\s+(\w+)', content):
            result['symbols']['classes'].append({
                'name': match.group(1),
                'analysis': cls.analyze_name(match.group(1)),
            })

        # 함수
        for match in re.finditer(r'(?:function|const|let|var)\s+(\w+)\s*(?:=\s*(?:async\s*)?\(|=\s*(?:async\s+)?function|\()', content):
            result['symbols']['functions'].append({
                'name': match.group(1),
                'analysis': cls.analyze_name(match.group(1)),
            })

        # 화살표 함수
        for match in re.finditer(r'(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>', content):
            name = match.group(1)
            if not any(f['name'] == name for f in result['symbols']['functions']):
                result['symbols']['functions'].append({
                    'name': name,
                    'analysis': cls.analyze_name(name),
                })

        # import
        for match in re.finditer(r'import\s+.*?from\s+[\'"]([^\'"]+)[\'"]', content):
            result['symbols']['imports'].append(match.group(1))

        # 메트릭
        result['metrics']['classes_count'] = len(result['symbols']['classes'])
        result['metrics']['functions_count'] = len(result['symbols']['functions'])

    @classmethod
    def _get_name(cls, node) -> str:
        """AST 노드에서 이름 추출"""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{cls._get_name(node.value)}.{node.attr}"
        elif isinstance(node, ast.Call):
            return cls._get_name(node.func)
        return str(node)

    @classmethod
    def get_project_summary(cls, root_path: Path, files_info: List[Dict]) -> Dict:
        """프로젝트 전체 요약"""
        summary = {
            'total_files': len(files_info),
            'by_role': {},
            'naming_consistency': {},
            'all_classes': [],
            'all_functions': [],
            'tech_stack': set(),
        }

        for info in files_info:
            role = info.get('role', ('unknown', 'unknown'))[1]
            summary['by_role'][role] = summary['by_role'].get(role, 0) + 1

            for cls_info in info.get('symbols', {}).get('classes', []):
                summary['all_classes'].append(cls_info['name'])

            for func_info in info.get('symbols', {}).get('functions', []):
                summary['all_functions'].append(func_info['name'])

        # 기술 스택 추론
        summary['tech_stack'] = list(summary['tech_stack'])

        return summary


# =============================================================================
# 터미널 반응형 UI (Terminal Responsive)
# =============================================================================
class TerminalUI:
    """터미널 너비에 맞춘 반응형 UI"""

    # 브레이크포인트
    NARROW = 60    # 좁은 터미널 (모바일/분할)
    MEDIUM = 100   # 중간
    WIDE = 140     # 넓은 터미널

    # ANSI
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    GREEN = "\033[32m"
    RED = "\033[31m"
    YELLOW = "\033[33m"
    CYAN = "\033[36m"
    MAGENTA = "\033[35m"
    BLUE = "\033[34m"

    @classmethod
    def get_width(cls) -> int:
        """터미널 너비 가져오기"""
        try:
            import shutil
            return shutil.get_terminal_size().columns
        except:
            return 80

    @classmethod
    def get_mode(cls) -> str:
        """현재 모드 (narrow/medium/wide)"""
        w = cls.get_width()
        if w < cls.NARROW:
            return 'narrow'
        elif w < cls.MEDIUM:
            return 'medium'
        else:
            return 'wide'

    @classmethod
    def truncate(cls, text: str, max_len: int = None, suffix: str = "...") -> str:
        """텍스트 자르기 (터미널 너비 기준)"""
        if max_len is None:
            max_len = cls.get_width() - 10
        if len(text) <= max_len:
            return text
        return text[:max_len - len(suffix)] + suffix

    @classmethod
    def box(cls, title: str, content: list, style: str = "single") -> str:
        """반응형 박스 그리기"""
        width = cls.get_width()
        mode = cls.get_mode()

        # 박스 문자
        if mode == 'narrow':
            # 좁은 모드: 최소한의 장식
            lines = [f"{cls.DIM}─ {title} ─{cls.RESET}"]
            for line in content:
                lines.append(cls.truncate(f"  {line}", width - 2))
            lines.append(f"{cls.DIM}{'─' * min(width - 4, 30)}{cls.RESET}")
        else:
            # 일반/넓은 모드: 풀 박스
            box_width = min(width - 4, 60)
            top = f"┌─ {title} " + "─" * (box_width - len(title) - 4) + "┐"
            bot = "└" + "─" * (box_width - 2) + "┘"

            lines = [f"{cls.DIM}{top}{cls.RESET}"]
            for line in content:
                truncated = cls.truncate(line, box_width - 4)
                lines.append(f"{cls.DIM}│{cls.RESET} {truncated}")
            lines.append(f"{cls.DIM}{bot}{cls.RESET}")

        return "\n".join(lines)

    @classmethod
    def progress_bar(cls, current: int, total: int, message: str = "") -> str:
        """반응형 진행률 바"""
        width = cls.get_width()
        mode = cls.get_mode()

        percent = int((current / total) * 100) if total > 0 else 0

        if mode == 'narrow':
            # 좁은 모드: 숫자만
            return f"{percent}% {cls.truncate(message, 20)}"
        elif mode == 'medium':
            # 중간: 짧은 바
            bar_width = 15
            filled = int(bar_width * current / total) if total > 0 else 0
            bar = "━" * filled + "░" * (bar_width - filled)
            return f"{cls.CYAN}{bar}{cls.RESET} {percent}% {cls.truncate(message, 30)}"
        else:
            # 넓은 모드: 풀 바
            bar_width = 25
            filled = int(bar_width * current / total) if total > 0 else 0
            bar = "━" * filled + "░" * (bar_width - filled)
            return f"{cls.CYAN}{bar}{cls.RESET} {percent:3d}% │ {message}"

    @classmethod
    def status_bar(cls, items: list) -> str:
        """반응형 상태바"""
        width = cls.get_width()
        mode = cls.get_mode()

        if mode == 'narrow':
            # 좁은 모드: 핵심만
            return f"{cls.DIM}│{cls.RESET}".join(items[:3])
        elif mode == 'medium':
            return f" {cls.DIM}│{cls.RESET} ".join(items[:5])
        else:
            return f"  {cls.DIM}│{cls.RESET}  ".join(items)

    @classmethod
    def columns(cls, items: list, min_col_width: int = 20) -> str:
        """반응형 컬럼 레이아웃"""
        width = cls.get_width()
        cols = max(1, width // min_col_width)

        lines = []
        for i in range(0, len(items), cols):
            row = items[i:i + cols]
            formatted = [cls.truncate(item, min_col_width - 2).ljust(min_col_width) for item in row]
            lines.append("".join(formatted))

        return "\n".join(lines)

    @classmethod
    def divider(cls, char: str = "─", label: str = None) -> str:
        """반응형 구분선"""
        width = cls.get_width()
        line_width = min(width - 4, 60)

        if label:
            left = (line_width - len(label) - 2) // 2
            right = line_width - left - len(label) - 2
            return f"{cls.DIM}{char * left} {label} {char * right}{cls.RESET}"
        return f"{cls.DIM}{char * line_width}{cls.RESET}"

    @classmethod
    def code_block(cls, code: str, lang: str = "", path: str = "") -> str:
        """반응형 코드 블록"""
        width = cls.get_width()
        mode = cls.get_mode()
        lines = code.split('\n')

        # 코드 줄 너비
        code_width = width - 8  # 여백

        result = []

        # 헤더
        if mode == 'narrow':
            header = f"{cls.DIM}─ {lang}"
            if path:
                header += f" → {cls.truncate(path, 20)}"
            result.append(header + cls.RESET)
        else:
            if path:
                result.append(f"{cls.DIM}┌─ {lang} → {path}{cls.RESET}")
            else:
                result.append(f"{cls.DIM}┌─ {lang or 'code'}{cls.RESET}")

        # 코드 라인
        max_lines = 30 if mode != 'narrow' else 15
        for i, line in enumerate(lines[:max_lines]):
            truncated = cls.truncate(line, code_width)
            if mode == 'narrow':
                result.append(f"  {truncated}")
            else:
                result.append(f"{cls.DIM}│{cls.RESET} {truncated}")

        if len(lines) > max_lines:
            result.append(f"{cls.DIM}│ ... (+{len(lines) - max_lines} lines){cls.RESET}")

        # 푸터
        if mode != 'narrow':
            result.append(f"{cls.DIM}└{'─' * min(40, width - 6)}{cls.RESET}")

        return "\n".join(result)

    @classmethod
    def diff(cls, old_lines: list, new_lines: list, max_show: int = None) -> str:
        """반응형 diff 표시"""
        width = cls.get_width()
        mode = cls.get_mode()

        if max_show is None:
            max_show = 20 if mode != 'narrow' else 10

        import difflib
        diff = list(difflib.unified_diff(old_lines, new_lines, lineterm='', n=2))

        result = []
        shown = 0

        for line in diff[2:]:  # 헤더 스킵
            if shown >= max_show:
                result.append(f"{cls.DIM}... (more changes){cls.RESET}")
                break

            truncated = cls.truncate(line, width - 6)

            if line.startswith('+'):
                result.append(f"{cls.GREEN}{truncated}{cls.RESET}")
                shown += 1
            elif line.startswith('-'):
                result.append(f"{cls.RED}{truncated}{cls.RESET}")
                shown += 1
            elif line.startswith('@'):
                result.append(f"{cls.BLUE}{truncated}{cls.RESET}")

        return "\n".join(result)


# =============================================================================
# 터미널 마크다운 렌더러
# =============================================================================
class TerminalMarkdown:
    """터미널용 마크다운 렌더러"""

    # ANSI 색상 코드
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"

    # 색상
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    GRAY = "\033[90m"

    # 배경
    BG_GRAY = "\033[100m"

    @classmethod
    def render(cls, text: str) -> str:
        """마크다운을 터미널 출력으로 변환"""
        if not text:
            return ""

        lines = text.split('\n')
        result = []
        in_code_block = False
        code_lang = ""

        for line in lines:
            # 코드 블록 시작/끝
            if line.startswith('```'):
                if not in_code_block:
                    in_code_block = True
                    code_lang = line[3:].strip()
                    if ':' in code_lang:
                        # ```python:path/to/file.py 형식
                        lang, path = code_lang.split(':', 1)
                        result.append(f"{cls.DIM}┌─ {lang} → {path}{cls.RESET}")
                    elif code_lang:
                        result.append(f"{cls.DIM}┌─ {code_lang}{cls.RESET}")
                    else:
                        result.append(f"{cls.DIM}┌─ code{cls.RESET}")
                else:
                    in_code_block = False
                    code_lang = ""
                    result.append(f"{cls.DIM}└─{cls.RESET}")
                continue

            # 코드 블록 내부
            if in_code_block:
                result.append(f"{cls.GRAY}│{cls.RESET} {line}")
                continue

            # 헤더
            if line.startswith('### '):
                result.append(f"{cls.BOLD}{cls.CYAN}   {line[4:]}{cls.RESET}")
                continue
            if line.startswith('## '):
                result.append(f"{cls.BOLD}{cls.BLUE}  {line[3:]}{cls.RESET}")
                continue
            if line.startswith('# '):
                result.append(f"{cls.BOLD}{cls.MAGENTA} {line[2:]}{cls.RESET}")
                result.append(f"{cls.DIM}{'─' * 50}{cls.RESET}")
                continue

            # 리스트
            if line.strip().startswith('- '):
                indent = len(line) - len(line.lstrip())
                content = line.strip()[2:]
                result.append(f"{' ' * indent}{cls.CYAN}•{cls.RESET} {cls._inline(content)}")
                continue
            if re.match(r'^\s*\d+\.\s', line):
                match = re.match(r'^(\s*)(\d+)\.\s(.*)$', line)
                if match:
                    indent, num, content = match.groups()
                    result.append(f"{indent}{cls.CYAN}{num}.{cls.RESET} {cls._inline(content)}")
                    continue

            # 수평선
            if line.strip() in ['---', '***', '___']:
                result.append(f"{cls.DIM}{'─' * 50}{cls.RESET}")
                continue

            # 인용
            if line.startswith('> '):
                result.append(f"{cls.DIM}│{cls.RESET} {cls.ITALIC}{line[2:]}{cls.RESET}")
                continue

            # 일반 텍스트 (인라인 스타일 적용)
            result.append(cls._inline(line))

        return '\n'.join(result)

    @classmethod
    def _inline(cls, text: str) -> str:
        """인라인 마크다운 처리"""
        # 굵게 **text** 또는 __text__
        text = re.sub(r'\*\*(.+?)\*\*', f'{cls.BOLD}\\1{cls.RESET}', text)
        text = re.sub(r'__(.+?)__', f'{cls.BOLD}\\1{cls.RESET}', text)

        # 기울임 *text* 또는 _text_
        text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', f'{cls.ITALIC}\\1{cls.RESET}', text)
        text = re.sub(r'(?<!_)_(?!_)(.+?)(?<!_)_(?!_)', f'{cls.ITALIC}\\1{cls.RESET}', text)

        # 인라인 코드 `code`
        text = re.sub(r'`([^`]+)`', f'{cls.BG_GRAY}{cls.WHITE}\\1{cls.RESET}', text)

        # 링크 [text](url) - 텍스트만 표시
        text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', f'{cls.UNDERLINE}{cls.BLUE}\\1{cls.RESET}', text)

        return text


# =============================================================================
# 위험도 분류
# =============================================================================
class RiskLevel:
    """파일 변경 위험도"""
    LOW = "low"        # 자동 적용
    MEDIUM = "medium"  # 간단히 묻기
    HIGH = "high"      # 전체 diff 보여주고 묻기

def classify_risk(file_path: str, is_new: bool, tolerance: Tolerance) -> str:
    """파일 변경 위험도 판정"""
    path_lower = file_path.lower()

    # 항상 HIGH
    dangerous_patterns = [
        'password', 'secret', 'credential', 'key', 'token',
        '.env', 'config', 'setting', 'auth', 'permission',
        'database', 'migration', 'schema', 'main.py', '__init__.py',
        'package.json', 'requirements.txt', 'setup.py', 'pyproject.toml'
    ]
    for pattern in dangerous_patterns:
        if pattern in path_lower:
            return RiskLevel.HIGH

    # 새 파일 생성
    if is_new:
        if tolerance == Tolerance.HIGH:
            return RiskLevel.LOW
        elif tolerance == Tolerance.MEDIUM:
            return RiskLevel.MEDIUM
        else:
            return RiskLevel.HIGH

    # 기존 파일 수정
    # core/service 파일은 MEDIUM 이상
    core_patterns = ['service', 'usecase', 'core', 'domain', 'model']
    for pattern in core_patterns:
        if pattern in path_lower:
            if tolerance == Tolerance.HIGH:
                return RiskLevel.MEDIUM
            else:
                return RiskLevel.HIGH

    # test 파일은 보통 안전
    if 'test' in path_lower or 'spec' in path_lower:
        if tolerance == Tolerance.HIGH:
            return RiskLevel.LOW
        else:
            return RiskLevel.MEDIUM

    # 기본값
    if tolerance == Tolerance.HIGH:
        return RiskLevel.MEDIUM
    elif tolerance == Tolerance.MEDIUM:
        return RiskLevel.MEDIUM
    else:
        return RiskLevel.HIGH


# =============================================================================
# 상태바
# =============================================================================
class StatusBar:
    """상단 상태바 - 반응형"""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    GREEN = "\033[32m"
    RED = "\033[31m"
    YELLOW = "\033[33m"
    CYAN = "\033[36m"
    BG_DARK = "\033[48;5;236m"

    @classmethod
    def render(cls, project: str, ai_online: bool, phase: str, todo_count: int,
               pending_count: int = 0, iteration: int = 0, max_iter: int = 48) -> str:
        """상태바 문자열 생성 - 반응형"""
        mode = TerminalUI.get_mode()
        width = TerminalUI.get_width()

        # AI 상태
        if ai_online:
            ai_status = f"{cls.GREEN}●{cls.RESET}" if mode == 'narrow' else f"{cls.GREEN}● AI{cls.RESET}"
        else:
            ai_status = f"{cls.RED}○{cls.RESET}" if mode == 'narrow' else f"{cls.RED}○ AI{cls.RESET}"

        # 프로젝트명
        max_name_len = 8 if mode == 'narrow' else (12 if mode == 'medium' else 20)
        proj_name = Path(project).name[:max_name_len]

        # Phase 색상
        phase_colors = {
            "MVP": cls.GREEN,
            "EXPERIMENT": cls.YELLOW,
            "REFACTOR": cls.CYAN,
            "STABILIZE": cls.RED
        }
        phase_color = phase_colors.get(phase, cls.RESET)

        if mode == 'narrow':
            # 좁은 모드: 핵심만
            parts = [f"📁{proj_name}", ai_status]
            if iteration > 0:
                parts.append(f"{iteration}/{max_iter}")
            return " ".join(parts)

        elif mode == 'medium':
            # 중간 모드
            parts = [f"📁 {proj_name}", ai_status, f"{phase_color}{phase}{cls.RESET}"]
            if todo_count > 0:
                parts.append(f"📋{pending_count}/{todo_count}")
            if iteration > 0:
                parts.append(f"🔍{iteration}/{max_iter}")
            return f"{cls.DIM}│{cls.RESET}".join(parts)

        else:
            # 넓은 모드: 풀 정보
            parts = [
                f"{cls.BG_DARK} 📁 {proj_name} {cls.RESET}",
                ai_status,
                f"{phase_color}{phase}{cls.RESET}",
            ]
            if todo_count > 0:
                parts.append(f"📋 {pending_count}/{todo_count}")
            if iteration > 0:
                parts.append(f"🔍 {iteration}/{max_iter}")

            return f" {cls.DIM}│{cls.RESET} ".join(parts)

    @classmethod
    def print(cls, project: str, ai_online: bool, phase: str, todo_count: int,
              pending_count: int = 0, iteration: int = 0):
        """상태바 출력"""
        bar = cls.render(project, ai_online, phase, todo_count, pending_count, iteration)
        width = TerminalUI.get_width()
        padding = max(0, width - len(bar) - 5)
        print(f"\r{bar}{' ' * padding}\r", end="", flush=True)


# =============================================================================
# 진행률 바 + ESC 중단
# =============================================================================
class ProgressBar:
    """진행률 바 with ESC 중단 기능"""

    RESET = "\033[0m"
    CYAN = "\033[36m"
    DIM = "\033[2m"
    YELLOW = "\033[33m"

    def __init__(self, message: str = "", total_steps: int = 48):
        self.message = message
        self.total_steps = total_steps
        self.current_step = 0
        self.running = False
        self.aborted = False
        self.thread = None
        self.key_thread = None
        self.spinner_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.start_time = 0

    def start(self, step: int = 0):
        self.current_step = step
        self.running = True
        self.aborted = False
        self.start_time = time.time()
        self.thread = threading.Thread(target=self._animate, daemon=True)
        self.thread.start()
        # ESC 키 감지 스레드
        self.key_thread = threading.Thread(target=self._watch_esc, daemon=True)
        self.key_thread.start()

    def _watch_esc(self):
        """ESC 키 감지 (Unix/macOS)"""
        try:
            import sys
            import termios
            import tty
            import select

            old_settings = termios.tcgetattr(sys.stdin)
            try:
                tty.setraw(sys.stdin.fileno())
                while self.running:
                    if select.select([sys.stdin], [], [], 0.1)[0]:
                        ch = sys.stdin.read(1)
                        if ch == '\x1b':  # ESC
                            self.aborted = True
                            self.running = False
                            break
            finally:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        except:
            # Windows나 다른 환경에서는 무시
            pass

    def _animate(self):
        """진행률 애니메이션 - 반응형"""
        idx = 0
        while self.running:
            spinner = self.spinner_frames[idx % len(self.spinner_frames)]
            elapsed = time.time() - self.start_time

            # 터미널 너비에 따른 반응형 표시
            width = TerminalUI.get_width()
            mode = TerminalUI.get_mode()

            # 경과 시간
            mins, secs = divmod(int(elapsed), 60)
            time_str = f"{mins:02d}:{secs:02d}"

            if self.total_steps > 0:
                progress = self.current_step / self.total_steps
                percent = int(progress * 100)

                if mode == 'narrow':
                    # 좁은 모드: 최소 정보
                    msg = TerminalUI.truncate(self.message, 15)
                    line = f"\r  {spinner} {percent}% {msg}"
                elif mode == 'medium':
                    # 중간 모드: 짧은 바
                    bar_width = 12
                    filled = int(bar_width * progress)
                    bar = "━" * filled + "░" * (bar_width - filled)
                    msg = TerminalUI.truncate(self.message, 25)
                    line = f"\r  {spinner} {self.CYAN}{bar}{self.RESET} {percent}% {msg} {self.DIM}{time_str}{self.RESET}"
                else:
                    # 넓은 모드: 풀 바
                    bar_width = 20
                    filled = int(bar_width * progress)
                    bar = "━" * filled + "░" * (bar_width - filled)
                    line = f"\r  {spinner} {self.CYAN}{bar}{self.RESET} {percent:3d}% │ {self.message} │ {self.DIM}{time_str}{self.RESET} {self.DIM}(ESC 중단){self.RESET}"
            else:
                if mode == 'narrow':
                    line = f"\r  {spinner} {TerminalUI.truncate(self.message, 20)}"
                else:
                    line = f"\r  {spinner} {self.message} {self.DIM}(ESC 중단){self.RESET}"

            # 줄 끝 정리
            padding = max(0, width - len(line) - 5)
            print(line + " " * padding, end="", flush=True)
            idx += 1
            time.sleep(0.1)

    def update(self, step: int, message: str = None):
        """진행 상황 업데이트"""
        self.current_step = step
        if message:
            self.message = message

    def stop(self, final_msg: str = ""):
        """중지"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=0.5)
        # 줄 지우기
        print(f"\r{' ' * 100}\r", end="")
        if self.aborted:
            print(f"  {self.YELLOW}⚠️  사용자에 의해 중단됨{self.RESET}")
        elif final_msg:
            print(f"  {final_msg}")

    def is_aborted(self) -> bool:
        return self.aborted


# =============================================================================
# 레거시 스피너 (호환성)
# =============================================================================
class Spinner(ProgressBar):
    """ProgressBar의 별칭 (하위 호환)"""
    pass


class MaeumCLI:
    """MAEUM_CODE CLI"""

    def __init__(self, root_path: str = "."):
        self.root_path = Path(root_path).resolve()
        self.client = AIServerClient()
        self.classifier = ActionClassifier()
        self.path_judge = PathJudge()
        self.context_store = ContextStore()
        self.clarifier = Clarifier()

        self.pending_input: Optional[str] = None
        self.dir_tree: str = ""

        # 변경 히스토리 (되돌리기용)
        # [(file_path, old_content, new_content, timestamp), ...]
        self.change_history: List[Tuple[str, Optional[str], str, str]] = []
        self.max_history: int = 500  # 최대 히스토리 개수
        self.max_history_bytes: int = 3 * 1024 * 1024 * 1024  # 3GB

        # AI 투두리스트
        self.ai_todos: List[Dict[str, str]] = []  # [{"task": "...", "status": "pending/done"}]

    def _print_status_bar(self, iteration: int = 0):
        """상태바 출력"""
        try:
            ctx = self.context_store.get_current()
            phase = ctx.phase.value
        except:
            phase = "MVP"

        todo_count = len(self.ai_todos)
        pending = sum(1 for t in self.ai_todos if t.get("status") == "pending")
        ai_online = self.client.is_available()

        bar = StatusBar.render(
            str(self.root_path), ai_online, phase,
            todo_count, pending, iteration
        )
        print(f"\n  {bar}")
        print()

    def run(self):
        """메인 루프"""
        print(f"\n  ╔══════════════════════════════════════════════════════════╗")
        print(f"  ║  MAEUM_CODE  ─  AI 코딩 어시스턴트                       ║")
        print(f"  ╚══════════════════════════════════════════════════════════╝")
        print(f"  📁 {self.root_path}")
        print(f"  💡 빈 줄로 전송 │ /q 종료 │ /undo 되돌리기 │ /history 이력")
        print()

        if not self.client.is_available():
            print("  \033[31m○ AI 서버 오프라인 (7860)\033[0m\n")
        else:
            print("  \033[32m● AI 서버 연결됨\033[0m")
            print("  [*] 스캔 중...", end=" ", flush=True)
            self.dir_tree = self._scan_directory(self.root_path)
            print(f"완료\n")

        # 초기 상태바
        self._print_status_bar()

        while True:
            try:
                print("> ", end="", flush=True)
                user_input = self._read_multiline()

                if not user_input:
                    continue

                if user_input in ['/q', '/quit', '/exit']:
                    break

                # 되돌리기 명령어
                if user_input in ['/undo', '/u']:
                    self._undo_last()
                    continue

                # 히스토리 보기
                if user_input in ['/history', '/h']:
                    self._show_history()
                    continue

                # 특정 파일 되돌리기: /undo path/to/file.py
                if user_input.startswith('/undo '):
                    target = user_input[6:].strip()
                    self._undo_file(target)
                    continue

                self._process(user_input)

            except KeyboardInterrupt:
                print()
                break
            except EOFError:
                break

    def _read_multiline(self) -> str:
        """멀티라인 입력"""
        lines = []
        while True:
            try:
                line = input()
                if line == "" and lines:
                    break
                lines.append(line)
            except EOFError:
                break
        return "\n".join(lines).strip()

    def _process(self, input_text: str):
        """입력 처리"""
        if self.pending_input and input_text in ['1', '2', '3', '4']:
            action_type = self.clarifier.resolve(input_text)
            if action_type:
                self._execute(action_type, self.pending_input)
            self.pending_input = None
            return

        result = self.classifier.classify(input_text)

        if result.action == ActionType.CLARIFY:
            print()
            print(self.clarifier.get_prompt())
            print()
            self.pending_input = input_text
            return

        if result.action == ActionType.SILENT:
            self._ask_ai(input_text)
            return

        self._execute(result.action, input_text, result.payload)

    def _execute(self, action: ActionType, input_text: str, payload: dict = None):
        """행동 실행"""
        payload = payload or {}
        ctx = self.context_store.get_current()

        if action == ActionType.ARCH_SNAPSHOT:
            self._arch_snapshot(input_text)
        elif action == ActionType.ERROR_CUT:
            self._error_cut(input_text)
        elif action == ActionType.PATH_JUDGE:
            path = payload.get('path') or input_text.strip()
            self._path_judge(path, ctx.tolerance)
        elif action == ActionType.CONTEXT_SET:
            self._context_set(input_text, payload)

    def _arch_snapshot(self, input_text: str):
        """구조 스냅샷"""
        if os.path.isdir(input_text) or input_text == '.':
            path = Path(input_text).resolve() if input_text != '.' else self.root_path
            tree = self._scan_directory(path)
        else:
            tree = input_text

        prompt = f"""프로젝트 구조 분석. 4줄로 요약.

{tree}

[SNAPSHOT]
Core:
Flow:
Pattern: """

        response = self.client.generate("구조 분석가", prompt)
        print()
        print(response)
        print()

    def _error_cut(self, input_text: str):
        """에러 분석"""
        prompt = f"""에러 분석. 원인 1개 + 조치 1개만.

프로젝트:
{self.dir_tree[:2000]}

에러:
{input_text}

[ERROR]
원인:
조치: """

        response = self.client.generate("에러 해결사", prompt)
        print()
        print(response)
        print()

    def _path_judge(self, path: str, tolerance: Tolerance):
        """경로 판단"""
        role, decision = self.path_judge.judge(path, tolerance)
        print()
        print(f"[PATH]")
        print(f"Role: {role.value}")
        print(f"Decision: {decision.value}")
        print()

    def _context_set(self, input_text: str, payload: dict):
        """맥락 설정"""
        phase = payload.get('phase', Phase.MVP)
        if phase in [Phase.MVP, Phase.EXPERIMENT]:
            tolerance = Tolerance.HIGH
        elif phase == Phase.REFACTOR:
            tolerance = Tolerance.MEDIUM
        else:
            tolerance = Tolerance.LOW
        self.context_store.update(phase, tolerance, input_text)

    def _ask_ai(self, input_text: str):
        """AI 질의 + 자율 탐색 + 코드 저장"""
        try:
            ctx = self.context_store.get_current()
        except Exception:
            ctx = type('obj', (object,), {'phase': Phase.MVP, 'tolerance': Tolerance.HIGH})()

        max_iterations = 48  # 최대 탐색 횟수
        original_input = input_text  # 원본 저장

        for iteration in range(max_iterations):
            # 히스토리 정보 (AI가 되돌리기 판단용)
            history_info = ""
            if self.change_history:
                history_info = "\n최근 변경 이력:\n"
                for fp, old, new, ts in self.change_history[-5:]:
                    try:
                        rel = Path(fp).relative_to(self.root_path)
                    except ValueError:
                        rel = fp
                    action = "생성" if old is None else "수정"
                    history_info += f"  - [{ts}] {action}: {rel}\n"

            system = f"""너는 MAEUM_CODE - 프로젝트를 처음부터 완성까지 만들 수 있는 전문 AI 코딩 에이전트다.

## 🎯 핵심 능력
너는 Claude Code Opus처럼 **완전한 프로젝트를 스스로 설계하고 구현**할 수 있다:
- 빈 폴더에서 전체 앱/서비스 구축
- 복잡한 아키텍처 설계 및 구현
- 프론트엔드 + 백엔드 + DB 전체 스택
- 테스트, CI/CD, 배포 설정까지

## 📁 현재 프로젝트
경로: {self.root_path}
{self.dir_tree}

Phase: {ctx.phase.value} | Iteration: {iteration + 1}/48
{history_info}

## 🔧 도구 (정확한 형식으로 사용할 것)

### 탐색 (자동 실행) - 예시:
```read:src/main.py```
```ls:src/```
```grep:function:src/```
```find:*.py```
```tree:src/```

### 코드 작성 (모든 언어 지원)
```python:경로
코드
```
```javascript:경로
코드
```
```typescript:경로
코드
```
```html:경로
코드
```
```css:경로
코드
```
```json:경로
코드
```
```yaml:경로
코드
```
```markdown:경로
코드
```
```shell:경로
코드
```
(어떤 언어든 ```언어:경로``` 형식으로 작성 가능)

### 파일/폴더 조작
```mkdir:경로```              - 디렉토리 생성
```delete:경로```
```move:원본:대상```
```copy:원본:대상```

### 명령 실행
```bash:설명
명령어
```
```python_run:설명
코드
```

### 작업 관리
```todo:add:작업내용```
```todo:done:번호```
```report:메시지```
```undo:경로```

## 🚀 프로젝트 생성 워크플로우

### 1단계: 분석 & 계획
```todo:add:프로젝트 구조 설계```
```todo:add:핵심 기능 구현```
```todo:add:부가 기능 구현```
```todo:add:테스트 & 검증```

### 2단계: 프로젝트 초기화
```bash:프로젝트 초기화
mkdir -p src tests docs
npm init -y  # 또는 적절한 초기화
```

### 3단계: 파일 생성 (한 번에 여러 파일)
```python:src/main.py
# 메인 코드
```

```python:src/utils.py
# 유틸리티
```

```json:package.json
{{...}}
```

### 4단계: 의존성 설치 & 테스트
```bash:의존성 설치
pip install -r requirements.txt
```

```bash:테스트 실행
pytest tests/
```

## ⚡ 중요 원칙

1. **완전한 코드 작성**: 주석만 달지 말고 실제 동작하는 전체 코드를 작성하라
2. **한 번에 여러 파일**: 관련 파일들을 한 iteration에서 모두 생성하라
3. **실행 가능한 상태 유지**: 매 단계가 끝나면 프로젝트가 실행 가능해야 한다
4. **에러 처리 포함**: 프로덕션 수준의 에러 처리를 포함하라
5. **자동 진행**: 사용자 개입 없이 끝까지 완성하라
6. **보고**: 주요 단계마다 report로 진행상황을 알려라

## 🎨 예시: "할일 앱 만들어줘"라고 하면

1. todo로 계획 수립
2. 프로젝트 구조 생성 (mkdir)
3. 백엔드 API 코드 작성 (여러 파일)
4. 프론트엔드 코드 작성 (여러 파일)
5. 설정 파일 생성 (package.json, requirements.txt 등)
6. 의존성 설치 (bash)
7. 테스트 실행 (bash)
8. 완료 보고

## ❌ 금지 (이렇게 하면 안 됨)
- ```read:.``` ← 잘못됨! 구체적 경로 필요
- ```ls``` ← 잘못됨! ```ls:.``` 또는 ```ls:src/```
- 빈 경로, 불완전한 명령어 금지

## ✅ 올바른 사용법
- ```read:src/main.py``` ← 정확한 파일 경로
- ```ls:.``` ← 현재 디렉토리
- ```tree:.``` ← 프로젝트 구조 보기

**도구만 사용하라. 설명 없이 바로 실행하라.**

{self._get_todo_status()}"""

            # 진행률 바 시작 (ESC로 중단 가능)
            progress = ProgressBar("AI 작업 중...", total_steps=max_iterations)
            progress.start(step=iteration)

            # AI 응답 받기
            try:
                response = self.client.generate(system, input_text)
            except Exception as e:
                progress.stop()
                print(f"\n  ❌ AI 서버 오류: {e}")
                break
            finally:
                progress.stop()

            # ESC로 중단됐으면 즉시 종료
            if progress.is_aborted():
                print("  작업이 중단되었습니다.")
                break

            # 응답 유효성 검사
            if not response or not isinstance(response, str):
                print("\n  ❌ AI 응답 없음")
                break

            if response.startswith("[Error]") or response.startswith("[AI Server Error]"):
                print(f"\n  ❌ {response}")
                break

            # 마크다운 렌더링하여 출력
            print()
            try:
                rendered = TerminalMarkdown.render(response)
                print(rendered)
            except Exception:
                print(response)  # 렌더링 실패 시 원본 출력
            print()

            # 모든 도구 블록 추출 및 실행 (각각 try-except로 보호)
            tool_results = []

            # 1. 탐색 도구 (즉시 자동 실행 - 허락 불필요)
            try:
                explore_blocks = self._extract_explore_blocks(response)
                if explore_blocks:
                    print(f"\n  ─── 탐색 실행 ({len(explore_blocks)}개) ───")
                    results = self._execute_explores(explore_blocks)
                    if results:
                        tool_results.append(("explore", results))
            except Exception as e:
                print(f"  ⚠️ 탐색 오류 (무시됨): {e}")

            # 2. 파일 조작 도구 (허락 필요)
            try:
                file_ops = self._extract_file_ops(response)
                if file_ops:
                    results = self._execute_file_ops(file_ops)
                    if results:
                        tool_results.append(("file_op", results))
            except Exception as e:
                print(f"  ⚠️ 파일 조작 오류 (무시됨): {e}")

            # 3. 명령어 실행 도구 (허락 필요)
            try:
                exec_blocks = self._extract_exec_blocks(response)
                if exec_blocks:
                    results = self._execute_commands(exec_blocks)
                    if results:
                        tool_results.append(("exec", results))
            except Exception as e:
                print(f"  ⚠️ 명령 실행 오류 (무시됨): {e}")

            # 4. 되돌리기 블록 처리
            try:
                undo_blocks = self._extract_undo_blocks(response)
                if undo_blocks:
                    self._apply_undos(undo_blocks)
            except Exception as e:
                print(f"  ⚠️ 되돌리기 오류 (무시됨): {e}")

            # 5. 투두리스트 처리 (자동)
            try:
                todo_blocks = self._extract_todo_blocks(response)
                if todo_blocks:
                    self._execute_todos(todo_blocks)
            except Exception as e:
                print(f"  ⚠️ 투두 오류 (무시됨): {e}")

            # 6. 사용자 보고 처리 (자동)
            try:
                report_blocks = self._extract_report_blocks(response)
                if report_blocks:
                    self._show_reports(report_blocks)
            except Exception as e:
                print(f"  ⚠️ 보고 오류 (무시됨): {e}")

            # 7. 코드 블록 추출 및 저장 (허락 필요)
            try:
                code_blocks = self._extract_code_blocks(response)
                if code_blocks:
                    self._apply_changes_with_risk(code_blocks, ctx.tolerance)
            except Exception as e:
                print(f"  ⚠️ 코드 저장 오류 (무시됨): {e}")

            # 도구 실행 결과가 있으면 AI에게 피드백하여 계속 진행
            try:
                explore_results = [r for t, r in tool_results if t == "explore"]
                file_op_results = [r for t, r in tool_results if t == "file_op"]
                exec_results = [r for t, r in tool_results if t == "exec"]

                if explore_results or file_op_results or exec_results:
                    # 결과를 컨텍스트에 추가하여 다음 iteration
                    feedback_parts = []
                    if explore_results:
                        feedback_parts.append("[탐색 결과]\n" + "\n\n".join(explore_results))
                    if file_op_results:
                        feedback_parts.append("[파일 조작 결과]\n" + "\n\n".join(file_op_results))
                    if exec_results:
                        feedback_parts.append("[실행 결과]\n" + "\n\n".join(exec_results))

                    feedback = "\n\n".join(feedback_parts)
                    input_text = f"[이전 요청]\n{input_text}\n\n{feedback}\n\n위 결과를 바탕으로 계속 진행하세요."

                    # 상태바 갱신하며 다음 iteration
                    self._print_status_bar(iteration + 2)
                    continue
            except Exception as e:
                print(f"  ⚠️ 피드백 처리 오류: {e}")

            break  # 더 이상 도구 실행 없으면 종료

        # 작업 완료 후 상태바 갱신
        self._print_status_bar()

    def _get_todo_status(self) -> str:
        """현재 투두리스트 상태"""
        if not self.ai_todos:
            return ""

        lines = ["\n## 현재 작업 계획"]
        for i, todo in enumerate(self.ai_todos, 1):
            status = "✓" if todo["status"] == "done" else "○"
            lines.append(f"  {i}. [{status}] {todo['task']}")
        return "\n".join(lines)

    def _extract_todo_blocks(self, text: str) -> List[Tuple[str, str]]:
        """투두 명령 추출: [(action, arg), ...]"""
        results = []

        # todo:add:내용
        for match in re.finditer(r'```todo:add:([^\n`]+)\n*```', text):
            results.append(('add', match.group(1).strip()))

        # todo:done:번호
        for match in re.finditer(r'```todo:done:(\d+)\n*```', text):
            results.append(('done', match.group(1).strip()))

        # todo:clear
        for match in re.finditer(r'```todo:clear\n*```', text):
            results.append(('clear', ''))

        return results

    def _execute_todos(self, blocks: List[Tuple[str, str]]):
        """투두리스트 실행"""
        for action, arg in blocks:
            try:
                if action == 'add' and arg:
                    self.ai_todos.append({"task": str(arg)[:200], "status": "pending"})
                    print(f"  📋 할 일 추가: {arg[:50]}")

                elif action == 'done':
                    idx = int(arg) - 1
                    if 0 <= idx < len(self.ai_todos):
                        self.ai_todos[idx]["status"] = "done"
                        print(f"  ✓ 완료: {self.ai_todos[idx]['task'][:50]}")

                elif action == 'clear':
                    self.ai_todos = []
                    print("  📋 투두리스트 초기화")
            except (ValueError, IndexError, TypeError):
                pass  # 잘못된 입력 무시

        # 현재 상태 출력
        if self.ai_todos:
            pending = sum(1 for t in self.ai_todos if t.get("status") == "pending")
            done = len(self.ai_todos) - pending
            print(f"  📊 진행: {done}/{len(self.ai_todos)} 완료")

    def _extract_report_blocks(self, text: str) -> List[str]:
        """보고 메시지 추출"""
        results = []
        for match in re.finditer(r'```report:([^\n`]+)\n*```', text):
            results.append(match.group(1).strip())
        return results

    def _show_reports(self, reports: List[str]):
        """사용자에게 보고"""
        for report in reports:
            try:
                report = str(report)[:200]  # 길이 제한
                print()
                print("  ┌" + "─" * 58 + "┐")
                # 55자에 맞추기
                if len(report) <= 55:
                    print(f"  │ 💬 {report:<55} │")
                else:
                    print(f"  │ 💬 {report[:52]}... │")
                print("  └" + "─" * 58 + "┘")
                print()
            except Exception:
                pass  # 보고 출력 실패 무시

    def _extract_explore_blocks(self, text: str) -> List[Tuple[str, str]]:
        """탐색 명령 추출: [(cmd, arg), ...]"""
        results = []

        # read:경로
        for match in re.finditer(r'```read:([^\n`]+)\n*```', text):
            results.append(('read', match.group(1).strip()))

        # ls:경로
        for match in re.finditer(r'```ls:([^\n`]*)\n*```', text):
            results.append(('ls', match.group(1).strip() or '.'))

        # grep:패턴:경로
        for match in re.finditer(r'```grep:([^:\n`]+):?([^\n`]*)\n*```', text):
            pattern = match.group(1).strip()
            path = match.group(2).strip() or '.'
            results.append(('grep', f"{pattern}:{path}"))

        # find:패턴
        for match in re.finditer(r'```find:([^\n`]+)\n*```', text):
            results.append(('find', match.group(1).strip()))

        # tree:경로
        for match in re.finditer(r'```tree:([^\n`]*)\n*```', text):
            results.append(('tree', match.group(1).strip() or '.'))

        return results

    def _extract_file_ops(self, text: str) -> List[Tuple[str, str]]:
        """파일 조작 명령 추출: [(op, arg), ...]"""
        results = []

        # mkdir:경로 (자동 실행 - 허락 불필요)
        for match in re.finditer(r'```mkdir:([^\n`]+)\n*```', text):
            results.append(('mkdir', match.group(1).strip()))

        # delete:경로
        for match in re.finditer(r'```delete:([^\n`]+)\n*```', text):
            results.append(('delete', match.group(1).strip()))

        # move:원본:대상
        for match in re.finditer(r'```move:([^:\n`]+):([^\n`]+)\n*```', text):
            src = match.group(1).strip()
            dst = match.group(2).strip()
            results.append(('move', f"{src}:{dst}"))

        # copy:원본:대상
        for match in re.finditer(r'```copy:([^:\n`]+):([^\n`]+)\n*```', text):
            src = match.group(1).strip()
            dst = match.group(2).strip()
            results.append(('copy', f"{src}:{dst}"))

        return results

    def _extract_exec_blocks(self, text: str) -> List[Tuple[str, str, str]]:
        """명령어 실행 블록 추출: [(type, desc, cmd), ...]"""
        results = []

        # bash:설명\n명령어
        for match in re.finditer(r'```bash:([^\n`]*)\n(.*?)```', text, re.DOTALL):
            desc = match.group(1).strip()
            cmd = match.group(2).strip()
            if cmd:
                results.append(('bash', desc, cmd))

        # python_run:설명\n코드
        for match in re.finditer(r'```python_run:([^\n`]*)\n(.*?)```', text, re.DOTALL):
            desc = match.group(1).strip()
            code = match.group(2).strip()
            if code:
                results.append(('python_run', desc, code))

        return results

    def _execute_explores(self, blocks: List[Tuple[str, str]]) -> str:
        """탐색 명령 실행"""
        results = []

        for cmd, arg in blocks:
            print(f"  📂 {cmd}: {arg}")

            try:
                if cmd == 'read':
                    result = self._cmd_read(arg)
                elif cmd == 'ls':
                    result = self._cmd_ls(arg)
                elif cmd == 'grep':
                    result = self._cmd_grep(arg)
                elif cmd == 'find':
                    result = self._cmd_find(arg)
                elif cmd == 'tree':
                    result = self._cmd_tree(arg)
                else:
                    result = f"[알 수 없는 명령: {cmd}]"

                results.append(f"=== {cmd}:{arg} ===\n{result[:5000]}")

            except Exception as e:
                results.append(f"=== {cmd}:{arg} ===\n[오류: {e}]")

        return "\n\n".join(results)

    def _cmd_read(self, path: str) -> str:
        """파일 읽기 + 의미론적 분석 (기본 활성화)"""
        if not path.startswith('/'):
            full_path = self.root_path / path
        else:
            full_path = Path(path)

        if not full_path.exists():
            return f"[파일 없음: {path}]"

        if full_path.is_dir():
            return f"[디렉토리입니다: {path}]"

        try:
            content = full_path.read_text(encoding='utf-8', errors='ignore')
            lines = content.splitlines()

            # 의미론적 분석 (코드 파일인 경우)
            analysis_header = ""
            if path.endswith(('.py', '.js', '.ts', '.jsx', '.tsx')):
                analysis = SemanticAnalyzer.analyze_file(path, content)
                role_desc, role_type = analysis['role']

                # 분석 요약 헤더
                parts = [f"[📊 {role_desc}]"]

                # 클래스 목록
                if analysis['symbols']['classes']:
                    cls_names = [c['name'] for c in analysis['symbols']['classes'][:5]]
                    parts.append(f"클래스: {', '.join(cls_names)}")

                # 함수 목록
                if analysis['symbols']['functions']:
                    func_names = [f['name'] for f in analysis['symbols']['functions'][:8]]
                    parts.append(f"함수: {', '.join(func_names)}")
                    if len(analysis['symbols']['functions']) > 8:
                        parts[-1] += f" (+{len(analysis['symbols']['functions']) - 8}개)"

                # 상수
                if analysis['symbols']['constants']:
                    const_names = [c['name'] for c in analysis['symbols']['constants'][:5]]
                    parts.append(f"상수: {', '.join(const_names)}")

                # imports
                if analysis['symbols']['imports']:
                    imp_count = len(analysis['symbols']['imports'])
                    parts.append(f"imports: {imp_count}개")

                # 복잡도
                parts.append(f"복잡도: {analysis['metrics']['complexity_hint']}")

                analysis_header = " | ".join(parts) + "\n" + "─" * 60 + "\n"

            # 줄번호 추가
            numbered = [f"{i+1:4}│ {line}" for i, line in enumerate(lines)]
            return analysis_header + "\n".join(numbered)  # 전체 읽기 (로컬 서버)
        except Exception as e:
            return f"[읽기 실패: {e}]"

    def _cmd_ls(self, path: str) -> str:
        """디렉토리 목록"""
        if not path or path == '.':
            target = self.root_path
        elif not path.startswith('/'):
            target = self.root_path / path
        else:
            target = Path(path)

        if not target.exists():
            return f"[경로 없음: {path}]"

        if not target.is_dir():
            return f"[디렉토리 아님: {path}]"

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

    def _cmd_grep(self, arg: str) -> str:
        """파일 내용 검색"""
        parts = arg.split(':', 1)
        pattern = parts[0]
        path = parts[1] if len(parts) > 1 else '.'

        if not path.startswith('/'):
            target = self.root_path / path
        else:
            target = Path(path)

        results = []
        try:
            if target.is_file():
                files = [target]
            else:
                files = list(target.rglob('*'))

            for f in files:  # 전체 파일 검색 (로컬 서버)
                if f.is_file() and f.suffix in ['.py', '.js', '.ts', '.tsx', '.jsx', '.json', '.md', '.txt', '.yaml', '.yml', '.toml']:
                    try:
                        content = f.read_text(encoding='utf-8', errors='ignore')
                        for i, line in enumerate(content.splitlines(), 1):
                            if re.search(pattern, line, re.IGNORECASE):
                                rel = f.relative_to(self.root_path) if str(f).startswith(str(self.root_path)) else f
                                results.append(f"{rel}:{i}: {line.strip()}")
                                if len(results) >= 50:
                                    break
                    except:
                        pass
                if len(results) >= 50:
                    break

            return "\n".join(results) if results else "[일치 없음]"
        except Exception as e:
            return f"[grep 실패: {e}]"

    def _cmd_find(self, pattern: str) -> str:
        """파일 찾기 (glob)"""
        try:
            matches = list(self.root_path.rglob(pattern))[:50]
            if not matches:
                return "[일치하는 파일 없음]"

            lines = []
            for m in matches:
                try:
                    rel = m.relative_to(self.root_path)
                    if m.is_dir():
                        lines.append(f"  📁 {rel}/")
                    else:
                        lines.append(f"  📄 {rel}")
                except:
                    pass

            return "\n".join(lines)
        except Exception as e:
            return f"[find 실패: {e}]"

    def _cmd_tree(self, path: str) -> str:
        """디렉토리 트리"""
        if not path or path == '.':
            target = self.root_path
        elif not path.startswith('/'):
            target = self.root_path / path
        else:
            target = Path(path)

        if not target.exists():
            return f"[경로 없음: {path}]"

        return self._scan_directory(target, max_depth=4)

    def _execute_file_ops(self, ops: List[Tuple[str, str]]) -> str:
        """파일 조작 실행"""
        results = []

        for op, arg in ops:
            # mkdir은 자동 실행 (허락 불필요)
            if op == 'mkdir':
                result = self._op_mkdir(arg)
            elif op == 'delete':
                print(f"\n  ⚠️  파일 조작: {op}")
                result = self._op_delete(arg)
            elif op == 'move':
                print(f"\n  ⚠️  파일 조작: {op}")
                result = self._op_move(arg)
            elif op == 'copy':
                print(f"\n  ⚠️  파일 조작: {op}")
                result = self._op_copy(arg)
            else:
                result = f"[알 수 없는 조작: {op}]"

            results.append(f"=== {op}:{arg} ===\n{result}")

        return "\n\n".join(results)

    def _op_mkdir(self, path: str) -> str:
        """디렉토리 생성 (자동 실행)"""
        DIM = "\033[2m"
        RESET = "\033[0m"
        GREEN = "\033[32m"
        CYAN = "\033[36m"

        if not path.startswith('/'):
            full_path = self.root_path / path
        else:
            full_path = Path(path)

        print(f"\n  {DIM}┌─ mkdir ────────────────────────────────────────{RESET}")
        print(f"  {DIM}│{RESET} {CYAN}{path}{RESET}")

        try:
            full_path.mkdir(parents=True, exist_ok=True)
            self.dir_tree = self._scan_directory(self.root_path)
            print(f"  {DIM}│{RESET} {GREEN}✓ Created{RESET}")
            print(f"  {DIM}└────────────────────────────────────────────────{RESET}\n")
            return f"✓ 디렉토리 생성: {path}"
        except Exception as e:
            print(f"  {DIM}│{RESET} ✗ 실패: {e}")
            print(f"  {DIM}└────────────────────────────────────────────────{RESET}\n")
            return f"✗ 생성 실패: {e}"

    def _op_delete(self, path: str) -> str:
        """파일/디렉토리 삭제 (허락 필요)"""
        if not path.startswith('/'):
            full_path = self.root_path / path
        else:
            full_path = Path(path)

        if not full_path.exists():
            return f"[파일 없음: {path}]"

        # 위험한 경로 차단
        dangerous = ['.git', '.env', 'node_modules', '__pycache__']
        if any(d in str(full_path) for d in dangerous):
            return f"[위험한 경로 삭제 차단: {path}]"

        print(f"     경로: {full_path}")
        if full_path.is_dir():
            print(f"     타입: 디렉토리")
        else:
            size = full_path.stat().st_size
            print(f"     타입: 파일 ({size} bytes)")

        try:
            choice = input("  삭제? (y/n): ").strip().lower()
        except EOFError:
            choice = 'n'

        if choice == 'y':
            try:
                if full_path.is_dir():
                    import shutil
                    shutil.rmtree(full_path)
                else:
                    full_path.unlink()
                self.dir_tree = self._scan_directory(self.root_path)
                return f"✓ 삭제됨: {path}"
            except Exception as e:
                return f"✗ 삭제 실패: {e}"
        else:
            return "건너뜀"

    def _op_move(self, arg: str) -> str:
        """파일 이동 (허락 필요)"""
        parts = arg.split(':', 1)
        if len(parts) != 2:
            return "[형식 오류: move:원본:대상]"

        src, dst = parts[0].strip(), parts[1].strip()

        if not src.startswith('/'):
            src_path = self.root_path / src
        else:
            src_path = Path(src)

        if not dst.startswith('/'):
            dst_path = self.root_path / dst
        else:
            dst_path = Path(dst)

        if not src_path.exists():
            return f"[원본 없음: {src}]"

        print(f"     원본: {src_path}")
        print(f"     대상: {dst_path}")

        try:
            choice = input("  이동? (y/n): ").strip().lower()
        except EOFError:
            choice = 'n'

        if choice == 'y':
            try:
                import shutil
                dst_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src_path), str(dst_path))
                self.dir_tree = self._scan_directory(self.root_path)
                return f"✓ 이동됨: {src} → {dst}"
            except Exception as e:
                return f"✗ 이동 실패: {e}"
        else:
            return "건너뜀"

    def _op_copy(self, arg: str) -> str:
        """파일 복사 (허락 필요)"""
        parts = arg.split(':', 1)
        if len(parts) != 2:
            return "[형식 오류: copy:원본:대상]"

        src, dst = parts[0].strip(), parts[1].strip()

        if not src.startswith('/'):
            src_path = self.root_path / src
        else:
            src_path = Path(src)

        if not dst.startswith('/'):
            dst_path = self.root_path / dst
        else:
            dst_path = Path(dst)

        if not src_path.exists():
            return f"[원본 없음: {src}]"

        print(f"     원본: {src_path}")
        print(f"     대상: {dst_path}")

        try:
            choice = input("  복사? (y/n): ").strip().lower()
        except EOFError:
            choice = 'n'

        if choice == 'y':
            try:
                import shutil
                dst_path.parent.mkdir(parents=True, exist_ok=True)
                if src_path.is_dir():
                    shutil.copytree(str(src_path), str(dst_path))
                else:
                    shutil.copy2(str(src_path), str(dst_path))
                self.dir_tree = self._scan_directory(self.root_path)
                return f"✓ 복사됨: {src} → {dst}"
            except Exception as e:
                return f"✗ 복사 실패: {e}"
        else:
            return "건너뜀"

    def _execute_commands(self, blocks: List[Tuple[str, str, str]]) -> str:
        """명령어 실행 (항상 허락 필요)"""
        results = []

        for cmd_type, desc, cmd in blocks:
            print("\n" + "═" * 60)
            print(f"  🔧 {cmd_type.upper()}: {desc or '(설명 없음)'}")
            print("═" * 60)

            # 명령어 미리보기
            lines = cmd.splitlines()
            for i, line in enumerate(lines[:10], 1):
                print(f"  {i:3}│ {line}")
            if len(lines) > 10:
                print(f"  ... (+{len(lines) - 10}줄)")

            print("═" * 60)

            try:
                choice = input("  실행? (y/n): ").strip().lower()
            except EOFError:
                choice = 'n'

            if choice == 'y':
                if cmd_type == 'bash':
                    result = self._run_bash(cmd)
                elif cmd_type == 'python_run':
                    result = self._run_python(cmd)
                else:
                    result = f"[알 수 없는 타입: {cmd_type}]"
            else:
                result = "건너뜀"

            results.append(f"=== {cmd_type}:{desc} ===\n{result}")

        return "\n\n".join(results)

    def _run_bash(self, cmd: str) -> str:
        """Bash 명령어 실행 - Claude Code 스타일"""
        DIM = "\033[2m"
        RESET = "\033[0m"
        GREEN = "\033[32m"
        RED = "\033[31m"
        CYAN = "\033[36m"
        YELLOW = "\033[33m"

        # 실행 박스 시작
        print(f"\n  {DIM}┌─ bash ─────────────────────────────────────────{RESET}")
        print(f"  {DIM}│{RESET} {CYAN}${RESET} {cmd[:60]}{'...' if len(cmd) > 60 else ''}")
        print(f"  {DIM}├────────────────────────────────────────────────{RESET}")

        try:
            start_time = time.time()

            # 실시간 출력을 위해 Popen 사용
            process = subprocess.Popen(
                cmd,
                shell=True,
                cwd=str(self.root_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            output_lines = []
            line_count = 0
            max_lines = 30  # 최대 표시 줄 수

            # 실시간 출력
            for line in iter(process.stdout.readline, ''):
                line = line.rstrip()
                output_lines.append(line)
                line_count += 1

                if line_count <= max_lines:
                    # 줄이 너무 길면 자르기
                    display_line = line[:70] + ('...' if len(line) > 70 else '')
                    print(f"  {DIM}│{RESET} {display_line}")
                elif line_count == max_lines + 1:
                    print(f"  {DIM}│{RESET} {YELLOW}... (출력 생략){RESET}")

            process.wait(timeout=300)
            elapsed = time.time() - start_time

            # 결과 상태
            if process.returncode == 0:
                status = f"{GREEN}✓ 완료{RESET}"
            else:
                status = f"{RED}✗ 종료코드 {process.returncode}{RESET}"

            print(f"  {DIM}├────────────────────────────────────────────────{RESET}")
            print(f"  {DIM}│{RESET} {status} {DIM}({elapsed:.1f}s){RESET}")
            print(f"  {DIM}└────────────────────────────────────────────────{RESET}\n")

            # 트리 갱신
            self.dir_tree = self._scan_directory(self.root_path)

            full_output = '\n'.join(output_lines)
            if process.returncode != 0:
                full_output += f"\n[EXIT CODE: {process.returncode}]"

            return full_output[:5000] if full_output else "[출력 없음]"

        except subprocess.TimeoutExpired:
            process.kill()
            print(f"  {DIM}│{RESET} {RED}⏱ 타임아웃 (5분 초과){RESET}")
            print(f"  {DIM}└────────────────────────────────────────────────{RESET}\n")
            return "[타임아웃: 5분 초과]"
        except Exception as e:
            print(f"  {DIM}│{RESET} {RED}✗ 오류: {e}{RESET}")
            print(f"  {DIM}└────────────────────────────────────────────────{RESET}\n")
            return f"[실행 오류: {e}]"

    def _run_python(self, code: str) -> str:
        """Python 코드 실행 - Claude Code 스타일"""
        DIM = "\033[2m"
        RESET = "\033[0m"
        GREEN = "\033[32m"
        RED = "\033[31m"
        CYAN = "\033[36m"
        YELLOW = "\033[33m"
        MAGENTA = "\033[35m"

        # 코드 미리보기 (첫 몇 줄)
        code_lines = code.strip().split('\n')
        preview_lines = code_lines[:5]

        print(f"\n  {DIM}┌─ python ───────────────────────────────────────{RESET}")
        for i, line in enumerate(preview_lines):
            display_line = line[:65] + ('...' if len(line) > 65 else '')
            print(f"  {DIM}│{RESET} {MAGENTA}{display_line}{RESET}")
        if len(code_lines) > 5:
            print(f"  {DIM}│{RESET} {YELLOW}... ({len(code_lines) - 5}줄 더){RESET}")
        print(f"  {DIM}├────────────────────────────────────────────────{RESET}")
        print(f"  {DIM}│{RESET} {CYAN}▶ 실행 중...{RESET}", end="", flush=True)

        try:
            start_time = time.time()

            # 임시 파일로 실행
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(code)
                temp_path = f.name

            try:
                # 실시간 출력
                process = subprocess.Popen(
                    ['python3', temp_path],
                    cwd=str(self.root_path),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1
                )

                print(f"\r  {DIM}│{RESET}                    ")  # 클리어

                output_lines = []
                line_count = 0
                max_lines = 25

                for line in iter(process.stdout.readline, ''):
                    line = line.rstrip()
                    output_lines.append(line)
                    line_count += 1

                    if line_count <= max_lines:
                        display_line = line[:70] + ('...' if len(line) > 70 else '')
                        print(f"  {DIM}│{RESET} {display_line}")
                    elif line_count == max_lines + 1:
                        print(f"  {DIM}│{RESET} {YELLOW}... (출력 생략){RESET}")

                process.wait(timeout=300)
                elapsed = time.time() - start_time

                # 결과 상태
                if process.returncode == 0:
                    status = f"{GREEN}✓ 완료{RESET}"
                else:
                    status = f"{RED}✗ 종료코드 {process.returncode}{RESET}"

                print(f"  {DIM}├────────────────────────────────────────────────{RESET}")
                print(f"  {DIM}│{RESET} {status} {DIM}({elapsed:.1f}s){RESET}")
                print(f"  {DIM}└────────────────────────────────────────────────{RESET}\n")

                full_output = '\n'.join(output_lines)
                if process.returncode != 0:
                    full_output += f"\n[EXIT CODE: {process.returncode}]"

                return full_output[:5000] if full_output else "[출력 없음]"

            finally:
                Path(temp_path).unlink(missing_ok=True)

        except subprocess.TimeoutExpired:
            process.kill()
            print(f"\n  {DIM}│{RESET} {RED}⏱ 타임아웃 (5분 초과){RESET}")
            print(f"  {DIM}└────────────────────────────────────────────────{RESET}\n")
            return "[타임아웃: 5분 초과]"
        except Exception as e:
            print(f"\n  {DIM}│{RESET} {RED}✗ 오류: {e}{RESET}")
            print(f"  {DIM}└────────────────────────────────────────────────{RESET}\n")
            return f"[실행 오류: {e}]"

    def _apply_changes_with_risk(self, code_blocks: List[Tuple[str, str, str]], tolerance: Tolerance):
        """코드 변경 적용 - Claude Code 스타일"""
        DIM = "\033[2m"
        RESET = "\033[0m"
        GREEN = "\033[32m"
        RED = "\033[31m"
        CYAN = "\033[36m"
        YELLOW = "\033[33m"
        MAGENTA = "\033[35m"
        BLUE = "\033[34m"

        if not code_blocks:
            return

        for i, (file_path, lang, code) in enumerate(code_blocks, 1):
            if not file_path.startswith('/'):
                full_path = self.root_path / file_path
            else:
                full_path = Path(file_path)

            is_new = not full_path.exists()
            risk = classify_risk(file_path, is_new, tolerance)
            action = "Create" if is_new else "Edit"
            lines = len(code.splitlines())

            # Claude Code 스타일 박스
            print(f"\n  {DIM}┌─ {action} ─────────────────────────────────────────{RESET}")
            print(f"  {DIM}│{RESET} {CYAN}{file_path}{RESET}")
            print(f"  {DIM}│{RESET} {DIM}{lines} lines │ {lang}{RESET}")

            # 위험도 표시
            if risk == RiskLevel.HIGH:
                print(f"  {DIM}│{RESET} {RED}⚠ HIGH RISK{RESET}")
            elif risk == RiskLevel.MEDIUM:
                print(f"  {DIM}│{RESET} {YELLOW}◐ MEDIUM{RESET}")

            print(f"  {DIM}├────────────────────────────────────────────────{RESET}")

            # diff 또는 미리보기
            if is_new:
                # 새 파일: 처음 몇 줄 표시
                preview_lines = code.splitlines()[:8]
                for ln, line in enumerate(preview_lines, 1):
                    display = line[:65] + ('...' if len(line) > 65 else '')
                    print(f"  {DIM}│{RESET} {GREEN}+{RESET} {display}")
                if lines > 8:
                    print(f"  {DIM}│{RESET} {DIM}... (+{lines - 8} more lines){RESET}")
            else:
                # 기존 파일: diff 스타일
                try:
                    old_content = full_path.read_text(encoding='utf-8', errors='ignore')
                    old_lines = old_content.splitlines()
                    new_lines = code.splitlines()

                    # 간단한 diff 표시 (변경된 부분만)
                    import difflib
                    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm='', n=2))

                    shown = 0
                    for line in diff[2:]:  # 헤더 스킵
                        if shown >= 15:
                            print(f"  {DIM}│{RESET} {DIM}... (more changes){RESET}")
                            break
                        if line.startswith('+'):
                            print(f"  {DIM}│{RESET} {GREEN}{line[:70]}{RESET}")
                            shown += 1
                        elif line.startswith('-'):
                            print(f"  {DIM}│{RESET} {RED}{line[:70]}{RESET}")
                            shown += 1
                        elif line.startswith('@'):
                            print(f"  {DIM}│{RESET} {BLUE}{line[:70]}{RESET}")
                except:
                    # 읽기 실패시 새 코드만 표시
                    for ln, line in enumerate(code.splitlines()[:8], 1):
                        print(f"  {DIM}│{RESET}   {line[:65]}")

            print(f"  {DIM}├────────────────────────────────────────────────{RESET}")
            print(f"  {DIM}│{RESET} {YELLOW}Apply changes?{RESET} {DIM}(y)es / (n)o / (v)iew full{RESET}")
            print(f"  {DIM}└────────────────────────────────────────────────{RESET}")

            try:
                choice = input(f"  {CYAN}>{RESET} ").strip().lower()
            except EOFError:
                choice = 'n'

            if choice == 'v':
                self._show_full_diff_and_ask(file_path, full_path, lang, code, is_new)
            elif choice == 'y':
                self._save_file(file_path, code)
                print(f"  {GREEN}✓ Applied{RESET}")
            else:
                print(f"  {DIM}Skipped{RESET}")

    def _show_full_diff_and_ask(self, file_path: str, full_path: Path, lang: str, code: str, is_new: bool):
        """전체 diff - Claude Code 스타일"""
        DIM = "\033[2m"
        RESET = "\033[0m"
        GREEN = "\033[32m"
        RED = "\033[31m"
        CYAN = "\033[36m"
        YELLOW = "\033[33m"
        BLUE = "\033[34m"

        print(f"\n  {DIM}╔══ Full View ══════════════════════════════════════════════{RESET}")
        print(f"  {DIM}║{RESET} {CYAN}{file_path}{RESET}")
        print(f"  {DIM}╠════════════════════════════════════════════════════════════{RESET}")

        if is_new:
            print(f"  {DIM}║{RESET} {GREEN}NEW FILE{RESET}")
            print(f"  {DIM}╟────────────────────────────────────────────────────────────{RESET}")
            for ln, line in enumerate(code.splitlines(), 1):
                print(f"  {DIM}║{RESET} {GREEN}{ln:4}│{RESET} {line}")
        else:
            old_content = full_path.read_text(encoding='utf-8', errors='ignore')

            print(f"  {DIM}║{RESET} {RED}─── BEFORE ───{RESET}")
            for ln, line in enumerate(old_content.splitlines(), 1):
                print(f"  {DIM}║{RESET} {RED}{ln:4}│{RESET} {DIM}{line}{RESET}")

            print(f"  {DIM}╟────────────────────────────────────────────────────────────{RESET}")
            print(f"  {DIM}║{RESET} {GREEN}─── AFTER ───{RESET}")
            for ln, line in enumerate(code.splitlines(), 1):
                print(f"  {DIM}║{RESET} {GREEN}{ln:4}│{RESET} {line}")

        print(f"  {DIM}╠════════════════════════════════════════════════════════════{RESET}")
        print(f"  {DIM}║{RESET} {YELLOW}Apply?{RESET} {DIM}(y)es / (n)o{RESET}")
        print(f"  {DIM}╚════════════════════════════════════════════════════════════{RESET}")

        try:
            choice = input(f"  {CYAN}>{RESET} ").strip().lower()
        except EOFError:
            choice = 'n'

        if choice == 'y':
            self._save_file(file_path, code)
            print(f"  {GREEN}✓ Applied{RESET}")
        else:
            print(f"  {DIM}Skipped{RESET}")

    def _extract_code_blocks(self, text: str) -> List[Tuple[str, str, str]]:
        """코드 블록 추출: [(path, lang, code), ...]"""
        pattern = r'```(\w+):([^\n`]+)\n(.*?)```'
        matches = re.findall(pattern, text, re.DOTALL)

        results = []
        for lang, path, code in matches:
            # undo 블록은 제외
            if lang.lower() == 'undo':
                continue
            path = path.strip()
            code = code.strip()
            if path and code:
                results.append((path, lang, code))
        return results

    def _extract_undo_blocks(self, text: str) -> List[Tuple[str, str]]:
        """되돌리기 블록 추출: [(target, reason), ...]"""
        pattern = r'```undo:([^\n`]+)\n(.*?)```'
        matches = re.findall(pattern, text, re.DOTALL)

        results = []
        for target, reason in matches:
            target = target.strip()
            reason = reason.strip()
            if target:
                results.append((target, reason))
        return results

    def _apply_undos(self, undo_blocks: List[Tuple[str, str]]):
        """AI가 요청한 되돌리기 적용"""
        for target, reason in undo_blocks:
            print("\n" + "═" * 60)
            print(f"  AI 되돌리기 요청: {target}")
            if reason:
                print(f"  이유: {reason}")
            print("═" * 60)

            try:
                choice = input("  되돌릴까요? (y/n): ").strip().lower()
            except EOFError:
                choice = 'n'

            if choice == 'y':
                if target.lower() == 'last':
                    self._undo_last()
                else:
                    self._undo_file(target)
            else:
                print("  건너뜀")

    def _get_history_size(self) -> int:
        """히스토리 총 용량 계산 (bytes)"""
        total = 0
        for file_path, old_content, new_content, timestamp in self.change_history:
            total += len(file_path.encode('utf-8'))
            total += len(timestamp.encode('utf-8'))
            if old_content:
                total += len(old_content.encode('utf-8'))
            total += len(new_content.encode('utf-8'))
        return total

    def _trim_history(self):
        """히스토리 용량 관리 - 3GB 초과 시 오래된 것부터 삭제"""
        # 개수 제한
        if len(self.change_history) > self.max_history:
            self.change_history = self.change_history[-self.max_history:]

        # 용량 제한 (오래된 것부터 삭제)
        while self.change_history and self._get_history_size() > self.max_history_bytes:
            removed = self.change_history.pop(0)
            try:
                rel = Path(removed[0]).relative_to(self.root_path)
            except ValueError:
                rel = removed[0]
            print(f"  [히스토리] 용량 초과로 삭제: {rel} ({removed[3]})")

    def _save_file(self, file_path: str, code: str):
        """파일 저장 (히스토리 기록)"""
        if not file_path.startswith('/'):
            full_path = self.root_path / file_path
        else:
            full_path = Path(file_path)

        try:
            # 이전 내용 저장 (되돌리기용)
            old_content = None
            if full_path.exists():
                old_content = full_path.read_text(encoding='utf-8', errors='ignore')

            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(code, encoding='utf-8')

            # 히스토리에 추가
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.change_history.append((str(full_path), old_content, code, timestamp))

            # 용량 체크 및 오래된 것부터 삭제 (3GB 제한)
            self._trim_history()

            print(f"  ✓ 저장: {file_path}")

            # 트리 갱신
            self.dir_tree = self._scan_directory(self.root_path)
        except Exception as e:
            print(f"  ✗ 실패: {e}")

    def _undo_last(self) -> bool:
        """마지막 변경 되돌리기"""
        if not self.change_history:
            print("  되돌릴 변경사항이 없습니다.")
            return False

        file_path, old_content, new_content, timestamp = self.change_history.pop()

        print(f"\n  되돌리기: {file_path}")
        print(f"  변경 시각: {timestamp}")

        try:
            path = Path(file_path)

            if old_content is None:
                # 새로 생성된 파일 → 삭제
                if path.exists():
                    path.unlink()
                    print(f"  ✓ 삭제됨 (새 파일이었음)")
            else:
                # 수정된 파일 → 이전 내용 복원
                path.write_text(old_content, encoding='utf-8')
                print(f"  ✓ 복원됨")

            # 트리 갱신
            self.dir_tree = self._scan_directory(self.root_path)
            return True

        except Exception as e:
            print(f"  ✗ 되돌리기 실패: {e}")
            return False

    def _undo_file(self, target_path: str) -> bool:
        """특정 파일의 마지막 변경 되돌리기"""
        if not target_path.startswith('/'):
            target_full = str(self.root_path / target_path)
        else:
            target_full = target_path

        # 해당 파일의 가장 최근 변경 찾기
        for i in range(len(self.change_history) - 1, -1, -1):
            file_path, old_content, new_content, timestamp = self.change_history[i]
            if file_path == target_full or file_path.endswith(target_path):
                # 찾음 - 히스토리에서 제거
                self.change_history.pop(i)

                print(f"\n  되돌리기: {target_path}")
                print(f"  변경 시각: {timestamp}")

                try:
                    path = Path(file_path)
                    if old_content is None:
                        if path.exists():
                            path.unlink()
                            print(f"  ✓ 삭제됨")
                    else:
                        path.write_text(old_content, encoding='utf-8')
                        print(f"  ✓ 복원됨")

                    self.dir_tree = self._scan_directory(self.root_path)
                    return True

                except Exception as e:
                    print(f"  ✗ 되돌리기 실패: {e}")
                    return False

        print(f"  {target_path}의 변경 이력이 없습니다.")
        return False

    def _show_history(self):
        """변경 히스토리 표시"""
        if not self.change_history:
            print("\n  변경 이력이 없습니다.\n")
            return

        print(f"\n  변경 이력 ({len(self.change_history)}개):")
        print("  " + "─" * 50)

        for i, (file_path, old_content, new_content, timestamp) in enumerate(reversed(self.change_history), 1):
            # 상대 경로로 표시
            try:
                rel_path = Path(file_path).relative_to(self.root_path)
            except ValueError:
                rel_path = file_path

            action = "생성" if old_content is None else "수정"
            print(f"  {i}. [{timestamp}] {action}: {rel_path}")

        print("  " + "─" * 50)
        print()

    def _scan_directory(self, path: Path, max_depth: int = 3) -> str:
        """디렉토리 스캔 + 의미론적 파일 역할 표시"""
        lines = []

        def scan(p: Path, prefix: str = "", depth: int = 0):
            if depth > max_depth:
                return
            try:
                items = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name))
            except PermissionError:
                return

            exclude = {'.git', 'node_modules', '__pycache__', '.venv', 'venv',
                      '.idea', '.vscode', 'dist', 'build', '.egg-info'}
            items = [i for i in items if i.name not in exclude and not i.name.startswith('.')]

            for i, item in enumerate(items[:20]):
                is_last = i == len(items) - 1
                connector = "└── " if is_last else "├── "

                if item.is_dir():
                    lines.append(f"{prefix}{connector}{item.name}/")
                    new_prefix = prefix + ("    " if is_last else "│   ")
                    scan(item, new_prefix, depth + 1)
                else:
                    # 의미론적 역할 표시
                    role_desc, _ = SemanticAnalyzer.infer_file_role(str(item))
                    if role_desc not in ('일반 파일', 'Python 소스', 'JavaScript 소스', 'TypeScript 소스'):
                        lines.append(f"{prefix}{connector}{item.name}  [{role_desc}]")
                    else:
                        lines.append(f"{prefix}{connector}{item.name}")

        lines.append(f"{path.name}/")
        scan(path)
        return "\n".join(lines)  # 전체 트리 (로컬 서버)


def main():
    cli = MaeumCLI()
    cli.run()


if __name__ == "__main__":
    main()
