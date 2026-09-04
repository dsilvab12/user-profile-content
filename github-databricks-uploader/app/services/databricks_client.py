from urllib.parse import quote

import httpx

from app.exceptions import (
    DatabricksAuthenticationError,
    DatabricksPermissionError,
    DatabricksUploadError,
)
from app.services.databricks_auth import DatabricksAuthProvider


class DatabricksClient:
    def __init__(
        self,
        *,
        host: str,
        auth_provider: DatabricksAuthProvider,
        timeout_seconds: float,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.host = host.rstrip("/")
        self.auth_provider = auth_provider
        self.timeout_seconds = timeout_seconds
        self.http_client = http_client

    async def upload_file(
        self,
        *,
        destination_path: str,
        content: bytes,
        overwrite: bool,
    ) -> None:
        async def request(client: httpx.AsyncClient) -> None:
            return await self._upload_with_client(
                client=client,
                destination_path=destination_path,
                content=content,
                overwrite=overwrite,
            )

        if self.http_client is not None:
            return await request(self.http_client)

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            return await request(client)

    async def _upload_with_client(
        self,
        *,
        client: httpx.AsyncClient,
        destination_path: str,
        content: bytes,
        overwrite: bool,
    ) -> None:
        encoded_destination_path = quote(destination_path, safe="/")
        authorization = self.auth_provider.authorize()
        host = authorization.host or self.host
        url = f"{host}/api/2.0/fs/files{encoded_destination_path}"
        headers = {
            "Authorization": authorization.authorization_header,
            "Content-Type": "application/octet-stream",
        }

        try:
            response = await client.put(
                url,
                params={"overwrite": str(overwrite).lower()},
                content=content,
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            raise DatabricksUploadError(
                "Timed out uploading the file to Databricks.",
                details={"destination_path": destination_path},
            ) from exc
        except httpx.HTTPError as exc:
            raise DatabricksUploadError(
                "Failed to upload the file to Databricks.",
                details={"destination_path": destination_path},
            ) from exc

        if response.status_code == 204:
            return

        details = {
            "destination_path": destination_path,
            "upstream_status_code": response.status_code,
        }
        if response.status_code == 401:
            raise DatabricksAuthenticationError(
                "Databricks rejected the authenticated request.", details=details
            )
        if response.status_code == 403:
            raise DatabricksPermissionError(
                "Databricks denied access to the destination path.", details=details
            )

        raise DatabricksUploadError(
            f"Databricks returned HTTP {response.status_code} while uploading the file.",
            details=details,
        )
