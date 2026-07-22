# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.4.0] - 2026-07-22

### Added
- `RaveDiagnostics.get_sites()` — retrieves site OIDs for a given study via `client.get_sites_raw()`
- `RaveDiagnostics._parse_site_oids()` — parses bare and ODM-namespaced `<Location>` elements
- `RaveDiagnostics._diagnose_site_not_found()` — full fuzzy-match diagnostic for `site_not_found` errors, mirroring the study-not-found flow
- `RaveDiagnostics._diagnose_subject_not_found()` — structured guidance for `subject_not_found` errors; correctly omits fuzzy matching because RWS exposes no subject list endpoint
- `RaveDiagnostics._extract_site_oid()` — read-only transaction inspector returning the first SiteOID
- `RaveDiagnostics._extract_subject_keys()` — read-only transaction inspector returning all subject keys
- `explain_submission_failure()` now routes `site_not_found` and `subject_not_found` categories to their respective private diagnostic methods
- Complete test coverage for all three new `explain_submission_failure` branches (`site_not_found` ×2, `subject_not_found` ×1)
- `CHANGELOG.md` (this file)

### Fixed
- `tests/test_validator.py` — broke three long fluent-chain lines that exceeded the `ruff` 100-character limit (`E501`)

---

## [0.3.0] - 2026-07-21

### Added
- `validator.py` — full ODM validation layer with severity-aware rule registry
  - Rules: `STUDY_OID_EMPTY`, `STUDY_OID_INVALID_CHARS`, `NO_SUBJECTS`, `SITE_OID_EMPTY`,
    `SUBJECT_NO_EVENTS`, `EVENT_NO_FORMS`, `FORM_NO_ITEM_GROUPS`, `ITEM_NO_VALUE`
  - `strict` flag promotes `WARNING`-level issues to `ValidationError`
  - Aggregates all issues in a single pass before raising
- `ValidationIssue` dataclass with `severity`, `code`, `message`, `location`, and `__str__`
- `validate()` public entry point exported from `raveforge.__init__`
- Comprehensive test suite for `validator.py` (`tests/test_validator.py`)

---

## [0.2.0] - 2026-07-20

### Added
- `diagnostics.py` — `RaveDiagnostics` class with `explain_submission_failure()`, `categorize_error()`, `get_studies()`, and `_diagnose_study_not_found()` with fuzzy OID matching
- `DiagnosticReport` dataclass with `format_human_readable()` and `__str__`
- `rws_client.py` — `RWSClient` with session reuse, configurable timeout, `post_odm()`, `ping()`, `get_studies_raw()`, and `_extract_rws_code()`
- Handles RWS errors embedded in HTTP 200 responses (`IsTransactionSuccessful=false`)
- `exceptions.py` — `RaveForgeError`, `HierarchyError`, `ValidationError`, `RWSError` hierarchy

---

## [0.1.0] - 2026-07-19

### Added
- `core.py` — `RaveTransaction` fluent builder for Medidata Rave ODM XML
  - Full hierarchy: `subject()` → `event()` → `form()` → `item_group()` → `item()`
  - Context manager support
  - `build()` / `build_pretty()` returning ODM-compliant XML bytes
  - `reset()` / `reset_context()`
- `enums.py` — `TransactionType` enum (`INSERT`, `UPDATE`, `UPSERT`)
- `__init__.py` — clean public API with `__all__` and pinned `__version__`
- `pyproject.toml` — PyPI-ready metadata, ruff, pytest-cov configuration
