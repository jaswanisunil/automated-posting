import asyncio
import json
from collections.abc import Callable
from datetime import datetime

import httpx
import pytest

from app.platforms.bluesky import BlueskyPlatform
from app.schemas import PostingError, PostingResult


SERVICE_URL = "https://pds.example"
IDENTIFIER = "sample.bsky.social"
APP_PASSWORD = "synthetic-app-password"
ACCESS_JWT = "synthetic-access-jwt"
REFRESH_JWT = "synthetic-refresh-jwt"
DID = "did:plc:abcdefghijklmnopqrstuvwx"
HANDLE = "sample.bsky.social"
RECORD_KEY = "3jzfcijpj2z2a"
RECORD_URI = f"at://{DID}/app.bsky.feed.post/{RECORD_KEY}"
MESSAGE = "A useful update https://example.com"


def session_response(**overrides: object) -> dict[str, object]:
    return {
        "accessJwt": ACCESS_JWT,
        "refreshJwt": REFRESH_JWT,
        "handle": HANDLE,
        "did": DID,
        **overrides,
    }


def record_response(**overrides: object) -> dict[str, object]:
    return {
        "uri": RECORD_URI,
        "cid": "bafyreibsyntheticcid",
        **overrides,
    }


def run_post(
    message: str,
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    identifier: str | None = IDENTIFIER,
    app_password: str | None = APP_PASSWORD,
    service_url: str | None = SERVICE_URL,
) -> PostingResult:
    async def execute() -> PostingResult:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as client:
            platform = BlueskyPlatform(
                identifier=identifier,
                app_password=app_password,
                service_url=service_url,
                client=client,
            )
            return await platform.post(message)

    return asyncio.run(execute())


def test_creates_session_then_publishes_original_message() -> None:
    captured: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(
            {
                "url": str(request.url),
                "headers": dict(request.headers),
                "payload": json.loads(request.content),
            }
        )
        if request.url.path.endswith("server.createSession"):
            return httpx.Response(200, json=session_response())
        return httpx.Response(200, json=record_response())

    result = run_post(MESSAGE, handler)

    assert len(captured) == 2
    session_request, post_request = captured
    assert session_request["url"] == (
        f"{SERVICE_URL}/xrpc/com.atproto.server.createSession"
    )
    assert session_request["payload"] == {
        "identifier": IDENTIFIER,
        "password": APP_PASSWORD,
    }
    assert post_request["url"] == (
        f"{SERVICE_URL}/xrpc/com.atproto.repo.createRecord"
    )
    post_headers = post_request["headers"]
    assert isinstance(post_headers, dict)
    assert post_headers["authorization"] == f"Bearer {ACCESS_JWT}"
    post_record = post_request["payload"]
    assert isinstance(post_record, dict)
    assert post_record["repo"] == DID
    assert post_record["collection"] == "app.bsky.feed.post"
    record = post_record["record"]
    assert isinstance(record, dict)
    assert record["$type"] == "app.bsky.feed.post"
    assert record["text"] == MESSAGE
    created_at = record["createdAt"]
    assert isinstance(created_at, str) and created_at.endswith("Z")

    result_time = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    assert result.status == "success"
    assert result.platform == "Bluesky"
    assert str(result.posted_url) == (
        f"https://bsky.app/profile/{DID}/post/{RECORD_KEY}"
    )
    assert result.public_access is None
    assert result.date == result_time.date()
    assert result.time == result_time.timetz()
    assert APP_PASSWORD not in result.model_dump_json()
    assert ACCESS_JWT not in result.model_dump_json()
    assert REFRESH_JWT not in result.model_dump_json()


@pytest.mark.parametrize(
    ("identifier", "app_password", "service_url"),
    [
        (None, APP_PASSWORD, SERVICE_URL),
        (IDENTIFIER, None, SERVICE_URL),
        (IDENTIFIER, APP_PASSWORD, None),
        (" ", APP_PASSWORD, SERVICE_URL),
        (IDENTIFIER, " ", SERVICE_URL),
        (IDENTIFIER, APP_PASSWORD, "http://pds.example"),
        (IDENTIFIER, APP_PASSWORD, "https://user:pass@pds.example"),
        (IDENTIFIER, APP_PASSWORD, "https://pds.example/path"),
        (IDENTIFIER, APP_PASSWORD, "https://pds.example?query=1"),
        (IDENTIFIER, APP_PASSWORD, "https://pds.example#fragment"),
    ],
)
def test_missing_or_invalid_configuration_does_not_make_requests(
    identifier: str | None,
    app_password: str | None,
    service_url: str | None,
) -> None:
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    result = run_post(
        MESSAGE,
        handler,
        identifier=identifier,
        app_password=app_password,
        service_url=service_url,
    )

    assert called is False
    assert result.error is PostingError.NOT_CONFIGURED


def test_invalid_credentials_stop_after_session_failure(caplog) -> None:
    secret = f"synthetic-login-error-{APP_PASSWORD}"
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(401, json={"message": secret})

    result = run_post(MESSAGE, handler)

    assert paths == ["/xrpc/com.atproto.server.createSession"]
    assert result.error is PostingError.AUTHENTICATION
    assert secret not in result.model_dump_json()
    assert secret not in caplog.text
    assert APP_PASSWORD not in caplog.text


@pytest.mark.parametrize(
    ("stage", "status_code", "expected_error"),
    [
        ("session", 429, PostingError.RATE_LIMITED),
        ("session", 500, PostingError.FAILURE),
        ("record", 400, PostingError.REJECTED),
        ("record", 401, PostingError.AUTHENTICATION),
        ("record", 403, PostingError.AUTHENTICATION),
        ("record", 429, PostingError.RATE_LIMITED),
        ("record", 500, PostingError.FAILURE),
    ],
)
def test_api_errors_are_sanitised(
    stage: str,
    status_code: int,
    expected_error: PostingError,
    caplog,
) -> None:
    secret = f"synthetic-api-error-{APP_PASSWORD}-{ACCESS_JWT}"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("server.createSession"):
            if stage == "session":
                return httpx.Response(status_code, json={"message": secret})
            return httpx.Response(200, json=session_response())
        return httpx.Response(status_code, json={"message": secret})

    result = run_post(MESSAGE, handler)

    assert result.status == "failed"
    assert result.error is expected_error
    assert secret not in result.model_dump_json()
    assert secret not in caplog.text
    assert APP_PASSWORD not in caplog.text
    assert ACCESS_JWT not in caplog.text
    assert REFRESH_JWT not in caplog.text


@pytest.mark.parametrize("stage", ["session", "record"])
def test_timeouts_are_sanitised(stage: str, caplog) -> None:
    secret = f"synthetic-timeout-{APP_PASSWORD}-{ACCESS_JWT}-{REFRESH_JWT}"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("server.createSession") and stage == "record":
            return httpx.Response(200, json=session_response())
        raise httpx.ReadTimeout(secret, request=request)

    result = run_post(MESSAGE, handler)

    assert result.error is PostingError.TIMEOUT
    assert secret not in result.model_dump_json()
    assert secret not in caplog.text


def test_network_errors_are_sanitised(caplog) -> None:
    secret = f"synthetic-network-{APP_PASSWORD}-{ACCESS_JWT}"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("server.createSession"):
            return httpx.Response(200, json=session_response())
        raise httpx.ConnectError(secret, request=request)

    result = run_post(MESSAGE, handler)

    assert result.error is PostingError.FAILURE
    assert secret not in result.model_dump_json()
    assert secret not in caplog.text


@pytest.mark.parametrize(
    ("message", "expected_error"),
    [
        ("x" * 301, PostingError.CONTENT_TOO_LONG),
        (("e\u0301") * 301, PostingError.CONTENT_TOO_LONG),
    ],
)
def test_messages_over_300_graphemes_are_rejected_without_truncation(
    message: str,
    expected_error: PostingError,
) -> None:
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    result = run_post(message, handler)

    assert called is False
    assert result.error is expected_error


def test_message_over_utf8_byte_limit_is_rejected() -> None:
    message = ("a" + "\u0301" * 11) * 200
    assert len(message.encode("utf-8")) > 3000

    def handler(_request: httpx.Request) -> httpx.Response:
        pytest.fail("Over-limit message must not be sent")

    result = run_post(message, handler)

    assert result.error is PostingError.CONTENT_TOO_LONG


@pytest.mark.parametrize(
    "message",
    [
        "x" * 300,
        ("e\u0301") * 300,
    ],
)
def test_300_graphemes_are_preserved_and_accepted(message: str) -> None:
    posted_messages: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("server.createSession"):
            return httpx.Response(200, json=session_response())
        payload = json.loads(request.content)
        posted_messages.append(payload["record"]["text"])
        return httpx.Response(200, json=record_response())

    result = run_post(message, handler)

    assert posted_messages == [message]
    assert result.status == "success"


@pytest.mark.parametrize(
    "session_data",
    [
        [],
        {},
        {"accessJwt": ACCESS_JWT, "refreshJwt": REFRESH_JWT, "did": DID},
        {**session_response(), "accessJwt": "bad\r\nAuthorization: injected"},
        {**session_response(), "did": "not-a-did"},
        {**session_response(), "active": None},
        {**session_response(), "active": "false"},
    ],
)
def test_malformed_session_response_stops_safely(session_data: object) -> None:
    record_request_made = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal record_request_made
        if request.url.path.endswith("server.createSession"):
            return httpx.Response(200, json=session_data)
        record_request_made = True
        return httpx.Response(200, json=record_response())

    result = run_post(MESSAGE, handler)

    assert result.error is PostingError.INVALID_RESPONSE
    assert record_request_made is False


@pytest.mark.parametrize(
    "record_data",
    [
        [],
        {},
        {"uri": RECORD_URI},
        {"uri": f"at://{DID}/app.bsky.feed.like/{RECORD_KEY}", "cid": "cid"},
        {
            "uri": f"at://did:plc:anotherdid/app.bsky.feed.post/{RECORD_KEY}",
            "cid": "cid",
        },
        {"uri": f"{RECORD_URI}/extra", "cid": "cid"},
    ],
)
def test_malformed_record_response_returns_safe_failure(record_data: object) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("server.createSession"):
            return httpx.Response(200, json=session_response())
        return httpx.Response(200, json=record_data)

    result = run_post(MESSAGE, handler)

    assert result.error is PostingError.INVALID_RESPONSE
    assert result.posted_url is None


def test_non_json_session_response_returns_safe_failure() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json")

    result = run_post(MESSAGE, handler)

    assert result.error is PostingError.INVALID_RESPONSE
