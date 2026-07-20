from enum import Enum


class ActionType(str, Enum):
    """TransactionType values supported by Medidata Rave RWS."""
    INSERT = "Insert"
    UPDATE = "Update"
    UPSERT = "Upsert"
    DELETE = "Delete"
    CONTEXT = "Context"


class QueryStatus(str, Enum):
    """Valid status values for mdsol:Query elements."""
    OPEN = "Open"
    ANSWERED = "Answered"
    CLOSED = "Closed"
    CANDIDATE = "Candidate"
    OPEN_PENDING_REVIEW = "OpenPendingReview"


class QueryRecipient(str, Enum):
    """Valid recipient values for mdsol:Query elements."""
    SITE_FROM_SYSTEM = "Site from System"
    SITE_FROM_DM = "Site from DM"
    SITE_FROM_SPONSOR = "Site from Sponsor"
    DM_FROM_SITE = "DM from Site"
    DM_FROM_SPONSOR = "DM from Sponsor"
    SPONSOR_FROM_SITE = "Sponsor from Site"