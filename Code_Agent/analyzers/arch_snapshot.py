"""
ArchSnapshotAnalyzer - 트리/레포 구조 스냅샷

출력 (4줄 제한):
    [SNAPSHOT]
    Core: <top domains 1~3>
    Flow: <dominant flow>
    State: <phase>

설명/개선 제안 금지 - "상태판"만
"""

import os
import re
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from collections import Counter
from pathlib import Path


@dataclass
class SnapshotResult:
    """스냅샷 결과"""
    core_domains: List[str]
    flow: str
    state: str
    file_count: int
    folder_count: int


class ArchSnapshotAnalyzer:
    """구조 스냅샷 분석기"""

    # 무시할 폴더
    IGNORE_DIRS = {
        'node_modules', '.git', '__pycache__', '.venv', 'venv',
        'dist', 'build', '.next', '.nuxt', 'coverage', '.idea',
        '.vscode', 'vendor', 'target', 'bin', 'obj'
    }

    # 도메인 키워드 -> 역할 매핑
    DOMAIN_KEYWORDS = {
        'controller': 'entry',
        'route': 'entry',
        'handler': 'entry',
        'api': 'entry',
        'service': 'core',
        'usecase': 'core',
        'domain': 'core',
        'model': 'model',
        'entity': 'model',
        'schema': 'model',
        'repo': 'infra',
        'repository': 'infra',
        'db': 'infra',
        'database': 'infra',
        'infra': 'infra',
        'util': 'util',
        'utils': 'util',
        'helper': 'util',
        'common': 'util',
        'test': 'test',
        'tests': 'test',
        'spec': 'test',
        '__test__': 'test',
    }

    def analyze_path(self, root_path: str) -> SnapshotResult:
        """디렉토리 경로 분석"""
        root = Path(root_path)
        if not root.exists():
            return SnapshotResult([], "unknown", "unknown", 0, 0)

        # 파일/폴더 수집
        folders = []
        files = []

        for item in root.rglob('*'):
            # 무시 폴더 체크
            if any(ignored in item.parts for ignored in self.IGNORE_DIRS):
                continue

            if item.is_dir():
                folders.append(item)
            elif item.is_file():
                files.append(item)

        # 도메인 분석
        core_domains = self._extract_domains(folders, root)

        # 플로우 추론
        flow = self._infer_flow(core_domains)

        # 상태 추론 (파일 수 기반)
        state = self._infer_state(len(files))

        return SnapshotResult(
            core_domains=core_domains[:3],
            flow=flow,
            state=state,
            file_count=len(files),
            folder_count=len(folders)
        )

    def analyze_tree_text(self, tree_text: str) -> SnapshotResult:
        """트리 텍스트 분석 (붙여넣기)"""
        lines = tree_text.strip().split('\n')

        # 폴더/파일 추출
        folders = []
        files = []

        for line in lines:
            # 트리 기호 제거
            clean = re.sub(r'^[\s│├└─]+', '', line).strip()
            if not clean:
                continue

            if clean.endswith('/') or '.' not in clean:
                folders.append(clean.rstrip('/'))
            else:
                files.append(clean)

        # 도메인 분석
        domain_counter = Counter()
        for folder in folders:
            folder_lower = folder.lower()
            for keyword, role in self.DOMAIN_KEYWORDS.items():
                if keyword in folder_lower:
                    domain_counter[folder] += 1

        core_domains = [d for d, _ in domain_counter.most_common(3)]

        # 플로우 추론
        flow = self._infer_flow(core_domains)

        # 상태 추론
        state = self._infer_state(len(files))

        return SnapshotResult(
            core_domains=core_domains,
            flow=flow,
            state=state,
            file_count=len(files),
            folder_count=len(folders)
        )

    def _extract_domains(self, folders: List[Path], root: Path) -> List[str]:
        """핵심 도메인 추출"""
        domain_counter = Counter()

        for folder in folders:
            try:
                rel_path = folder.relative_to(root)
                depth = len(rel_path.parts)

                # 1~2 depth 폴더에 가중치
                weight = 3 if depth <= 2 else 1

                folder_name = folder.name.lower()
                for keyword, role in self.DOMAIN_KEYWORDS.items():
                    if keyword in folder_name:
                        domain_counter[folder.name] += weight

            except ValueError:
                continue

        # 상위 3개 도메인 반환
        return [d for d, _ in domain_counter.most_common(3)]

    def _infer_flow(self, domains: List[str]) -> str:
        """지배적 플로우 추론"""
        domains_lower = [d.lower() for d in domains]

        # MVC 패턴 체크
        has_controller = any('controller' in d or 'route' in d for d in domains_lower)
        has_service = any('service' in d for d in domains_lower)
        has_model = any('model' in d or 'entity' in d for d in domains_lower)

        if has_controller and has_service and has_model:
            return "MVC: controller->service->model"

        # Layered 패턴 체크
        has_api = any('api' in d or 'handler' in d for d in domains_lower)
        has_domain = any('domain' in d or 'core' in d for d in domains_lower)
        has_infra = any('infra' in d or 'repo' in d or 'db' in d for d in domains_lower)

        if has_api and has_domain and has_infra:
            return "Layered: api->domain->infra"

        # Feature-based 체크
        if len(domains) >= 2:
            return f"Feature-based: {', '.join(domains[:2])}"

        return "unknown"

    def _infer_state(self, file_count: int) -> str:
        """프로젝트 상태 추론"""
        if file_count < 20:
            return "MVP/Prototype"
        elif file_count < 100:
            return "Early Development"
        elif file_count < 500:
            return "Active Development"
        else:
            return "Mature"

    def format_output(self, result: SnapshotResult) -> str:
        """고정 포맷 출력"""
        core_str = ', '.join(result.core_domains) if result.core_domains else 'unknown'

        return f"""[SNAPSHOT]
Core: {core_str}
Flow: {result.flow}
State: {result.state}"""
