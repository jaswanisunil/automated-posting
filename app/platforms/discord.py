import logging
import re
from datetime import datetime
from math import isfinite
from urllib.parse import urlsplit

import httpx

from app.platforms.base import Platform
from app.schemas import PostingError, PostingResult


logger = logging.getLogger(__name__)
_WEBHOOK_PATH_PATTERN = re.compile(
    r"/api/webhooks/[0-9]+/[A-Za-z0-9._-]+\Z"
)
_MESSAGE_ID_PATTERN = re.compile(r"[0-9]+\Z")


class DiscordPlatform(Platform):
    name = "Discord"

    def __init__(
        self,
        webhook_url: str | None,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("Platform timeout must be a positive, finite number.")

        self._webhook_url = self._normalize_webhook_url(webhook_url)
        self._client = client
        self._timeout_seconds = timeout_seconds

    async def post(self, message: str) -> PostingResult:
        webhook_url = self._webhook_url
        if webhook_url is None:
            return self._failed_result(PostingError.NOT_CONFIGURED)

        try:
            response = await self._execute_webhook(webhook_url, message)
        except httpx.TimeoutException as error:
            logger.warning("Discord webhook timed out (%s).", type(error).__name__)
            return self._failed_result(PostingError.TIMEOUT)
        except httpx.RequestError as error:
            logger.warning("Discord webhook request failed (%s).", type(error).__name__)
            return self._failed_result(PostingError.FAILURE)

        if not response.is_success:
            return self._handle_api_error(response.status_code)

        try:
            response_data = response.json()
        except ValueError:
            return self._invalid_response(response.status_code)

        if not isinstance(response_data, dict):
            return self._invalid_response(response.status_code)

        message_id = response_data.get("id")
        timestamp = response_data.get("timestamp")
        if (
            not isinstance(message_id, str)
            or _MESSAGE_ID_PATTERN.fullmatch(message_id) is None
            or not isinstance(timestamp, str)
        ):
            return self._invalid_response(response.status_code)

        try:
            posted_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            return self._invalid_response(response.status_code)
        if posted_at.tzinfo is None:
            return self._invalid_response(response.status_code)

        return PostingResult(
            platform=self.name,
            status="success",
            posted_url=None,
            public_access=False,
            date=posted_at.date(),
            time=posted_at.timetz(),
        )

    async def _execute_webhook(
        self,
        webhook_url: str,
        message: str,
    ) -> httpx.Response:
        if self._client is not None:
            return await self._client.post(
                webhook_url,
                params={"wait": "true"},
                json={"content": message},
                timeout=self._timeout_seconds,
            )

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            return await client.post(
                webhook_url,
                params={"wait": "true"},
                json={"content": message},
            )

    def _handle_api_error(self, status_code: int) -> PostingResult:
        if status_code in (401, 403, 404):
            error = PostingError.AUTHENTICATION
        elif status_code == 429:
            error = PostingError.RATE_LIMITED
        elif 400 <= status_code < 500:
            error = PostingError.REJECTED
        else:
            error = PostingError.FAILURE

        logger.warning("Discord webhook returned HTTP status %d.", status_code)
        return self._failed_result(error)

    def _invalid_response(self, status_code: int) -> PostingResult:
        logger.warning(
            "Discord webhook returned an invalid message response (HTTP %d).",
            status_code,
        )
        return self._failed_result(PostingError.INVALID_RESPONSE)

    def _failed_result(self, error: PostingError) -> PostingResult:
        return PostingResult(
            platform=self.name,
            status="failed",
            public_access=False,
            error=error,
        )

    @staticmethod
    def _normalize_webhook_url(value: str | None) -> str | None:
        if not value:
            return None

        candidate = value.strip()
        if not candidate or any(character.isspace() for character in candidate):
            return None
        try:
            parsed_url = urlsplit(candidate)
            port = parsed_url.port
        except ValueError:
            return None

        if (
            parsed_url.scheme.lower() != "https"
            or parsed_url.hostname is None
            or parsed_url.hostname.lower() != "discord.com"
            or port not in (None, 443)
            or parsed_url.username is not None
            or parsed_url.password is not None
            or parsed_url.query
            or parsed_url.fragment
            or _WEBHOOK_PATH_PATTERN.fullmatch(parsed_url.path) is None
        ):
            return None

        return f"https://discord.com{parsed_url.path}"
