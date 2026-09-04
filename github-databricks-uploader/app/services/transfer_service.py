import json

from app.config import Settings
from app.exceptions import ConfigurationError, InvalidJsonError
from app.models import DestinationInfo, SourceInfo, TransferRequest, TransferResponse
from app.services.databricks_auth import SdkDatabricksAuthProvider
from app.services.databricks_client import DatabricksClient
from app.services.github_client import GitHubClient


class TransferService:
    def __init__(
        self,
        settings: Settings,
        *,
        github_client: GitHubClient | None = None,
        databricks_client: DatabricksClient | None = None,
    ) -> None:
        self.settings = settings
        self.github_client = github_client
        self.databricks_client = databricks_client

    async def transfer(
        self, payload: TransferRequest, *, request_id: str
    ) -> TransferResponse:
        missing = self.settings.missing_databricks_config()
        if missing:
            raise ConfigurationError(
                "Databricks configuration is incomplete.",
                details={"missing": missing},
            )

        source = SourceInfo(
            github_owner=payload.github_owner or self.settings.github_owner,
            github_repo=payload.github_repo or self.settings.github_repo,
            github_branch=payload.github_branch or self.settings.github_branch,
            github_file_path=payload.github_file_path or self.settings.github_file_path,
        )
        destination = DestinationInfo(
            databricks_destination_path=(
                payload.databricks_destination_path
                or self.settings.databricks_destination_path
            ),
            overwrite=payload.overwrite if payload.overwrite is not None else True,
        )

        github_client = self.github_client or GitHubClient(
            timeout_seconds=self.settings.request_timeout_seconds,
            token=self.settings.github_token,
        )
        databricks_client = self.databricks_client or DatabricksClient(
            host=self.settings.databricks_host or "",
            auth_provider=self._databricks_auth_provider(),
            timeout_seconds=self.settings.request_timeout_seconds,
        )

        content = await github_client.fetch_json_file(
            owner=source.github_owner,
            repo=source.github_repo,
            branch=source.github_branch,
            file_path=source.github_file_path,
        )

        try:
            json.loads(content)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise InvalidJsonError(
                "Downloaded GitHub file is not valid JSON.",
                details={
                    "owner": source.github_owner,
                    "repo": source.github_repo,
                    "branch": source.github_branch,
                    "path": source.github_file_path,
                },
            ) from exc

        await databricks_client.upload_file(
            destination_path=destination.databricks_destination_path,
            content=content,
            overwrite=destination.overwrite,
        )

        return TransferResponse(
            success=True,
            request_id=request_id,
            byte_count=len(content),
            source=source,
            destination=destination,
        )

    def _databricks_auth_provider(self):
        return SdkDatabricksAuthProvider(
            configured_host=self.settings.databricks_host,
            profile=self.settings.databricks_config_profile or "",
        )
