import hmac
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import SecretStr

from app.config import Settings, get_settings


guest_list_bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="GuestListBearerAuth",
    description="Bearer API key for Guest List event ingestion.",
)


class GuestListAuthenticator:
    def __init__(self, api_key: SecretStr | str | None) -> None:
        self.api_key = _secret_value(api_key)

    def authenticate(self, credentials: HTTPAuthorizationCredentials | None) -> None:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise _unauthorized()

        provided_key = credentials.credentials
        if not provided_key:
            raise _unauthorized()

        if not self.api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Guest List API key is not configured.",
            )

        if not hmac.compare_digest(
            provided_key.encode("utf-8"),
            self.api_key.encode("utf-8"),
        ):
            raise _unauthorized()


def get_guest_list_authenticator(
    settings: Settings = Depends(get_settings),
) -> GuestListAuthenticator:
    return GuestListAuthenticator(settings.guest_list_api_key)


def require_guest_list_auth(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(guest_list_bearer_scheme),
    ],
    authenticator: Annotated[
        GuestListAuthenticator,
        Depends(get_guest_list_authenticator),
    ],
) -> None:
    authenticator.authenticate(credentials)


def _secret_value(secret: SecretStr | str | None) -> str | None:
    if secret is None:
        return None

    if isinstance(secret, SecretStr):
        value = secret.get_secret_value()
    else:
        value = secret

    value = value.strip()
    return value or None


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing or invalid Guest List credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )
