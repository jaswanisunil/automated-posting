import logging
import re
from datetime import datetime, timezone
from math import isfinite
from urllib.parse import quote, urlsplit

import httpx
import regex
from pydantic import AnyHttpUrl, TypeAdapter, ValidationError

from app.platforms.base import Platform
from app.schemas import PostingError, PostingResult


logger = logging.getLogger(__name__)
_GRAPHEME_PATTERN = regex.compile(r"\X")
_DID_PATTERN = re.compile(r"did:[a-z0-9]+:[A-Za-z0-9._:%-]+\Z")
_RECORD_KEY_PATTERN = re.compile(r"[A-Za-z0-9._~:-]{1,512}\Z")
_POST_URL_ADAPTER = TypeAdapter(AnyHttpUrl)
_MAX_POST_GRAPHEMES = 300
_MAX_POST_UTF8_BYTES = 3000


class BlueskyPlatform(Platform):
    name = "Bluesky"

    def __init__(
        self,
        identifier: str | None,
        app_password: str | None,
        service_url: str | None,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("Platform timeout must be a positive, finite number.")

        self._identifier = (
            identifier.strip() if identifier and identifier.strip() else None
        )
        self._app_password = (
            app_password.strip() if app_password and app_password.strip() else None
        )
        self._service_url = self._normalize_service_url(service_url)
        self._client = client
        self._timeout_seconds = timeout_seconds

    async def post(self, message: str) -> PostingResult:
        if (
            self._identifier is None
            or self._app_password is None
            or self._service_url is None
        ):
            return self._failed_result(PostingError.NOT_CONFIGURED)
        try:
            message_bytes = message.encode("utf-8")
        except UnicodeEncodeError:
            return self._failed_result(PostingError.CONTENT_TOO_LONG)
        if (
            len(_GRAPHEME_PATTERN.findall(message)) > _MAX_POST_GRAPHEMES
            or len(message_bytes) > _MAX_POST_UTF8_BYTES
        ):
            return self._failed_result(PostingError.CONTENT_TOO_LONG)

        created_at = datetime.now(timezone.utc)
        try:
            if self._client is not None:
                return await self._post_with_client(
                    self._client,
                    message,
                    created_at,
                )
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                return await self._post_with_client(client, message, created_at)
        except httpx.TimeoutException as error:
            logger.warning("Bluesky request timed out (%s).", type(error).__name__)
            return self._failed_result(PostingError.TIMEOUT)
        except httpx.RequestError as error:
            logger.warning("Bluesky request failed (%s).", type(error).__name__)
            return self._failed_result(PostingError.FAILURE)

    async def _post_with_client(
        self,
        client: httpx.AsyncClient,
        message: str,
        created_at: datetime,
    ) -> PostingResult:
        session_response = await client.post(
            f"{self._service_url}/xrpc/com.atproto.server.createSession",
            json={
                "identifier": self._identifier,
                "password": self._app_password,
            },
            timeout=self._timeout_seconds,
        )
        if not session_response.is_success:
            return self._handle_api_error(session_response.status_code)

        session = self._response_object(session_response)
        if session is None:
            return self._invalid_response(session_response.status_code)

        access_jwt = session.get("accessJwt")
        refresh_jwt = session.get("refreshJwt")
        did = session.get("did")
        handle = session.get("handle")
        active = session.get("active")
        if (
            not isinstance(access_jwt, str)
            or not access_jwt
            or any(
                ord(character) < 33 or ord(character) > 126
                for character in access_jwt
            )
            or not isinstance(refresh_jwt, str)
            or not refresh_jwt
            or not isinstance(did, str)
            or _DID_PATTERN.fullmatch(did) is None
            or not isinstance(handle, str)
            or not handle
            or ("active" in session and type(active) is not bool)
        ):
            return self._invalid_response(session_response.status_code)
        if active is False:
            return self._failed_result(PostingError.AUTHENTICATION)

        created_at_text = created_at.isoformat().replace("+00:00", "Z")
        post_response = await client.post(
            f"{self._service_url}/xrpc/com.atproto.repo.createRecord",
            headers={"Authorization": f"Bearer {access_jwt}"},
            json={
                "repo": did,
                "collection": "app.bsky.feed.post",
                "record": {
                    "$type": "app.bsky.feed.post",
                    "text": message,
                    "createdAt": created_at_text,
                },
            },
            timeout=self._timeout_seconds,
        )
        if not post_response.is_success:
            return self._handle_api_error(post_response.status_code)

        record = self._response_object(post_response)
        if record is None:
            return self._invalid_response(post_response.status_code)

        uri = record.get("uri")
        cid = record.get("cid")
        post_url = self._post_url(did, uri) if isinstance(uri, str) else None
        if not isinstance(cid, str) or not cid or post_url is None:
            return self._invalid_response(post_response.status_code)
        try:
            posted_url = _POST_URL_ADAPTER.validate_python(post_url)
        except ValidationError:
            return self._invalid_response(post_response.status_code)

        return PostingResult(
            platform=self.name,
            status="success",
            posted_url=posted_url,
            public_access=None,
            date=created_at.date(),
            time=created_at.timetz(),
        )

    @staticmethod
    def _response_object(response: httpx.Response) -> dict[str, object] | None:
        try:
            response_data = response.json()
        except ValueError:
            return None
        return response_data if isinstance(response_data, dict) else None

    def _handle_api_error(self, status_code: int) -> PostingResult:
        if status_code in (401, 403):
            error = PostingError.AUTHENTICATION
        elif status_code == 429:
            error = PostingError.RATE_LIMITED
        elif 400 <= status_code < 500:
            error = PostingError.REJECTED
        else:
            error = PostingError.FAILURE

        logger.warning("Bluesky API returned HTTP status %d.", status_code)
        return self._failed_result(error)

    def _invalid_response(self, status_code: int) -> PostingResult:
        logger.warning(
            "Bluesky API returned an invalid response (HTTP %d).",
            status_code,
        )
        return self._failed_result(PostingError.INVALID_RESPONSE)

    def _failed_result(self, error: PostingError) -> PostingResult:
        return PostingResult(
            platform=self.name,
            status="failed",
            public_access=None,
            error=error,
        )

    @staticmethod
    def _post_url(did: str, uri: str) -> str | None:
        prefix = f"at://{did}/app.bsky.feed.post/"
        if not uri.startswith(prefix):
            return None
        record_key = uri[len(prefix):]
        if _RECORD_KEY_PATTERN.fullmatch(record_key) is None:
            return None

        return (
            f"https://bsky.app/profile/{quote(did, safe=':')}"
            f"/post/{quote(record_key, safe='')}"
        )

    @staticmethod
    def _normalize_service_url(value: str | None) -> str | None:
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
            or port == 0
            or parsed_url.username is not None
            or parsed_url.password is not None
            or parsed_url.path not in ("", "/")
            or parsed_url.query
            or parsed_url.fragment
        ):
            return None

        return f"https://{parsed_url.netloc}".rstrip("/")
