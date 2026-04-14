"""
Logging processors for structlog.

Inspired by: https://ouassim.tech/notes/setting-up-structured-logging-in-fastapi-with-structlog/
"""

import logging.config
import uuid
from typing import Any, Callable, ClassVar, Generic, NotRequired, TypedDict, TypeVar

import structlog
from opentelemetry import trace
from structlog.typing import EventDict

from foreman.settings import settings

RendererType = TypeVar("RendererType")

Logger = structlog.stdlib.BoundLogger


class LoggerConfig(TypedDict):
    """The configuration of a logger."""

    level: NotRequired[str]
    propagate: NotRequired[bool]
    handlers: NotRequired[list[str]]
    extra: NotRequired[dict]


def drop_color_message_key(_: Any, __: Any, event_dict: EventDict) -> EventDict:
    """
    Drop the `color_message` key from the event dict if it exists.

    Uvicorn logs the message a second time in the extra `color_message`, but we don't need it.
    """
    event_dict.pop("color_message", None)
    return event_dict


def edit_event_name(_: Any, __: Any, event_dict: EventDict) -> EventDict:
    """Edit the event dict to change the event name, so we don't clobber elastic indices."""
    event = event_dict.pop("event")
    event_dict["message"] = event
    return event_dict


def tracer_injection(_: Any, __: Any, event_dict: EventDict) -> EventDict:
    """
    Inject the current trace and span ids into the event dictionary.

    This function gets called by `structlog` as a processor, and
    the logger and log_method are not used until called by structlog.
    """
    span = trace.get_current_span()
    if not span.is_recording():
        event_dict["span"] = None
        return event_dict

    ctx = span.get_span_context()
    parent = getattr(span, "parent", None)

    event_dict["span"] = {
        "span_id": format(ctx.span_id, "016x"),
        "trace_id": format(ctx.trace_id, "032x"),
        "parent_span_id": None if not parent else format(parent.span_id, "016x"),
    }

    return event_dict


class Logging(Generic[RendererType]):
    """
    Customized implementation inspired by the following documentation.

    https://www.structlog.org/en/stable/standard-library.html#rendering-using-structlog-based-formatters-within-logging
    """

    timestamper = structlog.processors.TimeStamper(fmt="iso")
    shared_processors: ClassVar[list[Callable]] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.PositionalArgumentsFormatter(),
        drop_color_message_key,
        tracer_injection,
        edit_event_name,
        timestamper,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.StackInfoRenderer(),
    ]
    addl_loggers: ClassVar[dict[str, LoggerConfig]] = {
        logger: {
            "handlers": [],
            "propagate": True,
        }
        for logger in [
            "uvicorn",
            "sqlalchemy",
            "arq",
        ]
    }

    @classmethod
    def get_processors(cls) -> list[Any]:
        """
        Retrieves and constructs a list of processors used for structlog logging.

        This method dynamically determines the appropriate processors for the current
        environment and ensures they are formatted correctly for logging. In production
        environments, additional processors may be included based on specific
        requirements.

        Returns:
            A list of processor instances used for structlog logging.
        """
        if settings.is_production:
            return [
                *cls.shared_processors,
                structlog.processors.format_exc_info,
                structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
            ]
        else:
            return [*cls.shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter]

    @classmethod
    def get_renderer(cls) -> RendererType:
        """Return the renderer for structlog logging based on the current environment."""
        raise NotImplementedError()

    @classmethod
    def configure_stdlib(cls) -> None:
        """Configure the standard Python logging module for structured logging."""
        level = settings.log_level

        processors = (
            [*cls.shared_processors, structlog.processors.format_exc_info]
            if settings.is_production
            else cls.shared_processors
        )
        loggers: dict[str, dict[str, Any]] = {
            "": {
                "handlers": ["default"],
                "level": level,
                "propagate": False,
            },
            **{logger: dict(config) for logger, config in cls.addl_loggers.items()},
        }

        logging.config.dictConfig(
            {
                "version": 1,
                "disable_existing_loggers": True,
                "formatters": {
                    "myLogger": {
                        "()": structlog.stdlib.ProcessorFormatter,
                        "processors": [
                            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                            cls.get_renderer(),
                        ],
                        "foreign_pre_chain": processors,
                    },
                },
                "handlers": {
                    "default": {
                        "level": level,
                        "class": "logging.StreamHandler",
                        "formatter": "myLogger",
                    },
                },
                "loggers": loggers,  # type: ignore[typeddict-item]
            }
        )

    @classmethod
    def configure_structlog(cls) -> None:
        """Configure structlog with the current settings."""
        structlog.configure_once(
            processors=cls.get_processors(),
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )

    @classmethod
    def configure(cls) -> None:
        """Configure structlog and standard Python logging for structured logging."""
        cls.configure_stdlib()
        cls.configure_structlog()


class Development(Logging[structlog.dev.ConsoleRenderer]):
    """The development logging configuration."""

    @classmethod
    def get_renderer(cls) -> structlog.dev.ConsoleRenderer:
        """Return the console renderer for the development environment."""
        return structlog.dev.ConsoleRenderer(colors=True)


class Production(Logging[structlog.processors.JSONRenderer]):
    """The production logging configuration."""

    addl_loggers: ClassVar[dict[str, LoggerConfig]] = {
        "uvicorn.access": {
            "handlers": [],
            "level": "WARNING",
            "propagate": False,
        }
    }

    @classmethod
    def get_renderer(cls) -> structlog.processors.JSONRenderer:
        """Return the JSON renderer for the production environment."""
        return structlog.processors.JSONRenderer()


def configure() -> None:
    """Configure structlog and standard Python logging for structured logging."""
    if settings.is_production:
        Production.configure()
    else:
        Development.configure()


def generate_correlation_id() -> str:
    """Generate a value that is unique for each request."""
    return str(uuid.uuid4())
