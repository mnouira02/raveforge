from __future__ import annotations

import difflib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .exceptions import RWSError

if TYPE_CHECKING:
    from .core import RaveTransaction

ODM_NS = "http://www.cdisc.org/ns/odm/v1.3"
_MATCH_THRESHOLD = 0.6


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

    def format_human_readable(self) -> str:
        lines = [
            f"[{self.severity.upper()}] "
            f"{self.category.replace('_', ' ').title()}"
        ]

        if self.requested:
            lines.append("")
            lines.append("Requested:")
            for key, value in self.requested.items():
                lines.append(f"  {key}: {value}")

        if self.evidence:
            lines.append("")
            lines.append("Evidence:")
            for key, value in self.evidence.items():
                lines.append(f"  {key}: {value}")

        if self.recommendation:
            lines.append("")
            lines.append("Recommendation:")
            lines.append(f"  {self.recommendation}")

        lines.append("")
        lines.append(f"Safe to retry automatically: {self.safe_to_retry}")
        return "\n".join(lines)

    def __str__(self) -> str:
        return self.format_human_readable()


class RaveDiagnostics:
    """
    Read-only diagnostic layer for RaveForge.

    Interprets RWS submission failures and returns evidence-based
    suggestions via targeted, read-only RWS GET calls. Never modifies
    the caller's transaction or automatically selects a study, site,
    or subject on their behalf.
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    # ------------------------------------------------------------------
    # Study helpers
    # ------------------------------------------------------------------

    def get_studies(self) -> List[Dict[str, str]]:
        """
        Retrieve the list of studies accessible to the authenticated user.

        Returns:
            A list of dicts: [{"oid": "...", "name": "..."}, ...]
        """
        body = self._client.get_studies_raw()
        return self._parse_studies(body)

    @staticmethod
    def _parse_studies(body: str) -> List[Dict[str, str]]:
        studies: List[Dict[str, str]] = []
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            return studies
        for study in root.iter(f"{{{ODM_NS}}}Study"):
            oid = study.attrib.get("OID", "")
            name_node = study.find(
                f"{{{ODM_NS}}}GlobalVariables/{{{ODM_NS}}}StudyName"
            )
            name = (
                name_node.text
                if name_node is not None and name_node.text
                else oid
            )
            studies.append({"oid": oid, "name": name})
        return studies

    # ------------------------------------------------------------------
    # Site helpers
    # ------------------------------------------------------------------

    def get_sites(self, study_oid: str) -> List[str]:
        """
        Retrieve the list of site OIDs for a given study.

        Delegates to ``client.get_sites_raw(study_oid)`` and parses
        LocationOID attributes from the returned ODM XML.

        Returns:
            A list of site OID strings.
        """
        body = self._client.get_sites_raw(study_oid)
        return self._parse_site_oids(body)

    @staticmethod
    def _parse_site_oids(body: str) -> List[str]:
        site_oids: List[str] = []
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            return site_oids
        # RWS returns sites as <Location OID="..." /> elements
        for loc in root.iter("Location"):
            oid = loc.attrib.get("OID", "")
            if oid:
                site_oids.append(oid)
        # Also handle ODM-namespaced Location elements
        for loc in root.iter(f"{{{ODM_NS}}}Location"):
            oid = loc.attrib.get("OID", "")
            if oid and oid not in site_oids:
                site_oids.append(oid)
        return site_oids

    # ------------------------------------------------------------------
    # Shared utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", (value or "").lower())

    def _find_close_matches(
        self,
        target: str,
        candidates: List[str],
        limit: int = 3,
        threshold: float = _MATCH_THRESHOLD,
    ) -> List[Dict[str, Any]]:
        if not target or not candidates:
            return []

        normalized_target = self._normalize(target)
        matches = []

        for candidate in candidates:
            normalized_candidate = self._normalize(candidate)
            if normalized_candidate == normalized_target:
                matches.append({"value": candidate, "similarity": 1.0})
                continue
            ratio = difflib.SequenceMatcher(
                None, normalized_target, normalized_candidate
            ).ratio()
            if ratio >= threshold:
                matches.append({"value": candidate, "similarity": round(ratio, 2)})

        matches.sort(key=lambda m: m["similarity"], reverse=True)
        return matches[:limit]

    # ------------------------------------------------------------------
    # Error categorisation
    # ------------------------------------------------------------------

    @staticmethod
    def categorize_error(error: RWSError) -> str:
        status = error.http_status
        message = str(error).lower()

        if status == 401:
            return "authentication_failed"
        if status == 403:
            return "authorization_failed"
        if status == 409:
            return "conflict"
        if status is not None and status >= 500:
            return "server_error"

        if "subject" in message and ("not found" in message or "invalid" in message):
            return "subject_not_found"
        if "site" in message and ("not found" in message or "invalid" in message):
            return "site_not_found"
        if "study" in message and ("not found" in message or "invalid" in message):
            return "study_not_found"
        if status == 404:
            return "not_found"

        return "unknown"

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def explain_submission_failure(
        self,
        error: RWSError,
        transaction: Optional["RaveTransaction"] = None,
        include_subject_location: bool = False,
    ) -> DiagnosticReport:
        category = self.categorize_error(error)

        if category == "authentication_failed":
            return DiagnosticReport(
                category=category,
                severity="error",
                evidence={"http_status": error.http_status},
                recommendation=(
                    "Verify the username and password used to authenticate with RWS."
                ),
                safe_to_retry=False,
            )

        if category == "authorization_failed":
            return DiagnosticReport(
                category=category,
                severity="error",
                evidence={"http_status": error.http_status},
                recommendation=(
                    "The authenticated user does not have sufficient permissions "
                    "for this study or operation. Diagnostics were not expanded "
                    "to avoid probing inaccessible resources."
                ),
                safe_to_retry=False,
            )

        if category == "conflict":
            return DiagnosticReport(
                category=category,
                severity="error",
                evidence={"http_status": error.http_status},
                recommendation=(
                    "RWS reported a data conflict. "
                    "Check for duplicate subject keys or concurrent edits."
                ),
                safe_to_retry=False,
            )

        if category == "server_error":
            return DiagnosticReport(
                category=category,
                severity="error",
                evidence={"http_status": error.http_status},
                recommendation=(
                    "RWS returned a server error. "
                    "Retry later or contact Medidata support."
                ),
                safe_to_retry=True,
            )

        if category == "study_not_found" and transaction is not None:
            return self._diagnose_study_not_found(transaction.study_oid)

        if category == "site_not_found" and transaction is not None:
            return self._diagnose_site_not_found(
                transaction.study_oid,
                self._extract_site_oid(transaction),
            )

        if category == "subject_not_found" and transaction is not None:
            return self._diagnose_subject_not_found(
                transaction.study_oid,
                self._extract_subject_keys(transaction),
            )

        return DiagnosticReport(
            category=category if category != "unknown" else "unrecognized_error",
            severity="error",
            evidence={
                "http_status": error.http_status,
                "rws_code": error.rws_code,
                "message": str(error),
            },
            recommendation=(
                "Review the RWS error details above for the specific cause."
            ),
            safe_to_retry=False,
        )

    # ------------------------------------------------------------------
    # Private diagnostic methods
    # ------------------------------------------------------------------

    def _diagnose_study_not_found(self, requested_study_oid: str) -> DiagnosticReport:
        try:
            studies = self.get_studies()
        except Exception:
            return DiagnosticReport(
                category="study_not_found",
                severity="error",
                requested={"study_oid": requested_study_oid},
                evidence={"accessible_study_count": None},
                recommendation=(
                    "Could not retrieve the accessible study list to compare. "
                    "Verify the StudyOID matches the exact configuration in Rave."
                ),
                safe_to_retry=False,
            )

        study_oids = [s["oid"] for s in studies]

        if requested_study_oid in study_oids:
            return DiagnosticReport(
                category="study_not_found",
                severity="warning",
                requested={"study_oid": requested_study_oid},
                evidence={
                    "accessible_study_count": len(studies),
                    "close_matches": [
                        {"value": requested_study_oid, "similarity": 1.0}
                    ],
                },
                recommendation=(
                    "The StudyOID exists in your accessible study list, so the "
                    "failure may be caused by metadata version, permissions, or "
                    "environment mismatch rather than the study identifier itself."
                ),
                safe_to_retry=False,
            )

        suggestions = self._find_close_matches(requested_study_oid, study_oids)

        return DiagnosticReport(
            category="study_not_found",
            severity="error",
            requested={"study_oid": requested_study_oid},
            evidence={
                "accessible_study_count": len(studies),
                "close_matches": suggestions,
            },
            recommendation=(
                "Confirm the intended environment and use the exact StudyOID "
                "configured in Rave. No payload was changed automatically."
            ),
            safe_to_retry=False,
        )

    def _diagnose_site_not_found(
        self,
        study_oid: str,
        requested_site_oid: Optional[str],
    ) -> DiagnosticReport:
        if not requested_site_oid:
            return DiagnosticReport(
                category="site_not_found",
                severity="error",
                evidence={"study_oid": study_oid},
                recommendation=(
                    "Could not extract a SiteOID from the transaction. "
                    "Ensure every subject carries a valid LocationOID."
                ),
                safe_to_retry=False,
            )

        try:
            site_oids = self.get_sites(study_oid)
        except Exception:
            return DiagnosticReport(
                category="site_not_found",
                severity="error",
                requested={"site_oid": requested_site_oid, "study_oid": study_oid},
                evidence={"accessible_site_count": None},
                recommendation=(
                    "Could not retrieve the site list for this study. "
                    "Verify the SiteOID matches the exact configuration in Rave."
                ),
                safe_to_retry=False,
            )

        if requested_site_oid in site_oids:
            return DiagnosticReport(
                category="site_not_found",
                severity="warning",
                requested={"site_oid": requested_site_oid, "study_oid": study_oid},
                evidence={
                    "accessible_site_count": len(site_oids),
                    "close_matches": [
                        {"value": requested_site_oid, "similarity": 1.0}
                    ],
                },
                recommendation=(
                    "The SiteOID exists in the study, so the failure may be caused "
                    "by subject-level permissions or environment mismatch."
                ),
                safe_to_retry=False,
            )

        suggestions = self._find_close_matches(requested_site_oid, site_oids)

        return DiagnosticReport(
            category="site_not_found",
            severity="error",
            requested={"site_oid": requested_site_oid, "study_oid": study_oid},
            evidence={
                "accessible_site_count": len(site_oids),
                "close_matches": suggestions,
            },
            recommendation=(
                "Confirm the SiteOID matches the exact LocationOID configured "
                "in Rave for this study. No payload was changed automatically."
            ),
            safe_to_retry=False,
        )

    def _diagnose_subject_not_found(
        self,
        study_oid: str,
        subject_keys: List[str],
    ) -> DiagnosticReport:
        """
        Provide guidance when RWS reports a subject-not-found error.

        RWS does not expose a subject list endpoint, so this method cannot
        perform fuzzy matching. Instead it returns the subject key(s) from
        the transaction and actionable advice.
        """
        return DiagnosticReport(
            category="subject_not_found",
            severity="error",
            requested={"study_oid": study_oid, "subject_keys": subject_keys},
            evidence={
                "subject_count_in_transaction": len(subject_keys),
            },
            recommendation=(
                "Verify that the SubjectKey(s) listed above exist in the target "
                "study and site. RWS does not expose a subject list endpoint, so "
                "no fuzzy matching is possible. Check for leading/trailing "
                "whitespace, case differences, or environment mismatches."
            ),
            safe_to_retry=False,
        )

    # ------------------------------------------------------------------
    # Transaction inspection helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_site_oid(transaction: "RaveTransaction") -> Optional[str]:
        """Return the first SiteOID found across all subjects, or None."""
        for subj_data in transaction._subjects.values():
            site = subj_data.get("SiteOID")
            if site:
                return site
        return None

    @staticmethod
    def _extract_subject_keys(transaction: "RaveTransaction") -> List[str]:
        """Return all subject keys present in the transaction."""
        return list(transaction._subjects.keys())
