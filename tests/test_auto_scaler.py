import pytest
import requests
from unittest.mock import patch, MagicMock
import sys, os


# Patch sys.argv BEFORE importing auto_scaler so startup() won't sys.exit
def _prepare_config_file():
    import tempfile
    import textwrap
    tmpdir = tempfile.mkdtemp()
    config_path = os.path.join(tmpdir, "config.yaml")
    with open(config_path, "w") as f:
        f.write(textwrap.dedent("""\
            base_url: http://localhost
            cpu_threshold: 0.5
            scale_up_step: 1
            scale_down_step: 1
            poll_interval: 1
            tasks:
              - name: auto_scaler_get_status
                request:
                  method: GET
                  endpoint: /status
              - name: auto_scaler_update_replicas
                request:
                  method: POST
                  endpoint: /update
        """))
    return config_path

sys.argv = ["auto_scaler.py", "--config", _prepare_config_file()]

from app import auto_scaler  # Now safe to import


def test_parse_response_with_json():
    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": "application/json"}
    mock_resp.text = '{"key": "value"}'
    mock_resp.json.return_value = {"key": "value"}

    status_code, headers, raw, json_body = auto_scaler.parse_response(mock_resp)

    assert status_code == 200
    assert headers["Content-Type"] == "application/json"
    assert raw == '{"key": "value"}'
    assert json_body == {"key": "value"}


def test_parse_response_with_invalid_json():
    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 200
    mock_resp.headers = {}
    mock_resp.text = "not-json"
    mock_resp.json.side_effect = ValueError("Invalid JSON")

    status_code, headers, raw, json_body = auto_scaler.parse_response(mock_resp)

    assert status_code == 200
    assert headers == {}
    assert raw == "not-json"
    assert json_body is None


def test_make_request_success():
    task = {
        "request": {
            "method": "GET",
            "endpoint": "/test",
            "headers": {"X-Test": "1"},
        }
    }
    auto_scaler.BASE_URL = "http://localhost"

    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"ok": True}
    mock_resp.text = '{"ok": true}'
    mock_resp.headers = {"Content-Type": "application/json"}
    mock_resp.raise_for_status.return_value = None

    with patch("requests.request", return_value=mock_resp) as mock_request:
        result = auto_scaler.make_request(task)

    mock_request.assert_called_once_with(
        method="GET",
        url="http://localhost/test",
        headers={"X-Test": "1"},
        json=None,
        timeout=5,
    )
    assert result == {"ok": True}


def test_make_request_http_error():
    task = {
        "request": {
            "method": "POST",
            "endpoint": "/fail",
            "headers": {},
        }
    }
    auto_scaler.BASE_URL = "http://localhost"

    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 500
    mock_resp.json.return_value = {"error": "server error"}
    mock_resp.text = '{"error": "server error"}'
    mock_resp.headers = {}
    mock_resp.raise_for_status.side_effect = requests.RequestException("Server Error")

    with patch("requests.request", return_value=mock_resp):
        result = auto_scaler.make_request(task)

    assert result is None


def test_make_request_connection_error():
    task = {
        "request": {
            "method": "GET",
            "endpoint": "/unreachable",
        }
    }
    auto_scaler.BASE_URL = "http://localhost"

    with patch("requests.request", side_effect=requests.RequestException("Network fail")):
        result = auto_scaler.make_request(task)

    assert result is None


def test_find_task_found():
    tasks = [
        {"name": "abc"},
        {"name": "mytask123"},
    ]
    config = {"tasks": tasks}
    auto_scaler.config = config

    assert auto_scaler.find_task("mytask") == {"name": "mytask123"}


def test_find_task_not_found():
    auto_scaler.config = {"tasks": [{"name": "a"}]}
    with pytest.raises(KeyError):
        auto_scaler.find_task("nope")
