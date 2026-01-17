"""
ErrorCutAnalyzer - 에러 원인 1 + 조치 1

출력:
    [ERROR]
    원인: <most likely 1>
    조치: <one action 1>

원인 후보를 나열하지 마라.
"""

import re
from typing import Tuple, Optional
from dataclasses import dataclass


@dataclass
class ErrorResult:
    """에러 분석 결과"""
    cause: str
    action: str
    error_type: str
    file_hint: Optional[str] = None
    line_hint: Optional[int] = None


class ErrorCutAnalyzer:
    """에러 분석기 - 시그니처 룰 기반"""

    # 에러 시그니처 → (원인, 조치) 매핑
    ERROR_SIGNATURES = {
        # Python
        'ModuleNotFoundError': ('모듈 없음', 'pip install로 설치'),
        'ImportError': ('임포트 실패', '패키지 설치 또는 경로 확인'),
        'NameError': ('정의되지 않은 변수/함수', '변수 선언 또는 import 확인'),
        'TypeError': ('타입 불일치', '인자 타입 확인'),
        'ValueError': ('값 오류', '입력값 검증'),
        'KeyError': ('딕셔너리 키 없음', '키 존재 확인 후 접근'),
        'IndexError': ('인덱스 범위 초과', '리스트 길이 확인'),
        'AttributeError': ('속성/메서드 없음', '객체 타입 확인'),
        'FileNotFoundError': ('파일 없음', '경로 확인'),
        'PermissionError': ('권한 없음', '파일 권한 확인'),
        'SyntaxError': ('문법 오류', '해당 라인 문법 수정'),
        'IndentationError': ('들여쓰기 오류', '들여쓰기 통일'),
        'ZeroDivisionError': ('0으로 나눔', '분모 검증 추가'),
        'RecursionError': ('재귀 한도 초과', '재귀 종료 조건 확인'),
        'ConnectionError': ('연결 실패', '네트워크/서버 상태 확인'),
        'TimeoutError': ('타임아웃', '타임아웃 설정 또는 최적화'),

        # JavaScript/TypeScript
        'ReferenceError': ('정의되지 않은 참조', '변수 선언 확인'),
        'SyntaxError: Unexpected token': ('문법 오류', 'JSON 또는 구문 확인'),
        'Cannot read property': ('undefined 접근', 'null 체크 추가'),
        'Cannot read properties of undefined': ('undefined 접근', '옵셔널 체이닝 사용'),
        'is not a function': ('함수 아님', 'import 또는 타입 확인'),
        'is not defined': ('정의되지 않음', 'import 또는 선언 확인'),
        'ENOENT': ('파일/경로 없음', '경로 확인'),
        'ECONNREFUSED': ('연결 거부됨', '서버 실행 확인'),
        'EADDRINUSE': ('포트 사용 중', '포트 변경 또는 기존 프로세스 종료'),

        # Java
        'NullPointerException': ('null 참조', 'null 체크 추가'),
        'ClassNotFoundException': ('클래스 없음', '클래스패스 확인'),
        'NoSuchMethodError': ('메서드 없음', '버전 호환성 확인'),
        'OutOfMemoryError': ('메모리 부족', '힙 사이즈 증가'),
        'StackOverflowError': ('스택 오버플로우', '재귀 종료 조건 확인'),

        # Database
        'SQLITE_CONSTRAINT': ('제약조건 위반', 'UNIQUE/NOT NULL 조건 확인'),
        'duplicate key': ('중복 키', '기존 데이터 확인 후 처리'),
        'foreign key constraint': ('외래키 제약', '참조 데이터 존재 확인'),

        # Network
        '404': ('리소스 없음', 'URL 경로 확인'),
        '500': ('서버 에러', '서버 로그 확인'),
        '401': ('인증 실패', '인증 토큰 확인'),
        '403': ('권한 없음', '권한 설정 확인'),
        'CORS': ('CORS 에러', '서버 CORS 설정 추가'),
    }

    def analyze(self, error_text: str) -> ErrorResult:
        """에러 텍스트 분석"""
        # 1. 시그니처 매칭
        cause, action = self._match_signature(error_text)

        # 2. 에러 타입 추출
        error_type = self._extract_error_type(error_text)

        # 3. 파일/라인 힌트 추출
        file_hint, line_hint = self._extract_location(error_text)

        return ErrorResult(
            cause=cause,
            action=action,
            error_type=error_type,
            file_hint=file_hint,
            line_hint=line_hint
        )

    def _match_signature(self, text: str) -> Tuple[str, str]:
        """시그니처 매칭"""
        text_lower = text.lower()

        for signature, (cause, action) in self.ERROR_SIGNATURES.items():
            if signature.lower() in text_lower:
                return (cause, action)

        # 매칭 실패 시 기본값
        return ('알 수 없는 에러', '에러 메시지 상세 확인')

    def _extract_error_type(self, text: str) -> str:
        """에러 타입 추출"""
        # Python 스타일: ErrorType: message
        match = re.search(r'(\w+Error|\w+Exception):', text)
        if match:
            return match.group(1)

        # JavaScript 스타일: Error: message
        match = re.search(r'(Error|TypeError|ReferenceError):', text)
        if match:
            return match.group(1)

        return 'Unknown'

    def _extract_location(self, text: str) -> Tuple[Optional[str], Optional[int]]:
        """파일/라인 위치 추출"""
        file_hint = None
        line_hint = None

        # Python: File "xxx.py", line N
        match = re.search(r'File "([^"]+)", line (\d+)', text)
        if match:
            file_hint = match.group(1)
            line_hint = int(match.group(2))
            return (file_hint, line_hint)

        # JavaScript: at xxx (file:line:col)
        match = re.search(r'at .+\((.+):(\d+):\d+\)', text)
        if match:
            file_hint = match.group(1)
            line_hint = int(match.group(2))
            return (file_hint, line_hint)

        # 일반 경로:라인 패턴
        match = re.search(r'([/\w.-]+\.\w+):(\d+)', text)
        if match:
            file_hint = match.group(1)
            line_hint = int(match.group(2))

        return (file_hint, line_hint)

    def format_output(self, result: ErrorResult) -> str:
        """고정 포맷 출력"""
        output = f"""[ERROR]
원인: {result.cause}
조치: {result.action}"""

        if result.file_hint:
            output += f"\n위치: {result.file_hint}"
            if result.line_hint:
                output += f":{result.line_hint}"

        return output
