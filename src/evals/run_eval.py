"""Run the agent against the labeled test case set and score detection accuracy.

For each test case, this script:
  1. Invokes the agent on the test case's query
  2. Extracts the structured findings from the agent's response
  3. Compares the findings to the test case's expected outcome
  4. Records pass/fail with diagnostic information

Outputs:
  - evals/results/run_<timestamp>.json    Full per-case results
  - Console summary with precision/recall by category

Run with:
    uv run python -m src.evals.run_eval
    uv run python -m src.evals.run_eval --limit 5    (run first 5 cases only)
    uv run python -m src.evals.run_eval --no-arize   (skip Arize annotation)
"""

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from src.agent.orchestrator import invoke_agent


TEST_CASES_PATH = Path("evals/test_cases.json")
RESULTS_DIR = Path("evals/results")


def load_test_cases(limit: int | None = None) -> list[dict]:
    with TEST_CASES_PATH.open() as f:
        data = json.load(f)
    cases = data["cases"]
    return cases[:limit] if limit is not None else cases


def build_query(case: dict) -> str:
    return (
        f"Please investigate claim {case['query_claim_id']} for possible "
        f"cross-state unemployment insurance fraud."
    )


def score_case(case: dict, findings: dict) -> dict:
    """Compare the agent's findings to the test case's expected outcome.

    Returns a structured score with pass/fail and diagnostic details.
    """
    expected_primary = case["expected_primary"]
    actual_primary = findings.get("primary_outcome", "unknown")

    primary_correct = actual_primary == expected_primary

    # Compare cross-state matches (set comparison per hash field)
    expected_cs = case["expected_cross_state_matches"]
    actual_cs = findings.get("cross_state_matches", {})

    cs_field_results = {}
    for field in ("claimant_ssn_hash", "device_fingerprint_hash",
                  "bank_routing_hash", "bank_account_hash"):
        expected_set = set(expected_cs.get(field, []))
        actual_set = set(actual_cs.get(field, []))
        cs_field_results[field] = {
            "expected": sorted(expected_set),
            "actual": sorted(actual_set),
            "missed": sorted(expected_set - actual_set),
            "false_positive": sorted(actual_set - expected_set),
            "exact_match": expected_set == actual_set,
        }

    # Compare within-state matches
    expected_ws = case["expected_within_state_matches"]
    actual_ws = findings.get("within_state_matches", {})

    ws_field_results = {}
    for field in ("claimant_ssn_hash", "device_fingerprint_hash",
                  "bank_routing_hash", "bank_account_hash"):
        expected_set = set(expected_ws.get(field, []))
        actual_set = set(actual_ws.get(field, []))
        ws_field_results[field] = {
            "expected": sorted(expected_set),
            "actual": sorted(actual_set),
            "missed": sorted(expected_set - actual_set),
            "false_positive": sorted(actual_set - expected_set),
            "exact_match": expected_set == actual_set,
        }

    # Aggregate pass criteria: primary outcome correct AND all match sets exact
    matches_exact = (
        all(r["exact_match"] for r in cs_field_results.values())
        and all(r["exact_match"] for r in ws_field_results.values())
    )
    overall_pass = primary_correct and matches_exact

    return {
        "case_id": case["case_id"],
        "category": case["category"],
        "query_claim_id": case["query_claim_id"],
        "expected_primary": expected_primary,
        "actual_primary": actual_primary,
        "primary_correct": primary_correct,
        "cross_state_matches": cs_field_results,
        "within_state_matches": ws_field_results,
        "matches_exact": matches_exact,
        "overall_pass": overall_pass,
        "agent_narrative": findings.get("narrative", ""),
    }


def summarize_results(case_results: list[dict]) -> dict:
    """Compute summary metrics from per-case results."""
    total = len(case_results)
    passing = sum(1 for r in case_results if r["overall_pass"])
    primary_correct = sum(1 for r in case_results if r["primary_correct"])

    # By category
    by_category: dict[str, dict[str, int]] = {}
    for r in case_results:
        cat = r["category"]
        if cat not in by_category:
            by_category[cat] = {"total": 0, "passing": 0, "primary_correct": 0}
        by_category[cat]["total"] += 1
        if r["overall_pass"]:
            by_category[cat]["passing"] += 1
        if r["primary_correct"]:
            by_category[cat]["primary_correct"] += 1

    # Add accuracy percentages
    for cat in by_category:
        c = by_category[cat]
        c["pass_rate"] = round(c["passing"] / c["total"], 3) if c["total"] else 0
        c["primary_accuracy"] = round(c["primary_correct"] / c["total"], 3) if c["total"] else 0

    return {
        "total_cases": total,
        "overall_pass": passing,
        "overall_pass_rate": round(passing / total, 3) if total else 0,
        "primary_correct": primary_correct,
        "primary_accuracy": round(primary_correct / total, 3) if total else 0,
        "by_category": by_category,
    }


def print_summary(summary: dict) -> None:
    print("\n" + "=" * 70)
    print("EVALUATION SUMMARY")
    print("=" * 70)
    print(f"Total cases:           {summary['total_cases']}")
    print(f"Primary outcome accuracy: {summary['primary_correct']}/{summary['total_cases']} ({summary['primary_accuracy'] * 100:.1f}%)")
    print(f"Overall pass (primary + exact match sets): {summary['overall_pass']}/{summary['total_cases']} ({summary['overall_pass_rate'] * 100:.1f}%)")
    print()
    print(f"{'Category':<30} {'Total':>6} {'Pass':>6} {'Pass%':>8} {'Primary%':>10}")
    print("-" * 70)
    for cat, stats in sorted(summary["by_category"].items()):
        print(
            f"{cat:<30} "
            f"{stats['total']:>6} "
            f"{stats['passing']:>6} "
            f"{stats['pass_rate'] * 100:>7.1f}% "
            f"{stats['primary_accuracy'] * 100:>9.1f}%"
        )
    print()


def print_per_case_brief(case_results: list[dict]) -> None:
    print("\nPER-CASE RESULTS")
    print("-" * 70)
    for r in case_results:
        status = "✓" if r["overall_pass"] else "✗"
        primary = "✓" if r["primary_correct"] else "✗"
        print(
            f"{status} {r['case_id']:<35} "
            f"[{r['category']:<25}] "
            f"primary {primary}: {r['expected_primary']:<18} -> {r['actual_primary']:<18}"
        )


def run_eval(limit: int | None = None) -> dict:
    cases = load_test_cases(limit=limit)
    print(f"Running eval on {len(cases)} test cases...\n")

    case_results = []
    for i, case in enumerate(cases, start=1):
        print(f"[{i}/{len(cases)}] {case['case_id']} ({case['category']}) ...", end=" ", flush=True)

        query = build_query(case)
        try:
            findings = invoke_agent(
                user_query=query,
                investigator_id="eval_runner",
                verbose=False,
            )
            error = None
        except Exception as e:
            findings = {}
            error = f"{type(e).__name__}: {e}"

        if error:
            print(f"ERROR: {error}")
            case_results.append({
                "case_id": case["case_id"],
                "category": case["category"],
                "query_claim_id": case["query_claim_id"],
                "expected_primary": case["expected_primary"],
                "actual_primary": "error",
                "primary_correct": False,
                "cross_state_matches": {},
                "within_state_matches": {},
                "matches_exact": False,
                "overall_pass": False,
                "agent_narrative": "",
                "error": error,
            })
            continue

        score = score_case(case, findings)
        case_results.append(score)
        marker = "✓" if score["overall_pass"] else "✗"
        print(f"{marker} (primary: {score['actual_primary']})")

    summary = summarize_results(case_results)
    print_summary(summary)
    print_per_case_brief(case_results)

    # Persist results
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    results_path = RESULTS_DIR / f"run_{timestamp}.json"
    with results_path.open("w") as f:
        json.dump({
            "timestamp_utc": timestamp,
            "summary": summary,
            "case_results": case_results,
        }, f, indent=2)
    print(f"\nFull results written to: {results_path}")

    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Run only the first N cases")
    parser.add_argument("--case-id", type=str, default=None, help="Re-run only the specified case_id")
    parser.add_argument("--no-arize", action="store_true", help="Skip Arize annotation (placeholder)")
    args = parser.parse_args()

    if args.case_id is not None:
        # Run a single case by ID
        all_cases = load_test_cases()
        matching = [c for c in all_cases if c["case_id"] == args.case_id]
        if not matching:
            print(f"No test case found with case_id={args.case_id!r}")
            return
        _run_specific_cases(matching)
    else:
        run_eval(limit=args.limit)


def _run_specific_cases(cases: list[dict]) -> None:
    """Run a specific subset of cases and print per-case results."""
    print(f"Running {len(cases)} specified case(s)...\n")
    case_results = []
    for i, case in enumerate(cases, start=1):
        print(f"[{i}/{len(cases)}] {case['case_id']} ({case['category']}) ...", end=" ", flush=True)
        query = build_query(case)
        try:
            findings = invoke_agent(
                user_query=query,
                investigator_id="eval_runner",
                verbose=False,
            )
            error = None
        except Exception as e:
            findings = {}
            error = f"{type(e).__name__}: {e}"

        if error:
            print(f"ERROR: {error}")
            continue

        score = score_case(case, findings)
        case_results.append(score)
        marker = "✓" if score["overall_pass"] else "✗"
        print(f"{marker} (primary: {score['actual_primary']})")

    if case_results:
        print("\n" + "=" * 70)
        print("SINGLE-CASE RESULTS")
        print("=" * 70)
        for r in case_results:
            import pprint
            pprint.pprint({k: v for k, v in r.items() if k != "agent_narrative"})
            print()
if __name__ == "__main__":
    main()