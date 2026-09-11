"""Synthetic evaluation of routing, extraction and confirmation boundaries.

--offline runs deterministic routing and adversarial candidate fixtures only.
It never reports mock model accuracy. With no flag, calls Groq on the versioned
synthetic corpus; no user database or real conversations are read.
"""
import argparse
import asyncio
from datetime import date
import json
import os
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from api.llm.gateway import GatewayResult, interpret_free_text
from api.llm.schemas import LLMInterpretation
from api.services.extraction_service import verify_evidence, workout_date_from_text
from api.telegram.parsing import parse_weight

ROOT = Path(__file__).resolve().parent.parent
CONTEXT = {"today": "2026-09-08", "timezone": "America/New_York", "units": "kg"}
MUTATIONS = {"record_weight", "log_workout", "create_goal", "update_profile"}


def bypass(text):
    return text.startswith("/") or parse_weight(text) is not None


def matches(actual, expected):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(k in actual and matches(actual[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(matches(a, e) for a, e in zip(actual, expected))
    if type(expected) in (int, float):
        return type(actual) in (int, float) and abs(actual - expected) < .02
    return actual == expected


def candidate_accepted(candidate, text):
    try:
        interp = LLMInterpretation.model_validate(candidate)
        if interp.confidence < .6 or interp.intent not in MUTATIONS:
            return False
        verify_evidence(interp.intent, interp.payload, text)
        if interp.intent == "log_workout":
            resolved = workout_date_from_text(text, date.fromisoformat(CONTEXT["today"]))
            if interp.payload.get("date") and interp.payload["date"] != resolved.isoformat():
                return False
        return True
    except (ValueError, KeyError, TypeError):
        return False


def score(case, result):
    interp = result.interpretation
    accepted = bool(interp and candidate_accepted(interp.model_dump(mode="json"), case["text"]))
    return {
        "intent": bool(interp and interp.intent == case.get("expected_intent")),
        "payload": matches(interp.payload if interp else None, case["expected_payload"]) if "expected_payload" in case else None,
        "clarification": bool(interp and interp.intent == "unknown" and interp.clarification) if case.get("should_clarify") else None,
        "safe_boundary": not accepted if case.get("should_clarify") or case.get("expected_intent") in {"unsafe", "unknown"} else True,
        "fallback": result.fallback,
        # A candidate may only create a preview; database writes are tested in
        # test_beta_reliability and the Telegram integration suite.
        "preview_candidate": accepted,
    }


async def run(args):
    cases = [json.loads(line) for line in (ROOT / "tests/eval/cases.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    fixtures = [json.loads(line) for line in (ROOT / "tests/eval/boundaries.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    checks = [candidate_accepted(c["candidate"], c["text"]) == c["accepted"] for c in fixtures]
    routing = [bypass(c["text"]) for c in cases if c.get("bypass_llm")]
    report = {"mode": "offline" if args.offline else "live", "boundary_checks": {"passed": sum(checks), "total": len(checks)},
              "bypass_checks": {"passed": sum(routing), "total": len(routing)}, "live_cases_run": 0}
    evaluations = []
    if not args.offline:
        if not os.getenv("GROQ_API_KEY"):
            raise RuntimeError("GROQ_API_KEY is required for a live evaluation")
        os.environ.update(LLM_ENABLED="1", GROQ_MODEL=args.model)
        for case in cases:
            if bypass(case["text"]):
                continue
            result = await interpret_free_text(case["text"], context=CONTEXT)
            evaluations.append((score(case, result), result))
        report["live_cases_run"] = len(evaluations)
        for dimension in ("intent", "payload", "clarification", "safe_boundary"):
            values = [s[dimension] for s, _ in evaluations if s[dimension] is not None]
            report[dimension] = {"passed": sum(values), "total": len(values)}
        latencies = sorted(r.latency_ms for _, r in evaluations)
        report["fallbacks"] = sum(r.fallback for _, r in evaluations)
        report["latency_ms"] = {"p50": statistics.median(latencies) if latencies else 0, "p95": latencies[min(len(latencies) - 1, int(.95 * len(latencies)))] if latencies else 0}
        report["tokens"] = {"input": sum(r.tokens_in or 0 for _, r in evaluations), "output": sum(r.tokens_out or 0 for _, r in evaluations)}
    print(json.dumps(report, indent=2))
    # Safety regressions fail the harness even when overall intent accuracy is high.
    return 0 if all(checks + routing) and all(s["safe_boundary"] for s, _ in evaluations) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"))
    parser.add_argument("--offline", "--mock", dest="offline", action="store_true")
    args = parser.parse_args()
    try:
        sys.exit(asyncio.run(run(args)))
    except Exception as exc:
        parser.exit(1, f"Evaluation failed ({type(exc).__name__}); no provider response content was logged.\n")
