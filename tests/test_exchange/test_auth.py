"""Tests for exchange.auth module."""

from __future__ import annotations

import hashlib
from urllib.parse import urlencode

import jwt as pyjwt

from coin_trader.exchange.auth import _build_query_string, create_token

ACCESS_KEY = "test-access-key"
SECRET_KEY = "test-secret-key"


class TestCreateToken:
    def test_basic_token(self) -> None:
        token = create_token(ACCESS_KEY, SECRET_KEY)
        payload = pyjwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        assert payload["access_key"] == ACCESS_KEY
        assert "nonce" in payload
        assert "query_hash" not in payload

    def test_token_with_query(self) -> None:
        query = {"market": "KRW-BTC", "count": "5"}
        token = create_token(ACCESS_KEY, SECRET_KEY, query)
        payload = pyjwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        assert payload["query_hash_alg"] == "SHA512"

        expected_qs = urlencode(list(query.items()))
        expected_hash = hashlib.sha512(expected_qs.encode()).hexdigest()
        assert payload["query_hash"] == expected_hash

    def test_unique_nonce(self) -> None:
        t1 = create_token(ACCESS_KEY, SECRET_KEY)
        t2 = create_token(ACCESS_KEY, SECRET_KEY)
        p1 = pyjwt.decode(t1, SECRET_KEY, algorithms=["HS256"])
        p2 = pyjwt.decode(t2, SECRET_KEY, algorithms=["HS256"])
        assert p1["nonce"] != p2["nonce"]


class TestBuildQueryString:
    def test_simple_params(self) -> None:
        result = _build_query_string({"market": "KRW-BTC", "count": "5"})
        assert result == "market=KRW-BTC&count=5"

    def test_array_params(self) -> None:
        result = _build_query_string({"states": ["wait", "watch"]})
        assert "states%5B%5D=wait" in result
        assert "states%5B%5D=watch" in result

    def test_mixed_params(self) -> None:
        result = _build_query_string({
            "market": "KRW-BTC",
            "states": ["wait", "done"],
        })
        assert "market=KRW-BTC" in result
        assert "states%5B%5D=wait" in result
