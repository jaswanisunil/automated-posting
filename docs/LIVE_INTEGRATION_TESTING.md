# Live Integration Testing

**Test date:** 21 November 2026

This record documents an actual live API test in which the request completed
with HTTP 200 and successfully published the same message to DEV Community and
Mastodon.

## Request Message

Testing automated-posting API on DEV and Mastodon. Verifying multi-platform publishing through FastAPI. Learn more: [https://example.com](https://example.com)

## DEV/Forem Result

- Platform: DEV/Forem
- Status: success
- Posted URL: [View DEV post](https://dev.to/sunil_jaswani_9439d460a33/testing-automated-posting-api-on-dev-and-mastodon-verifying-multi-platform-publishing-through-1a6p)
- public_access: null

DEV public accessibility was not independently verified by the API. The
`published` response value does not independently establish public
accessibility.

## Mastodon Result

- Platform: Mastodon
- Status: success
- Posted URL: [View Mastodon post](https://mastodon.social/@sunil_civica/117655780823919553)
- public_access: true

## Other Platform Results

- Telegram: failed - The platform is not configured.
- Discord: failed - The platform is not configured.
- Bluesky: failed - The platform is not configured.

The API supports independent platform results, so a failure on one platform
does not prevent configured platforms from completing. HTTP 200 represents the
valid API request and independent result collection; it does not mean every
platform succeeded.

Both DEV and Mastodon successfully published the test message. The other three
platforms still require live credentials, destination configuration, and
integration testing.
