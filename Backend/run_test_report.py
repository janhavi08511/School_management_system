"""
School Management System - Test Execution and Report Runner

Run from the Backend directory:
    python run_test_report.py --mode unit
    python run_test_report.py --mode api
    python run_test_report.py --mode all

Reports are written to Backend/tests/reports/
Requires pytest and pytest-html. The API suite additionally needs a running backend
and environment variables described in README.md.
"""
import argparse
import datetime as dt
import os
from pathlib import Path
import subprocess
import sys

BACKEND_DIR = Path(__file__).resolve().parent
TESTS_DIR = BACKEND_DIR / "tests"
REPORT_DIR = TESTS_DIR / "reports"

def main():
    parser = argparse.ArgumentParser(description="Run tests and generate HTML + JUnit reports.")
    parser.add_argument("--mode", choices=["unit", "api", "all"], default="unit",
                        help="unit excludes live test_api.py; api runs only test_api.py; all runs everything")
    parser.add_argument("--extra", nargs="*", default=[],
                        help="Optional extra pytest arguments, e.g. --extra -k payment")
    args = parser.parse_args()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")

    if args.mode == "unit":
        targets = [str(TESTS_DIR)]
        pytest_args = ["--ignore", str(TESTS_DIR / "test_api.py")]
    elif args.mode == "api":
        targets = [str(TESTS_DIR / "test_api.py")]
        pytest_args = []
    else:
        targets = [str(TESTS_DIR)]
        pytest_args = []

    html_report = REPORT_DIR / f"{args.mode}_report_{timestamp}.html"
    junit_report = REPORT_DIR / f"{args.mode}_report_{timestamp}.xml"

    command = [
        sys.executable, "-m", "pytest", *targets,
        "-v", "--tb=short",
        *pytest_args,
        f"--html={html_report}",
        "--self-contained-html",
        f"--junitxml={junit_report}",
        *args.extra,
    ]

    print("\nRunning command:\n", " ".join(command), "\n")
    result = subprocess.run(command, cwd=BACKEND_DIR)
    print("\nTest run finished.")
    print(f"HTML report:  {html_report}")
    print(f"JUnit report: {junit_report}")
    print(f"Pytest exit code: {result.returncode}")
    if result.returncode == 0:
        print("Result: PASS (all collected tests passed)")
    elif result.returncode == 1:
        print("Result: FAIL (one or more tests failed)")
    elif result.returncode == 5:
        print("Result: NO TESTS COLLECTED")
    else:
        print("Result: ERROR (collection/configuration/runtime issue)")
    sys.exit(result.returncode)

if __name__ == "__main__":
    main()
