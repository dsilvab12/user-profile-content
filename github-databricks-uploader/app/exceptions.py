from typing import Any


class ServiceError(Exception):
    status_code = 500
    code = "service_error"

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ConfigurationError(ServiceError):
    status_code = 503
    code = "missing_configuration"


class DatabricksConfigurationError(ServiceError):
    status_code = 503
    code = "databricks_configuration_error"


class GitHubFileNotFoundError(ServiceError):
    status_code = 404
    code = "github_file_not_found"


class GitHubDownloadError(ServiceError):
    status_code = 502
    code = "github_download_failed"


class InvalidJsonError(ServiceError):
    status_code = 422
    code = "invalid_json"


class DatabricksAuthenticationError(ServiceError):
    status_code = 502
    code = "databricks_authentication_failed"


class DatabricksPermissionError(ServiceError):
    status_code = 502
    code = "databricks_permission_denied"


class DatabricksUploadError(ServiceError):
    status_code = 502
    code = "databricks_upload_failed"
