from enum import Enum


class ActionType(Enum):
    UPSERT = "Upsert"
    INSERT = "Insert"
    UPDATE = "Update"
    REMOVE = "Remove"


class QueryStatus(Enum):
    OPEN = "Open"
    ANSWERED = "Answered"
    CLOSED = "Closed"
    CANCELLED = "Cancelled"


class QueryRecipient(Enum):
    SITE = "Site"
    DM_FROM_SITE = "DM from Site"
    DM_FROM_SPONSOR = "DM from Sponsor"
    SPONSOR_FROM_SITE = "Sponsor from Site"
