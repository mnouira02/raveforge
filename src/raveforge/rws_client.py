from __future__ import annotations

import logging
import re
from typing import Optional, Union

import requests
from requests.auth import HTTPBasicAuth

from .core import RaveTransaction
from .exceptions import RWSError

_LOGIN_PAGE_MARKERS = (
    "Login.aspx",
    "UserLoginBox",
    "Medidata Classic Rave",
)

logger = logging.getLogger(__name__)


class RWSClient:
    """
    Thin HTTP client for submitting ODM XML to Medidata Rave Web Services.

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
        self._session.headers.update({"Accept": "text/xml"})

    def post_odm(
        self,
        transaction_or_xml: Union[RaveTransaction, str, bytes],
        endpoint: str = "/RaveWebServices/webservice.aspx?PostODMClinicalData",
    ) -> str:
        """Submit ODM XML to RWS and return the raw response text."""
        if isinstance(transaction_or_xml, RaveTransaction):
            odm_bytes = transaction_or_xml.build()
        elif isinstance(transaction_or_xml, str):
            odm_bytes = transaction_or_xml.encode("utf-8")
        elif isinstance(transaction_or_xml, bytes):
            odm_bytes = transaction_or_xml
        else:
            raise ValueError("Payload must be a RaveTransaction, str, or bytes.")

        url = f"{self.base_url}{endpoint}"
        logger.debug("POST %s", url)

        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "Accept": "text/xml",
        }

        try:
            response = self._session.post(
                url,
                data=odm_bytes,
                headers=headers,
                timeout=self.timeout,
            )
        except requests.exceptions.Timeout as exc:
            raise RWSError(f"Request timed out after {self.timeout}s.") from exc
        except requests.exceptions.ConnectionError as exc:
            raise RWSError(f"Connection failed: {exc}") from exc
        except requests.exceptions.RequestException as exc:
            raise RWSError(f"Request failed: {exc}") from exc

        logger.debug(
            "Response HTTP %s — %d bytes",
            response.status_code,
            len(response.content),
        )
        return self._handle_response(response)

    def get_studies_raw(
        self,
        endpoint: str = "/RaveWebServices/studies",
    ) -> str:
        """Retrieve the raw studies XML."""
        url = f"{self.base_url}{endpoint}"
        logger.debug("GET %s", url)

        try:
            response = self._session.get(url, timeout=self.timeout)
        except requests.exceptions.Timeout as exc:
            raise RWSError(f"Request timed out after {self.timeout}s.") from exc
        except requests.exceptions.ConnectionError as exc:
            raise RWSError(f"Connection failed: {exc}") from exc
        except requests.exceptions.RequestException as exc:
            raise RWSError(f"Request failed: {exc}") from exc

        logger.debug(
            "get_studies_raw: HTTP %s — %d bytes",
            response.status_code,
            len(response.content),
        )
        return self._handle_response(response)

    def get_sites_raw(self, study_oid: str) -> str:
        """Retrieve the raw ODM XML listing of sites for a given study."""
        url = f"{self.base_url}/RaveWebServices/datasets/Sites.odm/"
        logger.debug("get_sites_raw: GET %s?studyoid=%s", url, study_oid)

        try:
            response = self._session.get(
                url,
                params={"studyoid": study_oid},
                timeout=self.timeout,
            )
        except requests.exceptions.Timeout as exc:
            raise RWSError(f"Request timed out after {self.timeout}s.") from exc
        except requests.exceptions.ConnectionError as exc:
            raise RWSError(f"Connection failed: {exc}") from exc
        except requests.exceptions.RequestException as exc:
            raise RWSError(f"Request failed: {exc}") from exc

        logger.debug(
            "get_sites_raw: HTTP %s — %d bytes",
            response.status_code,
            len(response.content),
        )
        return self._handle_response(response)

    def get_subjects_raw(self, study_oid: str) -> str:
        """Retrieve the raw ODM XML listing of subjects for a given study."""
        url = f"{self.base_url}/RaveWebServices/studies/{study_oid}/subjects"
        logger.debug("get_subjects_raw: GET %s", url)

        try:
            response = self._session.get(url, timeout=self.timeout)
        except requests.exceptions.Timeout as exc:
            raise RWSError(f"Request timed out after {self.timeout}s.") from exc
        except requests.exceptions.ConnectionError as exc:
            raise RWSError(f"Connection failed: {exc}") from exc
        except requests.exceptions.RequestException as exc:
            raise RWSError(f"Request failed: {exc}") from exc

        logger.debug(
            "get_subjects_raw: HTTP %s — %d bytes",
            response.status_code,
            len(response.content),
        )
        return self._handle_response(response)

    def ping(self) -> bool:
        """Check whether the RWS endpoint appears reachable."""
        try:
            url = f"{self.base_url}/RaveWebServices/webservice.aspx?GetVersion"
            response = self._session.get(url, timeout=self.timeout)

            if response.status_code == 401:
                return True

            if response.status_code == 200:
                response.encoding = "utf-8-sig"
                return not self._is_login_page(response.text)

            return False
        except requests.exceptions.RequestException:
            return False

    def _handle_response(self, response: requests.Response) -> str:
        """Convert an HTTP response into text or RWSError."""
        response.encoding = "utf-8-sig"
        body = response.text

        if response.status_code == 200:
            if self._is_login_page(body):
                raise RWSError(
                    "Unauthorised — RWS redirected to the login page. "
                    "Check your username and password.",
                    http_status=401,
                )

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
        message = rws_messages.get(
            response.status_code,
            f"Unexpected HTTP {response.status_code}.",
        )
        rws_code = self._extract_rws_code(body)
        raise RWSError(
            message,
            rws_code=rws_code,
            http_status=response.status_code,
        )

    @staticmethod
    def _is_login_page(body: str) -> bool:
        """Return True if the body looks like an RWS login page."""
        return any(marker in body for marker in _LOGIN_PAGE_MARKERS)

    @staticmethod
    def _extract_rws_code(body: str) -> Optional[str]:
        """Extract an RWS error code from the response body when present."""
        match = re.search(r'ErrorClientResponseMessage="([^"]+)"', body)
        if match:
            return match.group(1)

        match = re.search(r"<ErrorDescription>(.*?)</ErrorDescription>", body)
        if match:
            return match.group(1)

        return None
