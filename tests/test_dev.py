import asyncio
import json
from collections.abc import Callable
from datetime import date, time, timezone

import httpx
import pytest

from app.platforms.dev import DevPlatform
from app.schemas import PostingError, PostingResult


def run_post(
    message: str,
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    api_key: str | None = "synthetic-dev-key",
) -> PostingResult:
    async def execute():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as client:
            platform = DevPlatform(api_key=api_key, client=client)
            return await platform.post(message)

    return asyncio.run(execute())


def test_publishes_article_with_message_as_title_and_body() -> None:
    message = "A useful update https://example.com"
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["api_key"] = request.headers["api-key"]
        captured["accept"] = request.headers["accept"]
        captured["article"] = json.loads(request.content)["article"]
        return httpx.Response(
            201,
            json={
                "title": message,
                "url": "https://dev.to/example/a-useful-update",
                "published": True,
                "published_at": "2026-11-19T10:30:00Z",
            },
        )

    result = run_post(message, handler)

    assert captured == {
        "url": "https://dev.to/api/articles",
        "api_key": "synthetic-dev-key",
        "accept": "application/json",
        "article": {
            "title": message,
            "body_markdown": message,
            "published": True,
        },
    }
    assert result.status == "success"
    assert str(result.posted_url) == "https://dev.to/example/a-useful-update"
    assert result.public_access is True
    assert result.date == date(2026, 11, 19)
    assert result.time == time(10, 30, tzinfo=timezone.utc)


def test_long_message_title_is_a_source_prefix_and_body_is_unchanged() -> None:
    message = f'{"A" * 175} https://example.com'
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["article"] = json.loads(request.content)["article"]
        return httpx.Response(
            201,
            json={
                "url": None,
                "published": True,
                "published_at": "2026-11-19T10:30:00Z",
            },
        )

    result = run_post(message, handler)

    assert captured["article"] == {
        "title": "A" * 128,
        "body_markdown": message,
        "published": True,
    }
    assert result.status == "success"
    assert result.posted_url is None


def test_missing_published_flag_is_reported_as_unknown_access() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201,
            json={
                "url": "https://dev.to/example/post",
                "published_at": "2026-11-19T10:30:00Z",
            },
        )

    result = run_post("A useful update https://example.com", handler)

    assert result.status == "success"
    assert result.public_access is None


def test_null_published_flag_is_reported_as_unknown_access() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201,
            json={
                "published": None,
                "url": "https://dev.to/example/post",
                "published_at": "2026-11-19T10:30:00Z",
            },
        )

    result = run_post("A useful update https://example.com", handler)

    assert result.status == "success"
    assert result.public_access is None


def test_missing_api_key_returns_safe_failure_without_request() -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(201, json={})

    result = run_post(
        "A useful update https://example.com",
        handler,
        api_key=" ",
    )

    assert called is False
    assert result.error is PostingError.NOT_CONFIGURED
    assert result.public_access is False


@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [
        (401, PostingError.AUTHENTICATION),
        (403, PostingError.AUTHENTICATION),
        (422, PostingError.REJECTED),
        (429, PostingError.RATE_LIMITED),
        (500, PostingError.FAILURE),
    ],
)
def test_api_errors_are_mapped_without_exposing_response_body(
    status_code: int,
    expected_error: PostingError,
    caplog,
) -> None:
    secret = "synthetic-response-secret"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"error": secret})

    result = run_post("A useful update https://example.com", handler)

    assert result.status == "failed"
    assert result.error is expected_error
    assert secret not in result.model_dump_json()
    assert secret not in caplog.text
    assert "synthetic-dev-key" not in caplog.text


def test_http_timeout_returns_safe_timeout_result(caplog) -> None:
    secret = "synthetic-timeout-secret"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(secret, request=request)

    result = run_post("A useful update https://example.com", handler)

    assert result.status == "failed"
    assert result.error is PostingError.TIMEOUT
    assert secret not in result.model_dump_json()
    assert secret not in caplog.text


def test_unpublished_api_response_is_not_reported_as_public_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"published": False})

    result = run_post("A useful update https://example.com", handler)

    assert result.status == "failed"
    assert result.public_access is False
    assert result.error is PostingError.REJECTED
