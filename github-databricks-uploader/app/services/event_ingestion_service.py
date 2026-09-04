from collections.abc import Callable
from datetime import datetime, timezone

from app.config import Settings
from app.exceptions import ConfigurationError
from app.models import EventIngestionResponse, GuestListEventRequest
from app.services.databricks_auth import SdkDatabricksAuthProvider
from app.services.databricks_client import DatabricksClient
from app.services.event_transformer import EventTransformer


EVENT_DESTINATION_DIRECTORY = (
    "/Volumes/sandbox_prod/bdsilva/audience_requests/incoming"
)


class EventIngestionService:
    def __init__(
        self,
        settings: Settings,
        *,
        databricks_client: DatabricksClient | None = None,
        transformer: EventTransformer | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings
        self.databricks_client = databricks_client
        self.transformer = transformer or EventTransformer()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    async def ingest(self, payload: GuestListEventRequest) -> EventIngestionResponse:
        missing = self.settings.missing_databricks_config()
        if missing:
            raise ConfigurationError(
                "Databricks configuration is incomplete.",
                details={"missing": missing},
            )

        transformed = self.transformer.transform(payload)
        content = transformed.model_dump_json().encode("utf-8")
        destination_path = self._destination_path(transformed.request_id)

        databricks_client = self.databricks_client or DatabricksClient(
            host=self.settings.databricks_host or "",
            auth_provider=SdkDatabricksAuthProvider(
                configured_host=self.settings.databricks_host,
                profile=self.settings.databricks_config_profile or "",
            ),
            timeout_seconds=self.settings.request_timeout_seconds,
        )
        await databricks_client.upload_file(
            destination_path=destination_path,
            content=content,
            overwrite=False,
        )

        return EventIngestionResponse(
            success=True,
            request_id=transformed.request_id,
            destination_path=destination_path,
            bytes_uploaded=len(content),
        )

    def _destination_path(self, request_id: str) -> str:
        timestamp = self.clock()
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        timestamp = timestamp.astimezone(timezone.utc)
        timestamp_fragment = timestamp.strftime("%Y%m%dT%H%M%S%fZ")
        return f"{EVENT_DESTINATION_DIRECTORY}/{request_id}_{timestamp_fragment}.json"
