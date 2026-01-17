#!/usr/bin/env python3
"""
MAEUM_CODE Launcher - 통합 실행 파일
=====================================

CLI와 Web IDE를 하나의 명령으로 실행

사용법:
    python launcher.py                 # 대화형 모드 선택
    python launcher.py cli             # CLI 모드
    python launcher.py ide             # Web IDE 모드
    python launcher.py both            # 둘 다 실행
    python launcher.py --help          # 도움말

옵션:
    --path, -p      프로젝트 경로 (기본: 현재 디렉토리)
    --port          IDE 포트 (기본: 8880)
    --status, -s    상태 확인
    --version, -v   버전 정보
"""

import sys
import os
import argparse
import threading
import webbrowser
import time
import signal

# 경로 설정
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

VERSION = "1.1.0"


# ============================================================
# ANSI Colors
# ============================================================

class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    RESET = '\033[0m'


def print_banner():
    """배너 출력"""
    print(f"""
{Colors.CYAN}{Colors.BOLD}
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   ███╗   ███╗ █████╗ ███████╗██╗   ██╗███╗   ███╗           ║
║   ████╗ ████║██╔══██╗██╔════╝██║   ██║████╗ ████║           ║
║   ██╔████╔██║███████║█████╗  ██║   ██║██╔████╔██║           ║
║   ██║╚██╔╝██║██╔══██║██╔══╝  ██║   ██║██║╚██╔╝██║           ║
║   ██║ ╚═╝ ██║██║  ██║███████╗╚██████╔╝██║ ╚═╝ ██║           ║
║   ╚═╝     ╚═╝╚═╝  ╚═╝╚══════╝ ╚═════╝ ╚═╝     ╚═╝           ║
║                                                              ║
║              🧠 MAEUM_CODE v{VERSION}                          ║
║         Claude Code 스타일 AI 코딩 어시스턴트               ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
{Colors.RESET}""")


def print_status():
    """상태 출력"""
    try:
        from CUSTOM.stream_client import check_server
        status = check_server()

        ai_status = f"{Colors.GREEN}✓ 온라인{Colors.RESET}" if status['available'] else f"{Colors.RED}✗ 오프라인{Colors.RESET}"
        stream_status = f"{Colors.GREEN}✓ 지원{Colors.RESET}" if status.get('stream_support') else f"{Colors.YELLOW}○ 미지원{Colors.RESET}"

        print(f"""
{Colors.BOLD}MAEUM_CODE 상태{Colors.RESET}
{'━' * 40}
AI 서버:    {status['url']}
상태:       {ai_status}
스트리밍:   {stream_status}
IDE 포트:   8880
{'━' * 40}
""")
    except Exception as e:
        print(f"{Colors.RED}상태 확인 실패: {e}{Colors.RESET}")


def run_cli(path: str):
    """CLI 실행"""
    print(f"\n{Colors.CYAN}🖥️  CLI 모드 시작...{Colors.RESET}")
    print(f"{Colors.DIM}프로젝트: {path}{Colors.RESET}\n")

    try:
        from CUSTOM.cli_enhanced import EnhancedCLI
        cli = EnhancedCLI(path)
        cli.run()
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}CLI 종료{Colors.RESET}")
    except Exception as e:
        print(f"{Colors.RED}CLI 오류: {e}{Colors.RESET}")


def run_ide(path: str, port: int = 8880):
    """IDE 실행 - 브라우저 자동 열기 & 닫으면 자동 종료"""
    try:
        from CUSTOM.ide_server import IDEServer
        server = IDEServer(path)
        server.run(host="127.0.0.1", port=port, auto_shutdown=True)
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}IDE 종료{Colors.RESET}")
    except Exception as e:
        print(f"{Colors.RED}IDE 오류: {e}{Colors.RESET}")


def run_both(path: str, port: int = 8880):
    """CLI와 IDE 동시 실행"""
    print(f"\n{Colors.CYAN}🚀 CLI + Web IDE 동시 시작...{Colors.RESET}")
    print(f"{Colors.DIM}프로젝트: {path}{Colors.RESET}")
    print(f"{Colors.DIM}IDE URL: http://localhost:{port}{Colors.RESET}\n")

    # IDE를 백그라운드 스레드에서 실행
    def run_ide_background():
        try:
            from CUSTOM.ide_server import IDEServer
            import uvicorn

            server = IDEServer(path)
            # uvicorn을 직접 실행 (log_level을 warning으로)
            uvicorn.run(server.app, host="127.0.0.1", port=port, log_level="warning")
        except Exception as e:
            print(f"{Colors.RED}IDE 오류: {e}{Colors.RESET}")

    ide_thread = threading.Thread(target=run_ide_background, daemon=True)
    ide_thread.start()

    # 브라우저 열기
    time.sleep(1.5)
    webbrowser.open(f"http://localhost:{port}")

    print(f"{Colors.GREEN}✓ Web IDE가 백그라운드에서 실행 중입니다.{Colors.RESET}")
    print(f"{Colors.DIM}  브라우저에서 http://localhost:{port} 열림{Colors.RESET}\n")

    # CLI 실행 (메인 스레드)
    run_cli(path)


def interactive_mode(path: str, port: int = 8880):
    """대화형 모드 선택"""
    print_banner()

    print(f"""
{Colors.BOLD}실행 모드를 선택하세요:{Colors.RESET}

  {Colors.CYAN}[1]{Colors.RESET} 🖥️  CLI 모드
      터미널에서 AI와 대화하며 코딩

  {Colors.CYAN}[2]{Colors.RESET} 🌐 Web IDE 모드
      브라우저에서 VS Code 스타일 IDE 사용

  {Colors.CYAN}[3]{Colors.RESET} 🚀 둘 다 실행
      IDE는 백그라운드, CLI는 터미널에서

  {Colors.CYAN}[4]{Colors.RESET} 📊 상태 확인
      AI 서버 연결 상태 확인

  {Colors.CYAN}[q]{Colors.RESET} 종료

""")

    while True:
        try:
            choice = input(f"{Colors.BOLD}선택 (1-4, q): {Colors.RESET}").strip().lower()

            if choice == '1' or choice == 'cli':
                run_cli(path)
                break
            elif choice == '2' or choice == 'ide':
                run_ide(path, port)
                break
            elif choice == '3' or choice == 'both':
                run_both(path, port)
                break
            elif choice == '4' or choice == 'status':
                print_status()
            elif choice == 'q' or choice == 'quit' or choice == 'exit':
                print(f"{Colors.DIM}종료합니다.{Colors.RESET}")
                break
            else:
                print(f"{Colors.YELLOW}1, 2, 3, 4 또는 q를 입력하세요.{Colors.RESET}")

        except KeyboardInterrupt:
            print(f"\n{Colors.DIM}종료합니다.{Colors.RESET}")
            break
        except EOFError:
            break


def main():
    """메인 진입점"""
    parser = argparse.ArgumentParser(
        description="MAEUM_CODE - AI 코딩 어시스턴트 통합 런처",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
실행 모드:
    cli         터미널 CLI 모드
    ide         웹 IDE 모드 (브라우저)
    both        CLI + IDE 동시 실행

예시:
    python launcher.py                    대화형 모드 선택
    python launcher.py cli                CLI 모드
    python launcher.py ide                Web IDE 모드
    python launcher.py both               둘 다 실행
    python launcher.py ide -p ~/project   특정 프로젝트
    python launcher.py --status           상태 확인
"""
    )

    parser.add_argument(
        "mode",
        nargs="?",
        choices=["cli", "ide", "both"],
        help="실행 모드 (cli/ide/both)"
    )

    parser.add_argument(
        "--path", "-p",
        default=".",
        help="프로젝트 경로 (기본: 현재 디렉토리)"
    )

    parser.add_argument(
        "--port",
        type=int,
        default=8880,
        help="IDE 포트 (기본: 8880)"
    )

    parser.add_argument(
        "--status", "-s",
        action="store_true",
        help="상태 확인"
    )

    parser.add_argument(
        "--version", "-v",
        action="store_true",
        help="버전 정보"
    )

    args = parser.parse_args()

    # 버전 출력
    if args.version:
        print_banner()
        print(f"""
{Colors.BOLD}기능:{Colors.RESET}
  - 실시간 AI 스트리밍 응답
  - 강화된 코드/파일/심볼 검색
  - 대규모 코드 작업
  - 안전한 파일 조작 (Undo/Redo)
  - 프로젝트 인덱싱
  - Monaco Editor 기반 Web IDE

{Colors.BOLD}서버:{Colors.RESET}
  AI:  http://localhost:7860
  IDE: http://localhost:8880
""")
        return

    # 상태 확인
    if args.status:
        print_banner()
        print_status()
        return

    # 경로 확인
    path = os.path.abspath(args.path)
    if not os.path.exists(path):
        print(f"{Colors.RED}오류: 경로가 존재하지 않습니다: {path}{Colors.RESET}")
        sys.exit(1)

    if not os.path.isdir(path):
        print(f"{Colors.RED}오류: 디렉토리가 아닙니다: {path}{Colors.RESET}")
        sys.exit(1)

    # 모드 실행
    if args.mode == "cli":
        print_banner()
        run_cli(path)
    elif args.mode == "ide":
        print_banner()
        run_ide(path, args.port)
    elif args.mode == "both":
        print_banner()
        run_both(path, args.port)
    else:
        # 대화형 모드
        interactive_mode(path, args.port)


if __name__ == "__main__":
    main()
