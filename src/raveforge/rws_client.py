from __future__ import annotations

import logging
import re
from typing import Optional, Tuple

import requests
from requests.auth import HTTPBasicAuth

from .exceptions import RWSError

_LOGIN_PAGE_MARKERS = (
    "Login.aspx",
    "UserLoginBox",
    "Medidata Classic Rave",
)

# Matches OIDs of the form  ProjectName(EnvironmentName)
_OID_RE = re.compile(r"^(.+?)\((.+)\)$")

logger = logging.getLogger(__name__)


def _parse_study_oid(study_oid: str) -> Tuple[str, str]:
    """
    Split a Rave study OID into ``(project_name, environment_name)``.

    rwslib's ``SitesMetadataRequest`` and ``StudySubjectsRequest`` are both
    defined with separate ``project_name`` / ``environment_name`` parameters::

        SitesMetadataRequest(project_name=None, environment_name=None)
        StudySubjectsRequest(project_name, environment_name)

    so the OID ``Mediflex(Dev)`` must be parsed into
    ``project_name="Mediflex"`` and ``environment_name="Dev"`` before use.

    Raises:
        RWSError: If the OID does not match the expected ``Project(Env)`` format.
    """
    m = _OID_RE.match(study_oid)
    if not m:
        raise RWSError(
            f"Invalid study OID {study_oid!r}. "
            "Expected format: ProjectName(EnvironmentName), e.g. Mediflex(Dev)."
        )
    return m.group(1), m.group(2)


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
        url = f"{self.base_url}{endpoint}"
        logger.debug("POST %s", url)
        try:
            response = self._session.post(url, data=odm_bytes, timeout=self.timeout)
        except requests.exceptions.Timeout:
            raise RWSError(f"Request timed out after {self.timeout}s.")
        except requests.exceptions.ConnectionError as exc:
            raise RWSError(f"Connection failed: {exc}")
        logger.debug("Response HTTP %s \u2014 %d bytes", response.status_code, len(response.content))
        return self._handle_response(response)

    def get_studies_raw(
        self,
        endpoint: str = "/RaveWebServices/studies",
    ) -> str:
        url = f"{self.base_url}{endpoint}"
        logger.debug("GET %s", url)
        try:
            response = self._session.get(url, timeout=self.timeout)
        except requests.exceptions.Timeout:
            raise RWSError(f"Request timed out after {self.timeout}s.")
        except requests.exceptions.ConnectionError as exc:
            raise RWSError(f"Connection failed: {exc}")
        logger.debug(
            "get_studies_raw: HTTP %s \u2014 %d bytes",
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

        Mirrors ``rwslib.rws_requests.odm_adapter.SitesMetadataRequest``::

            SitesMetadataRequest(project_name=None, environment_name=None)

        Calls::

            GET /RaveWebServices/datasets/Sites.odm/?studyoid={project}({env})

        Ref: https://rwslib.readthedocs.io/en/latest/odm_adapter.html
        """
        project_name, environment_name = _parse_study_oid(study_oid)
        studyoid_param = f"{project_name}({environment_name})"
        url = f"{self.base_url}/RaveWebServices/datasets/Sites.odm/"
        logger.debug(
            "get_sites_raw: project=%r env=%r \u2192 GET %s?studyoid=%s",
            project_name,
            environment_name,
            url,
            studyoid_param,
        )
        try:
            response = self._session.get(
                url,
                params={"studyoid": studyoid_param},
                timeout=self.timeout,
            )
        except requests.exceptions.Timeout:
            raise RWSError(f"Request timed out after {self.timeout}s.")
        except requests.exceptions.ConnectionError as exc:
            raise RWSError(f"Connection failed: {exc}")
        logger.debug(
            "get_sites_raw (project=%r env=%r): HTTP %s \u2014 %d bytes",
            project_name,
            environment_name,
            response.status_code,
            len(response.content),
        )
        return self._handle_response(response)

    def get_subjects_raw(
        self,
        study_oid: str,
    ) -> str:
        """
        Retrieve the raw ODM XML listing of subjects for a given study.

        Mirrors ``rwslib.rws_requests.StudySubjectsRequest``::

            StudySubjectsRequest(project_name, environment_name)

        Calls::

            GET /RaveWebServices/studies/{project}({env})/subjects

        Each ``<SubjectData>`` in the response carries a
        ``<SiteRef LocationOID="..."/>`` child, enabling client-side
        filtering to a specific site.

        Returns:
            BOM-stripped XML suitable for ``ET.fromstring``.

        Raises:
            RWSError: On HTTP errors, auth failures, or network failures.

        Ref: https://rwslib.readthedocs.io/en/latest/retrieve_clinical_data.html
        """
        project_name, environment_name = _parse_study_oid(study_oid)
        url = f"{self.base_url}/RaveWebServices/studies/{project_name}({environment_name})/subjects"
        logger.debug("get_subjects_raw: project=%r env=%r \u2192 GET %s", project_name, environment_name, url)
        try:
            response = self._session.get(url, timeout=self.timeout)
        except requests.exceptions.Timeout:
            raise RWSError(f"Request timed out after {self.timeout}s.")
        except requests.exceptions.ConnectionError as exc:
            raise RWSError(f"Connection failed: {exc}")
        logger.debug(
            "get_subjects_raw (project=%r env=%r): HTTP %s \u2014 %d bytes",
            project_name,
            environment_name,
            response.status_code,
            len(response.content),
        )
        return self._handle_response(response)

    def ping(self) -> bool:
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
        response.encoding = "utf-8-sig"
        body = response.text

        if response.status_code == 200:
            if self._is_login_page(body):
                raise RWSError(
                    "Unauthorised \u2014 RWS redirected to the login page. "
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
            400: "Bad Request \u2014 malformed ODM XML.",
            401: "Unauthorised \u2014 check credentials.",
            403: "Forbidden \u2014 insufficient RWS permissions.",
            404: "Not Found \u2014 check study OID or endpoint URL.",
            409: "Conflict \u2014 transaction violates study configuration.",
        }
        message = rws_messages.get(
            response.status_code, f"Unexpected HTTP {response.status_code}."
        )
        rws_code = self._extract_rws_code(body)
        raise RWSError(message, rws_code=rws_code, http_status=response.status_code)

    @staticmethod
    def _is_login_page(body: str) -> bool:
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
