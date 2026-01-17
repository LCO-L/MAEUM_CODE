"""
Stream Client - 실시간 스트리밍 AI 클라이언트

Claude Code 수준의 안정적인 스트리밍:
- SSE (Server-Sent Events) 처리
- 자동 재연결
- 타임아웃 관리
- 청크 단위 콜백
- 에러 복구
"""

import os
import json
import time
import threading
import queue
from typing import Optional, Callable, Generator, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum
import requests


# =============================================================================
# Configuration
# =============================================================================

AI_SERVER_HOST = os.getenv("AI_SERVER_HOST", "localhost")
AI_SERVER_PORT = int(os.getenv("AI_SERVER_PORT", "7860"))
AI_SERVER_URL = f"http://{AI_SERVER_HOST}:{AI_SERVER_PORT}"

# 타임아웃 설정
CONNECT_TIMEOUT = 10  # 연결 타임아웃 (초)
READ_TIMEOUT = 60 * 30  # 읽기 타임아웃 (30분)
STREAM_TIMEOUT = 60 * 25  # 스트리밍 전체 타임아웃 (25분)


class StreamStatus(Enum):
    """스트리밍 상태"""
    CONNECTING = "connecting"
    STREAMING = "streaming"
    COMPLETED = "completed"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class StreamChunk:
    """스트리밍 청크"""
    content: str
    chunk_type: str = "text"  # text, code, tool_call, done
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StreamResult:
    """스트리밍 결과"""
    status: StreamStatus
    content: str = ""
    chunks: List[StreamChunk] = field(default_factory=list)
    error: Optional[str] = None
    elapsed_time: float = 0.0
    token_count: int = 0


# =============================================================================
# Stream Client
# =============================================================================

class StreamClient:
    """
    실시간 스트리밍 AI 클라이언트

    특징:
    - /api/chat/stream 엔드포인트 사용
    - SSE 파싱
    - 실시간 콜백
    - 자동 재시도
    - 안정적인 에러 처리
    """

    def __init__(
        self,
        base_url: str = None,
        connect_timeout: int = CONNECT_TIMEOUT,
        read_timeout: int = READ_TIMEOUT,
        max_retries: int = 3
    ):
        self.base_url = base_url or AI_SERVER_URL
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.max_retries = max_retries

        # 상태
        self._cancelled = False
        self._current_session = None

    def is_available(self) -> bool:
        """AI 서버 사용 가능 여부"""
        try:
            resp = requests.get(
                f"{self.base_url}/api/health",
                timeout=5
            )
            return resp.status_code == 200
        except Exception:
            # health 엔드포인트 없으면 기본 연결 테스트
            try:
                resp = requests.get(self.base_url, timeout=5)
                return resp.status_code < 500
            except Exception:
                return False

    def stream(
        self,
        message: str,
        system_prompt: str = "",
        on_chunk: Optional[Callable[[str], None]] = None,
        on_complete: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        max_tokens: int = 8192,
        temperature: float = 0.7,
        **kwargs
    ) -> StreamResult:
        """
        스트리밍 요청

        Args:
            message: 사용자 메시지
            system_prompt: 시스템 프롬프트
            on_chunk: 청크마다 호출되는 콜백
            on_complete: 완료 시 콜백
            on_error: 에러 시 콜백
            max_tokens: 최대 토큰
            temperature: 온도

        Returns:
            StreamResult
        """
        self._cancelled = False
        start_time = time.time()

        # 요청 데이터
        payload = {
            "message": message,
            "system_prompt": system_prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
            "coding_mode": True,
            **kwargs
        }

        # 재시도 루프
        last_error = None
        for attempt in range(self.max_retries):
            if self._cancelled:
                return StreamResult(
                    status=StreamStatus.CANCELLED,
                    elapsed_time=time.time() - start_time
                )

            try:
                result = self._do_stream(
                    payload, on_chunk, on_complete, on_error, start_time
                )
                return result

            except requests.exceptions.ConnectionError as e:
                last_error = f"연결 실패: {e}"
                if attempt < self.max_retries - 1:
                    time.sleep(1 * (attempt + 1))  # 점진적 대기

            except requests.exceptions.Timeout as e:
                last_error = f"타임아웃: {e}"
                break  # 타임아웃은 재시도 안 함

            except Exception as e:
                last_error = str(e)
                if attempt < self.max_retries - 1:
                    time.sleep(0.5)

        # 모든 재시도 실패
        if on_error:
            on_error(last_error)

        return StreamResult(
            status=StreamStatus.ERROR,
            error=last_error,
            elapsed_time=time.time() - start_time
        )

    def _do_stream(
        self,
        payload: dict,
        on_chunk: Optional[Callable],
        on_complete: Optional[Callable],
        on_error: Optional[Callable],
        start_time: float
    ) -> StreamResult:
        """실제 스트리밍 수행"""

        chunks = []
        full_content = ""
        token_count = 0

        # 스트리밍 요청
        with requests.post(
            f"{self.base_url}/api/chat/stream",
            json=payload,
            stream=True,
            timeout=(self.connect_timeout, self.read_timeout)
        ) as response:

            if response.status_code != 200:
                error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
                if on_error:
                    on_error(error_msg)
                return StreamResult(
                    status=StreamStatus.ERROR,
                    error=error_msg,
                    elapsed_time=time.time() - start_time
                )

            # SSE 파싱
            buffer = ""
            for raw_chunk in response.iter_content(chunk_size=None, decode_unicode=True):
                if self._cancelled:
                    return StreamResult(
                        status=StreamStatus.CANCELLED,
                        content=full_content,
                        chunks=chunks,
                        elapsed_time=time.time() - start_time,
                        token_count=token_count
                    )

                if raw_chunk:
                    buffer += raw_chunk

                    # SSE 이벤트 파싱
                    while "\n\n" in buffer or "\r\n\r\n" in buffer:
                        # 이벤트 분리
                        if "\r\n\r\n" in buffer:
                            event_str, buffer = buffer.split("\r\n\r\n", 1)
                        else:
                            event_str, buffer = buffer.split("\n\n", 1)

                        # 이벤트 처리
                        content = self._parse_sse_event(event_str)
                        if content:
                            if content == "[DONE]":
                                break

                            full_content += content
                            token_count += 1

                            chunk = StreamChunk(content=content)
                            chunks.append(chunk)

                            if on_chunk:
                                on_chunk(content)

        # 완료
        if on_complete:
            on_complete(full_content)

        return StreamResult(
            status=StreamStatus.COMPLETED,
            content=full_content,
            chunks=chunks,
            elapsed_time=time.time() - start_time,
            token_count=token_count
        )

    def _parse_sse_event(self, event_str: str) -> Optional[str]:
        """SSE 이벤트 파싱"""
        content = None

        for line in event_str.split("\n"):
            line = line.strip()

            if line.startswith("data:"):
                data = line[5:].strip()

                if data == "[DONE]":
                    return "[DONE]"

                # JSON 파싱 시도
                try:
                    parsed = json.loads(data)

                    # 다양한 형식 지원
                    if isinstance(parsed, dict):
                        content = (
                            parsed.get("content") or
                            parsed.get("text") or
                            parsed.get("delta", {}).get("content") or
                            parsed.get("choices", [{}])[0].get("delta", {}).get("content") or
                            parsed.get("response") or
                            ""
                        )
                    elif isinstance(parsed, str):
                        content = parsed

                except json.JSONDecodeError:
                    # JSON이 아니면 그냥 텍스트
                    content = data

        return content

    def cancel(self):
        """스트리밍 취소"""
        self._cancelled = True

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 8192,
        **kwargs
    ) -> str:
        """
        동기식 생성 (스트리밍 수집)

        Args:
            system_prompt: 시스템 프롬프트
            user_prompt: 사용자 프롬프트
            max_tokens: 최대 토큰

        Returns:
            str: 전체 응답
        """
        result = self.stream(
            message=user_prompt,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            **kwargs
        )

        if result.status == StreamStatus.COMPLETED:
            return result.content
        elif result.status == StreamStatus.ERROR:
            return f"[Error] {result.error}"
        elif result.status == StreamStatus.CANCELLED:
            return "[Cancelled]"
        else:
            return f"[{result.status.value}]"

    def generate_with_callback(
        self,
        system_prompt: str,
        user_prompt: str,
        on_token: Callable[[str], None],
        max_tokens: int = 8192,
        **kwargs
    ) -> StreamResult:
        """
        콜백과 함께 생성

        Args:
            system_prompt: 시스템 프롬프트
            user_prompt: 사용자 프롬프트
            on_token: 토큰마다 호출
            max_tokens: 최대 토큰

        Returns:
            StreamResult
        """
        return self.stream(
            message=user_prompt,
            system_prompt=system_prompt,
            on_chunk=on_token,
            max_tokens=max_tokens,
            **kwargs
        )


# =============================================================================
# Async Stream Client (for background tasks)
# =============================================================================

class AsyncStreamClient:
    """
    비동기 스트리밍 클라이언트

    백그라운드 작업용
    """

    def __init__(self, base_url: str = None):
        self.client = StreamClient(base_url)
        self._thread: Optional[threading.Thread] = None
        self._result_queue: queue.Queue = queue.Queue()
        self._chunk_queue: queue.Queue = queue.Queue()

    def start_stream(
        self,
        message: str,
        system_prompt: str = "",
        **kwargs
    ) -> None:
        """백그라운드 스트리밍 시작"""

        def _run():
            def on_chunk(chunk):
                self._chunk_queue.put(chunk)

            result = self.client.stream(
                message=message,
                system_prompt=system_prompt,
                on_chunk=on_chunk,
                **kwargs
            )
            self._result_queue.put(result)

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def get_chunks(self, timeout: float = 0.1) -> Generator[str, None, None]:
        """청크 가져오기 (제너레이터)"""
        while True:
            try:
                chunk = self._chunk_queue.get(timeout=timeout)
                yield chunk
            except queue.Empty:
                if not self._thread.is_alive():
                    break

    def get_result(self, timeout: float = None) -> Optional[StreamResult]:
        """최종 결과 가져오기"""
        try:
            return self._result_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def cancel(self):
        """취소"""
        self.client.cancel()

    def is_running(self) -> bool:
        """실행 중인지"""
        return self._thread is not None and self._thread.is_alive()


# =============================================================================
# Non-Streaming Fallback Client
# =============================================================================

class FallbackClient:
    """
    스트리밍 실패 시 폴백 클라이언트

    /api/chat 사용 (non-streaming)
    """

    def __init__(self, base_url: str = None):
        self.base_url = base_url or AI_SERVER_URL
        self.timeout = 60 * 25  # 25분

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 8192,
        **kwargs
    ) -> str:
        """동기식 생성"""
        try:
            payload = {
                "message": user_prompt,
                "system_prompt": system_prompt,
                "max_tokens": max_tokens,
                "coding_mode": True,
                **kwargs
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
                return f"[Error] HTTP {resp.status_code}: {resp.text[:200]}"

        except Exception as e:
            return f"[Error] {str(e)}"


# =============================================================================
# Smart Client (Auto-switch between stream and fallback)
# =============================================================================

class SmartClient:
    """
    스마트 클라이언트

    스트리밍 → 폴백 자동 전환
    """

    def __init__(self, base_url: str = None):
        self.stream_client = StreamClient(base_url)
        self.fallback_client = FallbackClient(base_url)
        self._stream_available = None

    def is_available(self) -> bool:
        """서버 사용 가능"""
        return self.stream_client.is_available()

    def _check_stream_support(self) -> bool:
        """스트리밍 지원 여부 확인"""
        if self._stream_available is not None:
            return self._stream_available

        try:
            # 짧은 테스트 요청
            result = self.stream_client.stream(
                message="test",
                system_prompt="Reply with 'ok'",
                max_tokens=10
            )
            self._stream_available = result.status == StreamStatus.COMPLETED
        except Exception:
            self._stream_available = False

        return self._stream_available

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        on_token: Optional[Callable[[str], None]] = None,
        max_tokens: int = 8192,
        **kwargs
    ) -> str:
        """
        스마트 생성

        스트리밍 가능하면 스트리밍, 아니면 폴백
        """
        if on_token and self._check_stream_support():
            # 스트리밍 모드
            result = self.stream_client.stream(
                message=user_prompt,
                system_prompt=system_prompt,
                on_chunk=on_token,
                max_tokens=max_tokens,
                **kwargs
            )

            if result.status == StreamStatus.COMPLETED:
                return result.content
            elif result.status == StreamStatus.ERROR:
                # 스트리밍 실패 → 폴백
                self._stream_available = False
                return self.fallback_client.generate(
                    system_prompt, user_prompt, max_tokens, **kwargs
                )
            else:
                return f"[{result.status.value}]"
        else:
            # 폴백 모드
            return self.fallback_client.generate(
                system_prompt, user_prompt, max_tokens, **kwargs
            )

    def stream(
        self,
        message: str,
        system_prompt: str = "",
        on_chunk: Optional[Callable[[str], None]] = None,
        **kwargs
    ) -> StreamResult:
        """직접 스트리밍"""
        return self.stream_client.stream(
            message=message,
            system_prompt=system_prompt,
            on_chunk=on_chunk,
            **kwargs
        )

    def cancel(self):
        """취소"""
        self.stream_client.cancel()


# =============================================================================
# Factory & Singleton
# =============================================================================

_default_client: Optional[SmartClient] = None


def get_client() -> SmartClient:
    """기본 클라이언트 가져오기"""
    global _default_client
    if _default_client is None:
        _default_client = SmartClient()
    return _default_client


def create_client(base_url: str = None) -> SmartClient:
    """새 클라이언트 생성"""
    return SmartClient(base_url)


# =============================================================================
# Quick Functions
# =============================================================================

def quick_generate(prompt: str, system: str = "") -> str:
    """빠른 생성"""
    return get_client().generate(system, prompt)


def quick_stream(
    prompt: str,
    system: str = "",
    on_token: Callable[[str], None] = None
) -> str:
    """빠른 스트리밍"""
    return get_client().generate(system, prompt, on_token=on_token)


def check_server() -> Dict[str, Any]:
    """서버 상태 확인"""
    client = get_client()
    available = client.is_available()

    return {
        "url": AI_SERVER_URL,
        "port": AI_SERVER_PORT,
        "available": available,
        "stream_support": client._check_stream_support() if available else False
    }
