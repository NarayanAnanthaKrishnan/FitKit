import pytest

from api.services.memory_service import proposal_payload, validate_proposal


def test_preference_memory_proposal_is_encrypted_and_validated():
    payload = proposal_payload("I train at home with dumbbells")
    assert "dumbbells" not in payload["encrypted_content"].lower()
    assert validate_proposal(payload) == "I train at home with dumbbells"


@pytest.mark.parametrize("content", [
    "I have knee pain",
    "Remember my medication schedule",
    "I was diagnosed with a heart condition",
])
def test_sensitive_health_details_are_not_saved_as_conversational_memory(content):
    with pytest.raises(ValueError, match="dedicated consented health-data flow"):
        proposal_payload(content)
