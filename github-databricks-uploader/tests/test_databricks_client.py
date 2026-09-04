import asyncio

import httpx
import pytest

from app.exceptions import (
    DatabricksAuthenticationError,
    DatabricksConfigurationError,
    DatabricksPermissionError,
)
from app.services.databricks_auth import DatabricksAuthorization, SdkDatabricksAuthProvider
from app.services.databricks_client import DatabricksClient


class StaticAuthProvider:
    def __init__(
        self,
        authorization_header: str,
        host: str = "https://dbc-2bcb7c03-2845.cloud.databricks.com",
    ) -> None:
        self._authorization_header = authorization_header
        self._host = host

    def authorize(self) -> DatabricksAuthorization:
        return DatabricksAuthorization(
            host=self._host,
            authorization_header=self._authorization_header,
        )

    def validate(self) -> None:
        self.authorize()


class FakeOAuthToken:
    access_token = "oauth-access-token-placeholder"


class FakeConfig:
    calls: list[dict[str, str]] = []
    host = "https://dbc-2bcb7c03-2845.cloud.databricks.com"

    def __init__(self, *, profile: str) -> None:
        self.calls.append({"profile": profile})

    def oauth_token(self) -> FakeOAuthToken:
        return FakeOAuthToken()


def test_successful_databricks_204_response() -> None:
    async def run() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "PUT"
            assert str(request.url) == (
                "https://dbc-2bcb7c03-2845.cloud.databricks.com/api/2.0/fs/files/"
                "Volumes/sandbox_prod/bdsilva/audience_requests/incoming/"
                "green_day_request.json?overwrite=true"
            )
            assert request.url.path == (
                "/api/2.0/fs/files/Volumes/sandbox_prod/bdsilva/"
                "audience_requests/incoming/green_day_request.json"
            )
            assert request.url.params["overwrite"] == "true"
            assert request.headers["Authorization"] == "Bearer oauth-access-token-placeholder"
            assert request.headers["Content-Type"] == "application/octet-stream"
            assert request.content == b'{"artist":"Green Day"}'
            return httpx.Response(204)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = DatabricksClient(
                host="https://dbc-2bcb7c03-2845.cloud.databricks.com",
                auth_provider=StaticAuthProvider(
                    "Bearer oauth-access-token-placeholder"
                ),
                timeout_seconds=1,
                http_client=http_client,
            )
            await client.upload_file(
                destination_path=(
                    "/Volumes/sandbox_prod/bdsilva/audience_requests/incoming/"
                    "green_day_request.json"
                ),
                content=b'{"artist":"Green Day"}',
                overwrite=True,
            )

    asyncio.run(run())


def test_databricks_authentication_failure() -> None:
    async def run() -> None:
        transport = httpx.MockTransport(lambda request: httpx.Response(401))
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = DatabricksClient(
                host="https://example.cloud.databricks.com",
                auth_provider=StaticAuthProvider("Bearer oauth-token"),
                timeout_seconds=1,
                http_client=http_client,
            )
            with pytest.raises(DatabricksAuthenticationError) as exc_info:
                await client.upload_file(
                    destination_path="/Volumes/catalog/schema/volume/file.json",
                    content=b"{}",
                    overwrite=True,
                )

        assert exc_info.value.code == "databricks_authentication_failed"
        assert exc_info.value.details["upstream_status_code"] == 401

    asyncio.run(run())


def test_databricks_permission_failure() -> None:
    async def run() -> None:
        transport = httpx.MockTransport(lambda request: httpx.Response(403))
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = DatabricksClient(
                host="https://example.cloud.databricks.com",
                auth_provider=StaticAuthProvider("Bearer oauth-token"),
                timeout_seconds=1,
                http_client=http_client,
            )
            with pytest.raises(DatabricksPermissionError) as exc_info:
                await client.upload_file(
                    destination_path="/Volumes/catalog/schema/volume/file.json",
                    content=b"{}",
                    overwrite=True,
                )

        assert exc_info.value.code == "databricks_permission_denied"
        assert exc_info.value.details["upstream_status_code"] == 403

    asyncio.run(run())


def test_oauth_u2m_auth_provider_uses_named_sdk_profile() -> None:
    FakeConfig.calls = []
    provider = SdkDatabricksAuthProvider(
        configured_host="https://dbc-2bcb7c03-2845.cloud.databricks.com",
        profile="brijesh.dsilva",
        config_factory=FakeConfig,
    )

    authorization = provider.authorize()

    assert authorization.authorization_header == "Bearer oauth-access-token-placeholder"
    assert authorization.host == "https://dbc-2bcb7c03-2845.cloud.databricks.com"
    assert FakeConfig.calls == [{"profile": "brijesh.dsilva"}]


def test_auth_provider_prefers_host_loaded_from_profile() -> None:
    provider = SdkDatabricksAuthProvider(
        configured_host=None,
        profile="brijesh.dsilva",
        config_factory=FakeConfig,
    )

    authorization = provider.authorize()

    assert authorization.host == "https://dbc-2bcb7c03-2845.cloud.databricks.com"


def test_oauth_u2m_auth_provider_uploads_with_sdk_authorization_header() -> None:
    async def run() -> None:
        provider = SdkDatabricksAuthProvider(
            configured_host="https://dbc-2bcb7c03-2845.cloud.databricks.com",
            profile="brijesh.dsilva",
            config_factory=FakeConfig,
        )

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["Authorization"] == "Bearer oauth-access-token-placeholder"
            assert request.headers["Content-Type"] == "application/octet-stream"
            return httpx.Response(204)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = DatabricksClient(
                host="https://dbc-2bcb7c03-2845.cloud.databricks.com",
                auth_provider=provider,
                timeout_seconds=1,
                http_client=http_client,
            )
            await client.upload_file(
                destination_path="/Volumes/catalog/schema/volume/file.json",
                content=b"{}",
                overwrite=True,
            )

    asyncio.run(run())


def test_auth_provider_rejects_profile_host_mismatch() -> None:
    class MismatchedHostConfig(FakeConfig):
        host = "https://different.cloud.databricks.com"

    provider = SdkDatabricksAuthProvider(
        configured_host="https://dbc-2bcb7c03-2845.cloud.databricks.com",
        profile="brijesh.dsilva",
        config_factory=MismatchedHostConfig,
    )

    with pytest.raises(DatabricksConfigurationError) as exc_info:
        provider.authorize()

    assert exc_info.value.code == "databricks_configuration_error"
    assert exc_info.value.details == {
        "profile": "brijesh.dsilva",
        "configured_host": "https://dbc-2bcb7c03-2845.cloud.databricks.com",
        "profile_host": "https://different.cloud.databricks.com",
    }
