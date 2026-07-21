from __future__ import annotations

from typing import List, Optional


class RaveForgeError(Exception):
    """Base exception for all RaveForge errors."""


class HierarchyError(RaveForgeError):
    """Raised when building an ODM structure out of its strict hierarchical order."""


class ValidationError(RaveForgeError):
    """
    Raised when the ODM transaction fails pre-build validation.

    Attributes:
        issues: The list of :class:`~raveforge.validator.ValidationIssue`
                objects that triggered this exception.  Empty when the
                exception is constructed from a raw message string rather than
                via the validator.
    """

    def __init__(self, message: str, issues: Optional[List] = None) -> None:
        super().__init__(message)
        self.issues: List = issues if issues is not None else []


class RWSError(RaveForgeError):
    """Raised when Medidata RWS returns an error response."""

    def __init__(
        self,
        message: str,
        rws_code: Optional[str] = None,
        http_status: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.rws_code = rws_code
        self.http_status = http_status

    def __str__(self) -> str:
        parts = [super().__str__()]
        if self.rws_code is not None:
            parts.append(f"RWS Code: {self.rws_code}")
        if self.http_status is not None:
            parts.append(f"HTTP Status: {self.http_status}")
        return " | ".join(parts)
