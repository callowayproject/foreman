"""Main entrypoint for Foreman."""

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import ORJSONResponse

from foreman.logging_info import configure as configure_logging
from foreman.middleware import LogCorrelationIdMiddleware
from foreman.otel import configure_otel
from foreman.routers import health
from foreman.settings import settings

configure_logging()

logger = structlog.get_logger(__name__)

app: FastAPI = FastAPI(
    title=settings.name,
    description=settings.name,
    docs_url="/swagger",
    default_response_class=ORJSONResponse,
    swagger_ui_oauth2_redirect_url="/auth/callback",
    swagger_ui_parameters={
        "persistAuthorization": True,
    },
)

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)
app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(LogCorrelationIdMiddleware)

app.include_router(health.router)

configure_otel(app, settings)
