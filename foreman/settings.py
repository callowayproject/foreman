"""Configuration for Foreman."""

from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from foreman import __version__

PROD_ENV_NAME = "prod"


class AppSettings(BaseSettings):
    """
    Configuration storage for Foreman.
    """

    name: str = f"Foreman ({__version__})"
    """Name and version of the application."""

    environment: str = "dev"
    """Environment we're running in (dev/prod/...)."""

    log_level: str = "INFO"
    """The logging level of the application."""

    otel_connection_string: Optional[str] = Field(default=None)
    """
    The connection string used to connect to application insights.
    Additional configuration can be provided with https://opentelemetry.io/docs/specs/otel/configuration/sdk-environment-variables/
    """

    otel_debug: bool = False
    """Enables debug logging to the console for OpenTelemetry."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def is_production(self) -> bool:
        """Return True if we are in production."""
        return self.environment == PROD_ENV_NAME


settings = AppSettings()
