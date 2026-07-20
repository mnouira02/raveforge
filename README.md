# RaveForge

An elegant Python builder for Medidata Rave ODM XML.

Pushing clinical data, lab results, operational signals, or AI-derived outputs into Medidata Rave Web Services (RWS) often becomes a mess of fragile XML string concatenation, namespace issues, and hard-to-maintain hierarchy handling. RaveForge was built to make that process clean, explicit, and reliable.

RaveForge is a fluent, stateful Python engine for building RWS-friendly ODM XML without manually writing XML tags. It helps you construct properly nested `Subject > Event > Form > ItemGroup > Item` structures and optionally submit them through a lightweight RWS client.

---

## Features

- Fluent builder API for CDISC ODM clinical data transactions
- Stateful hierarchy handling for `Subject > Event > Form > ItemGroup > Item`
- Early hierarchy validation with clear Python exceptions
- Support for Medidata-specific `mdsol` extensions
- Query generation with configurable status and recipient
- Support for item `SpecifyValue`
- Pretty-printed XML output for debugging
- Thin RWS client for submission to Medidata RWS
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

## Why use RaveForge?

- It keeps hierarchy handling readable and safe.
- It fails locally before bad ODM hits the network.
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