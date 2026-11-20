# Automated Multi-Platform Posting API

A FastAPI application for validating a short posting message and publishing it
through configured platforms. DEV/Forem, Mastodon, Telegram, Discord, and
Bluesky integrations are implemented; other platform integrations are not.

## Project overview and architecture

The application accepts one short message and fans it out to all five
integrations concurrently. Each integration is isolated behind the shared
`Platform` interface, so a failed provider returns its own result without
preventing the others from running.

- `app/main.py` defines the FastAPI health and posting endpoints.
- `app/schemas.py` validates requests and defines the common response/error
  contract.
- `app/platforms/base.py` defines the asynchronous platform interface.
- `app/platforms/` contains one API adapter per provider.
- `app/services/posting_service.py` runs platforms concurrently, applies an
  overall safety timeout, propagates cancellation, and sanitizes unexpected
  failures.
- `app/dependencies.py` constructs platform adapters from environment
  variables and injects them into the request handler.
- `tests/` contains unit tests with mocked provider APIs and an end-to-end
  endpoint test using mocked transports.

## Requirements

- Python 3.13 for running locally
- Docker Desktop with Docker Compose
- A Docker engine running for the build and run commands

The official `python:3.13-slim` image supports ARM64. The Docker configuration
does not pin a platform, so Docker uses the native architecture on an Apple
Silicon Mac.

## Local installation

Create a virtual environment, install the declared dependencies, and create
your private environment file:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Fill only the credentials for the services you intend to use. `.env.example`
contains placeholders and is safe to copy; `.env` is ignored by Git and
excluded from the Docker build context.

Run the API locally with Uvicorn loading that environment file:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 4000 --env-file .env --reload
```

## Environment variable reference

All provider credentials are optional. If a provider is not configured, its
result is a safe failure while the other providers are still attempted.
Timeout values must be positive finite numbers; each defaults to 10 seconds.

| Platform | Variables | Secret values |
| --- | --- | --- |
| DEV/Forem | `DEV_API_KEY`, `DEV_PLATFORM_TIMEOUT_SECONDS` | `DEV_API_KEY` |
| Mastodon | `MASTODON_INSTANCE_URL`, `MASTODON_ACCESS_TOKEN`, `MASTODON_PLATFORM_TIMEOUT_SECONDS` | `MASTODON_ACCESS_TOKEN` |
| Telegram | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_PLATFORM_TIMEOUT_SECONDS` | `TELEGRAM_BOT_TOKEN` |
| Discord | `DISCORD_WEBHOOK_URL`, `DISCORD_PLATFORM_TIMEOUT_SECONDS` | `DISCORD_WEBHOOK_URL` |
| Bluesky | `BLUESKY_IDENTIFIER`, `BLUESKY_APP_PASSWORD`, `BLUESKY_SERVICE_URL`, `BLUESKY_PLATFORM_TIMEOUT_SECONDS` | `BLUESKY_APP_PASSWORD` |

`BLUESKY_SERVICE_URL` defaults to `https://bsky.social`; all other credential
and service-specific values have no default. See the integration sections
below for permissions and account setup.

## Docker development setup

Create the external environment file:

```bash
cp .env.example .env
```

Set `DEV_API_KEY` in `.env` to a key generated from the DEV account's
[API key settings](https://dev.to/settings/extensions). The key belongs to the
account that will author the article. The official API documents API-key
authentication for article creation and does not specify a separate OAuth
scope. `DEV_PLATFORM_TIMEOUT_SECONDS` configures the per-platform request
timeout; it defaults to 10 seconds.

For Mastodon, set `MASTODON_INSTANCE_URL` to the HTTPS origin of your instance
and `MASTODON_ACCESS_TOKEN` to a user access token authorized for the
`write:statuses` scope. `MASTODON_PLATFORM_TIMEOUT_SECONDS` configures its
request timeout and defaults to 10 seconds. Keep the token secret.

For Telegram, set `TELEGRAM_BOT_TOKEN` to the token created by
[@BotFather](https://t.me/BotFather) and `TELEGRAM_CHAT_ID` to the target
numeric chat/channel ID or `@username`. The bot must be able to post to that
chat; for channels, it needs permission to post messages.
`TELEGRAM_PLATFORM_TIMEOUT_SECONDS` configures its request timeout and
defaults to 10 seconds. Keep the bot token secret.

For Discord, create an incoming webhook in the target channel (the account
creating it needs the channel's **Manage Webhooks** permission), then set
`DISCORD_WEBHOOK_URL` to the complete webhook URL.
`DISCORD_PLATFORM_TIMEOUT_SECONDS` configures its request timeout and defaults
to 10 seconds. Treat the URL as a password: anyone who obtains it can post to
that webhook.

For Bluesky, set `BLUESKY_IDENTIFIER` to the account handle or DID,
`BLUESKY_APP_PASSWORD` to an app password created in account settings (not the
account's regular password), and `BLUESKY_SERVICE_URL` to the PDS HTTPS base
URL. The default service URL in `.env.example` is `https://bsky.social`; use
your PDS URL for accounts hosted elsewhere.
`BLUESKY_PLATFORM_TIMEOUT_SECONDS` configures the request timeout and defaults
to 10 seconds. App passwords and session tokens are treated as secrets.

Compose passes `.env` into the container using `env_file`. The file is ignored
by Git and Docker's build context. Do not add credentials to the image or commit
the `.env` file.

Build and start the application:

```bash
docker compose up --build
```

Compose bind-mounts the source into the container and starts Uvicorn with
automatic reload. Only the `app/` and `tests/` directories are mounted; the
external `.env` file is passed as environment variables and is not mounted into
the application source tree. The application runs as a non-root user.

- Swagger UI: <http://localhost:4000/docs>
- Health check endpoint: <http://localhost:4000/health>

The image health check polls `/health`. To inspect container and health status
in another terminal:

```bash
docker compose ps
docker inspect --format='{{.State.Health.Status}}' "$(docker compose ps -q app)"
```

## Docker commands

Run the complete test suite in the application container:

```bash
docker compose run --rm app python -m pytest -q -p no:cacheprovider
```

The cache provider is disabled because the source directory is mounted from the
host and the container runs as a non-root user.

Show application logs when running detached:

```bash
docker compose up --build -d
docker compose logs -f app
```

Rebuild the image without using cached build layers, then start the application:

```bash
docker compose build --no-cache
docker compose up
```

Stop and remove the application container:

```bash
docker compose down
```

If you started in detached mode, `docker compose down` stops and removes the
container. It does not delete the source code or `.env` file.

## DEV/Forem integration

The integration calls `POST https://dev.to/api/articles` with the API key in
the `api-key` header and an `article` JSON object. The official API documentation
lists `title` and `body_markdown` as string fields; `published: true` publishes
the article immediately rather than saving a draft.

The request body is the submitted message unchanged. The title is derived only
from that message: it uses the message itself when it fits, otherwise a prefix
limited to Forem's current full-post title limit of 128 non-whitespace
characters. Forem's current model allows up to 800 KB of Markdown body; the
assessment's 200-character message limit is well below that. No tags,
description, or other copy are invented. The message body remains complete.

The result uses Forem's `published_at` timestamp, falling back to `created_at`;
if neither is returned, it records the local UTC confirmation time.

References:

- [Forem API V1 — Publish article](https://developers.forem.com/api/v1#tag/articles/operation/createArticle)
- [Forem Article model — title validation](https://github.com/forem/forem/blob/main/app/models/article.rb)

The API key is never hardcoded or logged. API failures are mapped to
standardized messages; response bodies and raw exception messages are not
returned or logged.

## Mastodon integration

The integration calls `POST {MASTODON_INSTANCE_URL}/api/v1/statuses` with
`Authorization: Bearer <user access token>`. The official API requires the
`write:statuses` scope. Requests use form data containing the submitted message
as `status` and explicitly set `visibility=public`; returned visibility is
used to report whether the status is publicly accessible.

Authentication failures, rate limits, other API errors, timeouts, and missing
or invalid configuration produce standardized per-platform results. Raw
response bodies, authorization headers, and exception messages are never
logged or returned.

Reference: [Mastodon API — Post a new status](https://docs.joinmastodon.org/methods/statuses/#create)

## Telegram integration

The integration calls Telegram's HTTPS Bot API `sendMessage` method with the
configured bot token in the API URL and submits the target `chat_id` and
original message as `text`. It does not add formatting, links, or other content.
An invalid token returns an authentication failure; missing configuration,
unavailable destinations or permissions, rate limits, timeouts, network errors,
and malformed responses become standardized per-platform failures. Sensitive
API error descriptions, request URLs, and exception messages are not logged or
returned.

Public accessibility is reported only when Telegram returns a `channel` or
`supergroup` chat with a username. Other chats—including private chats and
groups without a public username—are reported with `public_access: false`.
When a public username is present, the result includes a `t.me` message URL.

Reference: [Telegram Bot API — sendMessage](https://core.telegram.org/bots/api#sendmessage)

## Discord integration

The integration uses an incoming webhook; no Discord bot user or bot token is
required. It sends the original message as the webhook's `content` and sets
`wait=true`, so Discord returns the created message object instead of its
default `204 No Content` response. The returned message ID and timestamp are
validated before reporting success.

Successful posts are reported with `public_access: false` and no `posted_url`.
A Discord server message is available according to that server and channel's
permissions; a successful webhook post does not make it public on the internet.
Invalid/missing webhook configuration, authentication failures, rate limits,
timeouts, network failures, and malformed responses return standardized
results. The webhook URL, API response details, and exception messages are
never logged or returned.

Reference: [Discord API — Execute Webhook](https://discord.com/developers/docs/resources/webhook#execute-webhook)

## Bluesky integration

The integration creates a session with
`com.atproto.server.createSession`, then publishes an `app.bsky.feed.post`
record with `com.atproto.repo.createRecord` using the session access token.
The record's `text` is the submitted message unchanged. Bluesky limits posts to
300 Unicode grapheme clusters and 3000 UTF-8 bytes; both limits are validated.
Over-limit content is returned as a safe failure, never silently truncated.
The API's 200-character request limit is stricter for this assessment.

The create-record response must contain a valid AT URI for the authenticated
DID and a CID before a `bsky.app` post URL is returned. The AT Protocol response
does not confirm public visibility through an app view, so `public_access` is
reported as `null` rather than assumed. A custom PDS may not be indexed by
`bsky.app`.

Use an app password rather than your account password. App passwords can be
created from [Bluesky account settings](https://bsky.app/settings/app-passwords).
The configured PDS must support the standard AT Protocol XRPC session and
repository endpoints.

References:

- [AT Protocol — createSession](https://docs.bsky.app/docs/api/com-atproto-server-create-session)
- [AT Protocol — createRecord](https://docs.bsky.app/docs/api/com-atproto-repo-create-record)
- [AT Protocol post record lexicon](https://github.com/bluesky-social/atproto/blob/main/packages/api/lexicons/app/bsky/feed/post.json)

## API

`POST /posting` accepts a JSON `message` with a maximum length of 200 characters
and exactly one valid HTTP or HTTPS URL. Invalid input returns HTTP 422. A valid
request is posted to each configured platform and returns a per-platform
result. Missing platform credentials produce safe failed results without
making requests to those platforms.

Validation rules:

- The message must not be empty or whitespace-only.
- It must contain exactly one valid HTTP or HTTPS URL with a hostname.
- URLs containing embedded usernames or passwords are rejected.
- The message limit is 200 Python characters, inclusive.

Example request:

```bash
curl -X POST http://localhost:4000/posting \
  -H 'Content-Type: application/json' \
  -d '{"message":"A useful update https://example.com"}'
```

Example response (provider timestamps and identifiers are illustrative):

```json
{
  "success": true,
  "results": [
    {
      "platform": "DEV/Forem",
      "status": "success",
      "posted_url": "https://dev.to/example/post",
      "public_access": true,
      "date": "2026-11-19",
      "time": "10:30:00Z",
      "error": null
    },
    {
      "platform": "Mastodon",
      "status": "failed",
      "posted_url": null,
      "public_access": false,
      "date": null,
      "time": null,
      "error": "The platform authentication failed."
    },
    {
      "platform": "Telegram",
      "status": "success",
      "posted_url": "https://t.me/sample_channel/42",
      "public_access": true,
      "date": "2026-11-19",
      "time": "10:30:00Z",
      "error": null
    },
    {
      "platform": "Discord",
      "status": "success",
      "posted_url": null,
      "public_access": false,
      "date": "2026-11-19",
      "time": "10:30:00Z",
      "error": null
    },
    {
      "platform": "Bluesky",
      "status": "success",
      "posted_url": "https://bsky.app/profile/did:plc:example/post/example-key",
      "public_access": null,
      "date": "2026-11-19",
      "time": "10:30:00Z",
      "error": null
    }
  ]
}
```

The top-level `success` is true if at least one platform succeeds. Valid input
returns HTTP 200 even if every provider fails; inspect each result's `status`
and `error`. `public_access` is `null` when it cannot be confirmed.
`GET /health` returns `{"status": "ok"}`.

## Error handling and public visibility

Each adapter maps API authentication errors, rate limits, timeouts, network
errors, and malformed responses to standard error values. Results contain no
raw provider response or exception details. A provider failure is isolated
from the other concurrent requests. Cancelling the parent request propagates
cancellation rather than turning it into an ordinary provider failure.

Public visibility is provider-specific: DEV is public only when its response
confirms publication; Mastodon uses returned status visibility; Telegram
requires a public channel/supergroup username; Discord posts are not claimed
as internet-public; Bluesky returns `null` because record creation does not
confirm app-view visibility. A successful post does not necessarily mean a
publicly reachable web URL is available.

Automated tests mock all five APIs. None of the integrations has been verified
against live APIs; that requires valid credentials and successful real posts.

## Optional live verification

The automated tests never contact provider APIs. If you choose to verify a live
integration, use a test account and a low-risk destination, configure only that
provider in `.env`, and submit a harmless message. A valid `/posting` request
will send to every provider with complete credentials. Check the per-provider
result and the destination itself; a successful response is not a substitute
for verifying visibility. Revoke test tokens, app passwords, or webhooks when
finished. Do not use production credentials for test messages.

## Tests outside Docker

Run the complete mocked suite and basic compilation/dependency checks:

```bash
python -m pytest -q
python -m compileall -q app tests
python -m pip check
```

The Docker test command is documented above under Docker commands.
