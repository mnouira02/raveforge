"""Tests for the Phase 3 ODM validation layer (raveforge.validator)."""
import pytest

from raveforge import (
    RaveTransaction,
    ValidationError,
    ValidationIssue,
    Severity,
    validate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_full_tx(study_oid: str = "Test_Study") -> RaveTransaction:
    """Return a transaction with one complete, valid hierarchy chain."""
    return (
        RaveTransaction(study_oid)
        .subject("SUBJ-001", "SITE-001")
        .event("SCREENING")
        .form("DM")
        .item_group("DM_IG")
        .item("AGE", "42")
    )


def _codes(issues: list) -> list:
    return [i.code for i in issues]


# ---------------------------------------------------------------------------
# 1. Happy-path — valid transactions should not raise
# ---------------------------------------------------------------------------


def test_valid_transaction_passes_strict_validation():
    """A fully populated, correct transaction raises no ValidationError."""
    tx = _make_full_tx()
    issues = validate(tx, strict=True)
    assert issues == []


def test_valid_transaction_passes_non_strict_validation():
    tx = _make_full_tx()
    issues = validate(tx, strict=False)
    assert issues == []


# ---------------------------------------------------------------------------
# 2. study_oid rules
# ---------------------------------------------------------------------------


def test_empty_study_oid_raises_validation_error():
    tx = RaveTransaction(study_oid="")
    tx.subject("S-1", "SITE-1").event("E-1").form("F-1").item_group("IG-1").item("I-1", "V")

    with pytest.raises(ValidationError, match="STUDY_OID_EMPTY"):
        validate(tx)


def test_whitespace_only_study_oid_raises_validation_error():
    tx = RaveTransaction(study_oid="   ")
    tx.subject("S-1", "SITE-1").event("E-1").form("F-1").item_group("IG-1").item("I-1", "V")

    with pytest.raises(ValidationError, match="STUDY_OID_EMPTY"):
        validate(tx)


def test_study_oid_with_xml_illegal_chars_raises_validation_error():
    """OID containing < > & should be rejected before any XML is generated."""
    tx = RaveTransaction(study_oid="Study<Broken>&OID")
    tx.subject("S-1", "SITE-1").event("E-1").form("F-1").item_group("IG-1").item("I-1", "V")

    with pytest.raises(ValidationError, match="STUDY_OID_INVALID_CHARS"):
        validate(tx)


# ---------------------------------------------------------------------------
# 3. Empty transaction warnings
# ---------------------------------------------------------------------------


def test_transaction_with_no_subjects_raises_in_strict_mode():
    """NO_SUBJECTS is a WARNING, which strict mode promotes to an error."""
    tx = RaveTransaction(study_oid="Test_Study")

    with pytest.raises(ValidationError, match="NO_SUBJECTS"):
        validate(tx, strict=True)


def test_transaction_with_no_subjects_passes_in_non_strict_mode():
    """In non-strict mode a WARNING does not raise; the issue is returned."""
    tx = RaveTransaction(study_oid="Test_Study")
    issues = validate(tx, strict=False)

    assert any(i.code == "NO_SUBJECTS" for i in issues)
    assert all(i.severity == Severity.WARNING for i in issues)


# ---------------------------------------------------------------------------
# 4. Subject-level rules
# ---------------------------------------------------------------------------


def test_subject_with_no_events_is_a_warning():
    tx = RaveTransaction("Test_Study")
    tx.subject("SUBJ-001", "SITE-001")  # no event chained

    with pytest.raises(ValidationError, match="SUBJECT_NO_EVENTS"):
        validate(tx, strict=True)

    issues = validate(tx, strict=False)
    assert any(i.code == "SUBJECT_NO_EVENTS" for i in issues)


def test_subject_with_empty_site_oid_raises():
    """Manually construct a state with a blank SiteOID."""
    tx = RaveTransaction("Test_Study")
    tx._subjects["SUBJ-001"] = {"SiteOID": "", "Action": None, "Events": {}}
    tx._current_subject = "SUBJ-001"

    with pytest.raises(ValidationError, match="SITE_OID_EMPTY"):
        validate(tx)


# ---------------------------------------------------------------------------
# 5. Event-level rules
# ---------------------------------------------------------------------------


def test_event_with_no_forms_is_a_warning():
    tx = RaveTransaction("Test_Study")
    tx.subject("S-1", "SITE-001").event("SCREENING")  # no form chained

    with pytest.raises(ValidationError, match="EVENT_NO_FORMS"):
        validate(tx, strict=True)

    issues = validate(tx, strict=False)
    assert any(i.code == "EVENT_NO_FORMS" for i in issues)


# ---------------------------------------------------------------------------
# 6. Form-level rules
# ---------------------------------------------------------------------------


def test_form_with_no_item_groups_is_a_warning():
    tx = RaveTransaction("Test_Study")
    tx.subject("S-1", "SITE-001").event("SCREENING").form("DM")  # no item_group chained

    with pytest.raises(ValidationError, match="FORM_NO_ITEM_GROUPS"):
        validate(tx, strict=True)

    issues = validate(tx, strict=False)
    assert any(i.code == "FORM_NO_ITEM_GROUPS" for i in issues)


# ---------------------------------------------------------------------------
# 7. Item-level rules
# ---------------------------------------------------------------------------


def test_item_with_no_value_or_query_is_a_warning():
    """An item with Value=None, specify=None, query=None gets ITEM_NO_VALUE."""
    tx = (
        RaveTransaction("Test_Study")
        .subject("S-1", "SITE-001")
        .event("SCREENING")
        .form("DM")
        .item_group("DM_IG")
        .item("AETERM")  # no value, no specify, no query
    )

    with pytest.raises(ValidationError, match="ITEM_NO_VALUE"):
        validate(tx, strict=True)

    issues = validate(tx, strict=False)
    assert any(i.code == "ITEM_NO_VALUE" for i in issues)


def test_item_with_only_specify_value_does_not_warn():
    """An item with only a specify value (no primary value) should not warn."""
    tx = (
        RaveTransaction("Test_Study")
        .subject("S-1", "SITE-001")
        .event("SCREENING")
        .form("MEDS")
        .item_group("MEDS_IG")
        .item("CMTRT", specify="Custom Blend")  # specify without value
    )
    issues = validate(tx, strict=True)
    assert issues == []


def test_item_with_only_query_does_not_warn():
    """An item with only a query (no data value) should not warn."""
    tx = (
        RaveTransaction("Test_Study")
        .subject("S-1", "SITE-001")
        .event("SCREENING")
        .form("VS")
        .item_group("VS_IG")
        .item("TEMP", query="Please confirm.")  # query without value
    )
    issues = validate(tx, strict=True)
    assert issues == []


# ---------------------------------------------------------------------------
# 8. Multiple issues are all reported together
# ---------------------------------------------------------------------------


def test_multiple_issues_are_aggregated_in_one_exception():
    """ValidationError should aggregate all issues in a single raise."""
    tx = RaveTransaction(study_oid="Bad<OID>")
    # Also inject a subject with no events to trigger a second issue
    tx._subjects["SUBJ-001"] = {"SiteOID": "SITE-001", "Action": None, "Events": {}}
    tx._current_subject = "SUBJ-001"

    with pytest.raises(ValidationError) as exc_info:
        validate(tx, strict=True)

    message = str(exc_info.value)
    assert "STUDY_OID_INVALID_CHARS" in message
    assert "SUBJECT_NO_EVENTS" in message


# ---------------------------------------------------------------------------
# 9. ValidationIssue model
# ---------------------------------------------------------------------------


def test_validation_issue_str_includes_severity_code_and_message():
    issue = ValidationIssue(
        severity=Severity.ERROR,
        code="STUDY_OID_EMPTY",
        message="study_oid must not be empty.",
        location="",
    )
    text = str(issue)
    assert "[ERROR]" in text
    assert "STUDY_OID_EMPTY" in text
    assert "study_oid must not be empty." in text


def test_validation_issue_str_includes_location_when_set():
    issue = ValidationIssue(
        severity=Severity.WARNING,
        code="ITEM_NO_VALUE",
        message="Item has no value.",
        location="SUBJ-001 > SCREENING > VS > VS_IG > TEMP",
    )
    text = str(issue)
    assert "SUBJ-001 > SCREENING > VS > VS_IG > TEMP" in text


# ---------------------------------------------------------------------------
# 10. validate() return contract
# ---------------------------------------------------------------------------


def test_validate_returns_empty_list_on_clean_transaction():
    tx = _make_full_tx()
    result = validate(tx)
    assert result == []
    assert isinstance(result, list)


def test_validate_returns_warning_issues_in_non_strict_mode():
    """In non-strict mode, validate() must return issues instead of raising."""
    tx = RaveTransaction(study_oid="Test_Study")
    tx.subject("S-1", "SITE-001").event("VISIT_1").form("LABS")
    # Form has no item groups — WARNING

    issues = validate(tx, strict=False)

    assert len(issues) >= 1
    codes = _codes(issues)
    assert "FORM_NO_ITEM_GROUPS" in codes
    # Return type is always a list regardless of strict mode
    assert isinstance(issues, list)


# ---------------------------------------------------------------------------
# 11. Severity enum
# ---------------------------------------------------------------------------


def test_severity_enum_values():
    assert Severity.ERROR == "ERROR"
    assert Severity.WARNING == "WARNING"


# ---------------------------------------------------------------------------
# 12. ValidationError carries issues list
# ---------------------------------------------------------------------------


def test_validation_error_issues_attribute_is_empty_by_default():
    err = ValidationError("something went wrong")
    assert err.issues == []


def test_validation_error_issues_attribute_is_populated_when_passed():
    issue = ValidationIssue(
        severity=Severity.ERROR,
        code="STUDY_OID_EMPTY",
        message="study_oid must not be empty.",
    )
    err = ValidationError("1 validation issue(s) found", issues=[issue])
    assert len(err.issues) == 1
    assert err.issues[0].code == "STUDY_OID_EMPTY"
