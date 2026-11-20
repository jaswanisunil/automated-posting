import logging
import re
from datetime import datetime, timezone
from math import isfinite
from urllib.parse import quote

import httpx
from pydantic import AnyHttpUrl, TypeAdapter

from app.platforms.base import Platform
from app.schemas import PostingError, PostingResult


logger = logging.getLogger(__name__)
_BOT_TOKEN_PATTERN = re.compile(r"[0-9]+:[A-Za-z0-9_-]+\Z")
_CHAT_TYPES = {"private", "group", "supergroup", "channel"}
_POSTED_URL_ADAPTER = TypeAdapter(AnyHttpUrl)


class TelegramPlatform(Platform):
    name = "Telegram"
    api_base_url = "https://api.telegram.org"

    def __init__(
        self,
        bot_token: str | None,
        chat_id: str | None,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("Platform timeout must be a positive, finite number.")

        self._bot_token = bot_token.strip() if bot_token and bot_token.strip() else None
        self._chat_id = chat_id.strip() if chat_id and chat_id.strip() else None
        self._client = client
        self._timeout_seconds = timeout_seconds

    async def post(self, message: str) -> PostingResult:
        if self._bot_token is None or self._chat_id is None:
            return self._failed_result(PostingError.NOT_CONFIGURED)
        if _BOT_TOKEN_PATTERN.fullmatch(self._bot_token) is None:
            return self._failed_result(PostingError.AUTHENTICATION)

        try:
            response = await self._send_message(message)
        except httpx.TimeoutException as error:
            logger.warning("Telegram request timed out (%s).", type(error).__name__)
            return self._failed_result(PostingError.TIMEOUT)
        except httpx.RequestError as error:
            logger.warning("Telegram request failed (%s).", type(error).__name__)
            return self._failed_result(PostingError.FAILURE)

        if not response.is_success:
            return self._handle_api_error(response.status_code)

        try:
            response_data = response.json()
        except ValueError:
            return self._invalid_response(response.status_code)

        if not isinstance(response_data, dict):
            return self._invalid_response(response.status_code)
        if response_data.get("ok") is not True:
            error_code = response_data.get("error_code")
            if type(error_code) is not int:
                return self._invalid_response(response.status_code)
            return self._handle_api_error(error_code)

        result = response_data.get("result")
        if not isinstance(result, dict):
            return self._invalid_response(response.status_code)

        chat = result.get("chat")
        message_id = result.get("message_id")
        timestamp = result.get("date")
        if not isinstance(chat, dict):
            return self._invalid_response(response.status_code)
        chat_type = chat.get("type")
        if (
            type(chat.get("id")) is not int
            or not isinstance(chat_type, str)
            or chat_type not in _CHAT_TYPES
            or type(message_id) is not int
            or message_id <= 0
            or type(timestamp) is not int
        ):
            return self._invalid_response(response.status_code)

        username = chat.get("username")
        if username is not None and (
            not isinstance(username, str) or not username.strip()
        ):
            return self._invalid_response(response.status_code)

        try:
            posted_at = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return self._invalid_response(response.status_code)

        is_public_chat = False
        posted_url: AnyHttpUrl | None = None
        if (
            chat_type in {"channel", "supergroup"}
            and isinstance(username, str)
            and username
        ):
            is_public_chat = True
            posted_url = _POSTED_URL_ADAPTER.validate_python(
                f"https://t.me/{quote(username, safe='')}/{message_id}"
            )
        return PostingResult(
            platform=self.name,
            status="success",
            posted_url=posted_url,
            public_access=is_public_chat,
            date=posted_at.date(),
            time=posted_at.timetz(),
        )

    async def _send_message(self, message: str) -> httpx.Response:
        url = f"{self.api_base_url}/bot{self._bot_token}/sendMessage"
        payload = {"chat_id": self._chat_id, "text": message}
        if self._client is not None:
            return await self._client.post(
                url,
                json=payload,
                timeout=self._timeout_seconds,
            )

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            return await client.post(url, json=payload)

    def _handle_api_error(self, error_code: int) -> PostingResult:
        if error_code == 401:
            error = PostingError.AUTHENTICATION
        elif error_code == 429:
            error = PostingError.RATE_LIMITED
        elif error_code in (400, 403):
            error = PostingError.DESTINATION_UNAVAILABLE
        elif 400 <= error_code < 500:
            error = PostingError.REJECTED
        else:
            error = PostingError.FAILURE

        logger.warning("Telegram Bot API returned error code %d.", error_code)
        return self._failed_result(error)

    def _invalid_response(self, status_code: int) -> PostingResult:
        logger.warning(
            "Telegram Bot API returned an invalid message response (HTTP %d).",
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
