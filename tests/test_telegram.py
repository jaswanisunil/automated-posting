import asyncio
import json
from collections.abc import Callable
from datetime import date, datetime, time, timezone

import httpx
import pytest

from app.platforms.telegram import TelegramPlatform
from app.schemas import PostingError, PostingResult


BOT_TOKEN = "123456:synthetic_token"
MESSAGE = "A useful update https://example.com"
POSTED_AT = datetime(2026, 11, 19, 10, 30, tzinfo=timezone.utc)


def api_message(
    *,
    chat_type: str = "channel",
    username: str | None = "sample_channel",
    chat_id: int = -100123456,
    message_id: int = 42,
    timestamp: int | None = None,
) -> dict[str, object]:
    return {
        "message_id": message_id,
        "date": int(POSTED_AT.timestamp()) if timestamp is None else timestamp,
        "chat": {
            "id": chat_id,
            "type": chat_type,
            **({"username": username} if username is not None else {}),
        },
        "text": MESSAGE,
    }


def run_post(
    message: str,
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    bot_token: str | None = BOT_TOKEN,
    chat_id: str | None = "@sample_channel",
) -> PostingResult:
    async def execute() -> PostingResult:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as client:
            platform = TelegramPlatform(
                bot_token=bot_token,
                chat_id=chat_id,
                client=client,
            )
            return await platform.post(message)

    return asyncio.run(execute())


def test_sends_original_message_to_telegram_bot_api() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"ok": True, "result": api_message()},
        )

    result = run_post(MESSAGE, handler)

    assert captured == {
        "url": f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        "payload": {"chat_id": "@sample_channel", "text": MESSAGE},
    }
    assert result.platform == "Telegram"
    assert result.status == "success"
    assert str(result.posted_url) == "https://t.me/sample_channel/42"
    assert result.public_access is True
    assert result.date == date(2026, 11, 19)
    assert result.time == time(10, 30, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("bot_token", "chat_id"),
    [
        (None, "@sample_channel"),
        (BOT_TOKEN, None),
        (" ", "@sample_channel"),
        (BOT_TOKEN, " "),
    ],
)
def test_missing_configuration_does_not_make_request(
    bot_token: str | None,
    chat_id: str | None,
) -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    result = run_post(MESSAGE, handler, bot_token=bot_token, chat_id=chat_id)

    assert called is False
    assert result.error is PostingError.NOT_CONFIGURED


def test_malformed_token_is_rejected_without_request() -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    result = run_post(MESSAGE, handler, bot_token="not-a-valid-token")

    assert called is False
    assert result.error is PostingError.AUTHENTICATION


@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [
        (400, PostingError.DESTINATION_UNAVAILABLE),
        (401, PostingError.AUTHENTICATION),
        (403, PostingError.DESTINATION_UNAVAILABLE),
        (404, PostingError.REJECTED),
        (429, PostingError.RATE_LIMITED),
        (500, PostingError.FAILURE),
    ],
)
def test_http_api_errors_are_sanitised(
    status_code: int,
    expected_error: PostingError,
    caplog,
) -> None:
    secret = "synthetic-telegram-api-description"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"description": secret})

    result = run_post(MESSAGE, handler)

    assert result.status == "failed"
    assert result.error is expected_error
    assert result.public_access is False
    assert secret not in result.model_dump_json()
    assert secret not in caplog.text
    assert BOT_TOKEN not in caplog.text


def test_api_authentication_error_in_success_http_response_is_handled() -> None:
    secret = "synthetic-invalid-token-detail"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"ok": False, "error_code": 401, "description": secret},
        )

    result = run_post(MESSAGE, handler)

    assert result.error is PostingError.AUTHENTICATION
    assert secret not in result.model_dump_json()


def test_timeout_does_not_expose_bot_token_or_exception_message(caplog) -> None:
    secret = f"synthetic-timeout-detail-{BOT_TOKEN}"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(secret, request=request)

    result = run_post(MESSAGE, handler)

    assert result.error is PostingError.TIMEOUT
    assert secret not in result.model_dump_json()
    assert secret not in caplog.text


def test_network_error_does_not_expose_bot_token_or_exception_message(caplog) -> None:
    secret = f"synthetic-network-detail-{BOT_TOKEN}"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(secret, request=request)

    result = run_post(MESSAGE, handler)

    assert result.error is PostingError.FAILURE
    assert secret not in result.model_dump_json()
    assert secret not in caplog.text


@pytest.mark.parametrize(
    ("chat_type", "username", "expected_public", "expected_url"),
    [
        ("channel", "sample_channel", True, "https://t.me/sample_channel/42"),
        ("supergroup", "sample_group", True, "https://t.me/sample_group/42"),
        ("channel", None, False, None),
        ("group", "sample_group", False, None),
        ("private", "sample_user", False, None),
    ],
)
def test_public_access_depends_on_public_chat_type_and_username(
    chat_type: str,
    username: str | None,
    expected_public: bool,
    expected_url: str | None,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": api_message(chat_type=chat_type, username=username),
            },
        )

    result = run_post(MESSAGE, handler)

    assert result.status == "success"
    assert result.public_access is expected_public
    if expected_url is None:
        assert result.posted_url is None
    else:
        assert str(result.posted_url) == expected_url


@pytest.mark.parametrize(
    "response_data",
    [
        [],
        {"ok": True},
        {"ok": True, "result": []},
        {"ok": True, "result": {"chat": {"id": 1, "type": []}}},
        {
            "ok": True,
            "result": {
                **api_message(),
                "date": "not-a-timestamp",
            },
        },
        {
            "ok": True,
            "result": {
                **api_message(),
                "message_id": True,
            },
        },
        {"ok": False, "description": "response detail without an error code"},
    ],
)
def test_malformed_api_responses_return_safe_failure(response_data: object) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response_data)

    result = run_post(MESSAGE, handler)

    assert result.status == "failed"
    assert result.error is PostingError.INVALID_RESPONSE


def test_non_json_api_response_returns_safe_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json")

    result = run_post(MESSAGE, handler)

    assert result.error is PostingError.INVALID_RESPONSE
