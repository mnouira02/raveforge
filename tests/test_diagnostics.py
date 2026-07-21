from unittest.mock import Mock
import pytest

from raveforge import RaveTransaction, RaveDiagnostics, DiagnosticReport, RWSError


SAMPLE_STUDIES_XML = """<?xml version="1.0" encoding="UTF-8"?>
<ODM xmlns="http://www.cdisc.org/ns/odm/v1.3" FileType="Snapshot" FileOID="abc" CreationDateTime="2026-01-01T00:00:00" ODMVersion="1.3">
  <Study OID="Mediflex (Dev)">
    <GlobalVariables>
      <StudyName>Mediflex (Dev)</StudyName>
    </GlobalVariables>
  </Study>
  <Study OID="Oncology_Phase_II_Prod">
    <GlobalVariables>
      <StudyName>Oncology Phase II (Prod)</StudyName>
    </GlobalVariables>
  </Study>
  <Study OID="Cardio_Study_01">
    <GlobalVariables>
      <StudyName>Cardio Study 01</StudyName>
    </GlobalVariables>
  </Study>
</ODM>"""


def make_client_stub(studies_xml: str = SAMPLE_STUDIES_XML):
    client = Mock()
    client.get_studies_raw.return_value = studies_xml
    return client


# -------------------------------------------------------------------
# 1. Study parsing
# -------------------------------------------------------------------


def test_get_studies_parses_oid_and_name():
    client = make_client_stub()
    diagnostics = RaveDiagnostics(client)

    studies = diagnostics.get_studies()

    assert len(studies) == 3
    oids = [s["oid"] for s in studies]
    assert "Mediflex (Dev)" in oids
    assert "Oncology_Phase_II_Prod" in oids
    assert "Cardio_Study_01" in oids


def test_get_studies_returns_empty_list_on_malformed_xml():
    client = make_client_stub(studies_xml="not xml at all")
    diagnostics = RaveDiagnostics(client)

    studies = diagnostics.get_studies()

    assert studies == []


# -------------------------------------------------------------------
# 2. Error categorization
# -------------------------------------------------------------------


def test_categorize_error_authentication():
    error = RWSError("Unauthorised", http_status=401)
    assert RaveDiagnostics.categorize_error(error) == "authentication_failed"


def test_categorize_error_authorization():
    error = RWSError("Forbidden", http_status=403)
    assert RaveDiagnostics.categorize_error(error) == "authorization_failed"


def test_categorize_error_conflict():
    error = RWSError("Conflict", http_status=409)
    assert RaveDiagnostics.categorize_error(error) == "conflict"


def test_categorize_error_server_error():
    error = RWSError("Internal Server Error", http_status=502)
    assert RaveDiagnostics.categorize_error(error) == "server_error"


def test_categorize_error_study_not_found_from_message():
    error = RWSError("Study OID is invalid or not found", http_status=400)
    assert RaveDiagnostics.categorize_error(error) == "study_not_found"


def test_categorize_error_site_not_found_from_message():
    error = RWSError("Site not found for this study", http_status=400)
    assert RaveDiagnostics.categorize_error(error) == "site_not_found"


def test_categorize_error_subject_not_found_from_message():
    error = RWSError("Subject invalid for this site", http_status=400)
    assert RaveDiagnostics.categorize_error(error) == "subject_not_found"


def test_categorize_error_unknown_defaults_safely():
    error = RWSError("Something odd happened", http_status=418)
    assert RaveDiagnostics.categorize_error(error) == "unknown"


# -------------------------------------------------------------------
# 3. Fuzzy matching
# -------------------------------------------------------------------


def test_find_close_matches_exact_normalized_match():
    diagnostics = RaveDiagnostics(make_client_stub())
    matches = diagnostics._find_close_matches("mediflex dev", ["Mediflex (Dev)", "Cardio_Study_01"])

    assert matches[0]["value"] == "Mediflex (Dev)"
    assert matches[0]["similarity"] == 1.0


def test_find_close_matches_returns_similar_candidates():
    diagnostics = RaveDiagnostics(make_client_stub())
    matches = diagnostics._find_close_matches("Mediflex Dev", ["Mediflex (Dev)", "Cardio_Study_01"])

    assert len(matches) >= 1
    assert matches[0]["value"] == "Mediflex (Dev)"
    assert matches[0]["similarity"] > 0.6


def test_find_close_matches_returns_empty_for_unrelated_target():
    diagnostics = RaveDiagnostics(make_client_stub())
    matches = diagnostics._find_close_matches("Completely_Different_Name", ["Cardio_Study_01"])

    assert matches == []


def test_find_close_matches_handles_empty_input():
    diagnostics = RaveDiagnostics(make_client_stub())
    assert diagnostics._find_close_matches("", ["A", "B"]) == []
    assert diagnostics._find_close_matches("A", []) == []


# -------------------------------------------------------------------
# 4. explain_submission_failure — auth/server categories
# -------------------------------------------------------------------


def test_explain_submission_failure_authentication():
    diagnostics = RaveDiagnostics(make_client_stub())
    error = RWSError("Unauthorised", http_status=401)

    report = diagnostics.explain_submission_failure(error)

    assert isinstance(report, DiagnosticReport)
    assert report.category == "authentication_failed"
    assert report.safe_to_retry is False


def test_explain_submission_failure_authorization():
    diagnostics = RaveDiagnostics(make_client_stub())
    error = RWSError("Forbidden", http_status=403)

    report = diagnostics.explain_submission_failure(error)

    assert report.category == "authorization_failed"
    assert report.safe_to_retry is False


def test_explain_submission_failure_server_error_is_retryable():
    diagnostics = RaveDiagnostics(make_client_stub())
    error = RWSError("Internal Server Error", http_status=503)

    report = diagnostics.explain_submission_failure(error)

    assert report.category == "server_error"
    assert report.safe_to_retry is True


def test_explain_submission_failure_unknown_category():
    diagnostics = RaveDiagnostics(make_client_stub())
    error = RWSError("Teapot error", http_status=418)

    report = diagnostics.explain_submission_failure(error)

    assert report.category == "unrecognized_error"
    assert report.evidence["http_status"] == 418


# -------------------------------------------------------------------
# 5. explain_submission_failure — study_not_found (exact + fuzzy)
# -------------------------------------------------------------------


def test_explain_submission_failure_study_exact_match_still_in_list():
    client = make_client_stub()
    diagnostics = RaveDiagnostics(client)
    error = RWSError("Study OID is invalid or not found", http_status=400)

    tx = RaveTransaction(study_oid="Mediflex (Dev)")
    report = diagnostics.explain_submission_failure(error, transaction=tx)

    assert report.category == "study_not_found"
    assert report.severity == "warning"
    assert report.evidence["accessible_study_count"] == 3


def test_explain_submission_failure_study_suggests_close_match():
    client = make_client_stub()
    diagnostics = RaveDiagnostics(client)
    error = RWSError("Study OID is invalid or not found", http_status=400)

    tx = RaveTransaction(study_oid="Mediflex Dev")
    report = diagnostics.explain_submission_failure(error, transaction=tx)

    assert report.category == "study_not_found"
    assert report.severity == "error"
    suggestions = report.evidence["suggested_matches"]
    assert any(s["value"] == "Mediflex (Dev)" for s in suggestions)


def test_explain_submission_failure_study_list_retrieval_fails_gracefully():
    client = Mock()
    client.get_studies_raw.side_effect = RWSError("Network down")
    diagnostics = RaveDiagnostics(client)
    error = RWSError("Study OID is invalid or not found", http_status=400)

    tx = RaveTransaction(study_oid="Anything")
    report = diagnostics.explain_submission_failure(error, transaction=tx)

    assert report.category == "study_not_found"
    assert report.evidence["accessible_study_count"] is None
    assert report.safe_to_retry is False


# -------------------------------------------------------------------
# 6. DiagnosticReport formatting
# -------------------------------------------------------------------


def test_diagnostic_report_format_human_readable_contains_key_sections():
    report = DiagnosticReport(
        category="study_not_found",
        severity="error",
        requested={"study_oid": "Mediflex Dev"},
        evidence={"accessible_study_count": 3},
        recommendation="Confirm the exact StudyOID.",
        safe_to_retry=False,
    )

    text = report.format_human_readable()

    assert "Study Not Found" in text
    assert "study_oid: Mediflex Dev" in text
    assert "accessible_study_count: 3" in text
    assert "Confirm the exact StudyOID." in text
    assert "Safe to retry automatically: False" in text