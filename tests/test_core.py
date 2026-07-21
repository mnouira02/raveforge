import xml.etree.ElementTree as ET

import pytest

from raveforge import (
    ActionType,
    HierarchyError,
    QueryRecipient,
    QueryStatus,
    RaveTransaction,
)


ODM_NS = "http://www.cdisc.org/ns/odm/v1.3"
MDSOL_NS = "http://www.mdsol.com/ns/odm/metadata"


def qname(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


# -------------------------------------------------------------------
# 1. Envelope & Initialization Tests
# -------------------------------------------------------------------


def test_transaction_envelope_generation():
    """Validates the root ODM XML envelope and namespaces."""
    tx = RaveTransaction(study_oid="Mediflex_01", metadata_version_oid="V1")
    xml_bytes = tx.build()

    root = ET.fromstring(xml_bytes)

    assert root.tag == qname(ODM_NS, "ODM")
    assert root.attrib["FileType"] == "Transactional"
    assert root.attrib["ODMVersion"] == "1.3"
    assert "FileOID" in root.attrib
    assert "CreationDateTime" in root.attrib

    clinical_data = root.find(qname(ODM_NS, "ClinicalData"))
    assert clinical_data is not None
    assert clinical_data.attrib["StudyOID"] == "Mediflex_01"
    assert clinical_data.attrib["MetaDataVersionOID"] == "V1"


def test_build_pretty_returns_string_xml():
    """Validates pretty-print output is a string and contains expected XML nodes."""
    tx = (
        RaveTransaction("TestStudy")
        .subject("SUBJ-001", "SITE-001")
        .event("SCREENING")
        .form("DM")
        .item_group("DM_IG")
        .item("AGE", "42")
    )

    xml_pretty = tx.build_pretty()

    assert isinstance(xml_pretty, str)
    assert "<?xml" in xml_pretty
    assert "<ODM" in xml_pretty
    assert "ClinicalData" in xml_pretty
    assert "SubjectData" in xml_pretty


# -------------------------------------------------------------------
# 2. Fluent Builder (Happy Path)
# -------------------------------------------------------------------


def test_fluent_hierarchy_success():
    """Validates that a correctly chained builder produces the expected hierarchy."""
    tx = RaveTransaction(study_oid="Test_Study")

    tx.subject("SUBJ-101", site_oid="SITE-A", action=ActionType.UPSERT) \
        .event("SCREENING", repeat_key="1", action=ActionType.UPDATE) \
        .form("VS", repeat_key="2", action=ActionType.INSERT) \
        .item_group("VS_GROUP", repeat_key="3", action=ActionType.UPDATE) \
        .item("VSORRES", "120")

    root = ET.fromstring(tx.build())
    clinical_data = root.find(qname(ODM_NS, "ClinicalData"))

    subject = clinical_data.find(qname(ODM_NS, "SubjectData"))
    assert subject.attrib["SubjectKey"] == "SUBJ-101"
    assert subject.attrib["TransactionType"] == "Upsert"

    site_ref = subject.find(qname(ODM_NS, "SiteRef"))
    assert site_ref is not None
    assert site_ref.attrib["LocationOID"] == "SITE-A"

    event = subject.find(qname(ODM_NS, "StudyEventData"))
    assert event is not None
    assert event.attrib["StudyEventOID"] == "SCREENING"
    assert event.attrib["StudyEventRepeatKey"] == "1"
    assert event.attrib["TransactionType"] == "Update"

    form = event.find(qname(ODM_NS, "FormData"))
    assert form is not None
    assert form.attrib["FormOID"] == "VS"
    assert form.attrib["FormRepeatKey"] == "2"
    assert form.attrib["TransactionType"] == "Insert"

    item_group = form.find(qname(ODM_NS, "ItemGroupData"))
    assert item_group is not None
    assert item_group.attrib["ItemGroupOID"] == "VS_GROUP"
    assert item_group.attrib["ItemGroupRepeatKey"] == "3"
    assert item_group.attrib["TransactionType"] == "Update"

    item = item_group.find(qname(ODM_NS, "ItemData"))
    assert item is not None
    assert item.attrib["ItemOID"] == "VSORRES"
    assert item.attrib["Value"] == "120"


def test_multiple_items_in_group():
    """Validates that multiple items can be added to the same item group."""
    tx = RaveTransaction(study_oid="Test_Study")
    tx.subject("S-1", "Site-1").event("E-1").form("F-1").item_group("IG-1") \
        .item("WEIGHT", "75") \
        .item("HEIGHT", "180")

    root = ET.fromstring(tx.build())
    items = root.findall(f".//{qname(ODM_NS, 'ItemData')}")

    assert len(items) == 2
    item_oids = [item.attrib["ItemOID"] for item in items]
    assert "WEIGHT" in item_oids
    assert "HEIGHT" in item_oids


def test_specified_items_only_extension():
    """Validates mdsol:Submission='SpecifiedItemsOnly' is written on ItemGroupData."""
    tx = (
        RaveTransaction("Test_Study")
        .subject("S-1", "Site-1")
        .event("VISIT_1")
        .form("LABS")
        .item_group("LABS_IG", specified_items_only=True)
        .item("LBTEST", "ALT")
    )

    root = ET.fromstring(tx.build())
    item_group = root.find(f".//{qname(ODM_NS, 'ItemGroupData')}")

    assert item_group is not None
    assert item_group.attrib[qname(MDSOL_NS, "Submission")] == "SpecifiedItemsOnly"


def test_item_with_specify_value():
    """Validates mdsol:SpecifyValue is written on ItemData."""
    tx = (
        RaveTransaction("Test_Study")
        .subject("S-1", "Site-1")
        .event("VISIT_1")
        .form("MEDS")
        .item_group("MEDS_IG")
        .item("CMTRT", value="OTHER", specify="Investigational Vitamin Blend")
    )

    root = ET.fromstring(tx.build())
    item = root.find(f".//{qname(ODM_NS, 'ItemData')}")

    assert item is not None
    assert item.attrib["ItemOID"] == "CMTRT"
    assert item.attrib["Value"] == "OTHER"
    assert (
        item.attrib[qname(MDSOL_NS, "SpecifyValue")] == "Investigational Vitamin Blend"
    )


def test_item_with_query_metadata():
    """Validates mdsol:Query node is generated with configurable status and recipient."""
    tx = (
        RaveTransaction("Test_Study")
        .subject("S-1", "Site-1")
        .event("VISIT_1")
        .form("VS")
        .item_group("VS_IG")
        .item(
            "TEMP",
            value="39.2",
            query="Please confirm whether this was measured orally.",
            query_status=QueryStatus.OPEN,
            query_recipient=QueryRecipient.SITE_FROM_DM,
        )
    )

    root = ET.fromstring(tx.build())
    query_node = root.find(f".//{qname(MDSOL_NS, 'Query')}")

    assert query_node is not None
    assert (
        query_node.attrib["Value"]
        == "Please confirm whether this was measured orally."
    )
    assert query_node.attrib["Status"] == "Open"
    assert query_node.attrib["Recipient"] == "Site from DM"


def test_context_manager_support():
    """Validates the transaction can be used with a context manager."""
    with RaveTransaction("Test_Study") as tx:
        (
            tx.subject("S-1", "Site-1")
            .event("E-1")
            .form("F-1")
            .item_group("IG-1")
            .item("I-1", "V-1")
        )

    root = ET.fromstring(tx.build())
    item = root.find(f".//{qname(ODM_NS, 'ItemData')}")

    assert item is not None
    assert item.attrib["ItemOID"] == "I-1"
    assert item.attrib["Value"] == "V-1"


def test_subject_revisit_updates_site_oid():
    """Validates that calling subject() again with a new SiteOID updates it correctly."""
    tx = RaveTransaction("Test_Study")
    (
        tx.subject("S-1", "SITE-A")
        .event("E-1")
        .form("F-1")
        .item_group("IG-1")
        .item("I-1", "V-1")
    )
    tx.subject("S-1", "SITE-B")

    root = ET.fromstring(tx.build())
    site_ref = root.find(f".//{qname(ODM_NS, 'SiteRef')}")

    assert site_ref is not None
    assert site_ref.attrib["LocationOID"] == "SITE-B"


def test_subject_revisit_preserves_events():
    """Validates that revisiting a subject does not discard its accumulated events."""
    tx = RaveTransaction("Test_Study")
    (
        tx.subject("S-1", "SITE-A")
        .event("E-1")
        .form("F-1")
        .item_group("IG-1")
        .item("I-1", "V-1")
    )
    tx.subject("S-1", "SITE-B")

    root = ET.fromstring(tx.build())
    items = root.findall(f".//{qname(ODM_NS, 'ItemData')}")

    assert len(items) == 1
    assert items[0].attrib["ItemOID"] == "I-1"


# -------------------------------------------------------------------
# 3. Defensive State Machine (Negative Tests)
# -------------------------------------------------------------------


def test_hierarchy_enforcement_event_without_subject():
    """Ensures developers cannot define an event without subject context."""
    tx = RaveTransaction(study_oid="Test_Study")
    match = "Subject context required before calling event\\(\\)."

    with pytest.raises(HierarchyError, match=match):
        tx.event("SCREENING")


def test_hierarchy_enforcement_form_without_event():
    """Ensures developers cannot define a form without event context."""
    tx = RaveTransaction(study_oid="Test_Study")
    tx.subject("S-1", "Site-1")
    match = "Event context required before calling form\\(\\)."

    with pytest.raises(HierarchyError, match=match):
        tx.form("F-1")


def test_hierarchy_enforcement_item_group_without_form():
    """Ensures developers cannot define an item group without form context."""
    tx = RaveTransaction(study_oid="Test_Study")
    tx.subject("S-1", "Site-1").event("E-1")
    match = "Form context required before calling item_group\\(\\)."

    with pytest.raises(HierarchyError, match=match):
        tx.item_group("IG-1")


def test_hierarchy_enforcement_item_without_group():
    """Ensures data items cannot be added without an active item group."""
    tx = RaveTransaction(study_oid="Test_Study")
    tx.subject("S-1", "Site-1").event("E-1").form("F-1")
    match = "ItemGroup context required before calling item\\(\\)."

    with pytest.raises(HierarchyError, match=match):
        tx.item("VITAL", "120")


# -------------------------------------------------------------------
# 4. Reset Behavior
# -------------------------------------------------------------------


def test_reset_context_clears_only_current_pointers():
    """Validates reset_context clears active pointers but keeps accumulated data."""
    tx = RaveTransaction("Test_Study")
    (
        tx.subject("S-1", "Site-1")
        .event("E-1")
        .form("F-1")
        .item_group("IG-1")
        .item("I-1", "V-1")
    )

    tx.reset_context()

    root = ET.fromstring(tx.build())
    item = root.find(f".//{qname(ODM_NS, 'ItemData')}")

    assert item is not None
    assert item.attrib["ItemOID"] == "I-1"
    assert item.attrib["Value"] == "V-1"

    match = "Subject context required before calling event\\(\\)."
    with pytest.raises(HierarchyError, match=match):
        tx.event("E-2")


def test_reset_clears_all_data_and_generates_new_file_oid():
    """Validates full reset removes content and regenerates file identity."""
    tx = RaveTransaction("Test_Study")
    original_file_oid = tx.file_oid

    (
        tx.subject("S-1", "Site-1")
        .event("E-1")
        .form("F-1")
        .item_group("IG-1")
        .item("I-1", "V-1")
    )
    tx.reset()

    root = ET.fromstring(tx.build())
    clinical_data = root.find(qname(ODM_NS, "ClinicalData"))
    subjects = clinical_data.findall(qname(ODM_NS, "SubjectData"))

    assert len(subjects) == 0
    assert tx.file_oid != original_file_oid


# -------------------------------------------------------------------
# 5. Repeated Structures
# -------------------------------------------------------------------


def test_event_and_form_repeat_keys_are_serialized():
    """Validates event and form repeat keys are serialised correctly."""
    tx = (
        RaveTransaction("Test_Study")
        .subject("S-1", "Site-1")
        .event("UNSCHED", repeat_key="5")
        .form("AE", repeat_key="7")
        .item_group("AE_IG", repeat_key="1")
        .item("AETERM", "Headache")
    )

    root = ET.fromstring(tx.build())

    event = root.find(f".//{qname(ODM_NS, 'StudyEventData')}")
    form = root.find(f".//{qname(ODM_NS, 'FormData')}")
    item_group = root.find(f".//{qname(ODM_NS, 'ItemGroupData')}")

    assert event is not None
    assert form is not None
    assert item_group is not None

    assert event.attrib["StudyEventRepeatKey"] == "5"
    assert form.attrib["FormRepeatKey"] == "7"
    assert item_group.attrib["ItemGroupRepeatKey"] == "1"
