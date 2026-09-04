import asyncio

import httpx
import pytest

from app.exceptions import GitHubFileNotFoundError
from app.services.github_client import GitHubClient


def test_successful_public_github_download() -> None:
    async def run() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == (
                "/repos/dsilvab12/user-profile-content/contents/"
                "audience-requests/green_day_request.json"
            )
            assert request.url.params["ref"] == "main"
            assert "Authorization" not in request.headers
            assert request.headers["Accept"] == "application/vnd.github.raw+json"
            return httpx.Response(200, content=b'{"artist":"Green Day"}')

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = GitHubClient(timeout_seconds=1, http_client=http_client)
            content = await client.fetch_json_file(
                owner="dsilvab12",
                repo="user-profile-content",
                branch="main",
                file_path="audience-requests/green_day_request.json",
            )

        assert content == b'{"artist":"Green Day"}'

    asyncio.run(run())


def test_github_file_not_found() -> None:
    async def run() -> None:
        transport = httpx.MockTransport(lambda request: httpx.Response(404))
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = GitHubClient(timeout_seconds=1, http_client=http_client)
            with pytest.raises(GitHubFileNotFoundError) as exc_info:
                await client.fetch_json_file(
                    owner="dsilvab12",
                    repo="user-profile-content",
                    branch="main",
                    file_path="missing.json",
                )

        assert exc_info.value.status_code == 404
        assert exc_info.value.code == "github_file_not_found"

    asyncio.run(run())
