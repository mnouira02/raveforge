class RaveForgeError(Exception):
    """Base exception for all RaveForge errors."""
    pass

class HierarchyError(RaveForgeError):
    """Raised when building an ODM structure out of its strict hierarchical order."""
    pass