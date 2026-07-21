"""Tests for the ODM validation layer (raveforge.validator)."""
from __future__ import annotations

import pytest

from raveforge import RaveTransaction, ValidationError, validate
from raveforge.validator import Severity, ValidationIssue

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_valid_tx() -> RaveTransaction:
    """Return the simplest possible transaction that passes all rules."""
    tx = RaveTransaction("STUDY_01")
    (
        tx.subject("SUBJ-001", "SITE-01")
          .event("VISIT_1")
          .form("DM")
          .item_group("DM_IG")
          .item("AGE", value="34")
    )
    return tx


# ---------------------------------------------------------------------------
# validate() happy path
# ---------------------------------------------------------------------------

def test_validate_returns_empty_issues_for_valid_tx():
    """A fully-formed transaction with strict=True raises nothing."""
    issues = validate(_minimal_valid_tx())
    assert issues == []


def test_validate_does_not_mutate_transaction():
    """validate() must never modify the transaction it receives."""
    tx = _minimal_valid_tx()
    original_study = tx.study_oid
    validate(tx)
    assert tx.study_oid == original_study


# ---------------------------------------------------------------------------
# STUDY_OID_EMPTY
# ---------------------------------------------------------------------------

def test_validate_raises_on_empty_study_oid():
    tx = RaveTransaction("")
    with pytest.raises(ValidationError) as exc_info:
        validate(tx)
    err = exc_info.value
    assert any(i.code == "STUDY_OID_EMPTY" for i in err.issues)


def test_validate_raises_on_whitespace_study_oid():
    tx = RaveTransaction("   ")
    with pytest.raises(ValidationError) as exc_info:
        validate(tx)
    assert any(i.code == "STUDY_OID_EMPTY" for i in exc_info.value.issues)


def test_validate_raises_on_study_oid_with_lt():
    tx = RaveTransaction("STUDY<01")
    with pytest.raises(ValidationError) as exc_info:
        validate(tx)
    assert any(i.code == "STUDY_OID_INVALID_CHARS" for i in exc_info.value.issues)


def test_validate_raises_on_study_oid_with_gt():
    tx = RaveTransaction("STUDY>01")
    with pytest.raises(ValidationError) as exc_info:
        validate(tx)
    assert any(i.code == "STUDY_OID_INVALID_CHARS" for i in exc_info.value.issues)


def test_validate_raises_on_study_oid_with_ampersand():
    tx = RaveTransaction("STUDY&01")
    with pytest.raises(ValidationError) as exc_info:
        validate(tx)
    assert any(i.code == "STUDY_OID_INVALID_CHARS" for i in exc_info.value.issues)


# ---------------------------------------------------------------------------
# NO_SUBJECTS (WARNING promoted to error in strict mode)
# ---------------------------------------------------------------------------

def test_validate_strict_raises_on_no_subjects():
    tx = RaveTransaction("STUDY_01")
    with pytest.raises(ValidationError) as exc_info:
        validate(tx, strict=True)
    assert any(i.code == "NO_SUBJECTS" for i in exc_info.value.issues)


def test_validate_non_strict_does_not_raise_on_no_subjects():
    tx = RaveTransaction("STUDY_01")
    issues = validate(tx, strict=False)
    assert any(i.code == "NO_SUBJECTS" for i in issues)
    # non-strict should return the issues list without raising


def test_validate_no_subjects_is_warning_severity():
    tx = RaveTransaction("STUDY_01")
    issues = validate(tx, strict=False)
    no_subj = next(i for i in issues if i.code == "NO_SUBJECTS")
    assert no_subj.severity == Severity.WARNING


# ---------------------------------------------------------------------------
# SUBJECT_KEY_EMPTY / SITE_OID_EMPTY
# ---------------------------------------------------------------------------

def test_validate_raises_on_empty_site_oid():
    """Subjects added with an empty SiteOID should fail."""
    tx = RaveTransaction("STUDY_01")
    tx.subject("SUBJ-001", "").event("V1").form("F1").item_group("G1").item("IT", value="x")
    with pytest.raises(ValidationError) as exc_info:
        validate(tx)
    assert any(i.code == "SITE_OID_EMPTY" for i in exc_info.value.issues)


def test_validate_raises_on_whitespace_site_oid():
    tx = RaveTransaction("STUDY_01")
    tx.subject("SUBJ-001", "   ").event("V1").form("F1").item_group("G1").item("IT", value="x")
    with pytest.raises(ValidationError) as exc_info:
        validate(tx)
    assert any(i.code == "SITE_OID_EMPTY" for i in exc_info.value.issues)


# ---------------------------------------------------------------------------
# SUBJECT_NO_EVENTS (WARNING)
# ---------------------------------------------------------------------------

def test_validate_warns_on_subject_with_no_events_in_strict():
    tx = RaveTransaction("STUDY_01")
    tx.subject("SUBJ-001", "SITE-01")
    with pytest.raises(ValidationError) as exc_info:
        validate(tx, strict=True)
    assert any(i.code == "SUBJECT_NO_EVENTS" for i in exc_info.value.issues)


def test_validate_subject_no_events_is_warning():
    tx = RaveTransaction("STUDY_01")
    tx.subject("SUBJ-001", "SITE-01")
    issues = validate(tx, strict=False)
    no_ev = next((i for i in issues if i.code == "SUBJECT_NO_EVENTS"), None)
    assert no_ev is not None
    assert no_ev.severity == Severity.WARNING


# ---------------------------------------------------------------------------
# EVENT_NO_FORMS (WARNING)
# ---------------------------------------------------------------------------

def test_validate_warns_on_event_with_no_forms():
    tx = RaveTransaction("STUDY_01")
    tx.subject("SUBJ-001", "SITE-01").event("VISIT_1")
    with pytest.raises(ValidationError) as exc_info:
        validate(tx, strict=True)
    assert any(i.code == "EVENT_NO_FORMS" for i in exc_info.value.issues)


def test_validate_event_no_forms_is_warning():
    tx = RaveTransaction("STUDY_01")
    tx.subject("SUBJ-001", "SITE-01").event("VISIT_1")
    issues = validate(tx, strict=False)
    no_forms = next((i for i in issues if i.code == "EVENT_NO_FORMS"), None)
    assert no_forms is not None
    assert no_forms.severity == Severity.WARNING


# ---------------------------------------------------------------------------
# FORM_NO_ITEM_GROUPS (WARNING)
# ---------------------------------------------------------------------------

def test_validate_warns_on_form_with_no_item_groups():
    tx = RaveTransaction("STUDY_01")
    tx.subject("SUBJ-001", "SITE-01").event("V1").form("DM")
    with pytest.raises(ValidationError) as exc_info:
        validate(tx, strict=True)
    assert any(i.code == "FORM_NO_ITEM_GROUPS" for i in exc_info.value.issues)


def test_validate_form_no_item_groups_is_warning():
    tx = RaveTransaction("STUDY_01")
    tx.subject("SUBJ-001", "SITE-01").event("V1").form("DM")
    issues = validate(tx, strict=False)
    no_ig = next((i for i in issues if i.code == "FORM_NO_ITEM_GROUPS"), None)
    assert no_ig is not None
    assert no_ig.severity == Severity.WARNING


# ---------------------------------------------------------------------------
# ITEM_NO_VALUE (WARNING)
# ---------------------------------------------------------------------------

def test_validate_warns_on_item_with_no_value_no_specify_no_query():
    tx = RaveTransaction("STUDY_01")
    tx.subject("SUBJ-001", "SITE-01").event("V1").form("DM").item_group("G1").item("AGE")
    with pytest.raises(ValidationError) as exc_info:
        validate(tx, strict=True)
    assert any(i.code == "ITEM_NO_VALUE" for i in exc_info.value.issues)


def test_validate_item_no_value_is_warning():
    tx = RaveTransaction("STUDY_01")
    tx.subject("SUBJ-001", "SITE-01").event("V1").form("DM").item_group("G1").item("AGE")
    issues = validate(tx, strict=False)
    no_val = next((i for i in issues if i.code == "ITEM_NO_VALUE"), None)
    assert no_val is not None
    assert no_val.severity == Severity.WARNING


def test_validate_item_with_specify_does_not_warn():
    """An item with only a specify value should not trigger ITEM_NO_VALUE."""
    tx = RaveTransaction("STUDY_01")
    (
        tx.subject("SUBJ-001", "SITE-01")
          .event("V1")
          .form("DM")
          .item_group("G1")
          .item("RACE", specify="Mixed")
    )
    issues = validate(tx, strict=False)
    assert not any(i.code == "ITEM_NO_VALUE" for i in issues)


def test_validate_item_with_query_does_not_warn():
    """An item with only a query should not trigger ITEM_NO_VALUE."""
    tx = RaveTransaction("STUDY_01")
    (
        tx.subject("SUBJ-001", "SITE-01")
          .event("V1")
          .form("DM")
          .item_group("G1")
          .item("AGE", query="Please clarify.")
    )
    issues = validate(tx, strict=False)
    assert not any(i.code == "ITEM_NO_VALUE" for i in issues)


# ---------------------------------------------------------------------------
# Multiple issues collected in one pass
# ---------------------------------------------------------------------------

def test_validate_collects_all_issues_before_raising():
    """Validate aggregates every problem rather than stopping at the first."""
    tx = RaveTransaction("STUDY<01")  # STUDY_OID_INVALID_CHARS
    # Also add a subject with no events to stack up a second issue
    tx.subject("SUBJ-001", "SITE-01")
    with pytest.raises(ValidationError) as exc_info:
        validate(tx)
    codes = [i.code for i in exc_info.value.issues]
    assert "STUDY_OID_INVALID_CHARS" in codes
    assert "SUBJECT_NO_EVENTS" in codes


# ---------------------------------------------------------------------------
# ValidationIssue.__str__
# ---------------------------------------------------------------------------

def test_validation_issue_str_with_location():
    issue = ValidationIssue(
        severity=Severity.ERROR,
        code="SITE_OID_EMPTY",
        message="SiteOID is empty.",
        location="SUBJ-001",
    )
    text = str(issue)
    assert "[ERROR]" in text
    assert "SITE_OID_EMPTY" in text
    assert "[SUBJ-001]" in text
    assert "SiteOID is empty." in text


def test_validation_issue_str_without_location():
    issue = ValidationIssue(
        severity=Severity.WARNING,
        code="NO_SUBJECTS",
        message="No subjects in transaction.",
    )
    text = str(issue)
    assert "[WARNING]" in text
    assert "NO_SUBJECTS" in text
    assert "[" not in text.split("NO_SUBJECTS")[1]  # no location bracket


# ---------------------------------------------------------------------------
# ValidationError carries issues
# ---------------------------------------------------------------------------

def test_validation_error_issues_attribute_is_populated():
    tx = RaveTransaction("")
    with pytest.raises(ValidationError) as exc_info:
        validate(tx)
    assert len(exc_info.value.issues) >= 1
    assert all(isinstance(i, ValidationIssue) for i in exc_info.value.issues)


# ---------------------------------------------------------------------------
# strict=False vs strict=True
# ---------------------------------------------------------------------------

def test_strict_false_returns_warnings_without_raising():
    """strict=False should return warnings as issues but not raise."""
    tx = RaveTransaction("STUDY_01")
    tx.subject("SUBJ-001", "SITE-01").event("V1").form("DM").item_group("G1").item("AGE")
    issues = validate(tx, strict=False)
    severities = {i.severity for i in issues}
    assert Severity.WARNING in severities


def test_strict_true_raises_on_warnings():
    """strict=True (default) must raise even for WARNING-only findings."""
    tx = RaveTransaction("STUDY_01")
    tx.subject("SUBJ-001", "SITE-01").event("V1").form("DM").item_group("G1").item("AGE")
    with pytest.raises(ValidationError):
        validate(tx, strict=True)
