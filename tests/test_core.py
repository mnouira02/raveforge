import xml.etree.ElementTree as ET
from unittest.mock import patch
import pytest

from raveforge import RaveTransaction, ActionType, HierarchyError

# --- 1. Envelope & Initialization Tests ---

def test_transaction_envelope_generation():
    """Validates the root ODM XML envelope and namespaces."""
    tx = RaveTransaction(study_oid="Mediflex_01", metadata_version_oid="V1")
    xml_bytes = tx.build()
    
    # Parse the output
    root = ET.fromstring(xml_bytes)
    
    # Check standard CDISC ODM attributes
    assert root.tag == "{http://www.cdisc.org/ns/odm/v1.3}ODM"
    assert root.attrib["FileType"] == "Transactional"
    assert "FileOID" in root.attrib
    assert "CreationDateTime" in root.attrib
    
    # Check ClinicalData node
    clinical_data = root.find("{http://www.cdisc.org/ns/odm/v1.3}ClinicalData")
    assert clinical_data is not None
    assert clinical_data.attrib["StudyOID"] == "Mediflex_01"
    assert clinical_data.attrib["MetaDataVersionOID"] == "V1"


# --- 2. Fluent Builder (Happy Path) ---

def test_fluent_hierarchy_success():
    """Validates that a correctly chained builder produces the exact clinical hierarchy."""
    tx = RaveTransaction(study_oid="Test_Study")
    
    tx.subject("SUBJ-101", site_oid="SITE-A", action=ActionType.UPSERT) \
      .event("SCREENING") \
      .form("VS") \
      .item_group("VS_GROUP") \
      .item("VSORRES", "120")
      
    root = ET.fromstring(tx.build())
    clinical_data = root.find("{http://www.cdisc.org/ns/odm/v1.3}ClinicalData")
    
    # Navigate the tree down to the item
    subject = clinical_data.find("{http://www.cdisc.org/ns/odm/v1.3}SubjectData")
    assert subject.attrib["SubjectKey"] == "SUBJ-101"
    assert subject.attrib["{http://www.mdsol.com/ns/odm/metadata}Action"] == "Upsert"
    
    event = subject.find("{http://www.cdisc.org/ns/odm/v1.3}StudyEventData")
    assert event.attrib["StudyEventOID"] == "SCREENING"
    
    form = event.find("{http://www.cdisc.org/ns/odm/v1.3}FormData")
    item_group = form.find("{http://www.cdisc.org/ns/odm/v1.3}ItemGroupData")
    item = item_group.find("{http://www.cdisc.org/ns/odm/v1.3}ItemData")
    
    assert item.attrib["ItemOID"] == "VSORRES"
    assert item.attrib["Value"] == "120"


def test_batch_items_injection():
    """Validates the bulk-injection helper method."""
    tx = RaveTransaction(study_oid="Test_Study")
    tx.subject("S-1", "Site-1").event("E-1").form("F-1").item_group("IG-1")
    
    # Inject multiple items at once
    tx.batch_items({
        "WEIGHT": "75",
        "HEIGHT": "180"
    })
    
    root = ET.fromstring(tx.build())
    items = root.findall(".//{http://www.cdisc.org/ns/odm/v1.3}ItemData")
    
    assert len(items) == 2
    item_oids = [item.attrib["ItemOID"] for item in items]
    assert "WEIGHT" in item_oids
    assert "HEIGHT" in item_oids


# --- 3. Defensive State Machine (Negative Tests) ---

def test_hierarchy_enforcement_event_without_subject():
    """Ensures developers cannot skip hierarchy levels."""
    tx = RaveTransaction(study_oid="Test_Study")
    
    with pytest.raises(HierarchyError, match="Cannot define an event context without an active subject"):
        tx.event("SCREENING")


def test_hierarchy_enforcement_item_without_group():
    """Ensures data items cannot float outside of an ItemGroup context."""
    tx = RaveTransaction(study_oid="Test_Study")
    tx.subject("S-1", "Site-1").event("E-1").form("F-1")
    
    # Missing .item_group() here
    with pytest.raises(HierarchyError, match="Cannot add an item without an active item group"):
        tx.item("VITAL", "120")


# --- 4. Mock RWS Integration Test ---

@patch("requests.post")
def test_mock_rws_transmission(mock_post):
    """Simulates sending the generated ODM XML to Medidata RWS."""
    # Setup mock response
    mock_post.return_value.status_code = 200
    mock_post.return_value.text = "<Response>Success</Response>"
    
    # Generate Payload
    tx = RaveTransaction(study_oid="Test_Study").subject("S-1", "Site-1").event("E-1").form("F-1").item_group("IG-1").item("I-1", "V-1")
    xml_payload = tx.build()
    
    import requests
    response = requests.post(
        "https://innovate.mdsol.com/RaveWebServices/webservice.aspx?PostODMClinicalData",
        data=xml_payload,
        headers={'Content-Type': 'text/xml'},
        auth=('user', 'pass')
    )
    
    # Assert network call was made with exact bytes
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert kwargs["data"] == xml_payload
    assert kwargs["headers"]["Content-Type"] == "text/xml"
    assert response.status_code == 200