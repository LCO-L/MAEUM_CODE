"""
SemanticGraphBuilder - 코드를 의미 그래프로 변환

핵심:
- 폴더 구조 → Code Tree Graph → Semantic File Graph
- 파일명이 아니라 역할로 묶어 설명
- Entity(개념) 중심으로 관계 표현
"""

import os
import re
from pathlib import Path
from typing import List, Dict, Set, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict

from ..ARCHITECTURE import FileNode, EntityNode, SemanticGraph, FileRole


# -----------------------------------------------------------------------------
# CodeTreeParser - 폴더/파일 트리 파싱
# -----------------------------------------------------------------------------

class CodeTreeParser:
    """코드 트리 파서 - LLM 없이 기계적으로 파싱"""

    # 무시할 디렉토리
    IGNORE_DIRS = {
        'node_modules', '.git', '__pycache__', '.venv', 'venv',
        'dist', 'build', '.next', '.nuxt', 'coverage', '.idea',
        '.vscode', 'vendor', 'target', 'bin', 'obj', '.cache',
        '.pytest_cache', '.mypy_cache', 'eggs', '*.egg-info',
    }

    # 코드 파일 확장자
    CODE_EXTENSIONS = {
        '.py', '.js', '.ts', '.jsx', '.tsx', '.vue', '.svelte',
        '.java', '.kt', '.scala', '.go', '.rs', '.rb', '.php',
        '.c', '.cpp', '.h', '.hpp', '.cs', '.swift', '.m',
    }

    def __init__(self, root_path: str):
        self.root = Path(root_path).resolve()
        self.files: List[FileNode] = []

    def parse(self) -> List[FileNode]:
        """트리 파싱하여 FileNode 리스트 반환"""
        self.files = []

        for file_path in self.root.rglob('*'):
            # 무시할 디렉토리 체크
            if self._should_ignore(file_path):
                continue

            if file_path.is_file() and file_path.suffix in self.CODE_EXTENSIONS:
                node = self._parse_file(file_path)
                self.files.append(node)

        return self.files

    def _should_ignore(self, path: Path) -> bool:
        """무시할 경로인지 확인"""
        for part in path.parts:
            if part in self.IGNORE_DIRS:
                return True
            if part.startswith('.') and part not in ['.']:
                return True
        return False

    def _parse_file(self, file_path: Path) -> FileNode:
        """단일 파일 파싱"""
        rel_path = str(file_path.relative_to(self.root))

        imports = []
        exports = []
        functions = []

        try:
            content = file_path.read_text(encoding='utf-8', errors='ignore')

            # 언어별 파싱
            if file_path.suffix in ['.py']:
                imports, exports, functions = self._parse_python(content)
            elif file_path.suffix in ['.js', '.ts', '.jsx', '.tsx']:
                imports, exports, functions = self._parse_javascript(content)
            elif file_path.suffix in ['.java', '.kt']:
                imports, exports, functions = self._parse_java(content)
            elif file_path.suffix in ['.go']:
                imports, exports, functions = self._parse_go(content)

        except Exception:
            pass

        # 역할 추론
        role = self._infer_role(rel_path)

        return FileNode(
            path=rel_path,
            imports=imports,
            exports=exports,
            functions=functions,
            role=role
        )

    def _parse_python(self, content: str) -> Tuple[List[str], List[str], List[str]]:
        """Python 파일 파싱"""
        imports = []
        exports = []
        functions = []

        # import 추출
        for match in re.finditer(r'^(?:from\s+(\S+)\s+)?import\s+(.+)$', content, re.MULTILINE):
            module = match.group(1) or match.group(2).split(',')[0].strip()
            imports.append(module.split('.')[0])

        # 함수/클래스 추출
        for match in re.finditer(r'^(?:def|class)\s+(\w+)', content, re.MULTILINE):
            name = match.group(1)
            if not name.startswith('_'):
                functions.append(name)
                exports.append(name)

        return imports, exports, functions

    def _parse_javascript(self, content: str) -> Tuple[List[str], List[str], List[str]]:
        """JavaScript/TypeScript 파일 파싱"""
        imports = []
        exports = []
        functions = []

        # import 추출
        for match in re.finditer(r'import\s+.*?from\s+[\'"]([^\'"]+)[\'"]', content):
            imports.append(match.group(1).split('/')[-1])

        # require 추출
        for match in re.finditer(r'require\([\'"]([^\'"]+)[\'"]\)', content):
            imports.append(match.group(1).split('/')[-1])

        # export 추출
        for match in re.finditer(r'export\s+(?:default\s+)?(?:function|class|const|let|var)\s+(\w+)', content):
            exports.append(match.group(1))

        # 함수 추출
        for match in re.finditer(r'(?:function|const|let|var)\s+(\w+)\s*[=:]\s*(?:async\s+)?(?:function|\()', content):
            functions.append(match.group(1))

        return imports, exports, functions

    def _parse_java(self, content: str) -> Tuple[List[str], List[str], List[str]]:
        """Java/Kotlin 파일 파싱"""
        imports = []
        exports = []
        functions = []

        # import 추출
        for match in re.finditer(r'^import\s+([\w.]+);?', content, re.MULTILINE):
            parts = match.group(1).split('.')
            imports.append(parts[-1] if parts else match.group(1))

        # 클래스/인터페이스 추출
        for match in re.finditer(r'(?:public\s+)?(?:class|interface|enum)\s+(\w+)', content):
            exports.append(match.group(1))

        # 메서드 추출
        for match in re.finditer(r'(?:public|private|protected)?\s*(?:static\s+)?(?:\w+\s+)+(\w+)\s*\(', content):
            name = match.group(1)
            if name not in ['if', 'for', 'while', 'switch']:
                functions.append(name)

        return imports, exports, functions

    def _parse_go(self, content: str) -> Tuple[List[str], List[str], List[str]]:
        """Go 파일 파싱"""
        imports = []
        exports = []
        functions = []

        # import 추출
        for match in re.finditer(r'import\s+(?:\(([^)]+)\)|"([^"]+)")', content, re.DOTALL):
            if match.group(1):
                for imp in re.findall(r'"([^"]+)"', match.group(1)):
                    imports.append(imp.split('/')[-1])
            elif match.group(2):
                imports.append(match.group(2).split('/')[-1])

        # 함수 추출 (대문자 시작 = exported)
        for match in re.finditer(r'func\s+(?:\([^)]+\)\s+)?(\w+)\s*\(', content):
            name = match.group(1)
            functions.append(name)
            if name[0].isupper():
                exports.append(name)

        return imports, exports, functions

    def _infer_role(self, path: str) -> FileRole:
        """파일 역할 추론"""
        path_lower = path.lower()

        if any(k in path_lower for k in ['controller', 'route', 'handler', 'endpoint', 'api']):
            return FileRole.ENTRY
        if any(k in path_lower for k in ['service', 'usecase', 'domain', 'core', 'logic']):
            return FileRole.CORE
        if any(k in path_lower for k in ['repo', 'repository', 'dao', 'db', 'database', 'infra']):
            return FileRole.INFRA
        if any(k in path_lower for k in ['test', 'spec', '__test__']):
            return FileRole.TEST

        return FileRole.PERIPHERAL


# -----------------------------------------------------------------------------
# SemanticGraphBuilder - 의미 그래프 구축
# -----------------------------------------------------------------------------

class SemanticGraphBuilder:
    """의미 그래프 빌더 - 파일을 Entity 중심으로 묶기"""

    def __init__(self, files: List[FileNode]):
        self.files = files
        self.entities: List[EntityNode] = []
        self.graph: Optional[SemanticGraph] = None

    def build(self) -> SemanticGraph:
        """의미 그래프 구축"""
        # Entity 추출
        self.entities = self._extract_entities()

        # 엣지(관계) 연결
        self._connect_edges()

        self.graph = SemanticGraph(
            files=self.files,
            entities=self.entities,
            pattern_scores={},
            violations=[]
        )

        return self.graph

    def _extract_entities(self) -> List[EntityNode]:
        """Entity 추출 - 파일명에서 개념 추출"""
        entity_map: Dict[str, Dict[str, str]] = defaultdict(dict)

        # 역할 키워드 제거 패턴
        role_patterns = [
            r'controller', r'service', r'repository', r'repo',
            r'handler', r'model', r'entity', r'dto', r'dao',
            r'test', r'spec', r'mock', r'stub',
        ]

        for file_node in self.files:
            filename = Path(file_node.path).stem.lower()

            # 역할 키워드 제거하여 엔티티명 추출
            entity_name = filename
            for pattern in role_patterns:
                entity_name = re.sub(rf'[._-]?{pattern}[._-]?', '', entity_name)
                entity_name = re.sub(rf'{pattern}[._-]?', '', entity_name)

            entity_name = entity_name.strip('._-')
            if not entity_name:
                entity_name = filename

            # 역할 매핑
            if file_node.role:
                role_name = file_node.role.value
                entity_map[entity_name][role_name] = file_node.path

        # EntityNode 생성
        entities = []
        for name, roles in entity_map.items():
            if name and roles:
                entities.append(EntityNode(
                    name=name,
                    roles=roles,
                    edges=[]
                ))

        return entities

    def _connect_edges(self) -> None:
        """엔티티 간 관계 연결"""
        # import 기반 연결
        entity_names = {e.name.lower() for e in self.entities}

        for entity in self.entities:
            for role, file_path in entity.roles.items():
                # 해당 파일의 imports 찾기
                file_node = next(
                    (f for f in self.files if f.path == file_path),
                    None
                )
                if not file_node:
                    continue

                # import된 모듈이 다른 entity와 매칭되는지
                for imp in file_node.imports:
                    imp_lower = imp.lower()
                    for other in self.entities:
                        if other.name == entity.name:
                            continue
                        if other.name.lower() in imp_lower or imp_lower in other.name.lower():
                            if other.name not in entity.edges:
                                entity.edges.append(other.name)

    def get_summary(self) -> Dict:
        """그래프 요약"""
        if not self.graph:
            self.build()

        return {
            "file_count": len(self.files),
            "entity_count": len(self.entities),
            "entities": [
                {
                    "name": e.name,
                    "roles": list(e.roles.keys()),
                    "connections": len(e.edges)
                }
                for e in self.entities[:10]  # 상위 10개
            ],
            "role_distribution": self._get_role_distribution()
        }

    def _get_role_distribution(self) -> Dict[str, int]:
        """역할별 파일 수"""
        dist = defaultdict(int)
        for f in self.files:
            if f.role:
                dist[f.role.value] += 1
        return dict(dist)
