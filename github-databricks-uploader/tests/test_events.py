import asyncio
import json
from datetime import datetime, timezone

import httpx

from app.config import Settings
from app.exceptions import DatabricksAuthenticationError, DatabricksUploadError
from app.main import app, get_event_ingestion_service, get_settings
from app.models import GuestListEventRequest
from app.services.event_ingestion_service import EventIngestionService
from app.services.event_transformer import EventTransformer, normalize_artist_name


FIXED_NOW = datetime(2026, 8, 8, 12, 34, 56, 123456, tzinfo=timezone.utc)
EXPECTED_DESTINATION_PATH = (
    "/Volumes/sandbox_prod/bdsilva/audience_requests/incoming/"
    "guest-list-2026-08-07-green-day_20260808T123456123456Z.json"
)
TEST_GUEST_LIST_API_KEY = "guest-list-test-key"
AUTH_HEADERS = {"Authorization": f"Bearer {TEST_GUEST_LIST_API_KEY}"}


class FakeDatabricksClient:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, object]] = []

    async def upload_file(
        self, *, destination_path: str, content: bytes, overwrite: bool
    ) -> None:
        self.calls.append(
            {
                "destination_path": destination_path,
                "content": content,
                "overwrite": overwrite,
            }
        )
        if self.error:
            raise self.error


def make_settings(**overrides) -> Settings:
    defaults = {
        "databricks_auth_type": "oauth-u2m",
        "databricks_host": "https://dbc-2bcb7c03-2845.cloud.databricks.com",
        "databricks_config_profile": "brijesh.dsilva",
        "guest_list_api_key": TEST_GUEST_LIST_API_KEY,
        "github_token": None,
        "_env_file": None,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def valid_event_payload() -> dict:
    return {
        "event_id": "guest-list-2026-08-07-green-day",
        "event_date": "2026-08-05T19:30:00Z",
        "artist": {
            "id": "green-day",
            "name": "Green Day",
            "image_url": "https://images.example.com/green-day.jpg",
        },
        "channel": {"id": "34", "name": "Lithium"},
        "aod": {
            "episode_id": "episode-98765",
            "title": "Green Day Guest List",
            "url": "https://www.siriusxm.com/player/episode/98765",
        },
        "event": {
            "title": "Green Day Guest List",
            "description": "Green Day joined Lithium for a Guest List event.",
            "location": "Los Angeles",
        },
        "assets": {
            "hero_image_url": "https://images.example.com/green-day-hero.jpg",
            "thumbnail_url": "https://images.example.com/green-day-thumb.jpg",
        },
    }


def service_with_fake_client(
    fake_client: FakeDatabricksClient,
) -> EventIngestionService:
    return EventIngestionService(
        make_settings(),
        databricks_client=fake_client,
        clock=lambda: FIXED_NOW,
    )


def uploaded_json(fake_client: FakeDatabricksClient) -> dict:
    return json.loads(fake_client.calls[0]["content"].decode("utf-8"))


def test_valid_event_uploads_transformed_audience_request() -> None:
    async def run() -> None:
        fake_client = FakeDatabricksClient()
        service = service_with_fake_client(fake_client)

        response = await service.ingest(
            GuestListEventRequest.model_validate(valid_event_payload())
        )

        assert response.success is True
        assert response.request_id == "guest-list-2026-08-07-green-day"
        assert response.destination_path == EXPECTED_DESTINATION_PATH
        assert len(fake_client.calls) == 1

        upload_call = fake_client.calls[0]
        assert upload_call["destination_path"] == EXPECTED_DESTINATION_PATH
        assert upload_call["overwrite"] is False

        transformed = uploaded_json(fake_client)
        assert transformed == {
            "request_id": "guest-list-2026-08-07-green-day",
            "artist_name": "Green Day",
            "channel_names": ["Lithium"],
            "start_date": "2026-08-05",
            "end_date": "2026-05-06",
            "max_day_bucket": 91,
            "output_table": "sandbox_prod.bdsilva.green_day_channel_results",
        }
        assert response.bytes_uploaded == len(upload_call["content"])

    asyncio.run(run())


def test_event_endpoint_accepts_valid_event() -> None:
    async def run() -> None:
        fake_client = FakeDatabricksClient()
        service = service_with_fake_client(fake_client)
        app.dependency_overrides[get_event_ingestion_service] = lambda: service
        app.dependency_overrides[get_settings] = lambda: make_settings()
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                response = await client.post(
                    "/api/v1/events",
                    json=valid_event_payload(),
                    headers=AUTH_HEADERS,
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {
            "success": True,
            "request_id": "guest-list-2026-08-07-green-day",
            "destination_path": EXPECTED_DESTINATION_PATH,
            "bytes_uploaded": len(fake_client.calls[0]["content"]),
        }

    asyncio.run(run())


def test_missing_artist_is_rejected() -> None:
    async def run() -> None:
        payload = valid_event_payload()
        payload.pop("artist")

        app.dependency_overrides[get_settings] = lambda: make_settings()
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                response = await client.post(
                    "/api/v1/events", json=payload, headers=AUTH_HEADERS
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 422

    asyncio.run(run())


def test_missing_channel_is_rejected() -> None:
    async def run() -> None:
        payload = valid_event_payload()
        payload.pop("channel")

        app.dependency_overrides[get_settings] = lambda: make_settings()
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                response = await client.post(
                    "/api/v1/events", json=payload, headers=AUTH_HEADERS
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 422

    asyncio.run(run())


def test_optional_aod_data_missing_is_allowed() -> None:
    async def run() -> None:
        fake_client = FakeDatabricksClient()
        service = service_with_fake_client(fake_client)
        payload = valid_event_payload()
        payload.pop("aod")

        response = await service.ingest(GuestListEventRequest.model_validate(payload))

        assert response.success is True
        assert uploaded_json(fake_client)["request_id"] == payload["event_id"]

    asyncio.run(run())


def test_optional_image_data_missing_is_allowed() -> None:
    async def run() -> None:
        fake_client = FakeDatabricksClient()
        service = service_with_fake_client(fake_client)
        payload = valid_event_payload()
        payload["artist"].pop("image_url")
        payload.pop("assets")

        response = await service.ingest(GuestListEventRequest.model_validate(payload))

        assert response.success is True
        assert uploaded_json(fake_client)["artist_name"] == "Green Day"

    asyncio.run(run())


def test_extra_guest_list_fields_are_ignored() -> None:
    async def run() -> None:
        fake_client = FakeDatabricksClient()
        service = service_with_fake_client(fake_client)
        payload = valid_event_payload()
        payload["unexpected"] = {"should": "not upload"}
        payload["artist"]["extra_artist_field"] = "ignored"
        payload["channel"]["extra_channel_field"] = "ignored"

        await service.ingest(GuestListEventRequest.model_validate(payload))

        transformed = uploaded_json(fake_client)
        assert set(transformed) == {
            "request_id",
            "artist_name",
            "channel_names",
            "start_date",
            "end_date",
            "max_day_bucket",
            "output_table",
        }

    asyncio.run(run())


def test_artist_name_normalization() -> None:
    assert normalize_artist_name("Guns N' Roses / Green  Day") == (
        "guns_n_roses_green_day"
    )


def test_successful_databricks_upload_uses_no_overwrite() -> None:
    async def run() -> None:
        fake_client = FakeDatabricksClient()
        service = service_with_fake_client(fake_client)

        await service.ingest(GuestListEventRequest.model_validate(valid_event_payload()))

        assert fake_client.calls[0]["overwrite"] is False

    asyncio.run(run())


def test_databricks_authentication_error_is_returned() -> None:
    async def run() -> None:
        fake_client = FakeDatabricksClient(
            error=DatabricksAuthenticationError(
                "Databricks rejected the authenticated request."
            )
        )
        service = service_with_fake_client(fake_client)
        app.dependency_overrides[get_event_ingestion_service] = lambda: service
        app.dependency_overrides[get_settings] = lambda: make_settings()
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                response = await client.post(
                    "/api/v1/events",
                    json=valid_event_payload(),
                    headers=AUTH_HEADERS,
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 502
        assert response.json()["error"]["code"] == "databricks_authentication_failed"

    asyncio.run(run())


def test_databricks_upload_error_is_returned() -> None:
    async def run() -> None:
        fake_client = FakeDatabricksClient(
            error=DatabricksUploadError("Databricks upload failed.")
        )
        service = service_with_fake_client(fake_client)
        app.dependency_overrides[get_event_ingestion_service] = lambda: service
        app.dependency_overrides[get_settings] = lambda: make_settings()
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                response = await client.post(
                    "/api/v1/events",
                    json=valid_event_payload(),
                    headers=AUTH_HEADERS,
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 502
        assert response.json()["error"]["code"] == "databricks_upload_failed"

    asyncio.run(run())


def test_event_endpoint_rejects_missing_authorization() -> None:
    async def run() -> None:
        app.dependency_overrides[get_settings] = lambda: make_settings()
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                response = await client.post(
                    "/api/v1/events", json=valid_event_payload()
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"

    asyncio.run(run())


def test_event_endpoint_rejects_invalid_authorization() -> None:
    async def run() -> None:
        app.dependency_overrides[get_settings] = lambda: make_settings()
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                response = await client.post(
                    "/api/v1/events",
                    json=valid_event_payload(),
                    headers={"Authorization": "Bearer wrong-key"},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"

    asyncio.run(run())


def test_event_endpoint_reports_missing_server_api_key_configuration() -> None:
    async def run() -> None:
        app.dependency_overrides[get_settings] = lambda: make_settings(
            guest_list_api_key=None
        )
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                response = await client.post(
                    "/api/v1/events",
                    json=valid_event_payload(),
                    headers=AUTH_HEADERS,
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 503
        assert response.json() == {"detail": "Guest List API key is not configured."}

    asyncio.run(run())


def test_health_does_not_require_guest_list_authentication() -> None:
    async def run() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            response = await client.get("/health")

        assert response.status_code == 200

    asyncio.run(run())


def test_openapi_documents_events_endpoint() -> None:
    async def run() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            response = await client.get("/openapi.json")

        assert response.status_code == 200
        openapi = response.json()
        assert "/api/v1/events" in openapi["paths"]
        event_operation = openapi["paths"]["/api/v1/events"]["post"]
        assert event_operation["security"] == [{"GuestListBearerAuth": []}]
        assert "GuestListBearerAuth" in openapi["components"]["securitySchemes"]
        assert "security" not in openapi["paths"]["/health"]["get"]

    asyncio.run(run())
