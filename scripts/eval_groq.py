"""Benchmark the Groq gateway against the synthetic eval set.

Usage:
  GROQ_API_KEY=... python scripts/eval_groq.py --model openai/gpt-oss-120b

Reads tests/eval/cases.jsonl, calls the gateway (real Groq unless --mock),
and prints accuracy, latency, token usage, and cost estimate.
Synthetic data only — never commit real health data.
"""

import argparse
import asyncio
import json
import os
import statistics
import time
from pathlib import Path

# Ensure project imports work when run as `python scripts/eval_groq.py`
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.llm.gateway import interpret_free_text  # noqa: E402


async def run_one(text: str) -> tuple:
    start = time.monotonic()
    result = await interpret_free_text(text)
    latency = int((time.monotonic() - start) * 1000)
    intent = result.interpretation.intent if result.interpretation else None
    return intent, result, latency


async def main(model: str, mock: bool) -> None:
    if model:
        os.environ["GROQ_MODEL"] = model
    if mock:
        os.environ["LLM_ENABLED"] = "0"
    else:
        os.environ["LLM_ENABLED"] = "1"
        if not os.getenv("GROQ_API_KEY"):
            print("GROQ_API_KEY not set — use --mock for offline run or set the key.")
            return

    cases_path = Path(__file__).resolve().parent.parent / "tests" / "eval" / "cases.jsonl"
    cases = [json.loads(line) for line in open(cases_path, encoding="utf-8") if line.strip()]

    total = len(cases)
    bypass = sum(1 for c in cases if c.get("bypass_llm"))
    eval_cases = [c for c in cases if not c.get("bypass_llm")]

    correct_intent = 0
    fallback = 0
    latencies: list[int] = []
    tokens_in = 0
    tokens_out = 0

    print(f"Cases: {total} (bypass_llm={bypass}, eval={len(eval_cases)}) model={os.getenv('GROQ_MODEL')}\n")
    for case in eval_cases:
        text = case["text"]
        expected = case.get("expected_intent")
        intent, result, latency = await run_one(text)
        latencies.append(latency)
        if result.fallback:
            fallback += 1
        if expected and intent == expected:
            correct_intent += 1
        tokens_in += result.tokens_in or 0
        tokens_out += result.tokens_out or 0
        status = "OK" if intent == expected else f"got={intent} expected={expected}"
        fb = " [fallback]" if result.fallback else ""
        print(f"{case['id']:30} {status:45} {latency:4}ms{fb}")
        if result.error and result.fallback and not mock:
            print(f"  error: {result.error}")

    print("\n--- Summary ---")
    print(f"Evaluated: {len(eval_cases)}")
    print(f"Correct intent: {correct_intent}/{len(eval_cases)} ({100*correct_intent/max(1,len(eval_cases)):.1f}%)")
    print(f"Fallback: {fallback}")
    if latencies:
        print(f"p50 latency: {statistics.median(latencies)}ms  p95: {sorted(latencies)[int(0.95*len(latencies))]}ms")
    print(f"Tokens in/out: {tokens_in}/{tokens_out}")

    # Cost estimate at Groq's published rate for gpt-oss-120b (example: $0.15/1M in, $0.60/1M out — verify current pricing)
    price_in = float(os.getenv("GROQ_PRICE_IN", "0.15"))
    price_out = float(os.getenv("GROQ_PRICE_OUT", "0.60"))
    est = tokens_in / 1_000_000 * price_in + tokens_out / 1_000_000 * price_out
    print(f"Est. cost (at ${price_in}/${price_out} per 1M): ${est:.4f}")
    print(f"Cost per successful intent: ${est/max(1,correct_intent):.5f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"))
    parser.add_argument("--mock", action="store_true", help="offline run without Groq")
    args = parser.parse_args()
    asyncio.run(main(args.model, args.mock))
