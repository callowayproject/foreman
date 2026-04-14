"""Tests for the logging_info module."""

from unittest.mock import patch

import pytest
import structlog

from foreman.logging_info import (
    Development,
    Logging,  # Import the Logging class for testing get_processors
    Production,
    configure,
    drop_color_message_key,
    edit_event_name,
    tracer_injection,
)


class TestConfigure:
    """Test the configure function."""

    @patch("foreman.logging_info.settings")
    def test_calls_dev_config_in_nonprod_env(self, mock_settings):
        """If the settings say we are in a non-prod environment, configure_development should be called."""
        # Assemble
        mock_settings.is_production = False
        with (
            patch.object(Development, "configure_stdlib") as mock_configure_stdlib,
            patch.object(Development, "configure_structlog") as mock_configure_structlog,
        ):
            # Act
            configure()

            # Assert
            mock_configure_stdlib.assert_called_once()
            mock_configure_structlog.assert_called_once()

    @patch("foreman.logging_info.settings")
    def test_calls_prod_config_in_prod_env(self, mock_settings):
        """If the settings say we are in a prod environment, configure_production should be called."""
        # Assemble
        mock_settings.is_production = True
        with (
            patch.object(Production, "configure_stdlib") as mock_configure_stdlib,
            patch.object(Production, "configure_structlog") as mock_configure_structlog,
        ):
            # Act
            configure()

            # Assert
            mock_configure_stdlib.assert_called_once()
            mock_configure_structlog.assert_called_once()


class TestDropColorMessageKey:
    """Tests for the drop_color_message_key function."""

    def test_removes_color_message_key(self):
        """Test that the color_message key is removed if it exists."""
        # Assemble
        event_dict = {"color_message": "some value", "extra_key": "extra value"}

        # Act
        result = drop_color_message_key(None, None, event_dict)

        # Assert
        assert "color_message" not in result
        assert result == {"extra_key": "extra value"}

    def test_no_color_message_key(self):
        """Test that the function does nothing if color_message key is not present."""
        # Assemble
        event_dict = {"extra_key": "extra value"}

        # Act
        result = drop_color_message_key(None, None, event_dict)

        # Assert
        assert result == {"extra_key": "extra value"}


class TestEditEventName:
    """Tests for the edit_event_name function."""

    def test_edit_event_name_changes_event_to_message(self):
        """Test that the `event` key is replaced with `message` in the event dictionary."""
        # Assemble
        event_dict = {"event": "some_event", "extra_key": "extra value"}

        # Act
        result = edit_event_name(None, None, event_dict)

        # Assert
        assert "event" not in result
        assert result["message"] == "some_event"
        assert result["extra_key"] == "extra value"

    def test_edit_event_name_no_event_key(self):
        """Test that the function raises a KeyError if `event` key is missing."""
        # Assemble
        event_dict = {"extra_key": "extra value"}

        # Act & Assert
        with pytest.raises(KeyError):
            edit_event_name(None, None, event_dict)


class TestGetProcessors:
    """Tests for the get_processors method."""

    @patch("foreman.logging_info.settings")
    def test_get_processors_in_production_env(self, mock_settings):
        """Test that get_processors includes production-specific processors in a production environment."""
        # Assemble
        mock_settings.is_production = True

        # Act
        processors = Logging.get_processors()

        # Assert
        assert structlog.processors.format_exc_info in processors
        assert structlog.stdlib.ProcessorFormatter.wrap_for_formatter in processors

    @patch("foreman.logging_info.settings")
    def test_get_processors_in_non_production_env(self, mock_settings):
        """Test that get_processors includes only general processors in a non-production environment."""
        # Assemble
        mock_settings.is_production = False

        # Act
        processors = Logging.get_processors()

        # Assert
        assert structlog.processors.format_exc_info not in processors
        assert structlog.stdlib.ProcessorFormatter.wrap_for_formatter in processors


class TestTracerInjection:
    """Tests for the tracer_injection function."""

    @patch("foreman.logging_info.trace")
    def test_tracer_injection_with_active_span(self, mock_trace):
        """Test that trace and span IDs are injected when a span is active."""
        # Assemble
        mock_span = mock_trace.get_current_span.return_value
        mock_span.is_recording.return_value = True
        mock_span_context = mock_span.get_span_context.return_value
        mock_span_context.span_id = 123456
        mock_span_context.trace_id = 654321
        mock_span.parent.span_id = 111111

        event_dict = {}

        # Act
        result = tracer_injection(None, None, event_dict)

        # Assert
        assert "span" in result
        assert result["span"]["span_id"] == "000000000001e240"
        assert result["span"]["trace_id"] == "0000000000000000000000000009fbf1"
        assert result["span"]["parent_span_id"] == "000000000001b207"

    @patch("foreman.logging_info.trace")
    def test_tracer_injection_without_active_span(self, mock_trace):
        """Test that the span value is set to None when there is no active span."""
        # Assemble
        mock_span = mock_trace.get_current_span.return_value
        mock_span.is_recording.return_value = False

        event_dict = {}

        # Act
        from foreman.logging_info import tracer_injection

        result = tracer_injection(None, None, event_dict)

        # Assert
        assert "span" in result
        assert result["span"] is None
