import os
from typing import Optional

from fastapi import Header, HTTPException


async def verify_api_key(x_api_key: Optional[str] = Header(default=None)):
    expected = os.environ.get("FITKIT_API_KEY")
    if expected is None or x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid API key")
