from unittest.mock import Mock

from raveforge import DiagnosticReport, RaveDiagnostics, RaveTransaction, RWSError

SAMPLE_STUDIES_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<ODM xmlns="http://www.cdisc.org/ns/odm/v1.3"'
    ' FileType="Snapshot" FileOID="abc"'
    ' CreationDateTime="2026-01-01T00:00:00" ODMVersion="1.3">\n'
    '  <Study OID="Mediflex_01">\n'
    '    <GlobalVariables>\n'
    '      <StudyName>Mediflex Phase III</StudyName>\n'
    '    </GlobalVariables>\n'
    '  </Study>\n'
    '  <Study OID="ACME_Study_02">\n'
    '    <GlobalVariables>\n'
    '      <StudyName>ACME Phase II</StudyName>\n'
    '    </GlobalVariables>\n'
    '  </Study>\n'
    '  <Study OID="Pilot_XYZ">\n'
    '    <GlobalVariables>\n'
    '      <StudyName>Pilot XYZ</StudyName>\n'
    '    </GlobalVariables>\n'
    '  </Study>\n'
    '</ODM>'
)

SAMPLE_SITES_XML = (
    '<ODM xmlns="http://www.cdisc.org/ns/odm/v1.3">'
    '  <Location OID="SITE-001" />'
    '  <Location OID="SITE-002" />'
    '  <Location OID="SITE-ALPHA" />'
    '</ODM>'
)


def make_client(
    studies_xml: str = SAMPLE_STUDIES_XML,
    sites_xml: str = SAMPLE_SITES_XML,
) -> Mock:
    client = Mock()
    client.get_studies_raw.return_value = studies_xml
    client.get_sites_raw.return_value = sites_xml
    return client


# -------------------------------------------------------------------
# RaveDiagnostics.get_studies
# -------------------------------------------------------------------


def test_get_studies_returns_list_of_dicts():
    """Validates the studies parser returns a list of OID/name dicts."""
    diag = RaveDiagnostics(make_client())
    studies = diag.get_studies()

    assert len(studies) == 3
    oids = [s["oid"] for s in studies]
    assert "Mediflex_01" in oids
    assert "ACME_Study_02" in oids
    assert "Pilot_XYZ" in oids


def test_get_studies_includes_names():
    """Validates the study name is extracted from GlobalVariables/StudyName."""
    diag = RaveDiagnostics(make_client())
    studies = diag.get_studies()

    names = {s["oid"]: s["name"] for s in studies}
    assert names["Mediflex_01"] == "Mediflex Phase III"
    assert names["ACME_Study_02"] == "ACME Phase II"
    assert names["Pilot_XYZ"] == "Pilot XYZ"


def test_get_studies_returns_empty_on_malformed_xml():
    """Validates that malformed XML returns an empty list rather than raising."""
    client = Mock()
    client.get_studies_raw.return_value = "<<not valid xml"
    diag = RaveDiagnostics(client)

    studies = diag.get_studies()

    assert studies == []


def test_get_studies_falls_back_to_oid_when_name_missing():
    """Validates that the OID is used as the name when StudyName is absent."""
    xml = (
        '<ODM xmlns="http://www.cdisc.org/ns/odm/v1.3">'
        '<Study OID="NONAME_01"></Study>'
        '</ODM>'
    )
    client = Mock()
    client.get_studies_raw.return_value = xml
    diag = RaveDiagnostics(client)

    studies = diag.get_studies()

    assert len(studies) == 1
    assert studies[0]["oid"] == "NONAME_01"
    assert studies[0]["name"] == "NONAME_01"


# -------------------------------------------------------------------
# RaveDiagnostics.categorize_error
# -------------------------------------------------------------------


def test_categorize_error_401():
    error = RWSError("Unauthorised.", http_status=401)
    assert RaveDiagnostics.categorize_error(error) == "authentication_failed"


def test_categorize_error_403():
    error = RWSError("Forbidden.", http_status=403)
    assert RaveDiagnostics.categorize_error(error) == "authorization_failed"


def test_categorize_error_409():
    error = RWSError("Conflict.", http_status=409)
    assert RaveDiagnostics.categorize_error(error) == "conflict"


def test_categorize_error_500():
    error = RWSError("Server exploded.", http_status=500)
    assert RaveDiagnostics.categorize_error(error) == "server_error"


def test_categorize_error_subject_not_found():
    error = RWSError("Subject not found.", http_status=404)
    assert RaveDiagnostics.categorize_error(error) == "subject_not_found"


def test_categorize_error_site_not_found():
    error = RWSError("Site invalid.", http_status=404)
    assert RaveDiagnostics.categorize_error(error) == "site_not_found"


def test_categorize_error_study_not_found():
    error = RWSError("Study not found or invalid study OID.", http_status=404)
    assert RaveDiagnostics.categorize_error(error) == "study_not_found"


def test_categorize_error_unknown():
    error = RWSError("Something strange.", http_status=404)
    assert RaveDiagnostics.categorize_error(error) == "not_found"


# -------------------------------------------------------------------
# RaveDiagnostics.diagnose
# -------------------------------------------------------------------


def test_diagnose_authentication_failure_returns_report():
    """Validates a 401 error returns a structured DiagnosticReport."""
    diag = RaveDiagnostics(make_client())
    error = RWSError("Unauthorised.", http_status=401)
    tx = RaveTransaction("Mediflex_01")

    report = diag.explain_submission_failure(error, tx)

    assert isinstance(report, DiagnosticReport)
    assert report.category == "authentication_failed"
    assert report.severity == "error"
    assert report.safe_to_retry is False


def test_diagnose_authorization_failure_returns_report():
    """Validates a 403 error returns a structured DiagnosticReport."""
    diag = RaveDiagnostics(make_client())
    error = RWSError("Forbidden.", http_status=403)
    tx = RaveTransaction("Mediflex_01")

    report = diag.explain_submission_failure(error, tx)

    assert report.category == "authorization_failed"
    assert report.severity == "error"
    assert report.safe_to_retry is False


def test_diagnose_conflict_returns_report():
    """Validates a 409 error returns a structured DiagnosticReport."""
    diag = RaveDiagnostics(make_client())
    error = RWSError("Conflict.", http_status=409)
    tx = RaveTransaction("Mediflex_01")

    report = diag.explain_submission_failure(error, tx)

    assert report.category == "conflict"
    assert report.severity == "error"
    assert report.safe_to_retry is False


def test_diagnose_server_error_returns_safe_to_retry_true():
    """Validates a 500 server error is flagged as safe to retry."""
    diag = RaveDiagnostics(make_client())
    error = RWSError("Internal Server Error.", http_status=500)
    tx = RaveTransaction("Mediflex_01")

    report = diag.explain_submission_failure(error, tx)

    assert report.category == "server_error"
    assert report.safe_to_retry is True


def test_diagnose_study_not_found_includes_close_matches():
    """Validates that a study_not_found diagnosis surfaces close OID matches."""
    diag = RaveDiagnostics(make_client())
    error = RWSError("Study not found.", http_status=404)
    # Slightly misspelled OID — Mediflex_01 vs Mediflex_0l
    tx = RaveTransaction("Mediflex_0l")

    report = diag.explain_submission_failure(error, tx)

    assert report.category == "study_not_found"
    assert "accessible_study_count" in report.evidence
    assert report.evidence["accessible_study_count"] == 3
    # A close match should be suggested
    assert "close_matches" in report.evidence
    assert len(report.evidence["close_matches"]) >= 1
    suggested_oids = [m["value"] for m in report.evidence["close_matches"]]
    assert "Mediflex_01" in suggested_oids


def test_diagnose_study_not_found_no_matches_when_completely_different():
    """Validates no close matches are returned when the OID is completely different."""
    diag = RaveDiagnostics(make_client())
    error = RWSError("Study not found.", http_status=404)
    tx = RaveTransaction("ZZZZZZZ_99999")

    report = diag.explain_submission_failure(error, tx)

    assert report.category == "study_not_found"
    assert report.evidence["close_matches"] == []


def test_diagnose_study_not_found_exact_match_found():
    """Validates exact OID match surfaces with similarity 1.0."""
    diag = RaveDiagnostics(make_client())
    error = RWSError("Study not found.", http_status=404)
    tx = RaveTransaction("Mediflex_01")

    report = diag.explain_submission_failure(error, tx)

    assert report.category == "study_not_found"
    close_matches = report.evidence["close_matches"]
    exact = next(
        (m for m in close_matches if m["value"] == "Mediflex_01"), None
    )
    assert exact is not None
    assert exact["similarity"] == 1.0


# -------------------------------------------------------------------
# site_not_found branch
# -------------------------------------------------------------------


def test_diagnose_site_not_found_includes_close_matches():
    """A slightly misspelled SiteOID should surface the closest known site."""
    diag = RaveDiagnostics(make_client())
    error = RWSError("Site invalid.", http_status=404)
    tx = RaveTransaction("Mediflex_01")
    # SITE-001 vs SITE-00l (letter l instead of digit 1)
    tx.subject("SUBJ-001", "SITE-00l").event("V1").form("DM").item_group("G1").item(
        "AGE", value="30"
    )

    report = diag.explain_submission_failure(error, tx)

    assert report.category == "site_not_found"
    assert report.severity == "error"
    assert "accessible_site_count" in report.evidence
    assert report.evidence["accessible_site_count"] == 3
    assert "close_matches" in report.evidence
    suggested = [m["value"] for m in report.evidence["close_matches"]]
    assert "SITE-001" in suggested


def test_diagnose_site_not_found_no_matches_when_completely_different():
    """No close matches when the SiteOID bears no resemblance to known sites."""
    diag = RaveDiagnostics(make_client())
    error = RWSError("Site invalid.", http_status=404)
    tx = RaveTransaction("Mediflex_01")
    tx.subject("SUBJ-001", "ZZZZZZZ").event("V1").form("DM").item_group("G1").item(
        "AGE", value="30"
    )

    report = diag.explain_submission_failure(error, tx)

    assert report.category == "site_not_found"
    assert report.evidence["close_matches"] == []


# -------------------------------------------------------------------
# subject_not_found branch
# -------------------------------------------------------------------


def test_diagnose_subject_not_found_returns_subject_keys():
    """Validates that the subject keys from the transaction are surfaced."""
    diag = RaveDiagnostics(make_client())
    error = RWSError("Subject not found.", http_status=404)
    tx = RaveTransaction("Mediflex_01")
    tx.subject("SUBJ-001", "SITE-001").event("V1").form("DM").item_group("G1").item(
        "AGE", value="30"
    )

    report = diag.explain_submission_failure(error, tx)

    assert report.category == "subject_not_found"
    assert report.severity == "error"
    assert report.safe_to_retry is False
    assert "SUBJ-001" in report.requested["subject_keys"]
    assert report.evidence["subject_count_in_transaction"] == 1


# -------------------------------------------------------------------
# DiagnosticReport.format_human_readable
# -------------------------------------------------------------------


def test_diagnostic_report_format_human_readable_contains_key_sections():
    """Validates format_human_readable output includes all major sections."""
    report = DiagnosticReport(
        category="study_not_found",
        severity="error",
        requested={"study_oid": "MISSING_STUDY"},
        evidence={"accessible_study_count": 3},
        recommendation="Confirm the exact StudyOID.",
        safe_to_retry=False,
    )

    text = report.format_human_readable()

    assert "[ERROR]" in text
    assert "Study Not Found" in text
    assert "study_oid: MISSING_STUDY" in text
    assert "accessible_study_count: 3" in text
    assert "Confirm the exact StudyOID." in text
    assert "Safe to retry automatically: False" in text


def test_diagnostic_report_str_delegates_to_format_human_readable():
    """Validates __str__ returns the same output as format_human_readable."""
    report = DiagnosticReport(
        category="authentication_failed",
        severity="error",
        safe_to_retry=False,
    )
    assert str(report) == report.format_human_readable()
