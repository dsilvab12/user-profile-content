import asyncio

import httpx

from app.config import Settings
from app.exceptions import DatabricksAuthenticationError, InvalidJsonError
from app.main import (
    app,
    get_databricks_auth_provider,
    get_settings,
    get_transfer_service,
)
from app.models import (
    DestinationInfo,
    SourceInfo,
    TransferRequest,
    TransferResponse,
)
from app.services.transfer_service import TransferService


class FakeGitHubClient:
    def __init__(self, content: bytes) -> None:
        self.content = content

    async def fetch_json_file(self, **kwargs) -> bytes:
        return self.content


class FakeDatabricksClient:
    def __init__(self) -> None:
        self.uploaded_content: bytes | None = None

    async def upload_file(self, *, destination_path: str, content: bytes, overwrite: bool):
        self.uploaded_content = content


class FakeReadyAuthProvider:
    def __init__(self) -> None:
        self.validate_called = False

    def validate(self) -> None:
        self.validate_called = True


class FailingReadyAuthProvider:
    def validate(self) -> None:
        raise DatabricksAuthenticationError(
            "Unable to obtain Databricks OAuth credentials.",
            details={"profile": "brijesh.dsilva"},
        )


def make_settings(**overrides) -> Settings:
    defaults = {
        "databricks_auth_type": "oauth-u2m",
        "databricks_host": "example.cloud.databricks.com",
        "databricks_config_profile": "brijesh.dsilva",
        "github_token": None,
        "_env_file": None,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def test_invalid_json_is_rejected_and_original_bytes_are_not_uploaded() -> None:
    async def run() -> None:
        databricks_client = FakeDatabricksClient()
        service = TransferService(
            make_settings(),
            github_client=FakeGitHubClient(b'{"broken":'),
            databricks_client=databricks_client,
        )

        try:
            await service.transfer(payload=TransferRequest(), request_id="req-1")
        except InvalidJsonError:
            pass
        else:
            raise AssertionError("InvalidJsonError was not raised")

        assert databricks_client.uploaded_content is None

    asyncio.run(run())


def test_successful_end_to_end_api_request_with_mocked_service() -> None:
    async def run() -> None:
        class FakeTransferService:
            async def transfer(self, payload, *, request_id: str) -> TransferResponse:
                assert payload.github_owner is None
                return TransferResponse(
                    success=True,
                    request_id=request_id,
                    byte_count=22,
                    source=SourceInfo(
                        github_owner="dsilvab12",
                        github_repo="user-profile-content",
                        github_branch="main",
                        github_file_path="audience-requests/green_day_request.json",
                    ),
                    destination=DestinationInfo(
                        databricks_destination_path=(
                            "/Volumes/sandbox_prod/bdsilva/audience_requests/incoming/"
                            "green_day_request.json"
                        ),
                        overwrite=True,
                    ),
                )

        app.dependency_overrides[get_transfer_service] = lambda: FakeTransferService()
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                response = await client.post(
                    "/api/v1/transfers",
                    headers={"X-Request-ID": "req-api-1"},
                    json={},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["request_id"] == "req-api-1"
        assert response.headers["X-Request-ID"] == "req-api-1"

    asyncio.run(run())


def test_health_endpoint() -> None:
    async def run() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            response = await client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    asyncio.run(run())


def test_databricks_host_is_normalized() -> None:
    settings = make_settings(databricks_host="example.cloud.databricks.com/")

    assert settings.databricks_host == "https://example.cloud.databricks.com"


def test_databricks_config_requires_named_profile_not_token() -> None:
    settings = make_settings(
        databricks_auth_type="oauth-u2m",
        databricks_host="https://dbc-2bcb7c03-2845.cloud.databricks.com",
        databricks_config_profile="brijesh.dsilva",
    )

    assert settings.missing_databricks_config() == []


def test_ready_with_named_databricks_profile() -> None:
    async def run() -> None:
        auth_provider = FakeReadyAuthProvider()
        app.dependency_overrides[get_settings] = lambda: make_settings(
            databricks_auth_type="oauth-u2m",
            databricks_host="https://dbc-2bcb7c03-2845.cloud.databricks.com",
            databricks_config_profile="brijesh.dsilva",
        )
        app.dependency_overrides[get_databricks_auth_provider] = lambda: auth_provider
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                response = await client.get("/ready")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {
            "status": "ready",
            "databricks_configured": True,
            "databricks_authenticated": True,
            "missing": [],
            "authentication_error": None,
        }
        assert auth_provider.validate_called is True

    asyncio.run(run())


def test_ready_reports_authentication_failure_without_exposing_token() -> None:
    async def run() -> None:
        app.dependency_overrides[get_settings] = lambda: make_settings(
            databricks_auth_type="oauth-u2m",
            databricks_host="https://dbc-2bcb7c03-2845.cloud.databricks.com",
            databricks_config_profile="brijesh.dsilva",
        )
        app.dependency_overrides[get_databricks_auth_provider] = (
            lambda: FailingReadyAuthProvider()
        )
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                response = await client.get("/ready")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 503
        assert response.json() == {
            "status": "not_ready",
            "databricks_configured": True,
            "databricks_authenticated": False,
            "missing": [],
            "authentication_error": "databricks_authentication_failed",
        }

    asyncio.run(run())


def test_ready_reports_missing_configuration() -> None:
    async def run() -> None:
        app.dependency_overrides[get_settings] = lambda: make_settings(
            databricks_auth_type=None,
            databricks_host=None,
            databricks_config_profile=None,
        )
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                response = await client.get("/ready")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 503
        assert response.json() == {
            "status": "not_ready",
            "databricks_configured": False,
            "databricks_authenticated": False,
            "missing": [
                "DATABRICKS_HOST",
                "DATABRICKS_AUTH_TYPE",
                "DATABRICKS_CONFIG_PROFILE",
            ],
            "authentication_error": None,
        }

    asyncio.run(run())


def test_transfer_endpoint_reports_missing_configuration() -> None:
    async def run() -> None:
        app.dependency_overrides[get_settings] = lambda: make_settings(
            databricks_auth_type=None,
            databricks_host=None,
            databricks_config_profile=None,
        )
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                response = await client.post(
                    "/api/v1/transfers",
                    headers={"X-Request-ID": "req-missing-config"},
                    json={},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 503
        body = response.json()
        assert body["success"] is False
        assert body["request_id"] == "req-missing-config"
        assert body["error"]["code"] == "missing_configuration"
        assert body["error"]["details"]["missing"] == [
            "DATABRICKS_HOST",
            "DATABRICKS_AUTH_TYPE",
            "DATABRICKS_CONFIG_PROFILE",
        ]

    asyncio.run(run())


def test_default_databricks_profile_is_not_ready() -> None:
    settings = make_settings(
        databricks_auth_type="oauth-u2m",
        databricks_host="https://dbc-2bcb7c03-2845.cloud.databricks.com",
        databricks_config_profile="DEFAULT",
    )

    assert settings.missing_databricks_config() == ["DATABRICKS_CONFIG_PROFILE"]


def test_non_oauth_u2m_auth_type_is_not_ready() -> None:
    settings = make_settings(
        databricks_auth_type="pat",
        databricks_host="https://dbc-2bcb7c03-2845.cloud.databricks.com",
        databricks_config_profile="brijesh.dsilva",
    )

    assert settings.missing_databricks_config() == ["DATABRICKS_AUTH_TYPE"]
