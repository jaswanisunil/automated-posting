import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.schemas import PostingRequest


client = TestClient(app)


def test_accepts_message_with_exactly_200_characters() -> None:
    url = "https://example.com"
    message = f'{"x" * (200 - len(url) - 1)} {url}'

    assert len(message) == 200
    assert PostingRequest(message=message).message == message


@pytest.mark.parametrize(
    "message",
    [
        "",
        " ",
        "\t\n",
        "A message without a link",
        "Try this https://",
        "Try this https://example.com:invalid",
        "Try this https://user:secret@example.com",
        "Try this ftp://example.com",
        "Try https://example.com and ftp://example.org",
        "Try https://example.com and https://example.org",
        "Try https://example.com,https://example.org",
    ],
)
def test_rejects_invalid_messages(message: str) -> None:
    with pytest.raises(ValidationError):
        PostingRequest(message=message)


@pytest.mark.parametrize(
    "message",
    [
        "Try this https://example.com.",
        "Try this https://example.com/path).",
        "Try this http://example.com!",
    ],
)
def test_accepts_http_urls_with_trailing_punctuation(message: str) -> None:
    assert PostingRequest(message=message).message == message


def test_rejects_message_over_200_characters() -> None:
    message = f'{"x" * (201 - len("https://example.com"))}https://example.com'

    assert len(message) == 201
    with pytest.raises(ValidationError):
        PostingRequest(message=message)


def test_health_endpoint_returns_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_posting_endpoint_rejects_invalid_input() -> None:
    response = client.post("/posting", json={"message": "No CTA link"})

    assert response.status_code == 422


def test_posting_endpoint_reports_missing_dev_configuration(monkeypatch) -> None:
    monkeypatch.setenv("DEV_API_KEY", "")
    monkeypatch.setenv("MASTODON_INSTANCE_URL", "")
    monkeypatch.setenv("MASTODON_ACCESS_TOKEN", "")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "")
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "")
    monkeypatch.setenv("BLUESKY_IDENTIFIER", "")
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", "")
    monkeypatch.setenv("BLUESKY_SERVICE_URL", "")

    response = client.post(
        "/posting",
        json={"message": "Check this out https://example.com"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "success": False,
        "results": [
            {
                "platform": "DEV/Forem",
                "status": "failed",
                "posted_url": None,
                "public_access": False,
                "date": None,
                "time": None,
                "error": "The platform is not configured.",
            },
            {
                "platform": "Mastodon",
                "status": "failed",
                "posted_url": None,
                "public_access": False,
                "date": None,
                "time": None,
                "error": "The platform is not configured.",
            },
            {
                "platform": "Telegram",
                "status": "failed",
                "posted_url": None,
                "public_access": False,
                "date": None,
                "time": None,
                "error": "The platform is not configured.",
            },
            {
                "platform": "Discord",
                "status": "failed",
                "posted_url": None,
                "public_access": False,
                "date": None,
                "time": None,
                "error": "The platform is not configured.",
            },
            {
                "platform": "Bluesky",
                "status": "failed",
                "posted_url": None,
                "public_access": None,
                "date": None,
                "time": None,
                "error": "The platform is not configured.",
            },
        ],
    }
