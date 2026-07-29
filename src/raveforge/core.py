"""Core logic and processing engine for RaveForge."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4
import xml.etree.ElementTree as ET

from .enums import ActionType, QueryRecipient, QueryStatus
from .exceptions import HierarchyError


MDSOL_NS = "http://www.mdsol.com/ns/odm/metadata"
ODM_NS = "http://www.cdisc.org/ns/odm/v1.3"

_DEFAULT_REPEAT_KEY = "1"

ET.register_namespace("", ODM_NS)
ET.register_namespace("mdsol", MDSOL_NS)


def _odm_tag(tag_name: str) -> str:
    """Return a qualified CDISC ODM element name."""
    return f"{{{ODM_NS}}}{tag_name}"


def _mdsol_name(local_name: str) -> str:
    """Return a qualified Medidata ODM extension name."""
    return f"{{{MDSOL_NS}}}{local_name}"


@dataclass
class TransactionContext:
    """Tracks the active builder position."""

    subject_key: Optional[str] = None
    event_key: Optional[tuple[str, Optional[str]]] = None
    form_key: Optional[tuple[str, Optional[str]]] = None
    group_key: Optional[tuple[str, Optional[str]]] = None


@dataclass
class QueryDetails:
    """Optional Medidata query metadata for an item."""

    text: str
    status: QueryStatus = QueryStatus.OPEN
    recipient: QueryRecipient = QueryRecipient.SITE_FROM_SYSTEM


@dataclass
class Item:
    """A single ODM ItemData value and optional Medidata query."""

    value: Optional[str] = None
    specify: Optional[str] = None
    query: Optional[QueryDetails] = None


@dataclass
class ItemGroup:
    """An ODM ItemGroupData instance."""

    oid: str
    repeat_key: Optional[str]
    action: Optional[ActionType] = None
    specified_items_only: bool = False
    items: dict[str, Item] = field(default_factory=dict)


@dataclass
class Form:
    """An ODM FormData instance."""

    oid: str
    repeat_key: Optional[str]
    action: Optional[ActionType] = None
    item_groups: dict[tuple[str, Optional[str]], ItemGroup] = field(
        default_factory=dict
    )


@dataclass
class StudyEvent:
    """An ODM StudyEventData instance."""

    oid: str
    repeat_key: Optional[str]
    action: Optional[ActionType] = None
    forms: dict[tuple[str, Optional[str]], Form] = field(default_factory=dict)


@dataclass
class Subject:
    """An ODM SubjectData instance."""

    site_oid: str
    action: Optional[ActionType] = None
    events: dict[tuple[str, Optional[str]], StudyEvent] = field(default_factory=dict)


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
        self._subjects: dict[str, Subject] = {}
        self._context = TransactionContext()

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
        """Add or select a subject context."""
        subject = self._subjects.get(subject_key)

        if subject is None:
            subject = Subject(site_oid=site_oid, action=action)
            self._subjects[subject_key] = subject
        else:
            subject.site_oid = site_oid
            subject.action = action

        self._context = TransactionContext(subject_key=subject_key)
        return self

    def event(
        self,
        event_oid: str,
        repeat_key: Optional[str] = _DEFAULT_REPEAT_KEY,
        action: Optional[ActionType] = None,
    ) -> RaveTransaction:
        """Add or select a study-event context."""
        subject = self._require_subject()

        event_key = (event_oid, repeat_key)
        event = subject.events.get(event_key)

        if event is None:
            subject.events[event_key] = StudyEvent(
                oid=event_oid,
                repeat_key=repeat_key,
                action=action,
            )
        elif action is not None:
            event.action = action

        self._context.event_key = event_key
        self._context.form_key = None
        self._context.group_key = None
        return self

    def form(
        self,
        form_oid: str,
        repeat_key: Optional[str] = _DEFAULT_REPEAT_KEY,
        action: Optional[ActionType] = None,
    ) -> RaveTransaction:
        """Add or select a form context."""
        event = self._require_event()

        form_key = (form_oid, repeat_key)
        form = event.forms.get(form_key)

        if form is None:
            event.forms[form_key] = Form(
                oid=form_oid,
                repeat_key=repeat_key,
                action=action,
            )
        elif action is not None:
            form.action = action

        self._context.form_key = form_key
        self._context.group_key = None
        return self

    def item_group(
        self,
        item_group_oid: str,
        repeat_key: Optional[str] = _DEFAULT_REPEAT_KEY,
        action: Optional[ActionType] = None,
        specified_items_only: bool = False,
    ) -> RaveTransaction:
        """Add or select an item-group context."""
        form = self._require_form()

        group_key = (item_group_oid, repeat_key)
        group = form.item_groups.get(group_key)

        if group is None:
            form.item_groups[group_key] = ItemGroup(
                oid=item_group_oid,
                repeat_key=repeat_key,
                action=action,
                specified_items_only=specified_items_only,
            )
        else:
            if action is not None:
                group.action = action
            group.specified_items_only = specified_items_only

        self._context.group_key = group_key
        return self

    def item(
        self,
        item_oid: str,
        *,
        value: Optional[str] = None,
        specify: Optional[str] = None,
        query: Optional[QueryDetails] = None,
    ) -> RaveTransaction:
        """Add or replace an item in the active item-group context."""
        group = self._require_group()

        group.items[item_oid] = Item(
            value=value,
            specify=specify,
            query=query,
        )
        return self

    def reset_context(self) -> RaveTransaction:
        """Clear active builder context without discarding accumulated data."""
        self._context = TransactionContext()
        return self

    def reset(self) -> RaveTransaction:
        """Clear all transaction data and generate a new ODM FileOID."""
        self._subjects.clear()
        self.file_oid = str(uuid4())
        return self.reset_context()

    def build(self, encoding: str = "UTF-8") -> bytes | str:
        """
        Serialize the transaction to an ODM XML payload.

        Pass ``encoding="unicode"`` to receive a string without an XML
        declaration. All other encodings return bytes with an XML declaration.
        """
        root = self._build_xml_tree()

        if encoding.lower() == "unicode":
            return ET.tostring(root, encoding="unicode")

        return ET.tostring(root, encoding=encoding, xml_declaration=True)

    def build_pretty(self) -> str:
        """
        Serialize to human-readable, indented ODM XML.

        The returned Unicode string intentionally does not include an XML
        declaration and is intended for debugging or logging.
        """
        root = deepcopy(self._build_xml_tree())
        ET.indent(root, space="  ")
        return ET.tostring(root, encoding="unicode")

    def _build_xml_tree(self) -> ET.Element:
        """Create the complete ODM XML element tree."""
        root = ET.Element(
            _odm_tag("ODM"),
            {
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
            _odm_tag("ClinicalData"),
            {
                "StudyOID": self.study_oid,
                "MetaDataVersionOID": self.metadata_version_oid,
            },
        )

        for subject_key, subject in self._subjects.items():
            self._build_subject_node(clinical_data, subject_key, subject)

        return root

    def _build_subject_node(
        self,
        clinical_data: ET.Element,
        subject_key: str,
        subject: Subject,
    ) -> None:
        """Append an ODM SubjectData node and its descendants."""
        attributes = {"SubjectKey": subject_key}

        if subject.action is not None:
            attributes["TransactionType"] = subject.action.value

        subject_node = ET.SubElement(
            clinical_data,
            _odm_tag("SubjectData"),
            attributes,
        )
        ET.SubElement(
            subject_node,
            _odm_tag("SiteRef"),
            {"LocationOID": subject.site_oid},
        )

        for event in subject.events.values():
            self._build_event_node(subject_node, event)

    def _build_event_node(self, subject_node: ET.Element, event: StudyEvent) -> None:
        """Append an ODM StudyEventData node and its descendants."""
        attributes = {"StudyEventOID": event.oid}

        if event.repeat_key is not None:
            attributes["StudyEventRepeatKey"] = event.repeat_key

        if event.action is not None:
            attributes["TransactionType"] = event.action.value

        event_node = ET.SubElement(
            subject_node,
            _odm_tag("StudyEventData"),
            attributes,
        )

        for form in event.forms.values():
            self._build_form_node(event_node, form)

    def _build_form_node(self, event_node: ET.Element, form: Form) -> None:
        """Append an ODM FormData node and its descendants."""
        attributes = {"FormOID": form.oid}

        if form.repeat_key is not None:
            attributes["FormRepeatKey"] = form.repeat_key

        if form.action is not None:
            attributes["TransactionType"] = form.action.value

        form_node = ET.SubElement(
            event_node,
            _odm_tag("FormData"),
            attributes,
        )

        for group in form.item_groups.values():
            self._build_item_group_node(form_node, group)

    def _build_item_group_node(self, form_node: ET.Element, group: ItemGroup) -> None:
        """Append an ODM ItemGroupData node and its item data."""
        attributes = {"ItemGroupOID": group.oid}

        if group.repeat_key is not None:
            attributes["ItemGroupRepeatKey"] = group.repeat_key

        if group.action is not None:
            attributes["TransactionType"] = group.action.value

        if group.specified_items_only:
            attributes[_mdsol_name("Submission")] = "SpecifiedItemsOnly"

        group_node = ET.SubElement(
            form_node,
            _odm_tag("ItemGroupData"),
            attributes,
        )

        for item_oid, item in group.items.items():
            item_attributes = {"ItemOID": item_oid}

            if item.value is not None:
                item_attributes["Value"] = str(item.value)

            if item.specify is not None:
                item_attributes[_mdsol_name("SpecifyValue")] = str(item.specify)

            item_node = ET.SubElement(
                group_node,
                _odm_tag("ItemData"),
                item_attributes,
            )

            if item.query is not None:
                ET.SubElement(
                    item_node,
                    _mdsol_name("Query"),
                    {
                        "Value": item.query.text,
                        "Status": item.query.status.value,
                        "Recipient": item.query.recipient.value,
                    },
                )

    def _require_subject(self) -> Subject:
        """Return the active subject or raise a hierarchy error."""
        if self._context.subject_key is None:
            raise HierarchyError("Subject context required before calling event().")

        return self._subjects[self._context.subject_key]

    def _require_event(self) -> StudyEvent:
        """Return the active event or raise a hierarchy error."""
        if self._context.event_key is None:
            raise HierarchyError("Event context required before calling form().")

        return self._require_subject().events[self._context.event_key]

    def _require_form(self) -> Form:
        """Return the active form or raise a hierarchy error."""
        if self._context.form_key is None:
            raise HierarchyError("Form context required before calling item_group().")

        return self._require_event().forms[self._context.form_key]

    def _require_group(self) -> ItemGroup:
        """Return the active item group or raise a hierarchy error."""
        if self._context.group_key is None:
            raise HierarchyError("ItemGroup context required before calling item().")

        return self._require_form().item_groups[self._context.group_key]
