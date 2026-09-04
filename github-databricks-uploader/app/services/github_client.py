from urllib.parse import quote

import httpx
from pydantic import SecretStr

from app.exceptions import GitHubDownloadError, GitHubFileNotFoundError


GITHUB_API_BASE_URL = "https://api.github.com"


def _secret_value(secret: SecretStr | str | None) -> str | None:
    if secret is None:
        return None
    if isinstance(secret, SecretStr):
        value = secret.get_secret_value()
    else:
        value = secret
    value = value.strip()
    return value or None


class GitHubClient:
    def __init__(
        self,
        *,
        timeout_seconds: float,
        token: SecretStr | str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.token = _secret_value(token)
        self.http_client = http_client

    async def fetch_json_file(
        self,
        *,
        owner: str,
        repo: str,
        branch: str,
        file_path: str,
    ) -> bytes:
        async def request(client: httpx.AsyncClient) -> bytes:
            return await self._fetch_with_client(
                client=client,
                owner=owner,
                repo=repo,
                branch=branch,
                file_path=file_path,
            )

        if self.http_client is not None:
            return await request(self.http_client)

        async with httpx.AsyncClient(
            timeout=self.timeout_seconds, follow_redirects=True
        ) as client:
            return await request(client)

    async def _fetch_with_client(
        self,
        *,
        client: httpx.AsyncClient,
        owner: str,
        repo: str,
        branch: str,
        file_path: str,
    ) -> bytes:
        encoded_owner = quote(owner, safe="")
        encoded_repo = quote(repo, safe="")
        encoded_path = quote(file_path.lstrip("/"), safe="/")
        url = (
            f"{GITHUB_API_BASE_URL}/repos/{encoded_owner}/{encoded_repo}"
            f"/contents/{encoded_path}"
        )
        headers = {
            "Accept": "application/vnd.github.raw+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "github-databricks-uploader",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        try:
            response = await client.get(url, params={"ref": branch}, headers=headers)
        except httpx.TimeoutException as exc:
            raise GitHubDownloadError(
                "Timed out retrieving the GitHub file.",
                details={"owner": owner, "repo": repo, "branch": branch, "path": file_path},
            ) from exc
        except httpx.HTTPError as exc:
            raise GitHubDownloadError(
                "Failed to retrieve the GitHub file.",
                details={"owner": owner, "repo": repo, "branch": branch, "path": file_path},
            ) from exc

        if response.status_code == 404:
            raise GitHubFileNotFoundError(
                "GitHub file was not found.",
                details={"owner": owner, "repo": repo, "branch": branch, "path": file_path},
            )

        if response.status_code >= 400:
            raise GitHubDownloadError(
                f"GitHub returned HTTP {response.status_code} while retrieving the file.",
                details={
                    "owner": owner,
                    "repo": repo,
                    "branch": branch,
                    "path": file_path,
                    "upstream_status_code": response.status_code,
                },
            )

        return response.content
