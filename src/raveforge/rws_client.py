from __future__ import annotations
import re
import requests
from requests.auth import HTTPBasicAuth
from typing import Optional

from .exceptions import RWSError


class RWSClient:
    """
    Thin HTTP client for submitting ODM XML to Medidata Rave Web Services (RWS).

    Usage::

        client = RWSClient(
            base_url="https://yourdomain.mdsol.com",
            username="svc_account",
            password="secret",
        )
        response_text = client.post_odm(odm_bytes)
    """

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        timeout: int = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth = HTTPBasicAuth(username, password)
        self.timeout = timeout
        self._session = requests.Session()
        self._session.auth = self.auth
        self._session.headers.update({
            "Content-Type": "text/xml;charset=UTF-8",
            "Accept": "text/xml",
        })

    def post_odm(
        self,
        odm_bytes: bytes,
        endpoint: str = "/RaveWebServices/webservice.aspx?PostODMClinicalData",
    ) -> str:
        """
        POST an ODM XML payload to Rave RWS.

        Args:
            odm_bytes: The serialised ODM XML from :meth:`RaveTransaction.build`.
            endpoint:  RWS endpoint path (default: PostODMClinicalData).

        Returns:
            The raw RWS response body as a string.

        Raises:
            RWSError: On HTTP errors or RWS-level error responses.
        """
        url = f"{self.base_url}{endpoint}"
        try:
            response = self._session.post(url, data=odm_bytes, timeout=self.timeout)
        except requests.exceptions.Timeout:
            raise RWSError(f"Request timed out after {self.timeout}s.")
        except requests.exceptions.ConnectionError as exc:
            raise RWSError(f"Connection failed: {exc}")
        return self._handle_response(response)

    def get_studies_raw(
        self,
        endpoint: str = "/RaveWebServices/studies",
    ) -> str:
        """
        Retrieve the raw ODM XML listing of studies accessible to the
        authenticated user. Used by :class:`RaveDiagnostics` for read-only
        study-name comparison. Does not modify any data.

        Raises:
            RWSError: On HTTP errors or network failures.
        """
        url = f"{self.base_url}{endpoint}"
        try:
            response = self._session.get(url, timeout=self.timeout)
        except requests.exceptions.Timeout:
            raise RWSError(f"Request timed out after {self.timeout}s.")
        except requests.exceptions.ConnectionError as exc:
            raise RWSError(f"Connection failed: {exc}")
        if response.status_code != 200:
            raise RWSError(
                f"Failed to retrieve study list (HTTP {response.status_code}).",
                http_status=response.status_code,
            )
        return response.text

    def ping(self) -> bool:
        """
        Verify RWS connectivity by calling the version endpoint.

        Returns ``True`` if the server responds with 200 or 401 (reachable
        but credentials not yet validated). Returns ``False`` on any network
        failure.
        """
        try:
            url = f"{self.base_url}/RaveWebServices/webservice.aspx?GetVersion"
            r = self._session.get(url, timeout=self.timeout)
            return r.status_code in (200, 401)
        except requests.exceptions.RequestException:
            return False

    def _handle_response(self, response: requests.Response) -> str:
        body = response.text

        if response.status_code == 200:
            # RWS sometimes wraps a transaction failure in an HTTP 200 response.
            # The canonical signal is IsTransactionSuccessful set to false.
            if "<IsTransactionSuccessful>false</IsTransactionSuccessful>" in body:
                rws_code = self._extract_rws_code(body)
                raise RWSError(
                    f"RWS returned an error in a 200 response: {body[:300]}",
                    rws_code=rws_code,
                    http_status=200,
                )
            return body

        rws_messages = {
            400: "Bad Request — malformed ODM XML.",
            401: "Unauthorised — check credentials.",
            403: "Forbidden — insufficient RWS permissions.",
            404: "Not Found — check study OID or endpoint URL.",
            409: "Conflict — transaction violates study configuration.",
        }
        message = rws_messages.get(response.status_code, f"Unexpected HTTP {response.status_code}.")
        rws_code = self._extract_rws_code(body)
        raise RWSError(message, rws_code=rws_code, http_status=response.status_code)

    @staticmethod
    def _extract_rws_code(body: str) -> Optional[str]:
        match = re.search(r'ErrorClientResponseMessage="([^"]+)"', body)
        if match:
            return match.group(1)
        match = re.search(r'<ErrorDescription>(.*?)</ErrorDescription>', body)
        if match:
            return match.group(1)
        return None
