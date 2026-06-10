"""LLM-as-judge for agent narrative quality.

Reads a completed eval results file and scores each case's narrative along
three dimensions: faithfulness, coverage, and clarity. Uses gemini-2.5-flash
as the judge with a structured rubric and low temperature.

Run with:
    uv run python -m src.evals.narrative_judge
    uv run python -m src.evals.narrative_judge --results-file evals/results/run_<ts>.json
    uv run python -m src.evals.narrative_judge --limit 3

Writes a new file alongside the input:
    evals/results/run_<ts>.judged.json

Adds these fields to each case_result:
    narrative_scores: {
        faithfulness: int (1-5),
        coverage: int (1-5),
        clarity: int (1-5),
        rationale: str,
    }
"""

import argparse
import glob
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()


JUDGE_MODEL = "gemini-2.5-flash"


JUDGE_SYSTEM_PROMPT = """You are evaluating the quality of an investigation narrative produced by an AI agent that detects multi-state unemployment insurance fraud.

You are scoring the narrative along three dimensions, each on a 1-5 integer scale. You are NOT scoring whether the investigation conclusion is correct — that is evaluated separately. You are scoring the quality of the written explanation given the structured findings the agent produced.

You will be given:
  - The structured findings the agent produced (machine-readable, treated as ground truth for your scoring)
  - The narrative the agent produced (human-readable markdown)

Score each dimension independently. Be strict and consistent.

## Faithfulness (1-5)

Does the narrative accurately reflect — without contradicting — the structured findings?

The narrative is allowed and expected to include information BEYOND the structured findings, including:
  - Claimant names, DOBs, addresses, IPs (retrieved via the agent's audited per-claim lookup tool, which writes its own audit events)
  - Audit event hashes for federation queries and quasi-identifier releases
  - Plain-language assessment of what the pattern suggests

Faithfulness asks: where the narrative DOES reference the structured fields (primary outcome, match arrays by hash type, source claim ID), does it match?

  5: Narrative is consistent with structured findings on every field it touches. Match claim IDs, hash types, outcome classifications, source claim ID — all align. Additional content (claimant context, audit hashes, assessment narrative) is permitted and does not count against faithfulness.

  3: Minor inconsistency in fields shared with structured findings. For example: claims a cross-state match for SSN hash when structured findings list it under bank routing instead, or names a claim ID in narrative that doesn't appear in any structured match array.

  1: Major contradiction. The narrative claims a different primary outcome than the structured field says, OR systematically references claim IDs not in the structured match arrays as matches.

If the narrative includes legitimate additional content (claimant names from per-claim lookup, audit hashes from logging) that's NOT in the structured findings, this is expected behavior, not a faithfulness violation.## Coverage (1-5)

Does the narrative include the expected structural sections?
  Expected sections: claim under investigation, primary finding, secondary finding, retrieved claimant context (when applicable), assessment, audit references.
  5: All expected sections present and clearly labeled.
  3: Most sections present, one or two missing or unclear.
  1: Major sections missing; narrative is fragmentary.

## Clarity (1-5)

Is the explanation comprehensible to a human investigator unfamiliar with the codebase?
  5: Clear, well-organized, no jargon that would confuse a non-technical investigator. The pattern detected is described in plain language.
  3: Mostly clear but some passages require domain knowledge to follow.
  1: Confusing, poorly structured, or so technical that a non-technical investigator could not act on it.

Respond ONLY with a JSON object containing the three integer scores and a brief rationale (one or two sentences explaining the lowest score). Do not include any other text."""


JUDGE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "faithfulness": {"type": "integer", "minimum": 1, "maximum": 5},
        "coverage": {"type": "integer", "minimum": 1, "maximum": 5},
        "clarity": {"type": "integer", "minimum": 1, "maximum": 5},
        "rationale": {
            "type": "string",
            "description": "One or two sentences explaining the lowest score, or noting the case is uniformly high quality.",
        },
    },
    "required": ["faithfulness", "coverage", "clarity", "rationale"],
}


def find_latest_results_file() -> Path:
    """Find the most recent run_*.json file (excluding .judged.json)."""
    candidates = [
        Path(p) for p in glob.glob("evals/results/run_*.json")
        if not p.endswith(".judged.json")
    ]
    if not candidates:
        raise FileNotFoundError("No eval results files found in evals/results/")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def build_judge_input(case_result: dict, structured_from_findings: dict) -> str:
    """Construct the user message the judge sees."""
    return (
        f"Structured findings (treat as ground truth for your scoring):\n"
        f"```json\n{json.dumps(structured_from_findings, indent=2)}\n```\n\n"
        f"Narrative produced by the agent:\n"
        f"```markdown\n{case_result['agent_narrative']}\n```\n\n"
        f"Score this narrative on faithfulness, coverage, and clarity."
    )


def judge_narrative(
    client,
    case_result: dict,
    max_attempts: int = 3,
) -> dict:
    """Score a single case's narrative. Returns the score dict."""
    # Reconstruct the structured findings the agent produced (from the case result fields)
    structured_from_findings = {
    "source_claim_id": case_result.get("query_claim_id"),
    "primary_outcome": case_result.get("actual_primary"),
    "cross_state_matches": {
        field: case_result["cross_state_matches"].get(field, {}).get("actual", [])
        for field in (
            "claimant_ssn_hash", "device_fingerprint_hash",
            "bank_routing_hash", "bank_account_hash",
        )
        if isinstance(case_result["cross_state_matches"].get(field), dict)
    },
    "within_state_matches": {
        field: case_result["within_state_matches"].get(field, {}).get("actual", [])
        for field in (
            "claimant_ssn_hash", "device_fingerprint_hash",
            "bank_routing_hash", "bank_account_hash",
        )
        if isinstance(case_result["within_state_matches"].get(field), dict)
    },
}

    user_message = build_judge_input(case_result, structured_from_findings)

    config = types.GenerateContentConfig(
        system_instruction=JUDGE_SYSTEM_PROMPT,
        temperature=0.1,
        response_mime_type="application/json",
        response_schema=JUDGE_RESPONSE_SCHEMA,
    )

    contents = [types.Content(role="user", parts=[types.Part(text=user_message)])]

    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.models.generate_content(
                model=JUDGE_MODEL,
                contents=contents,
                config=config,
            )
            text = response.candidates[0].content.parts[0].text
            return json.loads(text)
        except Exception as e:
            last_error = e
            error_str = str(e)
            is_transient = (
                "429" in error_str or "RESOURCE_EXHAUSTED" in error_str
                or "503" in error_str or "SERVICE_UNAVAILABLE" in error_str
            )
            if attempt < max_attempts and (isinstance(e, json.JSONDecodeError) or is_transient):
                wait = 5 * (2 ** (attempt - 1))
                print(f"  judge retry {attempt}/{max_attempts} in {wait}s: {type(e).__name__}")
                time.sleep(wait)
                continue
            raise

    raise RuntimeError(f"Judge exhausted retries: {last_error}")


def summarize_narrative_scores(case_results: list[dict]) -> dict:
    """Aggregate narrative scores across all cases."""
    scored = [r for r in case_results if r.get("narrative_scores")]
    if not scored:
        return {"scored_count": 0}

    def mean_score(field: str) -> float:
        return round(sum(r["narrative_scores"][field] for r in scored) / len(scored), 2)

    def min_score(field: str) -> int:
        return min(r["narrative_scores"][field] for r in scored)

    return {
        "scored_count": len(scored),
        "mean_faithfulness": mean_score("faithfulness"),
        "mean_coverage": mean_score("coverage"),
        "mean_clarity": mean_score("clarity"),
        "min_faithfulness": min_score("faithfulness"),
        "min_coverage": min_score("coverage"),
        "min_clarity": min_score("clarity"),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--results-file",
        type=str,
        default=None,
        help="Path to eval results JSON (default: most recent run)",
    )
    parser.add_argument("--limit", type=int, default=None, help="Score only first N cases")
    args = parser.parse_args()

    results_path = Path(args.results_file) if args.results_file else find_latest_results_file()
    print(f"Reading: {results_path}")

    with results_path.open() as f:
        data = json.load(f)

    case_results = data["case_results"]
    if args.limit is not None:
        case_results = case_results[:args.limit]

    project_id = os.environ["GCP_PROJECT_ID"]
    location = os.environ.get("GCP_LOCATION", "us-central1")
    client = genai.Client(vertexai=True, project=project_id, location=location)

    print(f"\nScoring {len(case_results)} narratives with {JUDGE_MODEL} as judge...\n")

    scored_results = []
    for i, case_result in enumerate(case_results, start=1):
        case_id = case_result["case_id"]

        # Skip cases that failed with no narrative
        if not case_result.get("agent_narrative"):
            print(f"[{i}/{len(case_results)}] {case_id}: skipped (no narrative)")
            scored_results.append(case_result)
            continue

        print(f"[{i}/{len(case_results)}] {case_id} ...", end=" ", flush=True)
        try:
            scores = judge_narrative(client, case_result)
            case_result["narrative_scores"] = scores
            print(f"F={scores['faithfulness']} Cov={scores['coverage']} Cla={scores['clarity']}")
        except Exception as e:
            print(f"ERROR: {type(e).__name__}: {e}")
            case_result["narrative_scores"] = None
        scored_results.append(case_result)

    # Summarize and persist
    narrative_summary = summarize_narrative_scores(scored_results)
    print("\n" + "=" * 70)
    print("NARRATIVE QUALITY SUMMARY")
    print("=" * 70)
    print(f"Cases scored:          {narrative_summary['scored_count']}/{len(case_results)}")
    if narrative_summary["scored_count"]:
        print(f"Mean faithfulness:     {narrative_summary['mean_faithfulness']:.2f} / 5 (min: {narrative_summary['min_faithfulness']})")
        print(f"Mean coverage:         {narrative_summary['mean_coverage']:.2f} / 5 (min: {narrative_summary['min_coverage']})")
        print(f"Mean clarity:          {narrative_summary['mean_clarity']:.2f} / 5 (min: {narrative_summary['min_clarity']})")

    # Print any case with a sub-4 score for inspection
    weak = [r for r in scored_results if r.get("narrative_scores") and min(
        r["narrative_scores"]["faithfulness"],
        r["narrative_scores"]["coverage"],
        r["narrative_scores"]["clarity"],
    ) < 4]
    if weak:
        print(f"\n{len(weak)} case(s) with at least one sub-4 score:")
        for r in weak:
            s = r["narrative_scores"]
            print(f"  {r['case_id']:<35} F={s['faithfulness']} Cov={s['coverage']} Cla={s['clarity']}")
            print(f"    Rationale: {s['rationale']}")

    # Write judged results next to the original
    output_path = results_path.with_suffix(".judged.json")
    data["case_results"] = scored_results
    data["narrative_summary"] = narrative_summary
    data["judged_at_utc"] = datetime.now(timezone.utc).isoformat()
    data["judge_model"] = JUDGE_MODEL
    with output_path.open("w") as f:
        json.dump(data, f, indent=2)
    print(f"\nFull judged results written to: {output_path}")


if __name__ == "__main__":
    main()