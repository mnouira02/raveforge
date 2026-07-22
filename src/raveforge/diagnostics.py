from __future__ import annotations

import difflib
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .exceptions import RWSError

if TYPE_CHECKING:
    from .core import RaveTransaction

ODM_NS = "http://www.cdisc.org/ns/odm/v1.3"
MDSOL_NS = "http://www.mdsol.com/ns/odm/metadata"
_MATCH_THRESHOLD = 0.6

logger = logging.getLogger(__name__)


@dataclass
class DiagnosticReport:
    """
    Structured result of an RWS submission failure analysis.

    Every field is either a fact retrieved from RWS or a clearly-labelled
    suggestion. RaveForge never applies suggestions automatically.
    """

    category: str
    severity: str
    requested: Dict[str, Any] = field(default_factory=dict)
    evidence: Dict[str, Any] = field(default_factory=dict)
    recommendation: str = ""
    safe_to_retry: bool = False

    # Human-readable category titles
    _TITLES: Dict[str, str] = field(
        default_factory=lambda: {
            "authentication_failed": "Authentication Failed",
            "authorization_failed": "Authorization Failed",
            "conflict": "Transaction Conflict",
            "server_error": "Server Error",
            "study_not_found": "Study Not Found",
            "site_not_found": "Site Not Found",
            "subject_not_found": "Subject Not Found",
            "not_found": "Resource Not Found",
            "unrecognized_error": "Unrecognized Error",
        },
        repr=False,
        compare=False,
    )

    def format_human_readable(self) -> str:
        """Return a multi-line diagnostic summary suitable for logging or display."""
        title = self._TITLES.get(self.category, self.category.replace("_", " ").title())
        lines = [
            f"[{self.severity.upper()}] {title}",
            "-" * 60,
        ]
        if self.requested:
            lines.append("Requested:")
            for k, v in self.requested.items():
                lines.append(f"  {k}: {v}")
        if self.evidence:
            lines.append("Evidence:")
            for k, v in self.evidence.items():
                lines.append(f"  {k}: {v}")
        if self.recommendation:
            lines.append(f"Recommendation: {self.recommendation}")
        lines.append(f"Safe to retry automatically: {self.safe_to_retry}")
        return "\n".join(lines)

    def __str__(self) -> str:
        return self.format_human_readable()


class RaveDiagnostics:
    """
    Post-submission diagnostics for Medidata Rave Web Services errors.

    Accepts the same client interface as ``RWSClient`` so it can be
    constructed with a mock in tests.
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    # ------------------------------------------------------------------
    # Study helpers
    # ------------------------------------------------------------------

    def get_studies(self) -> List[Dict[str, str]]:
        """
        Return a list of ``{oid, name}`` dicts for every study accessible
        to the authenticated user.

        Returns an empty list if the XML cannot be parsed.
        """
        try:
            raw = self._client.get_studies_raw()
        except RWSError:
            return []
        return self._parse_studies(raw)

    @staticmethod
    def _parse_studies(xml_text: str) -> List[Dict[str, str]]:
        """Parse an ODM studies response into a list of {oid, name} dicts."""
        xml_text = xml_text.lstrip("\ufeff")  # strip BOM
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            logger.warning("_parse_studies: failed to parse XML")
            return []

        studies = []
        for study_el in root.findall(f"{{{ODM_NS}}}Study"):
            oid = study_el.get("OID", "")
            name_el = study_el.find(
                f"{{{ODM_NS}}}GlobalVariables/{{{ODM_NS}}}StudyName"
            )
            name = name_el.text if (name_el is not None and name_el.text) else oid
            studies.append({"oid": oid, "name": name})
        return studies

    # ------------------------------------------------------------------
    # Site helpers
    # ------------------------------------------------------------------

    def get_sites(self, study_oid: str) -> List[str]:
        """
        Return a deduplicated list of site OIDs for the given study.

        Returns an empty list on any error.
        """
        try:
            raw = self._client.get_sites_raw(study_oid)
        except RWSError:
            return []
        return self._parse_site_oids(raw)

    @staticmethod
    def _parse_site_oids(xml_text: str) -> List[str]:
        """
        Parse site OIDs from an ODM XML string.

        Handles two real RWS response shapes:

        1. Legacy ``<Location OID="..."/>`` elements anywhere in the document.
        2. Modern ``<SiteRef LocationOID="..."/>`` elements (under ClinicalData
           or elsewhere in the document).

        Duplicate OIDs are removed; the result order is deterministic
        (insertion order via ``dict.fromkeys``).

        Returns an empty list if the XML cannot be parsed.
        """
        xml_text = xml_text.lstrip("\ufeff")
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            logger.warning("_parse_site_oids: failed to parse XML")
            return []

        seen: dict = {}

        # Shape 1 — legacy: <Location OID="..." /> (with or without ODM namespace)
        for el in root.iter(f"{{{ODM_NS}}}Location"):
            oid = el.get("OID")
            if oid:
                seen[oid] = None
        # Also try without namespace (some older responses omit it)
        for el in root.iter("Location"):
            oid = el.get("OID")
            if oid:
                seen[oid] = None

        # Shape 2 — modern: <SiteRef LocationOID="..." /> anywhere
        for el in root.iter(f"{{{ODM_NS}}}SiteRef"):
            oid = el.get("LocationOID")
            if oid:
                seen[oid] = None
        for el in root.iter("SiteRef"):
            oid = el.get("LocationOID")
            if oid:
                seen[oid] = None

        return list(seen.keys())

    # ------------------------------------------------------------------
    # Error classification
    # ------------------------------------------------------------------

    @staticmethod
    def categorize_error(error: RWSError) -> str:
        """
        Map an ``RWSError`` to a stable category string.

        Categories
        ----------
        ``authentication_failed``
            HTTP 401 — credentials rejected.
        ``authorization_failed``
            HTTP 403 — authenticated but not permitted.
        ``conflict``
            HTTP 409 — transaction violates study configuration.
        ``server_error``
            HTTP 5xx — Rave-side error, usually transient.
        ``study_not_found``
            HTTP 404 with a message indicating the study OID was rejected.
        ``site_not_found``
            HTTP 404 with a message indicating an invalid LocationOID.
        ``subject_not_found``
            HTTP 404 with a message indicating a subject lookup failed.
        ``not_found``
            HTTP 404 that does not match a more specific sub-category.
        ``unrecognized_error``
            Any status code not handled above.
        """
        status = error.http_status
        msg = str(error).lower()

        if status == 401:
            return "authentication_failed"
        if status == 403:
            return "authorization_failed"
        if status == 409:
            return "conflict"
        if status is not None and status >= 500:
            return "server_error"
        if status == 404:
            if "study" in msg:
                return "study_not_found"
            if "site" in msg or "location" in msg:
                return "site_not_found"
            if "subject" in msg:
                return "subject_not_found"
            return "not_found"
        return "unrecognized_error"

    # ------------------------------------------------------------------
    # Top-level diagnosis
    # ------------------------------------------------------------------

    def explain_submission_failure(
        self,
        error: RWSError,
        transaction: Optional[RaveTransaction] = None,
    ) -> DiagnosticReport:
        """
        Analyse a submission failure and return a structured
        ``DiagnosticReport``.

        Parameters
        ----------
        error:
            The ``RWSError`` raised by :meth:`RWSClient.post_odm`.
        transaction:
            The ``RaveTransaction`` that was submitted. When provided,
            extra fields (study OID, site OIDs, subject keys) are included
            in the report.

        Returns
        -------
        DiagnosticReport
            A structured report. RaveForge never automatically applies any
            suggestion contained in the report.
        """
        category = self.categorize_error(error)
        dispatch = {
            "authentication_failed": self._report_auth,
            "authorization_failed": self._report_authz,
            "conflict": self._report_conflict,
            "server_error": self._report_server_error,
            "study_not_found": self._report_study_not_found,
            "site_not_found": self._report_site_not_found,
            "subject_not_found": self._report_subject_not_found,
        }
        handler = dispatch.get(category)
        if handler:
            return handler(error, transaction)
        return self._report_unrecognized(error, transaction)

    # ------------------------------------------------------------------
    # Per-category report builders
    # ------------------------------------------------------------------

    @staticmethod
    def _report_auth(
        error: RWSError,
        transaction: Optional[RaveTransaction],
    ) -> DiagnosticReport:
        return DiagnosticReport(
            category="authentication_failed",
            severity="error",
            evidence={"http_status": error.http_status},
            recommendation=(
                "Verify the username and password supplied to RWSClient. "
                "Ensure the account is not locked in Rave."
            ),
            safe_to_retry=False,
        )

    @staticmethod
    def _report_authz(
        error: RWSError,
        transaction: Optional[RaveTransaction],
    ) -> DiagnosticReport:
        return DiagnosticReport(
            category="authorization_failed",
            severity="error",
            evidence={"http_status": error.http_status},
            recommendation=(
                "The authenticated user lacks the necessary RWS permissions. "
                "Contact your Rave administrator to review role assignments."
            ),
            safe_to_retry=False,
        )

    @staticmethod
    def _report_conflict(
        error: RWSError,
        transaction: Optional[RaveTransaction],
    ) -> DiagnosticReport:
        evidence: Dict[str, Any] = {"http_status": error.http_status}
        if error.rws_code:
            evidence["rws_code"] = error.rws_code
        return DiagnosticReport(
            category="conflict",
            severity="error",
            evidence=evidence,
            recommendation=(
                "The transaction conflicts with the current study configuration. "
                "Review the RWS error code and the study's edit checks or data rules."
            ),
            safe_to_retry=False,
        )

    @staticmethod
    def _report_server_error(
        error: RWSError,
        transaction: Optional[RaveTransaction],
    ) -> DiagnosticReport:
        return DiagnosticReport(
            category="server_error",
            severity="error",
            evidence={"http_status": error.http_status},
            recommendation=(
                "This is a server-side error and may be transient. "
                "Retry the submission after a short delay. "
                "If the error persists, contact Medidata support."
            ),
            safe_to_retry=True,
        )

    def _report_study_not_found(
        self,
        error: RWSError,
        transaction: Optional[RaveTransaction],
    ) -> DiagnosticReport:
        study_oid = getattr(transaction, "study_oid", "") if transaction else ""
        studies = self.get_studies()
        known_oids = [s["oid"] for s in studies]
        close_matches = self._close_matches(study_oid, known_oids)
        return DiagnosticReport(
            category="study_not_found",
            severity="error",
            requested={"study_oid": study_oid},
            evidence={
                "accessible_study_count": len(studies),
                "close_matches": close_matches,
            },
            recommendation=(
                "Confirm the exact StudyOID using RaveDiagnostics.get_studies(). "
                "OIDs are case-sensitive and must include the environment suffix, "
                'e.g. \'Mediflex(Dev)\'.',
            ),
            safe_to_retry=False,
        )

    def _report_site_not_found(
        self,
        error: RWSError,
        transaction: Optional[RaveTransaction],
    ) -> DiagnosticReport:
        if not transaction or not transaction._subjects:
            return DiagnosticReport(
                category="site_not_found",
                severity="error",
                evidence={"http_status": error.http_status},
                recommendation=(
                    "No transaction was provided or it contained no subjects. "
                    "Ensure each SubjectData element carries a valid "
                    "SiteRef LocationOID."
                ),
                safe_to_retry=False,
            )

        study_oid = getattr(transaction, "study_oid", "") if transaction else ""
        # Collect the first site OID found in the transaction
        site_oid = ""
        for subj_data in transaction._subjects.values():
            site_oid = subj_data.get("SiteOID", "")
            if site_oid:
                break

        known_sites = self.get_sites(study_oid)
        close_matches = self._close_matches(site_oid, known_sites)

        return DiagnosticReport(
            category="site_not_found",
            severity="error",
            requested={"site_oid": site_oid, "study_oid": study_oid},
            evidence={
                "accessible_site_count": len(known_sites),
                "close_matches": close_matches,
            },
            recommendation=(
                "Confirm the exact LocationOID using RaveDiagnostics.get_sites(). "
                "OIDs are case-sensitive."
            ),
            safe_to_retry=False,
        )

    @staticmethod
    def _report_subject_not_found(
        error: RWSError,
        transaction: Optional[RaveTransaction],
    ) -> DiagnosticReport:
        subject_keys: List[str] = []
        if transaction and transaction._subjects:
            subject_keys = list(transaction._subjects.keys())
        return DiagnosticReport(
            category="subject_not_found",
            severity="error",
            requested={"subject_keys": subject_keys},
            evidence={
                "subject_count_in_transaction": len(subject_keys),
                "http_status": error.http_status,
            },
            recommendation=(
                "The SubjectKey in the transaction does not match an existing "
                "subject in Rave. Verify the SubjectKey or use ActionType.INSERT "
                "to create a new subject."
            ),
            safe_to_retry=False,
        )

    @staticmethod
    def _report_unrecognized(
        error: RWSError,
        transaction: Optional[RaveTransaction],
    ) -> DiagnosticReport:
        return DiagnosticReport(
            category="unrecognized_error",
            severity="error",
            evidence={
                "http_status": error.http_status,
                "message": str(error),
            },
            recommendation=(
                "This error was not recognised by RaveForge. "
                "Review the full error message and consult the Medidata RWS "
                "documentation or support."
            ),
            safe_to_retry=False,
        )

    # ------------------------------------------------------------------
    # Similarity helper
    # ------------------------------------------------------------------

    @staticmethod
    def _close_matches(
        query: str,
        candidates: List[str],
        threshold: float = _MATCH_THRESHOLD,
    ) -> List[Dict[str, Any]]:
        """
        Return candidates whose similarity to ``query`` meets ``threshold``.

        Each result is a dict with ``{value, similarity}`` keys. Results are
        sorted descending by similarity.
        """
        results = []
        for candidate in candidates:
            ratio = difflib.SequenceMatcher(None, query, candidate).ratio()
            if ratio >= threshold:
                results.append({"value": candidate, "similarity": round(ratio, 4)})
        return sorted(results, key=lambda x: x["similarity"], reverse=True)
