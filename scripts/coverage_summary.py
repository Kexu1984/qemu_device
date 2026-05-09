#!/usr/bin/env python3
"""
Firmware coverage summary generator.

This script reads sw_qa/test_matrix.yaml, scans e2e log artifacts for each
test's expected evidence strings, and writes a machine-readable summary plus a
small HTML report. It is intended as the first method-proof layer before source
line/function coverage is wired in.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    sys.exit(
        "ERROR: PyYAML is not installed. Run: pip install pyyaml\n"
        "       or:                          pip3 install pyyaml"
    )


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        data = yaml.safe_load(stream)
    if not isinstance(data, dict):
        raise ValueError(f"matrix must be a YAML mapping: {path}")
    return data


def read_evidence_logs(paths: list[Path]) -> tuple[str, list[dict[str, Any]]]:
    chunks: list[str] = []
    log_status: list[dict[str, Any]] = []

    for path in paths:
        entry: dict[str, Any] = {"path": path.as_posix(), "exists": path.exists()}
        if path.exists():
            text = path.read_text(encoding="utf-8", errors="replace")
            entry["bytes"] = len(text.encode("utf-8", errors="replace"))
            chunks.append(text)
        else:
            entry["bytes"] = 0
        log_status.append(entry)

    return "\n".join(chunks), log_status


def classify_test(test: dict[str, Any], evidence_text: str) -> dict[str, Any]:
    expected_raw = test.get("expected_log", [])
    if not isinstance(expected_raw, list):
        raise ValueError(f"{test.get('test_id')}: expected_log must be a list")
    for item in expected_raw:
        if not isinstance(item, str):
            raise ValueError(
                f"{test.get('test_id')}: expected_log entries must be strings; "
                "quote YAML values that contain ':'"
            )
    expected = expected_raw
    found = [item for item in expected if item in evidence_text]
    missing = [item for item in expected if item not in evidence_text]
    status = "pass" if expected and not missing else "fail"

    return {
        "test_id": test.get("test_id"),
        "requirement": test.get("requirement"),
        "module": test.get("module"),
        "scenario": test.get("scenario"),
        "priority": test.get("initial_priority", "P2"),
        "coverage_type": test.get("coverage_type", []),
        "expected_log_count": len(expected),
        "found_log": found,
        "missing_log": missing,
        "status": status,
    }


def summarize_requirements(
    requirements: list[dict[str, Any]], test_results: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    tests_by_req: dict[str, list[dict[str, Any]]] = {}
    for result in test_results:
        req_id = str(result.get("requirement") or "")
        tests_by_req.setdefault(req_id, []).append(result)

    summaries: list[dict[str, Any]] = []
    for req in requirements:
        req_id = str(req.get("id"))
        linked_tests = tests_by_req.get(req_id, [])
        passed = [item for item in linked_tests if item["status"] == "pass"]
        failed = [item for item in linked_tests if item["status"] != "pass"]
        status = "pass" if linked_tests and not failed else "fail"
        summaries.append(
            {
                "id": req_id,
                "title": req.get("title"),
                "module": req.get("module"),
                "linked_tests": [item["test_id"] for item in linked_tests],
                "passed_tests": [item["test_id"] for item in passed],
                "failed_tests": [item["test_id"] for item in failed],
                "status": status,
            }
        )

    return summaries


def pct(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round((numerator * 100.0) / denominator, 2)


def make_summary(matrix: dict[str, Any], evidence_text: str, log_status: list[dict[str, Any]]) -> dict[str, Any]:
    tests = matrix.get("tests", [])
    requirements = matrix.get("requirements", [])
    if not isinstance(tests, list):
        raise ValueError("matrix field 'tests' must be a list")
    if not isinstance(requirements, list):
        raise ValueError("matrix field 'requirements' must be a list")

    test_results = [classify_test(test, evidence_text) for test in tests]
    requirement_results = summarize_requirements(requirements, test_results)

    tests_passed = sum(1 for item in test_results if item["status"] == "pass")
    reqs_passed = sum(1 for item in requirement_results if item["status"] == "pass")
    p0_p1 = [item for item in test_results if item.get("priority") in {"P0", "P1"}]
    p0_p1_passed = sum(1 for item in p0_p1 if item["status"] == "pass")

    overall_status = "pass" if p0_p1 and p0_p1_passed == len(p0_p1) else "fail"

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "matrix_version": matrix.get("version"),
        "purpose": matrix.get("purpose"),
        "scope": matrix.get("scope", {}),
        "execution": matrix.get("execution", {}),
        "overall_status": overall_status,
        "metrics": {
            "tests_total": len(test_results),
            "tests_passed": tests_passed,
            "tests_failed": len(test_results) - tests_passed,
            "test_pass_rate_percent": pct(tests_passed, len(test_results)),
            "requirements_total": len(requirement_results),
            "requirements_passed": reqs_passed,
            "requirements_failed": len(requirement_results) - reqs_passed,
            "requirement_coverage_percent": pct(reqs_passed, len(requirement_results)),
            "p0_p1_tests_total": len(p0_p1),
            "p0_p1_tests_passed": p0_p1_passed,
            "p0_p1_pass_rate_percent": pct(p0_p1_passed, len(p0_p1)),
        },
        "logs": log_status,
        "requirements": requirement_results,
        "tests": test_results,
    }


def write_json(summary: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def status_class(status: str) -> str:
    return "pass" if status == "pass" else "fail"


def write_html(summary: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    metrics = summary["metrics"]

    req_rows = []
    for req in summary["requirements"]:
        req_rows.append(
            "<tr>"
            f"<td>{html.escape(str(req['id']))}</td>"
            f"<td>{html.escape(str(req.get('module', '')))}</td>"
            f"<td>{html.escape(str(req.get('title', '')))}</td>"
            f"<td>{html.escape(', '.join(str(x) for x in req.get('linked_tests', [])))}</td>"
            f"<td class='{status_class(req['status'])}'>{html.escape(req['status'].upper())}</td>"
            "</tr>"
        )

    test_rows = []
    for test in summary["tests"]:
        missing = "<br>".join(html.escape(str(item)) for item in test.get("missing_log", []))
        if not missing:
            missing = "-"
        test_rows.append(
            "<tr>"
            f"<td>{html.escape(str(test['test_id']))}</td>"
            f"<td>{html.escape(str(test.get('module', '')))}</td>"
            f"<td>{html.escape(str(test.get('priority', '')))}</td>"
            f"<td>{html.escape(str(test.get('scenario', '')))}</td>"
            f"<td class='{status_class(test['status'])}'>{html.escape(test['status'].upper())}</td>"
            f"<td>{missing}</td>"
            "</tr>"
        )

    log_rows = []
    for log in summary["logs"]:
        exists = "yes" if log.get("exists") else "no"
        log_rows.append(
            "<tr>"
            f"<td>{html.escape(log['path'])}</td>"
            f"<td>{exists}</td>"
            f"<td>{log.get('bytes', 0)}</td>"
            "</tr>"
        )

    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>KX6625 Firmware Coverage Summary</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #202124; }}
    h1, h2 {{ margin-bottom: 8px; }}
    .summary {{ display: grid; grid-template-columns: repeat(4, minmax(140px, 1fr)); gap: 12px; margin: 16px 0 24px; }}
    .metric {{ border: 1px solid #dadce0; border-radius: 6px; padding: 12px; }}
    .metric strong {{ display: block; font-size: 24px; margin-top: 6px; }}
    table {{ border-collapse: collapse; width: 100%; margin-bottom: 28px; }}
    th, td {{ border: 1px solid #dadce0; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f8f9fa; }}
    .pass {{ color: #137333; font-weight: 700; }}
    .fail {{ color: #b3261e; font-weight: 700; }}
  </style>
</head>
<body>
  <h1>KX6625 Firmware Coverage Summary</h1>
  <p>Generated at {html.escape(summary['generated_at'])}</p>
  <p>Overall status: <span class="{status_class(summary['overall_status'])}">{html.escape(summary['overall_status'].upper())}</span></p>

  <section class="summary">
    <div class="metric">Requirement coverage<strong>{metrics['requirement_coverage_percent']}%</strong></div>
    <div class="metric">Test pass rate<strong>{metrics['test_pass_rate_percent']}%</strong></div>
    <div class="metric">P0/P1 pass rate<strong>{metrics['p0_p1_pass_rate_percent']}%</strong></div>
    <div class="metric">Failed tests<strong>{metrics['tests_failed']}</strong></div>
  </section>

  <h2>Requirements</h2>
  <table>
    <thead><tr><th>ID</th><th>Module</th><th>Title</th><th>Linked Tests</th><th>Status</th></tr></thead>
    <tbody>{''.join(req_rows)}</tbody>
  </table>

  <h2>Tests</h2>
  <table>
    <thead><tr><th>ID</th><th>Module</th><th>Priority</th><th>Scenario</th><th>Status</th><th>Missing Evidence</th></tr></thead>
    <tbody>{''.join(test_rows)}</tbody>
  </table>

  <h2>Evidence Logs</h2>
  <table>
    <thead><tr><th>Path</th><th>Exists</th><th>Bytes</th></tr></thead>
    <tbody>{''.join(log_rows)}</tbody>
  </table>
</body>
</html>
"""
    path.write_text(document, encoding="utf-8")


def default_log_paths(matrix: dict[str, Any], repo_root: Path) -> list[Path]:
    execution = matrix.get("execution", {})
    paths = execution.get("evidence_logs", []) if isinstance(execution, dict) else []
    return [(repo_root / str(item)).resolve() for item in paths]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate firmware coverage summary from e2e logs.")
    parser.add_argument("--matrix", default="sw_qa/test_matrix.yaml", help="Path to the YAML test matrix.")
    parser.add_argument("--log", action="append", dest="logs", help="Evidence log path. Can be repeated. Defaults to matrix execution.evidence_logs.")
    parser.add_argument("--out", default="build/coverage/summary.json", help="Output JSON summary path.")
    parser.add_argument("--html", default="build/coverage/summary.html", help="Output HTML summary path.")
    parser.add_argument("--trend-only", action="store_true", help="Always exit 0 after writing reports, even if coverage checks fail.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    matrix_path = (repo_root / args.matrix).resolve()
    output_path = (repo_root / args.out).resolve()
    html_path = (repo_root / args.html).resolve()

    matrix = load_yaml(matrix_path)
    log_paths = [(repo_root / item).resolve() for item in args.logs] if args.logs else default_log_paths(matrix, repo_root)
    evidence_text, log_status = read_evidence_logs(log_paths)
    summary = make_summary(matrix, evidence_text, log_status)

    write_json(summary, output_path)
    write_html(summary, html_path)

    metrics = summary["metrics"]
    print(f"summary json: {output_path.relative_to(repo_root)}")
    print(f"summary html: {html_path.relative_to(repo_root)}")
    print(
        "requirements: "
        f"{metrics['requirements_passed']}/{metrics['requirements_total']} "
        f"({metrics['requirement_coverage_percent']}%)"
    )
    print(
        "tests: "
        f"{metrics['tests_passed']}/{metrics['tests_total']} "
        f"({metrics['test_pass_rate_percent']}%)"
    )
    print(f"overall: {summary['overall_status'].upper()}")

    if args.trend_only:
        return 0
    return 0 if summary["overall_status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())