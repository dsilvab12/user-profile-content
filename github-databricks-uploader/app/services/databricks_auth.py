from dataclasses import dataclass
from typing import Callable, Protocol

from app.exceptions import DatabricksAuthenticationError, DatabricksConfigurationError


@dataclass(frozen=True)
class DatabricksAuthorization:
    host: str
    authorization_header: str


class DatabricksAuthProvider(Protocol):
    def authorize(self) -> DatabricksAuthorization:
        """Return an SDK-derived host and complete Authorization header value."""

    def validate(self) -> None:
        """Verify that credentials can be obtained without returning them."""


class SdkDatabricksAuthProvider:
    def __init__(
        self,
        *,
        configured_host: str | None,
        profile: str,
        config_factory: Callable[..., object] | None = None,
    ) -> None:
        self.configured_host = _normalize_host(configured_host)
        self.profile = profile
        self.config_factory = config_factory

    def authorize(self) -> DatabricksAuthorization:
        try:
            config = self._load_config()
            profile_host = _normalize_host(getattr(config, "host", None))
            host = self._resolve_host(profile_host)
            oauth_token = config.oauth_token()
            access_token = getattr(oauth_token, "access_token", None)
        except Exception as exc:
            if isinstance(exc, DatabricksConfigurationError):
                raise
            raise DatabricksAuthenticationError(
                "Unable to authenticate to Databricks with SDK unified authentication.",
                details={"profile": self.profile},
            ) from exc

        if not isinstance(access_token, str) or not access_token.strip():
            raise DatabricksAuthenticationError(
                "Databricks SDK unified authentication did not return an OAuth access token.",
                details={"profile": self.profile},
            )

        return DatabricksAuthorization(
            host=host,
            authorization_header=f"Bearer {access_token}",
        )

    def validate(self) -> None:
        self.authorize()

    def _load_config(self) -> object:
        config_factory = self.config_factory
        if config_factory is None:
            from databricks.sdk.core import Config

            config_factory = Config

        return config_factory(profile=self.profile)

    def _resolve_host(self, profile_host: str | None) -> str:
        if profile_host and self.configured_host and profile_host != self.configured_host:
            raise DatabricksConfigurationError(
                "Databricks host in the selected profile does not match DATABRICKS_HOST.",
                details={
                    "profile": self.profile,
                    "configured_host": self.configured_host,
                    "profile_host": profile_host,
                },
            )

        host = profile_host or self.configured_host
        if not host:
            raise DatabricksConfigurationError(
                "Databricks host is missing from configuration and selected profile.",
                details={"profile": self.profile},
            )

        return host


def _normalize_host(value: object) -> str | None:
    if value is None:
        return None

    host = str(value).strip().rstrip("/")
    if not host:
        return None

    if not host.startswith(("http://", "https://")):
        host = f"https://{host}"

    return host
