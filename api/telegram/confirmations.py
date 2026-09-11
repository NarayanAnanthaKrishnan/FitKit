"""Only whole-message confirmations authorize a pending preview."""


def is_affirmative(text: str) -> bool:
    return text.strip().lower() in {"yes", "save"}


def is_negative(text: str) -> bool:
    return text.strip().lower() in {"no", "cancel", "stop"}
