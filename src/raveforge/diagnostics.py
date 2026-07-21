from __future__ import annotations
import difflib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .exceptions import RWSError

ODM_NS = "http://www.cdisc.org/ns/odm/v1.3"


@dataclass
class DiagnosticReport:
    """
    Structured, machine-readable explanation of an RWS failure.

    This is intentionally NOT a free-text guess. Every field is either
    a fact pulled from RWS or a clearly-labeled suggestion. RaveForge
    never applies these suggestions automatically.
    """

    category: str
    severity: str
    requested: Dict[str, Any] = field(default_factory=dict)
    evidence: Dict[str, Any] = field(default_factory=dict)
    recommendation: str = ""
    safe_to_retry: bool = False

    def format_human_readable(self) -> str:
        lines = [f"[{self.severity.upper()}] {self.category.replace('_', ' ').title()}"]

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

    RaveDiagnostics interprets RWS submission failures and returns
    evidence-based suggestions. It never modifies the caller's
    transaction or automatically selects a study, site, or subject.
    All lookups are read-only RWS GET calls, scoped to the minimum
    information needed to explain the failure.
    """

    def __init__(self, client) -> None:
        self._client = client

    # ------------------------------------------------------------------
    # Study directory
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
            name_node = study.find(f"{{{ODM_NS}}}GlobalVariables/{{{ODM_NS}}}StudyName")
            name = name_node.text if name_node is not None and name_node.text else oid
            studies.append({"oid": oid, "name": name})

        return studies

    # ------------------------------------------------------------------
    # Matching helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize(value: str) -> str:
        """
        Normalize an identifier for comparison by lowercasing and removing
        all non-alphanumeric characters.

        Examples:
            "Mediflex (Dev)" -> "mediflexdev"
            "mediflex dev"   -> "mediflexdev"
            "Cardio_Study-01" -> "cardiostudy01"
        """
        return re.sub(r"[^a-z0-9]+", "", (value or "").lower())

    def _find_close_matches(
        self,
        target: str,
        candidates: List[str],
        limit: int = 3,
        threshold: float = 0.6,
    ) -> List[Dict[str, Any]]:
        """
        Find close matches for `target` within `candidates`.

        Uses normalized exact matching first, then falls back to sequence
        similarity scoring against normalized values.
        """
        if not target or not candidates:
            return []

        normalized_target = self._normalize(target)
        matches = []

        for candidate in candidates:
            normalized_candidate = self._normalize(candidate)

            if normalized_candidate == normalized_target:
                matches.append({"value": candidate, "similarity": 1.0})
                continue

            ratio = difflib.SequenceMatcher(None, normalized_target, normalized_candidate).ratio()
            if ratio >= threshold:
                matches.append({"value": candidate, "similarity": round(ratio, 2)})

        matches.sort(key=lambda m: m["similarity"], reverse=True)
        return matches[:limit]

    # ------------------------------------------------------------------
    # Error categorization
    # ------------------------------------------------------------------

    @staticmethod
    def categorize_error(error: RWSError) -> str:
        """
        Categorize an RWSError into a diagnostic bucket based on HTTP
        status and message content.

        Ordering matters: check the most specific entity names first
        (subject -> site -> study) to avoid substring collisions like:
        'Subject invalid for this site'
        """
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
    # Main entry point
    # ------------------------------------------------------------------

    def explain_submission_failure(
        self,
        error: RWSError,
        transaction: Optional[Any] = None,
        include_subject_location: bool = False,
    ) -> DiagnosticReport:
        """
        Build a DiagnosticReport for a failed RWS submission.
        """
        category = self.categorize_error(error)

        if category == "authentication_failed":
            return DiagnosticReport(
                category=category,
                severity="error",
                evidence={"http_status": error.http_status},
                recommendation="Verify the username and password used to authenticate with RWS.",
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

        if category == "server_error":
            return DiagnosticReport(
                category=category,
                severity="error",
                evidence={"http_status": error.http_status},
                recommendation="RWS returned a server error. Retry later or contact Medidata support.",
                safe_to_retry=True,
            )

        if category == "study_not_found" and transaction is not None:
            return self._diagnose_study_not_found(transaction.study_oid)

        return DiagnosticReport(
            category=category if category != "unknown" else "unrecognized_error",
            severity="error",
            evidence={
                "http_status": error.http_status,
                "rws_code": error.rws_code,
                "message": str(error),
            },
            recommendation="Review the RWS error details above for the specific cause.",
            safe_to_retry=False,
        )

    # ------------------------------------------------------------------
    # Specific diagnostics
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
        exact_match = requested_study_oid in study_oids

        if exact_match:
            return DiagnosticReport(
                category="study_not_found",
                severity="warning",
                requested={"study_oid": requested_study_oid},
                evidence={"accessible_study_count": len(studies)},
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
                "suggested_matches": suggestions,
            },
            recommendation=(
                "Confirm the intended environment and use the exact StudyOID "
                "configured in Rave. No payload was changed automatically."
            ),
            safe_to_retry=False,
        )