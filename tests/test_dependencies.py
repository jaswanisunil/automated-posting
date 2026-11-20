from app.dependencies import get_posting_service
from app.platforms.bluesky import BlueskyPlatform
from app.platforms.dev import DevPlatform
from app.platforms.discord import DiscordPlatform
from app.platforms.mastodon import MastodonPlatform
from app.platforms.telegram import TelegramPlatform


def test_posting_service_injects_platforms_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("DEV_API_KEY", "synthetic-dev-key")
    monkeypatch.setenv("DEV_PLATFORM_TIMEOUT_SECONDS", "8")
    monkeypatch.setenv("MASTODON_INSTANCE_URL", "https://mastodon.example")
    monkeypatch.setenv("MASTODON_ACCESS_TOKEN", "synthetic-mastodon-token")
    monkeypatch.setenv("MASTODON_PLATFORM_TIMEOUT_SECONDS", "5")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:synthetic_token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "@example_channel")
    monkeypatch.setenv("TELEGRAM_PLATFORM_TIMEOUT_SECONDS", "3")
    monkeypatch.setenv(
        "DISCORD_WEBHOOK_URL",
        "https://discord.com/api/webhooks/123456/synthetic_webhook_token",
    )
    monkeypatch.setenv("DISCORD_PLATFORM_TIMEOUT_SECONDS", "2")
    monkeypatch.setenv("BLUESKY_IDENTIFIER", "sample.bsky.social")
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", "synthetic-app-password")
    monkeypatch.setenv("BLUESKY_SERVICE_URL", "https://pds.example")
    monkeypatch.setenv("BLUESKY_PLATFORM_TIMEOUT_SECONDS", "1")

    service = get_posting_service()

    assert len(service._platforms) == 5
    (
        dev_platform,
        mastodon_platform,
        telegram_platform,
        discord_platform,
        bluesky_platform,
    ) = service._platforms
    assert isinstance(dev_platform, DevPlatform)
    assert dev_platform._api_key == "synthetic-dev-key"
    assert dev_platform._timeout_seconds == 8
    assert isinstance(mastodon_platform, MastodonPlatform)
    assert mastodon_platform._instance_url == "https://mastodon.example"
    assert mastodon_platform._access_token == "synthetic-mastodon-token"
    assert mastodon_platform._timeout_seconds == 5
    assert isinstance(telegram_platform, TelegramPlatform)
    assert telegram_platform._bot_token == "123456:synthetic_token"
    assert telegram_platform._chat_id == "@example_channel"
    assert telegram_platform._timeout_seconds == 3
    assert isinstance(discord_platform, DiscordPlatform)
    assert (
        discord_platform._webhook_url
        == "https://discord.com/api/webhooks/123456/synthetic_webhook_token"
    )
    assert discord_platform._timeout_seconds == 2
    assert isinstance(bluesky_platform, BlueskyPlatform)
    assert bluesky_platform._identifier == "sample.bsky.social"
    assert bluesky_platform._app_password == "synthetic-app-password"
    assert bluesky_platform._service_url == "https://pds.example"
    assert bluesky_platform._timeout_seconds == 1
    assert service._platform_timeout_seconds == 8
