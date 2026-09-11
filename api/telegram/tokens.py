import secrets


def new_token() -> str:
    return secrets.token_urlsafe(16)
