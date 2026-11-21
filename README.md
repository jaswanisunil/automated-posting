# Automated Multi-Platform Posting API

A FastAPI service that validates one message and posts it to DEV/Forem,
Mastodon, Telegram, Discord, and Bluesky. The project is designed to
demonstrate clean API design, provider abstraction, dependency injection,
concurrent asynchronous integration, and safe handling of partial provider
failures.

The stack uses Python 3.13, FastAPI, Pydantic, HTTPX, Uvicorn, pytest, and
Docker Compose. One validated `POST /posting` request starts five independent
provider adapters concurrently; each platform returns its own success or
standardized failure in the response.

## Table of Contents

- [Project Overview](#project-overview)
- [Features](#features)
- [Supported Platforms](#supported-platforms)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Requirements](#requirements)
- [Quick Start](#quick-start)
- [Installation and Setup](#installation-and-setup)
- [Environment Variables](#environment-variables)
- [Running the Application](#running-the-application)
- [API Documentation](#api-documentation)
- [API Examples](#api-examples)
- [Error Handling](#error-handling)
- [Testing](#testing)
- [Docker Setup](#docker-setup)
- [Security Considerations](#security-considerations)
- [Limitations and Future Improvements](#limitations-and-future-improvements)

## Project Overview

The application exposes a small HTTP API for cross-platform posting. A request
contains a 200-character-or-fewer message with exactly one HTTP or HTTPS URL.
The application validates the request, creates a `PostingService` from the
configured environment variables, and invokes all available platform adapters.

If a provider is not configured or raises an error, the API keeps attempting
the remaining platforms and returns a separate result for each one. The
top-level `success` field is `true` when at least one provider succeeds.

## Features

- FastAPI health and posting endpoints
- Pydantic request validation and typed response models
- Concurrent calls to five provider integrations
- Per-platform timeout and standardized failure values
- Independent provider error handling and cancellation propagation
- Dependency injection for platform configuration
- Docker support with health checks and live reload
- Mocked unit, integration, and API tests

## Supported Platforms

| Platform | Provider behavior | Public visibility representation |
| --- | --- | --- |
| DEV/Forem | Creates a published article at `https://dev.to/api/articles` | Uses the API's `published` value, but that field does not independently verify public accessibility |
| Mastodon | Creates a public status through the instance API | Uses the returned status visibility |
| Telegram | Sends `text` through the Bot API `sendMessage` method | `true` only for public channel/supergroup usernames |
| Discord | Executes an incoming webhook with `wait=true` | Always `false`; no public internet URL is assumed |
| Bluesky | Creates an AT Protocol session and `app.bsky.feed.post` record | `null` because record creation does not confirm app-view visibility |

## Architecture

The application separates HTTP concerns, validation, orchestration, provider
configuration, and provider-specific API calls:

- `app/main.py` defines the FastAPI application and `/health` and `/posting`
  routes.
- Pydantic models in `app/schemas.py` validate `PostingRequest` and enforce
  the `PostingResponse` and `PostingResult` contracts.
- `app/platforms/base.py` defines the asynchronous `Platform` abstract base
  class and its `post(message)` interface.
- Individual adapters in `app/platforms/` implement DEV/Forem, Mastodon,
  Telegram, Discord, and Bluesky API behavior.
- `app/dependencies.py` reads environment variables and uses FastAPI dependency
  injection to construct the complete platform set.
- `app/services/posting_service.py` runs platform integrations concurrently,
  applies a service-level timeout to each adapter call, propagates
  cancellation, and sanitizes unexpected failures.

Provider calls use `asyncio.gather` and `asyncio.wait_for`. These are per-adapter
timeouts: the service may wait for slow adapters to finish or time out
individually, and a timeout for one platform does not cancel or block the
independent results of the others. Unexpected exceptions are converted to
standardized `PostingResult` values without exposing provider details.

## Project Structure

```text
app/
  main.py                 FastAPI application and routes
  schemas.py              Pydantic request, result, and response models
  dependencies.py         Environment configuration and dependency injection
  platforms/
    base.py               Platform abstract interface
    dev.py                DEV/Forem adapter
    mastodon.py           Mastodon adapter
    telegram.py           Telegram Bot API adapter
    discord.py            Discord incoming webhook adapter
    bluesky.py            AT Protocol/Bluesky adapter
  services/
    posting_service.py    Concurrent orchestration and timeout handling
tests/                    Mocked provider and API tests
.env.example              Credential and timeout variable template
Dockerfile                Python 3.13 application image
docker-compose.yml        Local container configuration
requirements.txt          Python dependencies
```

## Requirements

- Python 3.13 recommended for local execution
- `pip`
- Docker Engine with Docker Compose for container execution

The Docker image uses `python:3.13-slim`.

## Quick Start

```bash
git clone https://github.com/jaswanisunil/automated-posting.git
cd automated-posting

python3.13 -m venv .venv
source .venv/bin/activate

python -m pip install -r requirements.txt
cp .env.example .env

uvicorn app.main:app --host 127.0.0.1 --port 4000 --env-file .env --reload
```

With the server running, open:

- Swagger UI: <http://127.0.0.1:4000/docs>
- Health endpoint: <http://127.0.0.1:4000/health>

## Installation and Setup

Create a virtual environment and install the declared dependencies:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Then copy the environment template:

```bash
cp .env.example .env
```

Fill in only the providers you intend to use. An unconfigured provider is
returned as a safe failed result instead of causing the whole request to fail.

## Environment Variables

All variables in `.env.example` are listed below. The file contains placeholders
and timeout defaults, not real provider credentials. Real credentials are required
for successful live posting to the corresponding platform.

| Variable | Required | Platform | Purpose |
| --- | --- | --- | --- |
| `DEV_API_KEY` | Optional | DEV/Forem | API key used in the `api-key` request header |
| `DEV_PLATFORM_TIMEOUT_SECONDS` | Optional | DEV/Forem | Per-platform timeout; defaults to `10` |
| `MASTODON_INSTANCE_URL` | Optional | Mastodon | HTTPS origin of the Mastodon instance |
| `MASTODON_ACCESS_TOKEN` | Optional | Mastodon | User access token authorized for `write:statuses` |
| `MASTODON_PLATFORM_TIMEOUT_SECONDS` | Optional | Mastodon | Per-platform timeout; defaults to `10` |
| `TELEGRAM_BOT_TOKEN` | Optional | Telegram | Bot token created by BotFather |
| `TELEGRAM_CHAT_ID` | Optional | Telegram | Numeric chat/channel ID or `@username` |
| `TELEGRAM_PLATFORM_TIMEOUT_SECONDS` | Optional | Telegram | Per-platform timeout; defaults to `10` |
| `DISCORD_WEBHOOK_URL` | Optional | Discord | Complete HTTPS incoming webhook URL |
| `DISCORD_PLATFORM_TIMEOUT_SECONDS` | Optional | Discord | Per-platform timeout; defaults to `10` |
| `BLUESKY_IDENTIFIER` | Optional | Bluesky | Account handle or DID |
| `BLUESKY_APP_PASSWORD` | Optional | Bluesky | Bluesky app password, not the account password |
| `BLUESKY_SERVICE_URL` | Optional | Bluesky | PDS HTTPS base URL; defaults to `https://bsky.social` |
| `BLUESKY_PLATFORM_TIMEOUT_SECONDS` | Optional | Bluesky | Per-platform timeout; defaults to `10` |

Timeout values must be positive, finite numbers. Each adapter also has its own
HTTP timeout; the `PostingService` applies an additional per-adapter timeout
around the call.

## Running the Application

### Local Uvicorn server

```bash
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 4000 --env-file .env --reload
```

The HTTP port is `4000`.

### Docker Compose server

```bash
cp .env.example .env
docker compose up --build
```

Compose maps host port `4000` to container port `4000`, mounts `app/` and
`tests/`, and passes `.env` through `env_file`. It starts Uvicorn with reload.

## API Documentation

Interactive OpenAPI documentation is available at
<http://127.0.0.1:4000/docs>.

### Health endpoint

```http
GET /health
```

Port: `4000`

Response:

```json
{"status": "ok"}
```

### Posting endpoint

```http
POST /posting
Content-Type: application/json
```

Port: `4000`

Request schema:

| Field | Type | Constraints |
| --- | --- | --- |
| `message` | string | 1–200 Python characters, contains exactly one valid HTTP or HTTPS URL |

Validation rules:

- The message cannot be empty or whitespace-only.
- It must contain exactly one HTTP or HTTPS URL.
- The URL must have a hostname.
- Embedded usernames or passwords in the URL are rejected.
- The message is limited to 200 characters inclusive.

## API Examples

### Successful request

```bash
curl -X POST http://127.0.0.1:4000/posting \
  -H 'Content-Type: application/json' \
  -d '{"message":"A useful update https://example.com"}'
```

Successful response example. The URLs, IDs, and timestamps below are
illustrative values, not evidence that a real post was published:

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

The top-level `success` is `true` if at least one platform succeeds. Valid input
returns HTTP `200` even if every provider fails; inspect each per-platform
`status` and `error`.

### Validation error example

```bash
curl -X POST http://127.0.0.1:4000/posting \
  -H 'Content-Type: application/json' \
  -d '{"message":"No CTA link"}'
```

Response:

```json
{
  "detail": [
    {
      "type": "value_error",
      "loc": ["body", "message"],
      "msg": "Value error, Message must include exactly one HTTP or HTTPS URL.",
      "input": "No CTA link",
      "ctx": {}
    }
  ]
}
```

The HTTP status is `422 Unprocessable Entity`.

### Platform failure example

Valid input returns HTTP `200` when providers fail. For example, with all
credentials absent:

```json
{
  "success": false,
  "results": [
    {
      "platform": "DEV/Forem",
      "status": "failed",
      "posted_url": null,
      "public_access": false,
      "date": null,
      "time": null,
      "error": "The platform is not configured."
    }
  ]
}
```

The real response contains all five platform entries in the order shown below:
DEV/Forem, Mastodon, Telegram, Discord, and Bluesky.

## Error Handling

Platform failures use a fixed set of standardized Pydantic errors:

| Error | Meaning |
| --- | --- |
| `The platform request timed out.` | The adapter call exceeded its timeout |
| `The platform could not complete the post.` | A provider or unexpected failure occurred |
| `The platform is not configured.` | Required credentials or destination settings are absent |
| `The platform authentication failed.` | Authentication or authorization failed |
| `The platform rate limit was reached.` | The provider returned a rate-limit response |
| `The platform rejected the submitted content.` | The provider rejected the request content or parameters |
| `The platform could not access the configured destination.` | The destination could not be used |
| `The submitted message exceeds the platform's post-length limit.` | A provider-specific content limit was exceeded |
| `The platform returned an invalid response.` | The provider response was missing required valid fields |

The adapters also protect the response and logs from raw credentials, response
bodies, URLs containing secrets, and unexpected exception messages. Cancelling
a parent posting task propagates cancellation to in-progress adapter calls
rather than converting it into an ordinary provider failure.

## Testing

### Run all tests locally

```bash
python -m pytest -q
```

The verified suite currently reports `160 passed`.

The module-based command is recommended because it adds the repository root to
Python's import path.

### Run a specific test module

```bash
python -m pytest -q tests/test_posting_service.py
python -m pytest -q tests/test_validation.py
python -m pytest -q tests/test_api_integration.py
```

To run all tests for a platform adapter:

```bash
python -m pytest -q tests/test_bluesky.py
```

### Automated test coverage

The suite covers:

- Pydantic validation, URL rules, message limits, and the health endpoint
- HTTP endpoint status and per-platform response structure
- Environment-based construction of all five adapters
- Concurrent posting and partial-failure behavior
- Per-platform timeout behavior and parent cancellation
- Sanitization of credentials and unexpected exception details
- DEV/Forem, Mastodon, Telegram, Discord, and Bluesky request/response behavior
- Provider authentication, rate limits, malformed responses, network failures,
  and missing configuration

Automated tests use mocked provider APIs. Live posting to the five external
platforms has not yet been verified.

## Docker Setup

### Build the image

```bash
docker compose build
```

To force a rebuild without cached layers:

```bash
docker compose build --no-cache
```

### Start the application

```bash
cp .env.example .env
docker compose up --build
```

Start in the background:

```bash
docker compose up --build -d
```

The Docker health check calls `http://127.0.0.1:4000/health` from inside the
container.

### View logs and container status

```bash
docker compose logs -f app
docker compose ps
docker inspect --format='{{.State.Health.Status}}' "$(docker compose ps -q app)"
```

### Run tests in Docker

```bash
docker compose run --rm app python -m pytest -q
```

### Stop containers

```bash
docker compose down
```

This stops and removes the application container. It does not delete source
files or `.env`.

## Security Considerations

- Keep credentials in `.env`, and pass them to local or container processes
  through environment variables.
- Never commit `.env` or put real credentials in source code, Docker
  configuration, examples, or API responses.
- The repository `.gitignore` excludes `.env`, `.env.*`, virtual environments,
  Python caches, build output, and pytest caches while retaining
  `.env.example`.
- Docker Compose reads `.env` through `env_file`; it does not copy it into
  the application image.
- The Docker image runs as a non-root `app` user.
- Provider adapters return standardized errors and generally avoid logging
  status response bodies or exception messages that may contain secrets.
- Treat DEV API keys, Mastodon tokens, Telegram bot tokens, Discord webhook
  URLs, and Bluesky app passwords as revocable secrets.
- Use test accounts and low-risk destinations for any future live verification,
  and revoke test credentials after use.

## Limitations and Future Improvements

- Automated tests use mocked provider APIs and do not publish live posts.
- Live posting to the five external platforms has not yet been verified.
- No database, queue, retry policy, scheduled posting, or durable job tracking
  is implemented.
- No authentication or authorization is implemented for the FastAPI endpoint
  itself.
- Provider success is based on each API response, not independent verification
  that an internet user can see or discover the resulting post.
- Future work could add API authentication, persisted posting jobs, controlled
  retries, metrics, structured audit-safe logging, and opt-in live integration
  test tooling.

## Documentation

- [Local Development Guide](docs/LOCAL_DEVELOPMENT.md)
