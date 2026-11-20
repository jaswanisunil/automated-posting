import logging
from datetime import datetime
from math import isfinite

import httpx
from pydantic import AnyHttpUrl, TypeAdapter, ValidationError

from app.platforms.base import Platform
from app.schemas import PostingError, PostingResult


logger = logging.getLogger(__name__)
_INSTANCE_URL_ADAPTER = TypeAdapter(AnyHttpUrl)
_POSTED_URL_ADAPTER = TypeAdapter(AnyHttpUrl)
_VISIBILITIES = {"public", "unlisted", "private", "direct"}


class MastodonPlatform(Platform):
    name = "Mastodon"

    def __init__(
        self,
        instance_url: str | None,
        access_token: str | None,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("Platform timeout must be a positive, finite number.")

        self._instance_url = self._normalize_instance_url(instance_url)
        self._access_token = (
            access_token.strip() if access_token and access_token.strip() else None
        )
        self._client = client
        self._timeout_seconds = timeout_seconds

    async def post(self, message: str) -> PostingResult:
        if self._instance_url is None or self._access_token is None:
            return self._failed_result(
                PostingError.NOT_CONFIGURED,
                public_access=False,
            )

        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json",
        }
        data = {"status": message, "visibility": "public"}

        try:
            response = await self._send_status(headers, data)
        except httpx.TimeoutException as error:
            logger.warning("Mastodon request timed out (%s).", type(error).__name__)
            return self._failed_result(PostingError.TIMEOUT)
        except httpx.RequestError as error:
            logger.warning("Mastodon request failed (%s).", type(error).__name__)
            return self._failed_result(PostingError.FAILURE)

        if not response.is_success:
            return self._handle_api_error(response.status_code)

        try:
            response_data = response.json()
        except ValueError:
            return self._invalid_response(response.status_code)

        if not isinstance(response_data, dict):
            return self._invalid_response(response.status_code)

        visibility = response_data.get("visibility")
        created_at = response_data.get("created_at")
        posted_url = response_data.get("url")
        if (
            not isinstance(visibility, str)
            or visibility not in _VISIBILITIES
            or not isinstance(created_at, str)
        ):
            return self._invalid_response(response.status_code)
        validated_posted_url: AnyHttpUrl | None = None
        if posted_url is not None:
            if not isinstance(posted_url, str):
                return self._invalid_response(response.status_code)
            try:
                validated_posted_url = _POSTED_URL_ADAPTER.validate_python(posted_url)
            except ValidationError:
                return self._invalid_response(response.status_code)
            if (
                validated_posted_url.username is not None
                or validated_posted_url.password is not None
            ):
                return self._invalid_response(response.status_code)

        try:
            created_time = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError:
            return self._invalid_response(response.status_code)
        if created_time.tzinfo is None:
            return self._invalid_response(response.status_code)

        return PostingResult(
            platform=self.name,
            status="success",
            posted_url=validated_posted_url,
            public_access=visibility in {"public", "unlisted"},
            date=created_time.date(),
            time=created_time.timetz(),
        )

    async def _send_status(
        self,
        headers: dict[str, str],
        data: dict[str, str],
    ) -> httpx.Response:
        url = f"{self._instance_url}/api/v1/statuses"
        if self._client is not None:
            return await self._client.post(
                url,
                headers=headers,
                data=data,
                timeout=self._timeout_seconds,
            )

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            return await client.post(url, headers=headers, data=data)

    def _handle_api_error(self, status_code: int) -> PostingResult:
        if status_code in (401, 403):
            error = PostingError.AUTHENTICATION
        elif status_code == 429:
            error = PostingError.RATE_LIMITED
        elif 400 <= status_code < 500:
            error = PostingError.REJECTED
        else:
            error = PostingError.FAILURE

        logger.warning("Mastodon API returned HTTP status %d.", status_code)
        return self._failed_result(
            error,
            public_access=False if 400 <= status_code < 500 else None,
        )

    def _invalid_response(self, status_code: int) -> PostingResult:
        logger.warning("Mastodon API returned an invalid status response (HTTP %d).", status_code)
        return self._failed_result(PostingError.INVALID_RESPONSE)

    @staticmethod
    def _normalize_instance_url(value: str | None) -> str | None:
        if not value:
            return None
        try:
            parsed_url = _INSTANCE_URL_ADAPTER.validate_python(value.strip())
        except ValidationError:
            return None

        if (
            parsed_url.scheme != "https"
            or parsed_url.username is not None
            or parsed_url.password is not None
            or parsed_url.path not in ("", "/")
            or parsed_url.query
            or parsed_url.fragment
        ):
            return None

        return str(parsed_url).rstrip("/")

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
