"""Tests for CLI behavior when the daemon is not running."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from lexaloud import cli


def test_post_to_daemon_connection_refused_exits_3():
    """When the daemon is down, the CLI must exit with EXIT_DAEMON_DOWN=3."""

    def _raise_connect(*args, **kwargs):
        raise httpx.ConnectError("refused")

    with patch("httpx.Client") as mock_client:
        instance = mock_client.return_value.__enter__.return_value
        instance.post.side_effect = _raise_connect
        with patch("lexaloud.cli.try_notify"):  # swallow notify
            with pytest.raises(SystemExit) as ei:
                cli._post_to_daemon("/speak", {"text": "hi"})
    assert ei.value.code == cli.EXIT_DAEMON_DOWN


def test_get_from_daemon_connect_timeout_exits_3():
    with patch("httpx.Client") as mock_client:
        instance = mock_client.return_value.__enter__.return_value
        instance.get.side_effect = httpx.ConnectTimeout("timeout")
        with patch("lexaloud.cli.try_notify"):
            with pytest.raises(SystemExit) as ei:
                cli._get_from_daemon("/state")
    assert ei.value.code == cli.EXIT_DAEMON_DOWN


def test_post_413_exits_oversized():
    mock_response = httpx.Response(status_code=413, text="too large")
    with patch("httpx.Client") as mock_client:
        instance = mock_client.return_value.__enter__.return_value
        instance.post.return_value = mock_response
        with patch("lexaloud.cli.try_notify"):
            with pytest.raises(SystemExit) as ei:
                cli._post_to_daemon("/speak", {"text": "x" * 10})
    assert ei.value.code == cli.EXIT_OVERSIZED


def test_post_500_exits_generic_error():
    mock_response = httpx.Response(status_code=500, text="internal")
    with patch("httpx.Client") as mock_client:
        instance = mock_client.return_value.__enter__.return_value
        instance.post.return_value = mock_response
        with pytest.raises(SystemExit) as ei:
            cli._post_to_daemon("/speak", {"text": "hi"})
    assert ei.value.code == cli.EXIT_GENERIC_ERROR


def test_post_200_returns_json():
    mock_response = httpx.Response(status_code=200, json={"state": "speaking"})
    with patch("httpx.Client") as mock_client:
        instance = mock_client.return_value.__enter__.return_value
        instance.post.return_value = mock_response
        result = cli._post_to_daemon("/speak", {"text": "hi"})
    assert result == {"state": "speaking"}
