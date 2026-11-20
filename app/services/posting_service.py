import asyncio
import logging
from collections.abc import Sequence
from math import isfinite

from app.platforms.base import Platform
from app.schemas import PostingError, PostingResult


logger = logging.getLogger(__name__)


class PostingService:
    def __init__(
        self,
        platforms: Sequence[Platform],
        platform_timeout_seconds: float = 10.0,
    ) -> None:
        if not isfinite(platform_timeout_seconds) or platform_timeout_seconds <= 0:
            raise ValueError("Platform timeout must be a positive, finite number.")

        self._platforms = tuple(platforms)
        self._platform_timeout_seconds = platform_timeout_seconds

    async def post_message(self, message: str) -> list[PostingResult]:
        return await asyncio.gather(
            *(self._post_to_platform(platform, message) for platform in self._platforms)
        )

    async def _post_to_platform(
        self,
        platform: Platform,
        message: str,
    ) -> PostingResult:
        try:
            result = await asyncio.wait_for(
                platform.post(message),
                timeout=self._platform_timeout_seconds,
            )
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            logger.warning(
                "Platform implementation %s timed out after %.3f seconds.",
                type(platform).__name__,
                self._platform_timeout_seconds,
            )
            return self._failed_result(platform, PostingError.TIMEOUT)
        except Exception as error:
            logger.warning(
                "Platform implementation %s failed with exception type %s.",
                type(platform).__name__,
                type(error).__name__,
            )
            return self._failed_result(platform, PostingError.FAILURE)

        if not isinstance(result, PostingResult):
            logger.warning(
                "Platform implementation %s returned an invalid result type %s.",
                type(platform).__name__,
                type(result).__name__,
            )
            return self._failed_result(platform, PostingError.FAILURE)

        return result

    @staticmethod
    def _failed_result(platform: Platform, error: PostingError) -> PostingResult:
        return PostingResult(
            platform=platform.name,
            status="failed",
            public_access=None,
            error=error,
        )
