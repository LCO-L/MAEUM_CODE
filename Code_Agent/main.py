#!/usr/bin/env python3
"""
MAEUM_CODE - Claude Code 스타일 AI 코딩 어시스턴트

실행 방법:
    python main.py                    # 현재 디렉토리에서 시작
    python main.py /path/to/project   # 특정 경로에서 시작
    python main.py --status           # 서버 상태 확인
    python main.py --help             # 도움말

    # 또는 모듈로 실행
    python -m CUSTOM.main

AI 서버:
    포트 7860에서 /api/chat/stream 엔드포인트 사용
    스트리밍이 지원되지 않으면 /api/chat으로 폴백
"""

import sys
import os

# 경로 설정
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)


def main():
    """메인 진입점"""
    from CUSTOM.cli_enhanced import EnhancedCLI, check_server
    import argparse

    parser = argparse.ArgumentParser(
        description="MAEUM_CODE - AI 코딩 어시스턴트",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
    python main.py                    현재 디렉토리에서 시작
    python main.py ~/myproject        특정 프로젝트에서 시작
    python main.py --status           AI 서버 상태 확인

명령어 (/help로 전체 목록):
    /search <쿼리>    코드 검색
    /find <패턴>      파일 찾기
    /symbol <이름>    심볼 찾기
    /undo            마지막 변경 취소
    /redo            다시 실행
    /history         변경 이력
    /q               종료
"""
    )

    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="프로젝트 경로 (기본: 현재 디렉토리)"
    )

    parser.add_argument(
        "--status", "-s",
        action="store_true",
        help="AI 서버 상태 확인"
    )

    parser.add_argument(
        "--version", "-v",
        action="store_true",
        help="버전 정보"
    )

    parser.add_argument(
        "--legacy",
        action="store_true",
        help="기존 CLI 사용 (cli.py)"
    )

    args = parser.parse_args()

    # 버전
    if args.version:
        print("""
MAEUM_CODE v1.0.0
━━━━━━━━━━━━━━━━━━
Claude Code 스타일 AI 코딩 어시스턴트

- 실시간 스트리밍 응답
- 강화된 코드/파일/심볼 검색
- 대규모 코드 작업
- 안전한 파일 조작 (Undo/Redo)
- 프로젝트 인덱싱

AI 서버: http://localhost:7860
""")
        return

    # 상태 확인
    if args.status:
        status = check_server()
        available = "✓ 온라인" if status['available'] else "✗ 오프라인"
        stream = "✓ 지원" if status.get('stream_support') else "○ 미지원"

        print(f"""
MAEUM_CODE 상태
━━━━━━━━━━━━━━━━
AI 서버: {status['url']}
상태:    {available}
스트리밍: {stream}
""")
        return

    # 기존 CLI
    if args.legacy:
        from CUSTOM.cli import main as legacy_main
        legacy_main()
        return

    # 경로 확인
    path = os.path.abspath(args.path)
    if not os.path.exists(path):
        print(f"오류: 경로가 존재하지 않습니다: {path}")
        sys.exit(1)

    if not os.path.isdir(path):
        print(f"오류: 디렉토리가 아닙니다: {path}")
        sys.exit(1)

    # CLI 실행
    cli = EnhancedCLI(path)
    cli.run()


if __name__ == "__main__":
    main()
