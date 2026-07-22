from __future__ import annotations

import logging
import re
from typing import Optional

import requests
from requests.auth import HTTPBasicAuth

from .exceptions import RWSError

# Rave returns an HTTP 200 with the HTML login page when credentials are
# invalid or the session has expired.  Detect this by looking for the
# characteristic <form> action that Rave always uses on its login page.
_LOGIN_PAGE_MARKERS = (
    "Login.aspx",
    "UserLoginBox",
    "Medidata Classic Rave",
)

logger = logging.getLogger(__name__)


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
            The raw RWS response body as a string (BOM-stripped).

        Raises:
            RWSError: On HTTP errors or RWS-level error responses.
        """
        url = f"{self.base_url}{endpoint}"
        logger.debug("POST %s", url)
        try:
            response = self._session.post(url, data=odm_bytes, timeout=self.timeout)
        except requests.exceptions.Timeout:
            raise RWSError(f"Request timed out after {self.timeout}s.")
        except requests.exceptions.ConnectionError as exc:
            raise RWSError(f"Connection failed: {exc}")
        logger.debug("Response HTTP %s — %d bytes", response.status_code, len(response.content))
        return self._handle_response(response)

    def get_studies_raw(
        self,
        endpoint: str = "/RaveWebServices/studies",
    ) -> str:
        """
        Retrieve the raw ODM XML listing of studies accessible to the
        authenticated user.

        Returns BOM-stripped XML so callers can pass directly to
        ``ET.fromstring`` without a ``ParseError``.

        Raises:
            RWSError: On HTTP errors, auth failures, or network failures.
        """
        url = f"{self.base_url}{endpoint}"
        logger.debug("GET %s", url)
        try:
            response = self._session.get(url, timeout=self.timeout)
        except requests.exceptions.Timeout:
            raise RWSError(f"Request timed out after {self.timeout}s.")
        except requests.exceptions.ConnectionError as exc:
            raise RWSError(f"Connection failed: {exc}")
        logger.debug(
            "get_studies_raw: HTTP %s — %d bytes",
            response.status_code,
            len(response.content),
        )
        return self._handle_response(response)

    def get_sites_raw(
        self,
        study_oid: str,
    ) -> str:
        """
        Retrieve the raw ODM XML listing of sites for a given study.

        Uses the RWS **ODM Adapter SitesMetadata** endpoint::

            GET /RaveWebServices/datasets/Sites.odm/?studyoid={project_name}({environment_name})

        The study OID (e.g. ``Mediflex(Dev)``) is passed as the ``studyoid``
        query-string parameter.  ``requests`` percent-encodes it automatically
        so the parentheses become ``%28`` / ``%29`` as RWS expects.

        Returns an ODM ``<AdminData>`` document listing every active site and
        its metadata-version assignments for the study.

        Returns:
            BOM-stripped XML suitable for ``ET.fromstring``.

        Raises:
            RWSError: On HTTP errors, auth failures, or network failures.

        Reference:
            https://rwslib.readthedocs.io/en/latest/odm_adapter.html#sitesmetadatarequest
        """
        url = f"{self.base_url}/RaveWebServices/datasets/Sites.odm/"
        logger.debug("GET %s?studyoid=%s", url, study_oid)
        try:
            response = self._session.get(
                url,
                params={"studyoid": study_oid},
                timeout=self.timeout,
            )
        except requests.exceptions.Timeout:
            raise RWSError(f"Request timed out after {self.timeout}s.")
        except requests.exceptions.ConnectionError as exc:
            raise RWSError(f"Connection failed: {exc}")
        logger.debug(
            "get_sites_raw (oid=%r): HTTP %s — %d bytes",
            study_oid,
            response.status_code,
            len(response.content),
        )
        return self._handle_response(response)

    def ping(self) -> bool:
        """
        Verify RWS connectivity by calling the version endpoint.

        Returns ``True`` if the server responds with 200 or 401 (reachable
        but credentials not yet validated). Returns ``False`` on any network
        failure or if a login-page redirect is returned.
        """
        try:
            url = f"{self.base_url}/RaveWebServices/webservice.aspx?GetVersion"
            r = self._session.get(url, timeout=self.timeout)
            if r.status_code == 401:
                return True
            if r.status_code == 200:
                r.encoding = "utf-8-sig"
                return not self._is_login_page(r.text)
            return False
        except requests.exceptions.RequestException:
            return False

    def _handle_response(self, response: requests.Response) -> str:
        # RWS always prepends a UTF-8 BOM (0xEF 0xBB 0xBF) to every XML
        # response body.  When the HTTP Content-Type header omits a charset
        # (or specifies something other than utf-8), requests auto-detects the
        # encoding as latin-1 and decodes the 3-byte BOM into the three
        # characters ï»¿ rather than the single unicode character \ufeff.
        # A subsequent lstrip("\ufeff") then does nothing, and ET.fromstring()
        # raises ParseError: not well-formed (invalid token).
        #
        # Forcing utf-8-sig — Python's codec that decodes UTF-8 *and* strips
        # the BOM atomically — makes BOM removal unconditional and independent
        # of whatever encoding the HTTP headers advertise.
        response.encoding = "utf-8-sig"
        body = response.text

        if response.status_code == 200:
            # Rave sometimes returns a 200 with the HTML login page when
            # credentials are wrong or the session has expired.
            if self._is_login_page(body):
                raise RWSError(
                    "Unauthorised — RWS redirected to the login page. "
                    "Check your username and password.",
                    http_status=401,
                )
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
        message = rws_messages.get(
            response.status_code, f"Unexpected HTTP {response.status_code}."
        )
        rws_code = self._extract_rws_code(body)
        raise RWSError(message, rws_code=rws_code, http_status=response.status_code)

    @staticmethod
    def _is_login_page(body: str) -> bool:
        """Return True if the response body looks like the Rave HTML login page."""
        return any(marker in body for marker in _LOGIN_PAGE_MARKERS)

    @staticmethod
    def _extract_rws_code(body: str) -> Optional[str]:
        match = re.search(r'ErrorClientResponseMessage="([^"]+)"', body)
        if match:
            return match.group(1)
        match = re.search(r"<ErrorDescription>(.*?)</ErrorDescription>", body)
        if match:
            return match.group(1)
        return None
