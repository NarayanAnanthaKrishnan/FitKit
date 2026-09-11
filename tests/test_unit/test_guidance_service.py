from api.services.guidance_service import GUIDANCE_SOURCES, guidance_reply


def test_leg_warmup_labels_chat_claim_and_uses_reviewed_numbers():
    reply = guidance_reply("warmup", "I did legs yesterday")
    assert "what you just told me" in reply
    assert "not a recorded workout" in reply
    assert "5–10 minutes" in reply
    assert "sharp or worsening pain" in reply
    assert all(source.startswith("https://") for source in GUIDANCE_SOURCES)


def test_generic_warmup_asks_for_the_activity_without_inventing_one():
    reply = guidance_reply("warmup", "How should I warm up?")
    assert "Tell me today’s activity or muscle group" in reply
    assert "legs" not in reply.casefold()
