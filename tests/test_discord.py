import asyncio
import json
from collections.abc import Callable
from datetime import date, datetime, time, timezone

import httpx
import pytest

from app.platforms.discord import DiscordPlatform
from app.schemas import PostingError, PostingResult


WEBHOOK_URL = (
    "https://discord.com/api/webhooks/123456/synthetic_webhook_token"
)
MESSAGE = "A useful update https://example.com"
POSTED_AT = datetime(2026, 11, 19, 10, 30, tzinfo=timezone.utc)


def run_post(
    message: str,
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    webhook_url: str | None = WEBHOOK_URL,
) -> PostingResult:
    async def execute() -> PostingResult:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as client:
            platform = DiscordPlatform(
                webhook_url=webhook_url,
                client=client,
            )
            return await platform.post(message)

    return asyncio.run(execute())


def test_executes_webhook_with_wait_and_original_content() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "123456789012345678",
                "timestamp": "2026-11-19T10:30:00Z",
                "content": MESSAGE,
            },
        )

    result = run_post(MESSAGE, handler)

    assert captured == {
        "url": f"{WEBHOOK_URL}?wait=true",
        "payload": {"content": MESSAGE},
    }
    assert result.platform == "Discord"
    assert result.status == "success"
    assert result.posted_url is None
    assert result.public_access is False
    assert result.date == date(2026, 11, 19)
    assert result.time == time(10, 30, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "webhook_url",
    [
        None,
        "",
        " ",
        "http://discord.com/api/webhooks/123456/token",
        "https://example.com/api/webhooks/123456/token",
        "https://user:pass@discord.com/api/webhooks/123456/token",
        "https://discord.com/api/webhooks/123456/token/extra",
        "https://discord.com/api/webhooks/123456/token?wait=false",
        "https://discord.com/api/webhooks/123456/token#fragment",
        "https://discord.com:8443/api/webhooks/123456/token",
        "https://discord.com/api/webhooks/not-a-number/token",
        "https://discord.com/api/webhooks/123456/token with space",
    ],
)
def test_missing_or_invalid_webhook_url_does_not_make_request(
    webhook_url: str | None,
) -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    result = run_post(MESSAGE, handler, webhook_url=webhook_url)

    assert called is False
    assert result.error is PostingError.NOT_CONFIGURED


@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [
        (400, PostingError.REJECTED),
        (401, PostingError.AUTHENTICATION),
        (403, PostingError.AUTHENTICATION),
        (404, PostingError.AUTHENTICATION),
        (429, PostingError.RATE_LIMITED),
        (500, PostingError.FAILURE),
    ],
)
def test_api_errors_are_sanitised(
    status_code: int,
    expected_error: PostingError,
    caplog,
) -> None:
    secret = "synthetic-discord-response-detail"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            json={"message": secret, "retry_after": 123},
        )

    result = run_post(MESSAGE, handler)

    assert result.status == "failed"
    assert result.error is expected_error
    assert result.public_access is False
    assert secret not in result.model_dump_json()
    assert secret not in caplog.text
    assert WEBHOOK_URL not in caplog.text


def test_timeout_does_not_expose_webhook_url_or_exception(caplog) -> None:
    secret = f"synthetic-timeout-detail-{WEBHOOK_URL}"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(secret, request=request)

    result = run_post(MESSAGE, handler)

    assert result.error is PostingError.TIMEOUT
    assert secret not in result.model_dump_json()
    assert secret not in caplog.text


def test_network_error_does_not_expose_webhook_url_or_exception(caplog) -> None:
    secret = f"synthetic-network-detail-{WEBHOOK_URL}"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(secret, request=request)

    result = run_post(MESSAGE, handler)

    assert result.error is PostingError.FAILURE
    assert secret not in result.model_dump_json()
    assert secret not in caplog.text


@pytest.mark.parametrize(
    "response_data",
    [
        [],
        {},
        {"id": 123456789012345678, "timestamp": "2026-11-19T10:30:00Z"},
        {"id": "not-a-snowflake", "timestamp": "2026-11-19T10:30:00Z"},
        {"id": "123456789012345678"},
        {"id": "123456789012345678", "timestamp": "not-a-timestamp"},
        {"id": "123456789012345678", "timestamp": "2026-11-19T10:30:00"},
    ],
)
def test_malformed_success_response_returns_safe_failure(
    response_data: object,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response_data)

    result = run_post(MESSAGE, handler)

    assert result.status == "failed"
    assert result.error is PostingError.INVALID_RESPONSE
    assert result.public_access is False


@pytest.mark.parametrize(
    ("status_code", "content"),
    [
        (200, b"not-json"),
        (204, b""),
    ],
)
def test_missing_or_non_json_wait_response_is_invalid(
    status_code: int,
    content: bytes,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=content)

    result = run_post(MESSAGE, handler)

    assert result.error is PostingError.INVALID_RESPONSE
