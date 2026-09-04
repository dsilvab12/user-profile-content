# GitHub Databricks Uploader

FastAPI backend service that downloads a JSON file from GitHub, validates that it is JSON, and uploads the original downloaded bytes to a Databricks Unity Catalog volume with the Databricks Files REST API.

The default transfer reads:

`dsilvab12/user-profile-content@main:audience-requests/green_day_request.json`

and writes:

`/Volumes/sandbox_prod/bdsilva/audience_requests/incoming/green_day_request.json`

## Prerequisites

- Python 3.11 or newer
- Databricks CLI configured for OAuth user-to-machine local authentication
- A Databricks workspace URL
- Optional GitHub token for private repositories

## Environment Setup

Create a local `.env` from the example and fill in the Databricks values:

```bash
cp .env.example .env
```

Required for uploads:

```text
DATABRICKS_AUTH_TYPE
DATABRICKS_HOST
DATABRICKS_CONFIG_PROFILE
GUEST_LIST_API_KEY
```

For local development, use:

```text
DATABRICKS_AUTH_TYPE=oauth-u2m
DATABRICKS_HOST=https://dbc-2bcb7c03-2845.cloud.databricks.com
DATABRICKS_CONFIG_PROFILE=brijesh.dsilva
GUEST_LIST_API_KEY=<local-poc-api-key>
```

`DATABRICKS_TOKEN`, `DATABRICKS_CLIENT_ID`, `DATABRICKS_CLIENT_SECRET`, and `DATABRICKS_HTTP_PATH` are not required or stored for OAuth U2M. This service uploads to the Files REST API and does not connect to a SQL warehouse.

Optional defaults:

```text
GITHUB_TOKEN
GITHUB_OWNER
GITHUB_REPO
GITHUB_BRANCH
GITHUB_FILE_PATH
DATABRICKS_DESTINATION_PATH
REQUEST_TIMEOUT_SECONDS
```

`DATABRICKS_HOST` may be set with or without `https://`; the service normalizes it.

## Virtual Environment Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
```

## Dependency Installation

```bash
pip install -r requirements.txt
```

## Local Startup

```bash
uvicorn app.main:app --reload --port 8000
```

## Example Transfer Request

```bash
curl -X POST http://localhost:8000/api/v1/transfers \
  -H "Content-Type: application/json" \
  -d '{}'
```

Override source or destination values in the JSON body when needed:

```json
{
  "github_owner": "dsilvab12",
  "github_repo": "user-profile-content",
  "github_branch": "main",
  "github_file_path": "audience-requests/green_day_request.json",
  "databricks_destination_path": "/Volumes/sandbox_prod/bdsilva/audience_requests/incoming/green_day_request.json",
  "overwrite": true
}
```

## Example Guest List Event Request

The external Guest List application can POST an event directly to:

```bash
curl -X POST http://localhost:8000/api/v1/events \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <local-poc-api-key>" \
  -d '{
    "event_id": "guest-list-2026-08-07-green-day",
    "event_date": "2026-08-05T19:30:00Z",
    "artist": {
      "id": "green-day",
      "name": "Green Day",
      "image_url": "https://images.example.com/green-day.jpg"
    },
    "channel": {
      "id": "34",
      "name": "Lithium"
    },
    "aod": {
      "episode_id": "episode-98765",
      "title": "Green Day Guest List",
      "url": "https://www.siriusxm.com/player/episode/98765"
    },
    "event": {
      "title": "Green Day Guest List",
      "description": "Green Day joined Lithium for a Guest List event.",
      "location": "Los Angeles"
    },
    "assets": {
      "hero_image_url": "https://images.example.com/green-day-hero.jpg",
      "thumbnail_url": "https://images.example.com/green-day-thumb.jpg"
    }
  }'
```

Required fields are `event_id`, `event_date`, `artist.name`, and `channel.name`. Other Guest List fields are accepted but ignored by the Databricks audience request transformation.

The service transforms the event into this Databricks audience request shape:

```json
{
  "request_id": "guest-list-2026-08-07-green-day",
  "artist_name": "Green Day",
  "channel_names": ["Lithium"],
  "start_date": "2026-08-05",
  "end_date": "2026-05-06",
  "max_day_bucket": 91,
  "output_table": "sandbox_prod.bdsilva.green_day_channel_results"
}
```

The transformed JSON is serialized as UTF-8 and uploaded without overwrite to:

```text
/Volumes/sandbox_prod/bdsilva/audience_requests/incoming/<request_id>_<UTC timestamp>.json
```

`POST /api/v1/events` requires `Authorization: Bearer <key>`, where `<key>` matches `GUEST_LIST_API_KEY`. Missing or invalid credentials return HTTP 401. The API key comparison is constant-time, and API keys or authorization headers are never logged. This local POC authentication is isolated from event transformation and Databricks upload logic so it can be replaced with enterprise OAuth later.

`GET /health` does not require authentication.

## GitHub Authentication

Public repositories work without `GITHUB_TOKEN`.

For private repositories, set `GITHUB_TOKEN` to a token with read access to repository contents. The service sends it as a bearer token to the GitHub Contents API. Tokens and authorization headers are not logged.

## Databricks Authentication

Local development uses Databricks OAuth user-to-machine authentication through the Databricks CLI and the official Databricks Python SDK unified authentication.

Log in once with the Databricks CLI and create the named profile:

```bash
databricks auth login --host https://dbc-2bcb7c03-2845.cloud.databricks.com --profile brijesh.dsilva
```

Then set:

```text
DATABRICKS_AUTH_TYPE=oauth-u2m
DATABRICKS_HOST=https://dbc-2bcb7c03-2845.cloud.databricks.com
DATABRICKS_CONFIG_PROFILE=brijesh.dsilva
```

The service treats `DATABRICKS_AUTH_TYPE=oauth-u2m` as an application-level setting only. It does not pass `oauth-u2m` into the Databricks SDK as `auth_type`.

For authentication, the service loads the selected CLI OAuth profile with `Config(profile=settings.databricks_config_profile)`, obtains a short-lived OAuth token with `config.oauth_token()`, and uses that token only to build the `Authorization: Bearer ...` header for the Files REST API upload.

The host loaded from the selected profile is preferred for the upload URL. If `DATABRICKS_HOST` is also set, the service validates that it matches the profile host.

Do not rely on the Databricks `DEFAULT` profile for this service. `DATABRICKS_CONFIG_PROFILE` must name the profile to use.

The service uploads with:

```text
PUT /api/2.0/fs/files{destination_path}?overwrite=true
Content-Type: application/octet-stream
Authorization: Bearer <SDK-provided OAuth access token>
```

HTTP 204 from Databricks is treated as a successful upload.

## Required Unity Catalog Permissions

The Databricks user authenticated through the named OAuth U2M profile must have permission to write to the destination volume path. In practice this usually means the user can use the catalog and schema and has write access to the target volume.

For the default path, verify permissions on:

```text
catalog: sandbox_prod
schema: bdsilva
volume: audience_requests
```

## Troubleshooting

HTTP 401 from GitHub usually means the token is missing, expired, malformed, or lacks access to a private repository.

HTTP 404 from GitHub means the owner, repo, branch, or file path is wrong, or a private repository is being accessed without a usable token.

HTTP 401 from Databricks means the OAuth session for the named profile was rejected. Rerun `databricks auth login --host https://dbc-2bcb7c03-2845.cloud.databricks.com --profile brijesh.dsilva`.

HTTP 403 from Databricks means authentication worked, but the identity does not have permission to write to the destination volume path.

HTTP 404 from Databricks usually means the catalog, schema, volume, or destination path does not exist, or the configured identity cannot see it.

`GET /ready` returns `503` when required Databricks configuration is missing or when the named profile cannot produce an OAuth token. It reports missing environment variable names or a non-secret error code, but never token values or authorization headers.

## Verify The Uploaded File In Databricks

In Databricks, inspect the destination volume path:

```sql
LIST '/Volumes/sandbox_prod/bdsilva/audience_requests/incoming/';
```

You can also read the uploaded JSON:

```sql
SELECT * FROM json.`/Volumes/sandbox_prod/bdsilva/audience_requests/incoming/green_day_request.json`;
```

## Security

Do not commit `.env` or tokens. `.env` is intentionally ignored by Git.

Do not paste tokens, OAuth access tokens, OAuth refresh tokens, Databricks CLI token-cache contents, or authorization headers into logs, issue trackers, shell history, or screenshots. Rotate or revoke credentials immediately if they are exposed.

Run tests with mocked HTTP calls only:

```bash
pytest
```
