# RaveForge

An elegant Python builder for Medidata Rave ODM XML.

Pushing clinical data, lab results, operational signals, or AI-derived outputs into Medidata Rave Web Services (RWS) often becomes a mess of fragile XML string concatenation, namespace issues, and hard-to-maintain hierarchy handling. RaveForge was built to make that process clean, explicit, and reliable.

RaveForge is a fluent, stateful Python engine for building RWS-friendly ODM XML without manually writing XML tags. It helps you construct properly nested `Subject > Event > Form > ItemGroup > Item` structures, optionally validates the transaction before serialisation, and optionally submits through a lightweight RWS client.

---

## Features

- Fluent builder API for CDISC ODM clinical data transactions
- Stateful hierarchy handling for `Subject > Event > Form > ItemGroup > Item`
- Early hierarchy validation with clear Python exceptions
- **Pre-build structural validation** with aggregated, location-aware error reporting
- Support for Medidata-specific `mdsol` extensions
- Query generation with configurable status and recipient
- Support for item `SpecifyValue`
- Pretty-printed XML output for debugging
- Thin RWS client for submission to Medidata RWS
- Read-only diagnostics layer for interpreting RWS submission failures
- Tested with `pytest`

---

## Installation

```bash
pip install raveforge
```

For development:

```bash
pip install -e .[dev]
```

---

## Quick Start

```python
from raveforge import RaveTransaction, ActionType

tx = (
    RaveTransaction(study_oid="Oncology_Phase_II_Prod")
    .subject("SUBJ-001", site_oid="SITE-101", action=ActionType.UPSERT)
    .event("SCREENING", repeat_key="1")
    .form("VS", repeat_key="1")
    .item_group("VS_GROUP", repeat_key="1")
    .item("VSTEST", "Weight")
    .item("VSORRES", "75")
)

xml_payload = tx.build()
print(tx.build_pretty())
```

---

## Pre-build Validation

Call `validate()` before `build()` to catch structural and semantic problems early, with a single aggregated report instead of one exception at a time.

```python
from raveforge import RaveTransaction, validate, ValidationError

tx = (
    RaveTransaction(study_oid="Oncology_Phase_II_Prod")
    .subject("SUBJ-001", site_oid="SITE-101")
    .event("SCREENING")
    .form("VS")
    .item_group("VS_GROUP")
    .item("VSORRES", "75")
)

try:
    validate(tx)           # raises ValidationError if anything is wrong
    xml_payload = tx.build()
except ValidationError as err:
    print(err)
```

Sample output for an empty study OID and a subject with no events:

```
2 validation issue(s) found:
  [ERROR] STUDY_OID_EMPTY []: study_oid must not be empty.
  [WARNING] SUBJECT_NO_EVENTS [SUBJ-001]: Subject 'SUBJ-001' has no events. ...
```

### Strict vs. non-strict mode

By default `validate()` runs in **strict mode**: both `ERROR` and `WARNING`
severity issues raise `ValidationError`. Pass `strict=False` to raise only on
errors and receive warnings as return values:

```python
from raveforge import validate, Severity

issues = validate(tx, strict=False)   # never raises on WARNING
warnings = [i for i in issues if i.severity == Severity.WARNING]
for w in warnings:
    print(w)
```

### What the validator checks

| Code | Severity | Trigger |
|---|---|---|
| `STUDY_OID_EMPTY` | ERROR | `study_oid` is blank or whitespace-only |
| `STUDY_OID_INVALID_CHARS` | ERROR | `study_oid` contains `<`, `>`, or `&` |
| `NO_SUBJECTS` | WARNING | Transaction has no subjects at all |
| `SUBJECT_KEY_EMPTY` | ERROR | A subject was added with an empty `SubjectKey` |
| `SUBJECT_NO_EVENTS` | WARNING | A subject has no events |
| `SITE_OID_EMPTY` | ERROR | A subject's `SiteOID` is blank |
| `EVENT_NO_FORMS` | WARNING | An event has no forms |
| `EVENT_OID_EMPTY` | ERROR | An event has a blank OID |
| `FORM_NO_ITEM_GROUPS` | WARNING | A form has no item groups |
| `FORM_OID_EMPTY` | ERROR | A form has a blank OID |
| `ITEM_GROUP_OID_EMPTY` | ERROR | An item group has a blank OID |
| `ITEM_NO_VALUE` | WARNING | An item has no value, specify, or query |
| `ITEM_OID_EMPTY` | ERROR | An item has a blank OID |

---

## Queries and Specify Values

```python
from raveforge import (
    RaveTransaction,
    QueryStatus,
    QueryRecipient,
)

tx = (
    RaveTransaction("Mediflex_Study")
    .subject("SUBJ-1001", "SITE-NL-01")
    .event("VISIT_1")
    .form("LABS")
    .item_group("LABS_IG", specified_items_only=True)
    .item(
        "LBTEST",
        value="OTHER",
        specify="Custom Biomarker Panel",
        query="Please confirm the local lab method.",
        query_status=QueryStatus.OPEN,
        query_recipient=QueryRecipient.SITE_FROM_DM,
    )
)

xml_payload = tx.build()
```

---

## Submitting to RWS

```python
from raveforge import RaveTransaction
from raveforge.rws_client import RWSClient

tx = (
    RaveTransaction("Mediflex_Study")
    .subject("SUBJ-001", "SITE-001")
    .event("SCREENING")
    .form("DM")
    .item_group("DM_IG")
    .item("AGE", "42")
)

client = RWSClient(
    base_url="https://innovate.mdsol.com",
    username="username",
    password="password",
)

response = client.post_odm(tx.build())
print(response)
```

---

## Diagnosing Submission Failures

`RaveDiagnostics` interprets RWS errors after a failed submission, performs
read-only lookups against RWS, and returns structured, evidence-based
reports. It never modifies your transaction or selects a study on your behalf.

```python
from raveforge import RaveTransaction, RWSError, RaveDiagnostics
from raveforge.rws_client import RWSClient

tx = (
    RaveTransaction("Mediflex_Dev")
    .subject("SUBJ-001", "SITE-001")
    .event("SCREENING")
    .form("DM")
    .item_group("DM_IG")
    .item("AGE", "42")
)

client = RWSClient(
    base_url="https://innovate.mdsol.com",
    username="username",
    password="password",
)

diagnostics = RaveDiagnostics(client)

try:
    client.post_odm(tx.build())
except RWSError as error:
    report = diagnostics.explain_submission_failure(error, transaction=tx)
    print(report)
```

Sample output for a study OID mismatch:

```
[ERROR] Study Not Found

Requested:
  study_oid: Mediflex_Dev

Evidence:
  accessible_study_count: 4
  close_matches: [{'value': 'Mediflex_DEV', 'similarity': 0.95}]

Recommendation:
  Confirm the intended environment and use the exact StudyOID
  configured in Rave. No payload was changed automatically.

Safe to retry automatically: False
```

---

## Why use RaveForge?

- It keeps hierarchy handling readable and safe.
- It validates your payload locally before bad ODM hits the network.
- It fails fast with precise, location-aware error messages.
- It reduces XML-handling boilerplate in clinical integrations.
- It works well in automation pipelines that generate transactional ODM.

---

## Testing

Run the test suite with:

```bash
pytest -v
```

---

## Contributing

Pull requests are welcome. If you add new builder or RWS features, please include or update pytest coverage.

---

## License

MIT License
