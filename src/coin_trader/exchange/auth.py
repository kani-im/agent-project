"""Upbit API JWT authentication."""

from __future__ import annotations

import hashlib
import uuid
from urllib.parse import urlencode

import jwt


def create_token(
    access_key: str,
    secret_key: str,
    query: dict | None = None,
) -> str:
    """Create a JWT token for Upbit API authentication.

    Args:
        access_key: Upbit API access key.
        secret_key: Upbit API secret key.
        query: Optional query parameters. If provided, query_hash is included.

    Returns:
        JWT token string.
    """
    payload: dict = {
        "access_key": access_key,
        "nonce": str(uuid.uuid4()),
    }

    if query:
        # Handle array parameters (e.g., states[]=wait&states[]=watch)
        query_string = _build_query_string(query)
        query_hash = hashlib.sha512(query_string.encode()).hexdigest()
        payload["query_hash"] = query_hash
        payload["query_hash_alg"] = "SHA512"

    return jwt.encode(payload, secret_key, algorithm="HS256")


def _build_query_string(query: dict) -> str:
    """Build a query string handling array parameters."""
    parts = []
    for key, value in query.items():
        if isinstance(value, list):
            for item in value:
                parts.append((f"{key}[]", item))
        else:
            parts.append((key, value))
    return urlencode(parts)
