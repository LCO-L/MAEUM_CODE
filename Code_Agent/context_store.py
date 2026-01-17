"""
ContextStore - 맥락 상태 저장 (세션 단위)

핵심:
- CONTEXT_SET은 무출력 (상태만 바꿈)
- 다음 ERROR/PATH/ARCH 분석에만 영향
- 세션 단위로 유지
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional
from datetime import datetime
import json
import os

from .ARCHITECTURE import Phase, Tolerance, ContextState


# -----------------------------------------------------------------------------
# ContextStore
# -----------------------------------------------------------------------------
class ContextStore:
    """맥락 상태 저장소"""

    def __init__(self, persist_path: Optional[str] = None):
        self.sessions: Dict[str, ContextState] = {}
        self.current_session_id: Optional[str] = None
        self.persist_path = persist_path

        if persist_path and os.path.exists(persist_path):
            self._load()

    def new_session(self, session_id: Optional[str] = None) -> str:
        """새 세션 생성"""
        if session_id is None:
            session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        self.sessions[session_id] = ContextState()
        self.current_session_id = session_id
        return session_id

    def get_current(self) -> ContextState:
        """현재 세션 상태"""
        if self.current_session_id is None:
            self.new_session()
        return self.sessions[self.current_session_id]

    def set_phase(self, phase: Phase) -> None:
        """단계 설정"""
        state = self.get_current()
        state.phase = phase

        # 단계에 따른 자동 tolerance 조정
        if phase == Phase.MVP:
            state.tolerance = Tolerance.HIGH
        elif phase == Phase.EXPERIMENT:
            state.tolerance = Tolerance.HIGH
        elif phase == Phase.REFACTOR:
            state.tolerance = Tolerance.MEDIUM
        elif phase == Phase.STABILIZE:
            state.tolerance = Tolerance.LOW

        self._persist()

    def set_tolerance(self, tolerance: Tolerance) -> None:
        """허용 수준 설정"""
        state = self.get_current()
        state.tolerance = tolerance
        self._persist()

    def add_note(self, note: str) -> None:
        """노트 추가"""
        state = self.get_current()
        state.notes.append(note)
        # 최대 10개만 유지
        state.notes = state.notes[-10:]
        self._persist()

    def clear_notes(self) -> None:
        """노트 초기화"""
        state = self.get_current()
        state.notes = []
        self._persist()

    def update_from_text(self, text: str) -> None:
        """
        텍스트에서 맥락 추출하여 업데이트

        예: "지금 MVP, 빨리 돌아가게" → phase=MVP, tolerance=HIGH
        """
        text_lower = text.lower()

        # Phase 추론
        if any(k in text_lower for k in ['mvp', '빨리', '급함', '당장', 'urgent']):
            self.set_phase(Phase.MVP)
        elif any(k in text_lower for k in ['실험', 'experiment', '프로토타입', 'prototype']):
            self.set_phase(Phase.EXPERIMENT)
        elif any(k in text_lower for k in ['리팩토링', 'refactor', '정리']):
            self.set_phase(Phase.REFACTOR)
        elif any(k in text_lower for k in ['안정', 'stable', '배포', 'deploy', 'production']):
            self.set_phase(Phase.STABILIZE)

        # Tolerance 명시적 조정
        if any(k in text_lower for k in ['엄격', 'strict', '조심', 'careful']):
            self.set_tolerance(Tolerance.LOW)
        elif any(k in text_lower for k in ['자유', 'free', '허용', 'allow']):
            self.set_tolerance(Tolerance.HIGH)

        # 노트로 원문 저장
        self.add_note(text[:100])

    def _persist(self) -> None:
        """파일로 저장"""
        if not self.persist_path:
            return

        data = {}
        for sid, state in self.sessions.items():
            data[sid] = {
                "phase": state.phase.value,
                "tolerance": state.tolerance.value,
                "notes": state.notes
            }

        with open(self.persist_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load(self) -> None:
        """파일에서 로드"""
        if not self.persist_path or not os.path.exists(self.persist_path):
            return

        try:
            with open(self.persist_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            for sid, state_data in data.items():
                self.sessions[sid] = ContextState(
                    phase=Phase(state_data.get("phase", "MVP")),
                    tolerance=Tolerance(state_data.get("tolerance", "HIGH")),
                    notes=state_data.get("notes", [])
                )

            # 가장 최근 세션을 current로
            if self.sessions:
                self.current_session_id = list(self.sessions.keys())[-1]

        except (json.JSONDecodeError, KeyError):
            pass  # 손상된 파일 무시

    def update(self, phase: Phase, tolerance: Tolerance, note: str = None) -> None:
        """직접 업데이트"""
        state = self.get_current()
        state.phase = phase
        state.tolerance = tolerance
        if note:
            self.add_note(note[:100])
        self._persist()

    def to_dict(self) -> dict:
        """현재 상태를 dict로"""
        state = self.get_current()
        return {
            "session_id": self.current_session_id,
            "phase": state.phase.value,
            "tolerance": state.tolerance.value,
            "notes": state.notes
        }

    def __repr__(self) -> str:
        state = self.get_current()
        return f"ContextStore(phase={state.phase.value}, tolerance={state.tolerance.value})"
