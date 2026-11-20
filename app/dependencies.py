import os
from math import isfinite

from app.platforms.bluesky import BlueskyPlatform
from app.platforms.dev import DevPlatform
from app.platforms.discord import DiscordPlatform
from app.platforms.mastodon import MastodonPlatform
from app.platforms.telegram import TelegramPlatform
from app.services.posting_service import PostingService


def _configured_timeout(variable_name: str) -> float:
    timeout_value = os.getenv(variable_name, "10")
    try:
        timeout_seconds = float(timeout_value)
    except ValueError as error:
        raise ValueError(f"{variable_name} must be a number.") from error

    if not isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError(f"{variable_name} must be a positive finite number.")

    return timeout_seconds


def get_posting_service() -> PostingService:
    dev_timeout = _configured_timeout("DEV_PLATFORM_TIMEOUT_SECONDS")
    mastodon_timeout = _configured_timeout("MASTODON_PLATFORM_TIMEOUT_SECONDS")
    telegram_timeout = _configured_timeout("TELEGRAM_PLATFORM_TIMEOUT_SECONDS")
    discord_timeout = _configured_timeout("DISCORD_PLATFORM_TIMEOUT_SECONDS")
    bluesky_timeout = _configured_timeout("BLUESKY_PLATFORM_TIMEOUT_SECONDS")
    return PostingService(
        [
            DevPlatform(
                api_key=os.getenv("DEV_API_KEY"),
                timeout_seconds=dev_timeout,
            ),
            MastodonPlatform(
                instance_url=os.getenv("MASTODON_INSTANCE_URL"),
                access_token=os.getenv("MASTODON_ACCESS_TOKEN"),
                timeout_seconds=mastodon_timeout,
            ),
            TelegramPlatform(
                bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
                chat_id=os.getenv("TELEGRAM_CHAT_ID"),
                timeout_seconds=telegram_timeout,
            ),
            DiscordPlatform(
                webhook_url=os.getenv("DISCORD_WEBHOOK_URL"),
                timeout_seconds=discord_timeout,
            ),
            BlueskyPlatform(
                identifier=os.getenv("BLUESKY_IDENTIFIER"),
                app_password=os.getenv("BLUESKY_APP_PASSWORD"),
                service_url=os.getenv("BLUESKY_SERVICE_URL"),
                timeout_seconds=bluesky_timeout,
            ),
        ],
        platform_timeout_seconds=max(
            dev_timeout,
            mastodon_timeout,
            telegram_timeout,
            discord_timeout,
            bluesky_timeout,
        ),
    )
