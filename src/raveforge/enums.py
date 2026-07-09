from enum import Enum

class ActionType(Enum):
    """Medidata custom transaction actions."""
    UPSERT = "Upsert"
    UPDATE = "Update"
    INSERT = "Insert"
    REPLACE = "Replace"