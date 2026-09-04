from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_GITHUB_OWNER = "dsilvab12"
DEFAULT_GITHUB_REPO = "user-profile-content"
DEFAULT_GITHUB_BRANCH = "main"
DEFAULT_GITHUB_FILE_PATH = "audience-requests/green_day_request.json"
DEFAULT_DATABRICKS_DESTINATION_PATH = (
    "/Volumes/sandbox_prod/bdsilva/audience_requests/incoming/green_day_request.json"
)
REQUIRED_DATABRICKS_AUTH_TYPE = "oauth-u2m"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    databricks_host: str | None = Field(default=None, validation_alias="DATABRICKS_HOST")
    databricks_auth_type: str | None = Field(
        default=None, validation_alias="DATABRICKS_AUTH_TYPE"
    )
    databricks_config_profile: str | None = Field(
        default=None, validation_alias="DATABRICKS_CONFIG_PROFILE"
    )
    guest_list_api_key: SecretStr | None = Field(
        default=None, validation_alias="GUEST_LIST_API_KEY"
    )
    github_token: SecretStr | None = Field(default=None, validation_alias="GITHUB_TOKEN")

    github_owner: str = Field(
        default=DEFAULT_GITHUB_OWNER, validation_alias="GITHUB_OWNER"
    )
    github_repo: str = Field(default=DEFAULT_GITHUB_REPO, validation_alias="GITHUB_REPO")
    github_branch: str = Field(
        default=DEFAULT_GITHUB_BRANCH, validation_alias="GITHUB_BRANCH"
    )
    github_file_path: str = Field(
        default=DEFAULT_GITHUB_FILE_PATH, validation_alias="GITHUB_FILE_PATH"
    )
    databricks_destination_path: str = Field(
        default=DEFAULT_DATABRICKS_DESTINATION_PATH,
        validation_alias="DATABRICKS_DESTINATION_PATH",
    )
    request_timeout_seconds: float = Field(
        default=30.0, gt=0, validation_alias="REQUEST_TIMEOUT_SECONDS"
    )

    @field_validator("databricks_host", mode="before")
    @classmethod
    def normalize_databricks_host(cls, value: object) -> str | None:
        if value is None:
            return None

        host = str(value).strip().rstrip("/")
        if not host:
            return None

        if not host.startswith(("http://", "https://")):
            host = f"https://{host}"

        return host

    @field_validator("databricks_auth_type", mode="before")
    @classmethod
    def normalize_databricks_auth_type(cls, value: object) -> str | None:
        if value is None:
            return None

        auth_type = str(value).strip().lower()
        return auth_type or None

    @field_validator("databricks_config_profile", mode="before")
    @classmethod
    def normalize_databricks_config_profile(cls, value: object) -> str | None:
        if value is None:
            return None

        profile = str(value).strip()
        return profile or None

    def missing_databricks_config(self) -> list[str]:
        missing = []
        if not self.databricks_host:
            missing.append("DATABRICKS_HOST")

        if self.databricks_auth_type != REQUIRED_DATABRICKS_AUTH_TYPE:
            missing.append("DATABRICKS_AUTH_TYPE")

        if (
            not self.databricks_config_profile
            or self.databricks_config_profile.upper() == "DEFAULT"
        ):
            missing.append("DATABRICKS_CONFIG_PROFILE")

        return missing


@lru_cache
def get_settings() -> Settings:
    return Settings()
