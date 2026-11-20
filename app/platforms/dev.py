import logging
from datetime import datetime, timezone
from math import isfinite
from typing import Any

import httpx
from pydantic import AnyHttpUrl, TypeAdapter, ValidationError

from app.platforms.base import Platform
from app.schemas import PostingError, PostingResult


logger = logging.getLogger(__name__)
_ARTICLE_URL_ADAPTER = TypeAdapter(AnyHttpUrl)
_MAX_FULL_POST_TITLE_CHARACTERS = 128


class DevPlatform(Platform):
    name = "DEV/Forem"
    articles_url = "https://dev.to/api/articles"

    def __init__(
        self,
        api_key: str | None,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("Platform timeout must be a positive, finite number.")

        self._api_key = api_key.strip() if api_key and api_key.strip() else None
        self._client = client
        self._timeout_seconds = timeout_seconds

    async def post(self, message: str) -> PostingResult:
        if self._api_key is None:
            return self._failed_result(PostingError.NOT_CONFIGURED, public_access=False)

        article = {
            "title": self._title_from_message(message),
            "body_markdown": message,
            "published": True,
        }
        headers = {
            "api-key": self._api_key,
            "Accept": "application/json",
        }

        try:
            response = await self._send_article(headers, article)
        except httpx.TimeoutException as error:
            logger.warning("DEV API request timed out (%s).", type(error).__name__)
            return self._failed_result(PostingError.TIMEOUT)
        except httpx.RequestError as error:
            logger.warning("DEV API request failed (%s).", type(error).__name__)
            return self._failed_result(PostingError.FAILURE)

        if not response.is_success:
            return self._handle_api_error(response.status_code)

        try:
            response_data = response.json()
        except ValueError:
            return self._invalid_response(response.status_code)

        if not isinstance(response_data, dict):
            return self._invalid_response(response.status_code)

        article_data = response_data.get("article", response_data)
        if not isinstance(article_data, dict):
            return self._invalid_response(response.status_code)

        published = article_data.get("published")
        if published is not None and not isinstance(published, bool):
            return self._invalid_response(response.status_code)
        if published is False:
            logger.warning(
                "DEV API created an unpublished article (HTTP %d).",
                response.status_code,
            )
            return self._failed_result(
                PostingError.REJECTED,
                public_access=False,
            )

        posted_url = article_data.get("url")
        validated_posted_url: AnyHttpUrl | None = None
        if posted_url is not None:
            if not isinstance(posted_url, str):
                return self._invalid_response(response.status_code)
            try:
                validated_posted_url = _ARTICLE_URL_ADAPTER.validate_python(posted_url)
            except ValidationError:
                return self._invalid_response(response.status_code)

        try:
            published_at = self._publication_time(article_data)
        except ValueError:
            return self._invalid_response(response.status_code)

        return PostingResult(
            platform=self.name,
            status="success",
            posted_url=validated_posted_url,
            public_access=published if isinstance(published, bool) else None,
            date=published_at.date(),
            time=published_at.timetz(),
        )

    async def _send_article(
        self,
        headers: dict[str, str],
        article: dict[str, Any],
    ) -> httpx.Response:
        if self._client is not None:
            return await self._client.post(
                self.articles_url,
                headers=headers,
                json={"article": article},
                timeout=self._timeout_seconds,
            )

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            return await client.post(
                self.articles_url,
                headers=headers,
                json={"article": article},
            )

    def _handle_api_error(self, status_code: int) -> PostingResult:
        if status_code in (401, 403):
            error = PostingError.AUTHENTICATION
        elif status_code == 429:
            error = PostingError.RATE_LIMITED
        elif 400 <= status_code < 500:
            error = PostingError.REJECTED
        else:
            error = PostingError.FAILURE

        logger.warning("DEV API returned HTTP status %d.", status_code)
        return self._failed_result(
            error,
            public_access=False if 400 <= status_code < 500 else None,
        )

    def _invalid_response(self, status_code: int) -> PostingResult:
        logger.warning("DEV API returned an invalid article response (HTTP %d).", status_code)
        return self._failed_result(PostingError.INVALID_RESPONSE)

    @staticmethod
    def _title_from_message(message: str) -> str:
        title_characters = []
        non_whitespace_count = 0

        for character in message:
            if not character.isspace():
                if non_whitespace_count == _MAX_FULL_POST_TITLE_CHARACTERS:
                    break
                non_whitespace_count += 1
            title_characters.append(character)

        return "".join(title_characters).strip()

    @staticmethod
    def _publication_time(article_data: dict[str, Any]) -> datetime:
        value = article_data.get("published_at") or article_data.get("created_at")
        if value is None:
            return datetime.now(timezone.utc)
        if not isinstance(value, str):
            raise ValueError("Invalid publication timestamp.")

        publication_time = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if publication_time.tzinfo is None:
            publication_time = publication_time.replace(tzinfo=timezone.utc)
        return publication_time

    def _failed_result(
        self,
        error: PostingError,
        public_access: bool | None = None,
    ) -> PostingResult:
        return PostingResult(
            platform=self.name,
            status="failed",
            public_access=public_access,
            error=error,
        )
