"""Core logic and processing engine for RaveForge."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4
from xml.dom import minidom

from .enums import ActionType, QueryRecipient, QueryStatus
from .exceptions import HierarchyError

MDSOL_NS = "http://www.mdsol.com/ns/odm/metadata"
ODM_NS = "http://www.cdisc.org/ns/odm/v1.3"

_DEFAULT_REPEAT_KEY = "1"

ET.register_namespace("", ODM_NS)
ET.register_namespace("mdsol", MDSOL_NS)


class RaveTransaction:
    """
    Build a CDISC ODM transactional payload for Medidata Rave Web Services.

    Example:
        xml_bytes = (
            RaveTransaction("MY_STUDY")
            .subject("SUBJ-001", "SITE-01", ActionType.UPDATE)
            .event("VISIT_1")
            .form("DEMOGRAPHICS")
            .item_group("DM_IG", specified_items_only=True)
            .item("AGE", value="34")
            .build()
        )
    """

    def __init__(self, study_oid: str, metadata_version_oid: str = "1") -> None:
        self.study_oid = study_oid
        self.metadata_version_oid = metadata_version_oid
        self.file_oid = str(uuid4())

        self._subjects: dict[str, dict[str, Any]] = {}

        self._current_subject: Optional[str] = None
        self._current_site: Optional[str] = None
        self._current_event: Optional[str] = None
        self._current_form: Optional[str] = None
        self._current_group: Optional[str] = None

    def __enter__(self) -> RaveTransaction:
        return self

    def __exit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        return None

    def subject(
        self,
        subject_key: str,
        site_oid: str,
        action: Optional[ActionType] = None,
    ) -> RaveTransaction:
        """Add or revisit a subject context."""
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
        repeat_key: Optional[str] = _DEFAULT_REPEAT_KEY,
        action: Optional[ActionType] = None,
    ) -> RaveTransaction:
        """Add or switch to a study event context."""
        if self._current_subject is None:
            raise HierarchyError("Subject context required before calling event().")

        events = self._subjects[self._current_subject]["Events"]
        event_key = f"{event_oid}_{repeat_key}"

        if event_key not in events:
            events[event_key] = {
                "OID": event_oid,
                "RepeatKey": repeat_key,
                "Action": action.value if action else None,
                "Forms": {},
            }
        elif action is not None:
            events[event_key]["Action"] = action.value

        self._current_event = event_key
        self._current_form = None
        self._current_group = None
        return self

    def form(
        self,
        form_oid: str,
        repeat_key: Optional[str] = _DEFAULT_REPEAT_KEY,
        action: Optional[ActionType] = None,
    ) -> RaveTransaction:
        """Add or switch to a form context."""
        if self._current_event is None or self._current_subject is None:
            raise HierarchyError("Event context required before calling form().")

        forms = self._subjects[self._current_subject]["Events"][self._current_event][
            "Forms"
        ]
        form_key = f"{form_oid}_{repeat_key}"

        if form_key not in forms:
            forms[form_key] = {
                "OID": form_oid,
                "RepeatKey": repeat_key,
                "Action": action.value if action else None,
                "ItemGroups": {},
            }
        elif action is not None:
            forms[form_key]["Action"] = action.value

        self._current_form = form_key
        self._current_group = None
        return self

    def item_group(
        self,
        item_group_oid: str,
        repeat_key: Optional[str] = _DEFAULT_REPEAT_KEY,
        action: Optional[ActionType] = None,
        specified_items_only: bool = False,
    ) -> RaveTransaction:
        """Add or switch to an item-group context."""
        if (
            self._current_subject is None
            or self._current_event is None
            or self._current_form is None
        ):
            raise HierarchyError("Form context required before calling item_group().")

        groups = self._subjects[self._current_subject]["Events"][self._current_event][
            "Forms"
        ][self._current_form]["ItemGroups"]
        group_key = f"{item_group_oid}_{repeat_key}"

        if group_key not in groups:
            groups[group_key] = {
                "OID": item_group_oid,
                "RepeatKey": repeat_key,
                "Action": action.value if action else None,
                "SpecifiedItemsOnly": specified_items_only,
                "Items": {},
            }
        else:
            if action is not None:
                groups[group_key]["Action"] = action.value
            groups[group_key]["SpecifiedItemsOnly"] = specified_items_only

        self._current_group = group_key
        return self

    def item(
        self,
        item_oid: str,
        value: Optional[str] = None,
        *,
        specify: Optional[str] = None,
        query: Optional[str] = None,
        query_status: QueryStatus = QueryStatus.OPEN,
        query_recipient: QueryRecipient = QueryRecipient.SITE_FROM_SYSTEM,
    ) -> RaveTransaction:
        """Add an item to the current item group."""
        if (
            self._current_subject is None
            or self._current_event is None
            or self._current_form is None
            or self._current_group is None
        ):
            raise HierarchyError("ItemGroup context required before calling item().")

        items = self._subjects[self._current_subject]["Events"][self._current_event][
            "Forms"
        ][self._current_form]["ItemGroups"][self._current_group]["Items"]

        items[item_oid] = {
            "Value": value,
            "Specify": specify,
            "Query": query,
            "QueryStatus": query_status.value,
            "QueryRecipient": query_recipient.value,
        }
        return self

    def reset_context(self) -> RaveTransaction:
        """Clear active builder context without discarding accumulated data."""
        self._current_subject = None
        self._current_site = None
        self._current_event = None
        self._current_form = None
        self._current_group = None
        return self

    def reset(self) -> RaveTransaction:
        """Clear all transaction data and generate a new ODM FileOID."""
        self._subjects = {}
        self.file_oid = str(uuid4())
        return self.reset_context()

    def build(self, encoding: str = "UTF-8") -> bytes | str:
        """
        Serialize the transaction to an ODM XML payload.

        Pass ``encoding="unicode"`` to receive a string without an XML
        declaration. All other encodings return bytes with an XML declaration.
        """
        root = ET.Element(
            "ODM",
            {
                "xmlns": ODM_NS,
                "FileType": "Transactional",
                "FileOID": self.file_oid,
                "CreationDateTime": datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%S"
                ),
                "ODMVersion": "1.3",
            },
        )

        clinical_data = ET.SubElement(
            root,
            "ClinicalData",
            {
                "StudyOID": self.study_oid,
                "MetaDataVersionOID": self.metadata_version_oid,
            },
        )

        for subject_key, subject_data in self._subjects.items():
            self._build_subject_node(clinical_data, subject_key, subject_data)

        raw_data = ET.tostring(root, encoding=encoding, xml_declaration=True)

        if isinstance(raw_data, bytes) and encoding.lower() != "unicode":
            xml_str = raw_data.decode(encoding)
            if xml_str.startswith("<?xml"):
                decl_end = xml_str.find(">")
                xml_str = (
                    xml_str[: decl_end + 1].replace("'", '"')
                    + xml_str[decl_end + 1 :]
                )
            return xml_str.encode(encoding)

        return raw_data

    def build_pretty(self) -> str:
        """
        Serialize to human-readable, indented XML.

        Returns a Unicode string including an XML declaration.
        Intended for debugging and logging.
        """
        raw = self.build(encoding="unicode")
        parsed = minidom.parseString(raw)
        return parsed.toprettyxml(indent="  ")

    def _build_subject_node(
        self,
        clinical_data: ET.Element,
        subject_key: str,
        subject_data: dict[str, Any],
    ) -> None:
        """Build the SubjectData node and descendants."""
        subject_attributes: dict[str, str] = {"SubjectKey": subject_key}

        if subject_data.get("Action"):
            subject_attributes["TransactionType"] = subject_data["Action"]

        subject_node = ET.SubElement(clinical_data, "SubjectData", subject_attributes)
        ET.SubElement(
            subject_node,
            "SiteRef",
            {"LocationOID": subject_data["SiteOID"]},
        )

        for event_data in subject_data["Events"].values():
            event_attributes: dict[str, str] = {
                "StudyEventOID": event_data["OID"],
            }

            if event_data["RepeatKey"] is not None:
                event_attributes["StudyEventRepeatKey"] = str(
                    event_data["RepeatKey"]
                )

            if event_data.get("Action"):
                event_attributes["TransactionType"] = event_data["Action"]

            event_node = ET.SubElement(
                subject_node,
                "StudyEventData",
                event_attributes,
            )

            for form_data in event_data["Forms"].values():
                self._build_form_node(event_node, form_data)

    def _build_form_node(
        self,
        event_node: ET.Element,
        form_data: dict[str, Any],
    ) -> None:
        """Build the FormData node and descendants."""
        form_attributes: dict[str, str] = {"FormOID": form_data["OID"]}

        if form_data["RepeatKey"] is not None:
            form_attributes["FormRepeatKey"] = str(form_data["RepeatKey"])

        if form_data.get("Action"):
            form_attributes["TransactionType"] = form_data["Action"]

        form_node = ET.SubElement(event_node, "FormData", form_attributes)

        for group_data in form_data["ItemGroups"].values():
            self._build_item_group_node(form_node, group_data)

    def _build_item_group_node(
        self,
        form_node: ET.Element,
        group_data: dict[str, Any],
    ) -> None:
        """Build the ItemGroupData node and descendants."""
        group_attributes: dict[str, str] = {
            "ItemGroupOID": group_data["OID"],
        }

        if group_data["RepeatKey"] is not None:
            group_attributes["ItemGroupRepeatKey"] = str(group_data["RepeatKey"])

        if group_data.get("Action"):
            group_attributes["TransactionType"] = group_data["Action"]

        if group_data["SpecifiedItemsOnly"]:
            group_attributes[f"{{{MDSOL_NS}}}Submission"] = "SpecifiedItemsOnly"

        group_node = ET.SubElement(form_node, "ItemGroupData", group_attributes)

        for item_oid, item_data in group_data["Items"].items():
            item_attributes: dict[str, str] = {"ItemOID": item_oid}

            if item_data["Value"] is not None:
                item_attributes["Value"] = str(item_data["Value"])

            if item_data["Specify"] is not None:
                item_attributes[f"{{{MDSOL_NS}}}SpecifyValue"] = str(
                    item_data["Specify"]
                )

            item_node = ET.SubElement(group_node, "ItemData", item_attributes)

            if item_data["Query"]:
                ET.SubElement(
                    item_node,
                    f"{{{MDSOL_NS}}}Query",
                    {
                        "Value": str(item_data["Query"]),
                        "Status": item_data["QueryStatus"],
                        "Recipient": item_data["QueryRecipient"],
                    },
                )
