"""Tests for the ODM validation layer (raveforge.validator)."""

import pytest

from raveforge import (
    RaveTransaction,
    Severity,
    ValidationError,
    ValidationIssue,
    validate,
)
