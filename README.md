# RaveForge

An elegant, zero-dependency Python builder for Medidata Rave ODM XML.

Let's be honest: pushing clinical data, lab results, or AI risk scores into Medidata Rave Web Services (RWS) is usually a headache. Integration pipelines quickly turn into a mess of fragile XML string concatenations, nested dictionary hacks, and constant wrestling with `mdsol` namespaces. 

RaveForge was built to fix that. It is a stateful, fluent Python engine that translates flat data into perfectly nested, RWS-compliant ODM XML without you ever having to write or format a single XML tag.

## Why use RaveForge?

* **It remembers your state:** Clinical data is deeply nested (`Subject > Event > Form > ItemGroup`). Because RaveForge is stateful, you set the context once, and the library automatically attaches your data points exactly where they belong.
* **Fails locally, not on the network:** If you accidentally try to add an item before defining a form, RaveForge throws a clear Python error immediately. It prevents you from pushing malformed CDISC hierarchies to Rave, saving you from expensive, silent HTTP timeouts.
* **Zero dependencies:** It is built entirely on the Python Standard Library. No bloated requirements, making it incredibly easy to install and approve in locked-down corporate clinical environments.

---

## Installation

```bash
pip install raveforge
```

---

## Quick Start: The Fluent Builder

Here is what it looks like to generate a transaction. Notice how clean the method chaining is compared to standard XML DOM manipulation.

```python
from raveforge import RaveTransaction, ActionType

# Initialize the transaction envelope
tx = RaveTransaction(study_oid="Oncology_Phase_II(Prod)")

# Chain the hierarchy context and inject your data
(
    tx.subject(subject_key="SUBJ-001", site_oid="SITE-101", action=ActionType.UPSERT)
      .event("SCREENING")
      .form("VS")
      .item_group("VS_GROUP")
      .item("VSTEST", "Weight")
      .item("VSORRES", "75")
)

# Generate the perfectly namespaced, RWS-compliant XML payload
xml_payload = tx.build()
```

## The Real Power: Pandas & Bulk Integration

RaveForge really shines when combined with data engineering pipelines or MLOps workflows. If you are reading from a CSV, a database, or a Pandas DataFrame, batching the data is incredibly straightforward.

```python
import pandas as pd
import requests
from raveforge import RaveTransaction

df = pd.read_csv("automated_risk_scores.csv")
tx = RaveTransaction(study_oid="Project_Mediflex_2026")

for _, row in df.iterrows():
    # The builder context switches automatically as it loops
    (
        tx.subject(row['SubjectKey'], site_oid=row['SiteID'])
          .event(row['StudyEvent'])
          .form(row['FormOID'])
          .item_group(row['ItemGroup'])
    )
    
    # Bulk inject an entire dictionary of items for this specific row
    tx.batch_items({
        "RSK_SCORE": row['RiskScore'],
        "RSK_FLAG": row['HighRiskFlag'],
        "LBDAT": row['AnalysisDate']
    })

# Push directly to Medidata RWS
response = requests.post(
    "[https://innovate.mdsol.com/RaveWebServices/webservice.aspx?PostODMClinicalData](https://innovate.mdsol.com/RaveWebServices/webservice.aspx?PostODMClinicalData)",
    data=tx.build(), 
    headers={'Content-Type': 'text/xml'},
    auth=('username', 'password')
)
```

## Contributing

Pull requests are always welcome. If you are adding new RWS features (like manual query generation), please ensure all additions are fully covered by the internal `pytest` validation suite.

## License

MIT License