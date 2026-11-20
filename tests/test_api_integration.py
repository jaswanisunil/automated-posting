import asyncio
import json
from contextlib import AsyncExitStack
from datetime import datetime, timezone

import httpx

from app.dependencies import get_posting_service
from app.main import app
from app.platforms.bluesky import BlueskyPlatform
from app.platforms.dev import DevPlatform
from app.platforms.discord import DiscordPlatform
from app.platforms.mastodon import MastodonPlatform
from app.platforms.telegram import TelegramPlatform
from app.services.posting_service import PostingService


MESSAGE = "A useful update https://example.com"
DID = "did:plc:abcdefghijklmnopqrstuvwx"


def test_post_endpoint_attempts_all_platforms_and_returns_each_result() -> None:
    async def run() -> None:
        attempts: dict[str, int] = {}
        posted_content: dict[str, str] = {}

        def mark(name: str) -> None:
            attempts[name] = attempts.get(name, 0) + 1

        def dev_handler(request: httpx.Request) -> httpx.Response:
            mark("DEV/Forem")
            posted_content["DEV/Forem"] = json.loads(request.content)["article"][
                "body_markdown"
            ]
            return httpx.Response(
                201,
                json={
                    "article": {
                        "published": True,
                        "url": "https://dev.to/example/post",
                        "published_at": "2026-11-19T10:30:00Z",
                    }
                },
            )

        def mastodon_handler(request: httpx.Request) -> httpx.Response:
            mark("Mastodon")
            return httpx.Response(401, json={"error": "synthetic auth detail"})

        def telegram_handler(request: httpx.Request) -> httpx.Response:
            mark("Telegram")
            posted_content["Telegram"] = json.loads(request.content)["text"]
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "result": {
                        "message_id": 42,
                        "date": int(
                            datetime(2026, 11, 19, 10, 30, tzinfo=timezone.utc).timestamp()
                        ),
                        "chat": {
                            "id": -100123456,
                            "type": "channel",
                            "username": "sample_channel",
                        },
                    },
                },
            )

        def discord_handler(request: httpx.Request) -> httpx.Response:
            mark("Discord")
            posted_content["Discord"] = json.loads(request.content)["content"]
            return httpx.Response(
                200,
                json={
                    "id": "123456789012345678",
                    "timestamp": "2026-11-19T10:30:00Z",
                },
            )

        def bluesky_handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("server.createSession"):
                mark("Bluesky session")
                return httpx.Response(
                    200,
                    json={
                        "accessJwt": "synthetic-access-token",
                        "refreshJwt": "synthetic-refresh-token",
                        "did": DID,
                        "handle": "sample.bsky.social",
                    },
                )
            mark("Bluesky")
            posted_content["Bluesky"] = json.loads(request.content)["record"]["text"]
            return httpx.Response(
                200,
                json={
                    "uri": f"at://{DID}/app.bsky.feed.post/3jzfcijpj2z2a",
                    "cid": "bafyreibsyntheticcid",
                },
            )

        async with AsyncExitStack() as stack:
            clients: list[httpx.AsyncClient] = []
            for handler in (
                dev_handler,
                mastodon_handler,
                telegram_handler,
                discord_handler,
                bluesky_handler,
            ):
                clients.append(
                    await stack.enter_async_context(
                        httpx.AsyncClient(
                            transport=httpx.MockTransport(handler),
                        )
                    )
                )

            service = PostingService(
                [
                    DevPlatform("synthetic-dev-key", clients[0]),
                    MastodonPlatform(
                        "https://mastodon.example",
                        "synthetic-mastodon-token",
                        clients[1],
                    ),
                    TelegramPlatform(
                        "123456:synthetic_token",
                        "@sample_channel",
                        clients[2],
                    ),
                    DiscordPlatform(
                        "https://discord.com/api/webhooks/123456/synthetic_token",
                        clients[3],
                    ),
                    BlueskyPlatform(
                        "sample.bsky.social",
                        "synthetic-app-password",
                        "https://pds.example",
                        clients[4],
                    ),
                ],
                platform_timeout_seconds=2,
            )
            previous_override = app.dependency_overrides.get(get_posting_service)
            app.dependency_overrides[get_posting_service] = lambda: service
            try:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://test",
                ) as api_client:
                    response = await api_client.post(
                        "/posting",
                        json={"message": MESSAGE},
                    )
            finally:
                if previous_override is None:
                    app.dependency_overrides.pop(get_posting_service, None)
                else:
                    app.dependency_overrides[get_posting_service] = previous_override

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert [result["platform"] for result in data["results"]] == [
            "DEV/Forem",
            "Mastodon",
            "Telegram",
            "Discord",
            "Bluesky",
        ]
        assert [result["status"] for result in data["results"]] == [
            "success",
            "failed",
            "success",
            "success",
            "success",
        ]
        assert [result["public_access"] for result in data["results"]] == [
            True,
            False,
            True,
            False,
            None,
        ]
        assert data["results"][1]["error"] == "The platform authentication failed."
        assert attempts == {
            "DEV/Forem": 1,
            "Mastodon": 1,
            "Telegram": 1,
            "Discord": 1,
            "Bluesky session": 1,
            "Bluesky": 1,
        }
        assert posted_content == {
            "DEV/Forem": MESSAGE,
            "Telegram": MESSAGE,
            "Discord": MESSAGE,
            "Bluesky": MESSAGE,
        }

    asyncio.run(run())
