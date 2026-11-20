import asyncio
from datetime import date, time

import pytest
from pydantic import AnyHttpUrl, TypeAdapter, ValidationError

from app.platforms.base import Platform
from app.schemas import PostingError, PostingResult
from app.services.posting_service import PostingService


_URL_ADAPTER = TypeAdapter(AnyHttpUrl)


class MockPlatform(Platform):
    def __init__(
        self,
        name: str,
        result: PostingResult | None = None,
        error: Exception | None = None,
        delay: float = 0,
        started: asyncio.Event | None = None,
        cancelled: asyncio.Event | None = None,
    ) -> None:
        self.name = name
        self.result = result
        self.error = error
        self.delay = delay
        self.started = started
        self.cancelled = cancelled
        self.messages: list[str] = []

    async def post(self, message: str) -> PostingResult:
        self.messages.append(message)
        if self.started is not None:
            self.started.set()
        try:
            await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            if self.cancelled is not None:
                self.cancelled.set()
            raise
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


def successful_result(platform: str) -> PostingResult:
    return PostingResult(
        platform=platform,
        status="success",
        posted_url=_URL_ADAPTER.validate_python(
            f"https://example.com/{platform.lower()}"
        ),
        public_access=True,
        date=date(2026, 11, 19),
        time=time(10, 30),
    )


def test_posts_to_all_platforms_when_all_succeed() -> None:
    platforms = [
        MockPlatform("First", result=successful_result("First")),
        MockPlatform("Second", result=successful_result("Second")),
    ]
    service = PostingService(platforms)

    results = asyncio.run(service.post_message("A message https://example.com"))

    assert [result.status for result in results] == ["success", "success"]
    assert [result.platform for result in results] == ["First", "Second"]
    assert all(platform.messages == ["A message https://example.com"] for platform in platforms)


def test_one_platform_failure_does_not_stop_other_platforms() -> None:
    failed_platform = MockPlatform("Failed", error=RuntimeError("simulated failure"))
    successful_platform = MockPlatform(
        "Successful",
        result=successful_result("Successful"),
    )
    service = PostingService([failed_platform, successful_platform])

    results = asyncio.run(service.post_message("A message https://example.com"))

    assert [(result.platform, result.status) for result in results] == [
        ("Failed", "failed"),
        ("Successful", "success"),
    ]
    assert results[0].error is PostingError.FAILURE
    assert successful_platform.messages == ["A message https://example.com"]


def test_all_platform_failures_return_individual_results() -> None:
    service = PostingService(
        [
            MockPlatform("First", error=RuntimeError("first failure")),
            MockPlatform("Second", error=ValueError("second failure")),
        ]
    )

    results = asyncio.run(service.post_message("A message https://example.com"))

    assert [(result.platform, result.status) for result in results] == [
        ("First", "failed"),
        ("Second", "failed"),
    ]
    assert [result.error for result in results] == [
        PostingError.FAILURE,
        PostingError.FAILURE,
    ]


def test_exception_details_are_sanitised_in_results_and_logs(caplog) -> None:
    secret = "synthetic-webhook-secret"
    platform = MockPlatform("Discord", error=RuntimeError(secret))

    result = asyncio.run(
        PostingService([platform]).post_message("A message https://example.com")
    )[0]

    assert result.error is PostingError.FAILURE
    assert secret not in result.model_dump_json()
    assert secret not in caplog.text
    assert "MockPlatform" in caplog.text
    assert "RuntimeError" in caplog.text


def test_one_platform_timeout_does_not_stop_another() -> None:
    platforms = [
        MockPlatform("Slow", result=successful_result("Slow"), delay=0.1),
        MockPlatform("Fast", result=successful_result("Fast")),
    ]

    results = asyncio.run(
        PostingService(platforms, platform_timeout_seconds=0.01).post_message(
            "A message https://example.com"
        )
    )

    assert [(result.platform, result.status) for result in results] == [
        ("Slow", "failed"),
        ("Fast", "success"),
    ]
    assert results[0].error is PostingError.TIMEOUT


def test_all_platform_timeouts_return_failure_results() -> None:
    platforms = [
        MockPlatform("First", result=successful_result("First"), delay=0.1),
        MockPlatform("Second", result=successful_result("Second"), delay=0.1),
    ]

    results = asyncio.run(
        PostingService(platforms, platform_timeout_seconds=0.01).post_message(
            "A message https://example.com"
        )
    )

    assert [(result.platform, result.status) for result in results] == [
        ("First", "failed"),
        ("Second", "failed"),
    ]
    assert all(result.error is PostingError.TIMEOUT for result in results)


def test_parent_task_cancellation_propagates() -> None:
    async def run() -> None:
        started = asyncio.Event()
        cancelled = asyncio.Event()
        platform = MockPlatform(
            "Blocking",
            result=successful_result("Blocking"),
            delay=10,
            started=started,
            cancelled=cancelled,
        )
        task = asyncio.create_task(
            PostingService(
                [platform],
                platform_timeout_seconds=20,
            ).post_message("A message https://example.com")
        )

        await asyncio.wait_for(started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert cancelled.is_set()

    asyncio.run(run())


def test_successful_result_requires_success_fields_but_not_public_url() -> None:
    with pytest.raises(ValidationError):
        PostingResult(
            platform="Example",
            status="success",
            public_access=True,
        )

    result = PostingResult(
        platform="Example",
        status="success",
        public_access=True,
        date=date(2026, 11, 19),
        time=time(10, 30),
    )

    assert result.posted_url is None


def test_failed_result_requires_error() -> None:
    with pytest.raises(ValidationError):
        PostingResult(
            platform="Example",
            status="failed",
            public_access=False,
        )
