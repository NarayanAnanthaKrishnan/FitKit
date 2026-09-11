import json
from pathlib import Path
from scripts.eval_groq import candidate_accepted, matches, score
from api.llm.gateway import GatewayResult


def test_adversarial_eval_fixtures():
    path = Path(__file__).resolve().parents[1] / "eval/boundaries.jsonl"
    for line in path.read_text().splitlines():
        case = json.loads(line)
        assert candidate_accepted(case["candidate"], case["text"]) == case["accepted"], case["text"]


def test_eval_scores_payload_and_fallback_without_claiming_accuracy():
    assert not matches({"weight_kg": 90}, {"weight_kg": 80})
    assert matches({"weight_kg": 79.832}, {"weight_kg": 79.83})
    result = score({"text": "75", "expected_intent": "unknown", "should_clarify": True}, GatewayResult(fallback=True))
    assert result["fallback"] and result["safe_boundary"]
    assert not result["intent"] and not result["clarification"]
