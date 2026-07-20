class RaveForgeError(Exception):
    """Base exception for all RaveForge errors."""
    pass


class HierarchyError(RaveForgeError):
    """Raised when building an ODM structure out of its strict hierarchical order."""
    pass


class ValidationError(RaveForgeError):
    """Raised when the ODM transaction fails pre-build validation."""
    pass


class RWSError(RaveForgeError):
    """Raised when Medidata RWS returns an error response."""

    def __init__(self, message: str, rws_code: str = None, http_status: int = None):
        super().__init__(message)
        self.rws_code = rws_code
        self.http_status = http_status

    def __str__(self):
        parts = [super().__str__()]
        if self.rws_code:
            parts.append(f"RWS Code: {self.rws_code}")
        if self.http_status:
            parts.append(f"HTTP Status: {self.http_status}")
        return " | ".join(parts)