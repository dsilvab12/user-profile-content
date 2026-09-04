from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TransferRequest(BaseModel):
    github_owner: str | None = Field(default=None, min_length=1)
    github_repo: str | None = Field(default=None, min_length=1)
    github_branch: str | None = Field(default=None, min_length=1)
    github_file_path: str | None = Field(default=None, min_length=1)
    databricks_destination_path: str | None = Field(default=None, min_length=1)
    overwrite: bool | None = None

    @field_validator(
        "github_owner",
        "github_repo",
        "github_branch",
        "github_file_path",
        "databricks_destination_path",
        mode="before",
    )
    @classmethod
    def trim_optional_strings(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("databricks_destination_path")
    @classmethod
    def validate_databricks_volume_path(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith("/Volumes/"):
            raise ValueError("Databricks destination path must start with /Volumes/")
        return value


class SourceInfo(BaseModel):
    github_owner: str
    github_repo: str
    github_branch: str
    github_file_path: str


class DestinationInfo(BaseModel):
    databricks_destination_path: str
    overwrite: bool


class TransferResponse(BaseModel):
    success: bool
    request_id: str
    byte_count: int
    source: SourceInfo
    destination: DestinationInfo


class HealthResponse(BaseModel):
    status: str


class ReadyResponse(BaseModel):
    status: str
    databricks_configured: bool
    databricks_authenticated: bool
    missing: list[str]
    authentication_error: str | None = None


class GuestListArtist(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    name: str = Field(min_length=1)
    image_url: str | None = None


class GuestListChannel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    name: str = Field(min_length=1)


class GuestListAod(BaseModel):
    model_config = ConfigDict(extra="ignore")

    episode_id: str | None = None
    title: str | None = None
    url: str | None = None


class GuestListEventDetails(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str | None = None
    description: str | None = None
    location: str | None = None


class GuestListAssets(BaseModel):
    model_config = ConfigDict(extra="ignore")

    hero_image_url: str | None = None
    thumbnail_url: str | None = None


class GuestListEventRequest(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
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
        },
    )

    event_id: str = Field(min_length=1)
    event_date: datetime
    artist: GuestListArtist
    channel: GuestListChannel
    aod: GuestListAod | None = None
    event: GuestListEventDetails | None = None
    assets: GuestListAssets | None = None

    @field_validator("event_id", mode="before")
    @classmethod
    def trim_event_id(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class DatabricksAudienceRequest(BaseModel):
    request_id: str
    artist_name: str
    channel_names: list[str]
    start_date: str
    end_date: str
    max_day_bucket: int
    output_table: str


class EventIngestionResponse(BaseModel):
    success: bool
    request_id: str
    destination_path: str
    bytes_uploaded: int
