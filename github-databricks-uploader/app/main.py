import logging
from uuid import uuid4

from fastapi import Depends, FastAPI, Request, Response, status
from fastapi.responses import JSONResponse

from app.config import Settings, get_settings
from app.exceptions import ServiceError
from app.models import (
    EventIngestionResponse,
    GuestListEventRequest,
    HealthResponse,
    ReadyResponse,
    TransferRequest,
    TransferResponse,
)
from app.services.databricks_auth import SdkDatabricksAuthProvider
from app.services.event_ingestion_service import EventIngestionService
from app.services.guest_list_auth import require_guest_list_auth
from app.services.transfer_service import TransferService


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="GitHub Databricks Uploader",
    version="0.1.0",
    description=(
        "Transfers JSON bytes from GitHub and ingests Guest List events into "
        "Databricks Unity Catalog volumes."
    ),
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


def get_transfer_service(settings: Settings = Depends(get_settings)) -> TransferService:
    return TransferService(settings)


def get_event_ingestion_service(
    settings: Settings = Depends(get_settings),
) -> EventIngestionService:
    return EventIngestionService(settings)


def get_databricks_auth_provider(
    settings: Settings = Depends(get_settings),
) -> SdkDatabricksAuthProvider:
    return SdkDatabricksAuthProvider(
        configured_host=settings.databricks_host,
        profile=settings.databricks_config_profile or "",
    )


@app.exception_handler(ServiceError)
async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", str(uuid4()))
    logger.warning(
        "Request %s failed with %s: %s",
        request_id,
        exc.code,
        exc.message,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "request_id": request_id,
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            },
        },
        headers={"X-Request-ID": request_id},
    )


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/ready", response_model=ReadyResponse)
async def ready(
    response: Response,
    settings: Settings = Depends(get_settings),
    databricks_auth_provider=Depends(get_databricks_auth_provider),
) -> ReadyResponse:
    missing = settings.missing_databricks_config()
    if missing:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadyResponse(
            status="not_ready",
            databricks_configured=False,
            databricks_authenticated=False,
            missing=missing,
        )

    try:
        databricks_auth_provider.validate()
    except ServiceError as exc:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        logger.warning(
            "Databricks readiness authentication failed with %s: %s",
            exc.code,
            exc.message,
        )
        return ReadyResponse(
            status="not_ready",
            databricks_configured=True,
            databricks_authenticated=False,
            missing=[],
            authentication_error=exc.code,
        )

    return ReadyResponse(
        status="ready",
        databricks_configured=True,
        databricks_authenticated=True,
        missing=[],
    )


@app.post("/api/v1/transfers", response_model=TransferResponse)
async def create_transfer(
    payload: TransferRequest,
    request: Request,
    transfer_service: TransferService = Depends(get_transfer_service),
) -> TransferResponse:
    request_id = getattr(request.state, "request_id", str(uuid4()))
    return await transfer_service.transfer(payload, request_id=request_id)


@app.post(
    "/api/v1/events",
    response_model=EventIngestionResponse,
    summary="Ingest a Guest List event",
    tags=["events"],
)
async def create_event(
    payload: GuestListEventRequest,
    _auth: None = Depends(require_guest_list_auth),
    event_ingestion_service: EventIngestionService = Depends(
        get_event_ingestion_service
    ),
) -> EventIngestionResponse:
    return await event_ingestion_service.ingest(payload)
