from __future__ import annotations
import datetime
import uuid
import xml.etree.ElementTree as ET
from xml.dom import minidom
from typing import Dict, Any, Optional

from .exceptions import HierarchyError
from .enums import ActionType, QueryStatus, QueryRecipient

MDSOL_NS = "http://www.mdsol.com/ns/odm/metadata"
ODM_NS = "http://www.cdisc.org/ns/odm/v1.3"

_DEFAULT_REPEAT_KEY = "1"

# Register namespaces once at module load so ET.tostring() emits clean
# prefixes (xmlns="..." and xmlns:mdsol="...") rather than ns0/ns1.
ET.register_namespace("", ODM_NS)
ET.register_namespace("mdsol", MDSOL_NS)


class RaveTransaction:
    """
    Builds a CDISC ODM transactional payload for submission to Medidata Rave
    Web Services (RWS), including Medidata-specific ODM extensions.

    Supports a fluent/chained builder API::

        tx = RaveTransaction("MY_STUDY")
        xml_bytes = (
            tx.subject("SUBJ-001", "SITE-01", ActionType.UPDATE)
              .event("VISIT_1", repeat_key="1")
              .form("DEMOGRAPHICS")
              .item_group("DM_IG", repeat_key="1", specified_items_only=True)
              .item("AGE", value="34")
              .build()
        )

    Pre-build validation::

        from raveforge import validate
        validate(tx)           # raises ValidationError if the transaction is malformed
        xml_bytes = tx.build() # safe to call after validation passes
    """

    def __init__(self, study_oid: str, metadata_version_oid: str = "1") -> None:
        self.study_oid: str = study_oid
        self.metadata_version_oid: str = metadata_version_oid
        self.file_oid: str = str(uuid.uuid4())

        self._subjects: Dict[str, Dict[str, Any]] = {}
        self._current_subject: Optional[str] = None
        self._current_site: Optional[str] = None
        self._current_event: Optional[str] = None
        self._current_form: Optional[str] = None
        self._current_group: Optional[str] = None

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    def __enter__(self) -> RaveTransaction:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> Optional[bool]:
        return None

    # ------------------------------------------------------------------
    # Builder methods
    # ------------------------------------------------------------------

    def subject(
        self,
        subject_key: str,
        site_oid: str,
        action: Optional[ActionType] = None,
    ) -> RaveTransaction:
        """Add or revisit a subject context.

        If the subject already exists in this transaction, its SiteOID and
        Action are updated to the values provided in the current call.
        The subject's accumulated events are always preserved.
        """
        if subject_key not in self._subjects:
            self._subjects[subject_key] = {"Events": {}}

        self._subjects[subject_key]["SiteOID"] = site_oid
        self._subjects[subject_key]["Action"] = action.value if action else None

        self._current_subject = subject_key
        self._current_site = site_oid
        self._current_event = None
        self._current_form = None
        self._current_group = None
        return self

    def event(
        self,
        event_oid: str,
        repeat_key: Optional[str] = None,
        action: Optional[ActionType] = None,
    ) -> RaveTransaction:
        """Add or switch to a study event context."""
        if not self._current_subject:
            raise HierarchyError("Subject context required before calling event().")
        effective_repeat_key = repeat_key if repeat_key is not None else _DEFAULT_REPEAT_KEY
        events = self._subjects[self._current_subject]["Events"]
        event_key = f"{event_oid}_{effective_repeat_key}"
        if event_key not in events:
            events[event_key] = {
                "OID": event_oid,
                "RepeatKey": effective_repeat_key,
                "Action": action.value if action else None,
                "Forms": {},
            }
        self._current_event = event_key
        self._current_form = None
        self._current_group = None
        return self

    def form(
        self,
        form_oid: str,
        repeat_key: Optional[str] = None,
        action: Optional[ActionType] = None,
    ) -> RaveTransaction:
        """Add or switch to a form context."""
        if not self._current_event:
            raise HierarchyError("Event context required before calling form().")
        effective_repeat_key = repeat_key if repeat_key is not None else _DEFAULT_REPEAT_KEY
        forms = self._subjects[self._current_subject]["Events"][self._current_event]["Forms"]
        form_key = f"{form_oid}_{effective_repeat_key}"
        if form_key not in forms:
            forms[form_key] = {
                "OID": form_oid,
                "RepeatKey": effective_repeat_key,
                "Action": action.value if action else None,
                "ItemGroups": {},
            }
        self._current_form = form_key
        self._current_group = None
        return self

    def item_group(
        self,
        item_group_oid: str,
        repeat_key: Optional[str] = None,
        action: Optional[ActionType] = None,
        specified_items_only: bool = False,
    ) -> RaveTransaction:
        """Add or switch to an item group context."""
        if not self._current_form:
            raise HierarchyError("Form context required before calling item_group().")
        groups = (
            self._subjects[self._current_subject]["Events"][self._current_event]
            ["Forms"][self._current_form]["ItemGroups"]
        )
        group_key = f"{item_group_oid}_{repeat_key or 'default'}"
        if group_key not in groups:
            groups[group_key] = {
                "OID": item_group_oid,
                "RepeatKey": repeat_key,
                "Action": action.value if action else None,
                "SpecifiedItemsOnly": specified_items_only,
                "Items": {},
            }
        self._current_group = group_key
        return self

    def item(
        self,
        item_oid: str,
        value: Optional[str] = None,
        specify: Optional[str] = None,
        query: Optional[str] = None,
        query_status: QueryStatus = QueryStatus.OPEN,
        query_recipient: QueryRecipient = QueryRecipient.SITE_FROM_SYSTEM,
    ) -> RaveTransaction:
        """
        Add an item (field value) to the current item group.

        Args:
            item_oid:        The ODM ItemOID.
            value:           The data value to submit.
            specify:         Free-text value for coded items with an open-other response.
            query:           Query text to attach as an mdsol:Query element.
            query_status:    Status of the query (default: Open).
            query_recipient: Recipient of the query (default: Site from System).
        """
        if not self._current_group:
            raise HierarchyError("ItemGroup context required before calling item().")
        items = (
            self._subjects[self._current_subject]["Events"][self._current_event]
            ["Forms"][self._current_form]["ItemGroups"][self._current_group]["Items"]
        )
        items[item_oid] = {
            "Value": value,
            "Specify": specify,
            "Query": query,
            "QueryStatus": query_status.value,
            "QueryRecipient": query_recipient.value,
        }
        return self

    # ------------------------------------------------------------------
    # Reset helpers
    # ------------------------------------------------------------------

    def reset_context(self) -> RaveTransaction:
        """Clear all active context pointers without discarding accumulated data."""
        self._current_subject = None
        self._current_site = None
        self._current_event = None
        self._current_form = None
        self._current_group = None
        return self

    def reset(self) -> RaveTransaction:
        """Fully reset the transaction, clearing all subjects and regenerating the file identity."""
        self._subjects = {}
        self.file_oid = str(uuid.uuid4())
        return self.reset_context()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self, encoding: str = "UTF-8") -> bytes:
        """Serialise the transaction to ODM XML bytes."""
        root = ET.Element("ODM", {
            "xmlns": ODM_NS,
            "FileType": "Transactional",
            "FileOID": self.file_oid,
            "CreationDateTime": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "ODMVersion": "1.3",
        })

        clinical_data = ET.SubElement(root, "ClinicalData", {
            "StudyOID": self.study_oid,
            "MetaDataVersionOID": self.metadata_version_oid,
        })

        for subj_key, subj_data in self._subjects.items():
            subj_attribs: Dict[str, str] = {"SubjectKey": subj_key}
            if subj_data["Action"]:
                subj_attribs["TransactionType"] = subj_data["Action"]

            subj_node = ET.SubElement(clinical_data, "SubjectData", subj_attribs)
            ET.SubElement(subj_node, "SiteRef", {"LocationOID": subj_data["SiteOID"]})

            for event_data in subj_data["Events"].values():
                event_attribs: Dict[str, str] = {
                    "StudyEventOID": event_data["OID"],
                    "StudyEventRepeatKey": event_data["RepeatKey"],
                }
                if event_data["Action"]:
                    event_attribs["TransactionType"] = event_data["Action"]
                event_node = ET.SubElement(subj_node, "StudyEventData", event_attribs)

                for form_data in event_data["Forms"].values():
                    form_attribs: Dict[str, str] = {
                        "FormOID": form_data["OID"],
                        "FormRepeatKey": form_data["RepeatKey"],
                    }
                    if form_data["Action"]:
                        form_attribs["TransactionType"] = form_data["Action"]
                    form_node = ET.SubElement(event_node, "FormData", form_attribs)

                    for group_data in form_data["ItemGroups"].values():
                        group_attribs: Dict[str, str] = {"ItemGroupOID": group_data["OID"]}
                        if group_data["RepeatKey"] is not None:
                            group_attribs["ItemGroupRepeatKey"] = group_data["RepeatKey"]
                        if group_data["Action"]:
                            group_attribs["TransactionType"] = group_data["Action"]
                        if group_data["SpecifiedItemsOnly"]:
                            group_attribs[f"{{{MDSOL_NS}}}Submission"] = "SpecifiedItemsOnly"

                        group_node = ET.SubElement(form_node, "ItemGroupData", group_attribs)

                        for item_oid, item_dict in group_data["Items"].items():
                            item_attribs: Dict[str, str] = {"ItemOID": item_oid}
                            if item_dict["Value"] is not None:
                                item_attribs["Value"] = str(item_dict["Value"])
                            if item_dict["Specify"] is not None:
                                item_attribs[f"{{{MDSOL_NS}}}SpecifyValue"] = str(item_dict["Specify"])

                            item_node = ET.SubElement(group_node, "ItemData", item_attribs)

                            if item_dict["Query"]:
                                ET.SubElement(
                                    item_node,
                                    f"{{{MDSOL_NS}}}Query",
                                    {
                                        "Value": str(item_dict["Query"]),
                                        "Status": item_dict["QueryStatus"],
                                        "Recipient": item_dict["QueryRecipient"],
                                    },
                                )

        return ET.tostring(root, encoding=encoding, xml_declaration=True)

    def build_pretty(self) -> str:
        """
        Serialise to a human-readable, indented XML string.

        Returns a Unicode string without an encoding declaration.
        Intended for debugging and logging; use :meth:`build` for transmission.
        """
        raw = self.build(encoding="unicode")
        parsed = minidom.parseString(raw)
        return parsed.toprettyxml(indent="  ", encoding=None)
