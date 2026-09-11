"""Presentation conversion only; storage and engine calculations use kg."""


def display_load(value: float, unit: str = "kg") -> float:
    return value / 0.45359237 if unit == "lb" else value


def format_load(value: float, unit: str = "kg", *, digits: int = 1) -> str:
    return f"{display_load(value, unit):.{digits}f} {unit}"
