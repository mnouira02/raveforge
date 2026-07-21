"""Pre-build ODM validation layer.

The validator performs structural and semantic checks on a RaveTransaction
before any XML is serialised. Catching problems here — before bytes hit the
network — gives a developer a clear, actionable Python exception with the
precise location of the offending element.

Design principles
-----------------
* **Read-only**: the validator never mutates the transaction it receives.
* **Composable**: each rule is an independent function that appends to a
  shared ``List[ValidationIssue]``.  Adding a rule is a one-liner.
* **Severity-aware**: rules are classified as ERROR or WARNING.  A ``strict``
  flag (default ``True``) controls whether WARNINGs are promoted to errors.
* **Aggregating**: unlike ``HierarchyError``, which fires at the first
  problem, validation collects *all* issues and surfaces them together so
  the developer can fix everything in one pass.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, List

from .exceptions import ValidationError

if TYPE_CHECKING:
    from .core import RaveTransaction


# ---------------------------------------------------------------------------
# Issue model
# ---------------------------------------------------------------------------

class Severity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"


@dataclass
class ValidationIssue:
    """A single validation finding produced by a rule."""

    severity: Severity
    code: str
    message: str
    location: str = ""

    def __str__(self) -> str:
        loc = f" [{self.location}]" if self.location else ""
        return f"[{self.severity.value}] {self.code}{loc}: {self.message}"


# ---------------------------------------------------------------------------
# Validation rules
# ---------------------------------------------------------------------------

_INVALID_OID_CHARS_RE = re.compile(r"[<>&]")


def _validate_study_oid(tx: "RaveTransaction", issues: List[ValidationIssue]) -> None:
    if not tx.study_oid or not tx.study_oid.strip():
        issues.append(ValidationIssue(
            severity=Severity.ERROR,
            code="STUDY_OID_EMPTY",
            message="study_oid must not be empty.",
        ))
    elif _INVALID_OID_CHARS_RE.search(tx.study_oid):
        issues.append(ValidationIssue(
            severity=Severity.ERROR,
            code="STUDY_OID_INVALID_CHARS",
            message=(
                f"study_oid '{tx.study_oid}' contains characters that are "
                f"illegal in an ODM OID attribute (<, >, &)."
            ),
        ))


def _validate_has_subjects(
    tx: "RaveTransaction", issues: List[ValidationIssue]
) -> None:
    if not tx._subjects:
        issues.append(ValidationIssue(
            severity=Severity.WARNING,
            code="NO_SUBJECTS",
            message=(
                "The transaction contains no subjects. Submitting an empty "
                "ClinicalData block is valid ODM but is unlikely to be intentional."
            ),
        ))


def _validate_subjects(tx: "RaveTransaction", issues: List[ValidationIssue]) -> None:
    for subj_key, subj_data in tx._subjects.items():
        subj_loc = subj_key

        if not subj_key or not subj_key.strip():
            issues.append(ValidationIssue(
                severity=Severity.ERROR,
                code="SUBJECT_KEY_EMPTY",
                message="A subject was added with an empty SubjectKey.",
                location=subj_loc,
            ))

        if not subj_data.get("SiteOID") or not subj_data["SiteOID"].strip():
            issues.append(ValidationIssue(
                severity=Severity.ERROR,
                code="SITE_OID_EMPTY",
                message=f"Subject '{subj_key}' has an empty SiteOID.",
                location=subj_loc,
            ))

        if not subj_data.get("Events"):
            issues.append(ValidationIssue(
                severity=Severity.WARNING,
                code="SUBJECT_NO_EVENTS",
                message=(
                    f"Subject '{subj_key}' has no events. The subject node will "
                    f"be serialised but carry no clinical data."
                ),
                location=subj_loc,
            ))
            continue

        for event_data in subj_data["Events"].values():
            event_loc = f"{subj_loc} > {event_data['OID']}"

            if not event_data.get("OID") or not event_data["OID"].strip():
                issues.append(ValidationIssue(
                    severity=Severity.ERROR,
                    code="EVENT_OID_EMPTY",
                    message="An event was added with an empty StudyEventOID.",
                    location=event_loc,
                ))

            if not event_data.get("Forms"):
                issues.append(ValidationIssue(
                    severity=Severity.WARNING,
                    code="EVENT_NO_FORMS",
                    message=(
                        f"Event '{event_data['OID']}' has no forms. The event node "
                        f"will be serialised but carry no clinical data."
                    ),
                    location=event_loc,
                ))
                continue

            for form_data in event_data["Forms"].values():
                form_loc = f"{event_loc} > {form_data['OID']}"

                if not form_data.get("OID") or not form_data["OID"].strip():
                    issues.append(ValidationIssue(
                        severity=Severity.ERROR,
                        code="FORM_OID_EMPTY",
                        message="A form was added with an empty FormOID.",
                        location=form_loc,
                    ))

                if not form_data.get("ItemGroups"):
                    issues.append(ValidationIssue(
                        severity=Severity.WARNING,
                        code="FORM_NO_ITEM_GROUPS",
                        message=(
                            f"Form '{form_data['OID']}' has no item groups. The form "
                            f"node will be serialised but carry no clinical data."
                        ),
                        location=form_loc,
                    ))
                    continue

                for group_data in form_data["ItemGroups"].values():
                    group_loc = f"{form_loc} > {group_data['OID']}"

                    if not group_data.get("OID") or not group_data["OID"].strip():
                        issues.append(ValidationIssue(
                            severity=Severity.ERROR,
                            code="ITEM_GROUP_OID_EMPTY",
                            message=(
                                "An item group was added with an empty ItemGroupOID."
                            ),
                            location=group_loc,
                        ))

                    for item_oid, item_dict in group_data.get("Items", {}).items():
                        item_loc = f"{group_loc} > {item_oid}"

                        if not item_oid or not item_oid.strip():
                            issues.append(ValidationIssue(
                                severity=Severity.ERROR,
                                code="ITEM_OID_EMPTY",
                                message="An item was added with an empty ItemOID.",
                                location=group_loc,
                            ))

                        has_data = (
                            item_dict.get("Value") is not None
                            or item_dict.get("Specify") is not None
                            or item_dict.get("Query") is not None
                        )
                        if not has_data:
                            issues.append(ValidationIssue(
                                severity=Severity.WARNING,
                                code="ITEM_NO_VALUE",
                                message=(
                                    f"Item '{item_oid}' has no value, specify, or "
                                    f"query. An empty ItemData element will be "
                                    f"serialised."
                                ),
                                location=item_loc,
                            ))


# ---------------------------------------------------------------------------
# Rule registry
# ---------------------------------------------------------------------------

_RULES = [
    _validate_study_oid,
    _validate_has_subjects,
    _validate_subjects,
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate(
    tx: "RaveTransaction",
    strict: bool = True,
) -> List[ValidationIssue]:
    """
    Run all validation rules against *tx* and return the full issue list.

    Args:
        tx:     The transaction to validate.
        strict: When ``True`` (default), any WARNING is treated as an ERROR
                for the purposes of raising ``ValidationError``.
                When ``False``, only ERROR-severity issues raise.

    Returns:
        The complete list of :class:`ValidationIssue` objects, regardless of
        whether an exception is raised.  Inspect this list to understand every
        finding.

    Raises:
        ValidationError: If any ERROR-level issue is found, or if *strict* is
            ``True`` and any WARNING-level issue is found.  The exception
            message aggregates all qualifying issues, and the ``issues``
            attribute on the exception carries the structured list.
    """
    issues: List[ValidationIssue] = []
    for rule in _RULES:
        rule(tx, issues)

    blocking = [
        i for i in issues
        if i.severity == Severity.ERROR or (strict and i.severity == Severity.WARNING)
    ]

    if blocking:
        summary = "\n".join(f"  {i}" for i in blocking)
        raise ValidationError(
            f"{len(blocking)} validation issue(s) found:\n{summary}",
            issues=blocking,
        )

    return issues
