import asyncio
from collections.abc import Callable
from datetime import date, time, timezone
from urllib.parse import parse_qs

import httpx
import pytest

from app.platforms.mastodon import MastodonPlatform
from app.schemas import PostingError, PostingResult


def run_post(
    message: str,
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    instance_url: str | None = "https://mastodon.example",
    access_token: str | None = "synthetic-mastodon-token",
) -> PostingResult:
    async def execute() -> PostingResult:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as client:
            platform = MastodonPlatform(
                instance_url=instance_url,
                access_token=access_token,
                client=client,
            )
            return await platform.post(message)

    return asyncio.run(execute())


def test_posts_status_with_bearer_auth_and_public_visibility() -> None:
    message = "A useful update https://example.com"
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["authorization"]
        captured["accept"] = request.headers["accept"]
        captured["form"] = parse_qs(request.content.decode())
        return httpx.Response(
            200,
            json={
                "id": "123",
                "url": "https://mastodon.example/@user/123",
                "visibility": "public",
                "created_at": "2026-11-19T10:30:00Z",
            },
        )

    result = run_post(message, handler)

    assert captured == {
        "url": "https://mastodon.example/api/v1/statuses",
        "authorization": "Bearer synthetic-mastodon-token",
        "accept": "application/json",
        "form": {"status": [message], "visibility": ["public"]},
    }
    assert result.platform == "Mastodon"
    assert result.status == "success"
    assert str(result.posted_url) == "https://mastodon.example/@user/123"
    assert result.public_access is True
    assert result.date == date(2026, 11, 19)
    assert result.time == time(10, 30, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("instance_url", "access_token"),
    [
        (None, "synthetic-mastodon-token"),
        ("https://mastodon.example", None),
        ("http://mastodon.example", "synthetic-mastodon-token"),
        ("https://user:pass@mastodon.example", "synthetic-mastodon-token"),
        ("https://mastodon.example/path", "synthetic-mastodon-token"),
    ],
)
def test_missing_or_invalid_configuration_does_not_make_request(
    instance_url: str | None,
    access_token: str | None,
) -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    result = run_post(
        "A useful update https://example.com",
        handler,
        instance_url=instance_url,
        access_token=access_token,
    )

    assert called is False
    assert result.error is PostingError.NOT_CONFIGURED


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
def test_api_errors_are_sanitised(
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
    assert "synthetic-mastodon-token" not in caplog.text


def test_timeout_is_sanitised() -> None:
    secret = "synthetic-timeout-secret"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(secret, request=request)

    result = run_post("A useful update https://example.com", handler)

    assert result.status == "failed"
    assert result.error is PostingError.TIMEOUT
    assert secret not in result.model_dump_json()


def test_network_error_is_sanitised_and_not_logged(caplog) -> None:
    secret = "synthetic-network-secret"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(secret, request=request)

    result = run_post("A useful update https://example.com", handler)

    assert result.status == "failed"
    assert result.error is PostingError.FAILURE
    assert secret not in result.model_dump_json()
    assert secret not in caplog.text
    assert "synthetic-mastodon-token" not in caplog.text


@pytest.mark.parametrize(
    ("visibility", "public_access"),
    [
        ("public", True),
        ("unlisted", True),
        ("private", False),
        ("direct", False),
    ],
)
def test_public_access_matches_returned_visibility(
    visibility: str,
    public_access: bool,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "visibility": visibility,
                "created_at": "2026-11-19T10:30:00Z",
            },
        )

    result = run_post("A useful update https://example.com", handler)

    assert result.status == "success"
    assert result.posted_url is None
    assert result.public_access is public_access


def test_invalid_status_response_returns_safe_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"visibility": "unknown"})

    result = run_post("A useful update https://example.com", handler)

    assert result.status == "failed"
    assert result.error is PostingError.INVALID_RESPONSE


def test_malformed_visibility_type_returns_safe_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "visibility": [],
                "created_at": "2026-11-19T10:30:00Z",
            },
        )

    result = run_post("A useful update https://example.com", handler)

    assert result.status == "failed"
    assert result.error is PostingError.INVALID_RESPONSE
