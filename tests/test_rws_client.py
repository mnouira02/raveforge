from unittest.mock import Mock, patch

import pytest
import requests

from raveforge.exceptions import RWSError
from raveforge.rws_client import RWSClient


def make_mock_response(status_code=200, text="<Response>Success</Response>"):
    response = Mock(spec=requests.Response)
    response.status_code = status_code
    response.text = text
    return response


# -------------------------------------------------------------------
# 1. Initialization
# -------------------------------------------------------------------


def test_client_initialization():
    """Validates the client stores configuration correctly."""
    client = RWSClient(
        base_url="https://innovate.mdsol.com/",
        username="user1",
        password="pass1",
        timeout=45,
    )

    assert client.base_url == "https://innovate.mdsol.com"
    assert client.timeout == 45
    assert client._session is not None


# -------------------------------------------------------------------
# 2. Successful ODM Submission
# -------------------------------------------------------------------


@patch("requests.Session.post")
def test_post_odm_success(mock_post):
    """Validates a successful ODM POST returns the raw response text."""
    mock_post.return_value = make_mock_response(
        status_code=200,
        text="<Response>Success</Response>",
    )

    client = RWSClient(
        base_url="https://innovate.mdsol.com",
        username="user",
        password="pass",
    )

    odm_bytes = b'<?xml version="1.0" encoding="UTF-8"?><ODM></ODM>'
    result = client.post_odm(odm_bytes)

    assert result == "<Response>Success</Response>"
    mock_post.assert_called_once()

    _, kwargs = mock_post.call_args
    assert kwargs["data"] == odm_bytes
    assert kwargs["timeout"] == 30


@patch("requests.Session.post")
def test_post_odm_success_with_custom_endpoint(mock_post):
    """Validates that a custom endpoint can be passed to post_odm()."""
    mock_post.return_value = make_mock_response(
        status_code=200,
        text="<Response>Custom Success</Response>",
    )

    client = RWSClient(
        base_url="https://innovate.mdsol.com",
        username="user",
        password="pass",
    )

    odm_bytes = b"<ODM />"
    endpoint = "/RaveWebServices/custom.aspx?PostODMClinicalData"
    result = client.post_odm(odm_bytes, endpoint=endpoint)

    assert result == "<Response>Custom Success</Response>"
    mock_post.assert_called_once()

    args, kwargs = mock_post.call_args
    assert args[0] == (
        "https://innovate.mdsol.com"
        "/RaveWebServices/custom.aspx?PostODMClinicalData"
    )
    assert kwargs["data"] == odm_bytes


# -------------------------------------------------------------------
# 3. HTTP Failure Handling
# -------------------------------------------------------------------


@patch("requests.Session.post")
def test_post_odm_raises_on_400(mock_post):
    """Validates HTTP 400 becomes RWSError with helpful message."""
    mock_post.return_value = make_mock_response(
        status_code=400,
        text="<Response><ErrorDescription>RWS00001</ErrorDescription></Response>",
    )

    client = RWSClient(
        base_url="https://innovate.mdsol.com",
        username="user",
        password="pass",
    )

    with pytest.raises(RWSError) as exc_info:
        client.post_odm(b"<ODM />")

    err = exc_info.value
    assert "Bad Request" in str(err)
    assert err.http_status == 400
    assert err.rws_code == "RWS00001"


@patch("requests.Session.post")
def test_post_odm_raises_on_401(mock_post):
    """Validates HTTP 401 becomes RWSError."""
    mock_post.return_value = make_mock_response(
        status_code=401,
        text="Unauthorized",
    )

    client = RWSClient(
        base_url="https://innovate.mdsol.com",
        username="bad_user",
        password="bad_pass",
    )

    with pytest.raises(RWSError) as exc_info:
        client.post_odm(b"<ODM />")

    err = exc_info.value
    assert "Unauthorised" in str(err)
    assert err.http_status == 401


@patch("requests.Session.post")
def test_post_odm_raises_on_403(mock_post):
    """Validates HTTP 403 becomes RWSError."""
    mock_post.return_value = make_mock_response(
        status_code=403,
        text="Forbidden",
    )

    client = RWSClient(
        base_url="https://innovate.mdsol.com",
        username="user",
        password="pass",
    )

    with pytest.raises(RWSError) as exc_info:
        client.post_odm(b"<ODM />")

    err = exc_info.value
    assert "Forbidden" in str(err)
    assert err.http_status == 403


@patch("requests.Session.post")
def test_post_odm_raises_on_404(mock_post):
    """Validates HTTP 404 becomes RWSError."""
    mock_post.return_value = make_mock_response(
        status_code=404,
        text="Not Found",
    )

    client = RWSClient(
        base_url="https://innovate.mdsol.com",
        username="user",
        password="pass",
    )

    with pytest.raises(RWSError) as exc_info:
        client.post_odm(b"<ODM />")

    err = exc_info.value
    assert "Not Found" in str(err)
    assert err.http_status == 404


@patch("requests.Session.post")
def test_post_odm_raises_on_409(mock_post):
    """Validates HTTP 409 becomes RWSError."""
    mock_post.return_value = make_mock_response(
        status_code=409,
        text="<Response><ErrorDescription>RWS00037</ErrorDescription></Response>",
    )

    client = RWSClient(
        base_url="https://innovate.mdsol.com",
        username="user",
        password="pass",
    )

    with pytest.raises(RWSError) as exc_info:
        client.post_odm(b"<ODM />")

    err = exc_info.value
    assert "Conflict" in str(err)
    assert err.http_status == 409
    assert err.rws_code == "RWS00037"


@patch("requests.Session.post")
def test_post_odm_raises_on_unexpected_http_status(mock_post):
    """Validates unknown HTTP errors still raise RWSError."""
    mock_post.return_value = make_mock_response(
        status_code=500,
        text="Internal Server Error",
    )

    client = RWSClient(
        base_url="https://innovate.mdsol.com",
        username="user",
        password="pass",
    )

    with pytest.raises(RWSError) as exc_info:
        client.post_odm(b"<ODM />")

    err = exc_info.value
    assert "Unexpected HTTP 500" in str(err)
    assert err.http_status == 500


# -------------------------------------------------------------------
# 4. RWS Error Hidden Inside HTTP 200
# -------------------------------------------------------------------


@patch("requests.Session.post")
def test_post_odm_raises_when_rws_error_is_embedded_in_200(mock_post):
    """Validates a 200 with IsTransactionSuccessful=false is treated as failure."""
    mock_post.return_value = make_mock_response(
        status_code=200,
        text=(
            '<Response ReferenceNumber="123" '
            'ErrorClientResponseMessage="RWS00037">'
            '<IsTransactionSuccessful>false</IsTransactionSuccessful>'
            '</Response>'
        ),
    )

    client = RWSClient(
        base_url="https://innovate.mdsol.com",
        username="user",
        password="pass",
    )

    with pytest.raises(RWSError) as exc_info:
        client.post_odm(b"<ODM />")

    err = exc_info.value
    assert "RWS returned an error in a 200 response" in str(err)
    assert err.http_status == 200
    assert err.rws_code == "RWS00037"


@patch("requests.Session.post")
def test_post_odm_success_body_word_error_does_not_raise(mock_post):
    """Validates a 200 body with 'Error' in non-failure context does not raise."""
    mock_post.return_value = make_mock_response(
        status_code=200,
        text='<Response ReferenceNumber="abc">No errors reported.</Response>',
    )

    client = RWSClient(
        base_url="https://innovate.mdsol.com",
        username="user",
        password="pass",
    )

    result = client.post_odm(b"<ODM />")
    assert "No errors reported" in result


# -------------------------------------------------------------------
# 5. Network Exceptions
# -------------------------------------------------------------------


@patch("requests.Session.post")
def test_post_odm_timeout_raises_rwserror(mock_post):
    """Validates request timeout is converted into RWSError."""
    mock_post.side_effect = requests.exceptions.Timeout

    client = RWSClient(
        base_url="https://innovate.mdsol.com",
        username="user",
        password="pass",
        timeout=5,
    )

    with pytest.raises(RWSError) as exc_info:
        client.post_odm(b"<ODM />")

    assert "timed out" in str(exc_info.value).lower()


@patch("requests.Session.post")
def test_post_odm_connection_error_raises_rwserror(mock_post):
    """Validates connection failure is converted into RWSError."""
    mock_post.side_effect = requests.exceptions.ConnectionError("Connection refused")

    client = RWSClient(
        base_url="https://innovate.mdsol.com",
        username="user",
        password="pass",
    )

    with pytest.raises(RWSError) as exc_info:
        client.post_odm(b"<ODM />")

    assert "Connection failed" in str(exc_info.value)


# -------------------------------------------------------------------
# 6. RWS Code Extraction
# -------------------------------------------------------------------


def test_extract_rws_code_from_error_client_response_message():
    """Validates extraction from ErrorClientResponseMessage attribute."""
    body = '<Response ErrorClientResponseMessage="RWS00024"></Response>'
    code = RWSClient._extract_rws_code(body)
    assert code == "RWS00024"


def test_extract_rws_code_from_error_description():
    """Validates extraction from ErrorDescription element."""
    body = "<Response><ErrorDescription>RWS00099</ErrorDescription></Response>"
    code = RWSClient._extract_rws_code(body)
    assert code == "RWS00099"


def test_extract_rws_code_returns_none_when_missing():
    """Validates None is returned when no error code is present."""
    body = "<Response>Success</Response>"
    code = RWSClient._extract_rws_code(body)
    assert code is None


# -------------------------------------------------------------------
# 7. Ping
# -------------------------------------------------------------------


@patch("requests.Session.get")
def test_ping_returns_true_on_200(mock_get):
    """Validates ping succeeds when endpoint is reachable."""
    mock_get.return_value = make_mock_response(status_code=200, text="OK")

    client = RWSClient(
        base_url="https://innovate.mdsol.com",
        username="user",
        password="pass",
    )

    assert client.ping() is True


@patch("requests.Session.get")
def test_ping_returns_true_on_401(mock_get):
    """Validates ping returns True when reachable but credentials not validated."""
    mock_get.return_value = make_mock_response(status_code=401, text="Unauthorized")

    client = RWSClient(
        base_url="https://innovate.mdsol.com",
        username="user",
        password="pass",
    )

    assert client.ping() is True


@patch("requests.Session.get")
def test_ping_returns_false_on_request_exception(mock_get):
    """Validates ping returns False when the network call fails."""
    mock_get.side_effect = requests.exceptions.RequestException("DNS failure")

    client = RWSClient(
        base_url="https://innovate.mdsol.com",
        username="user",
        password="pass",
    )

    assert client.ping() is False
