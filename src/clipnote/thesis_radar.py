"""CLI-only investment claim extraction built on the shared Clipnote pipeline."""
import argparse
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(
        description="공개 YouTube 투자 콘텐츠에서 검증 가능한 주장 후보를 추출합니다.")
    parser.add_argument("url")
    parser.add_argument("--language", default="ko")
    parser.add_argument("--model", default="gemini-flash-lite-latest")
    parser.add_argument("--max-claims", type=int, default=20)
    parser.add_argument(
        "--max-duration",
        type=int,
        help="기본 3600초 상한을 명시적으로 변경")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    command = [
        sys.executable, "-m", "clipnote.pipeline", args.url,
        "--profile", "investment_claims",
        "--language", args.language,
        "--model", args.model,
        "--max-claims", str(args.max_claims),
        "--links-only",
    ]
    if args.force:
        command.append("--force")
    if args.max_duration is not None:
        command += ["--max-duration", str(args.max_duration)]
    result = subprocess.run(command)
    if result.returncode != 0:
        sys.exit(result.returncode)


if __name__ == "__main__":
    main()
