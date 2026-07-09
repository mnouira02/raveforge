from __future__ import annotations
import datetime
import uuid
import xml.etree.ElementTree as ET
from typing import Dict, Any, Optional

# Import our custom types from our internal modules
from .exceptions import HierarchyError
from .enums import ActionType


class RaveTransaction:
    """
    The main coordinator for generating CDISC ODM XML payloads optimized for 
    Medidata Rave Web Services (RWS). Enforces hierarchy and manages builder state.
    """
    
    def __init__(self, study_oid: str, metadata_version_oid: str = "1") -> None:
        self.study_oid: str = study_oid
        self.metadata_version_oid: str = metadata_version_oid
        self.file_oid: str = str(uuid.uuid4())
        
        # Internal hierarchical data storage
        self._subjects: Dict[str, Dict[str, Any]] = {}
        
        # Stateful pointers for the fluent interface
        self._current_subject: Optional[str] = None
        self._current_site: Optional[str] = None
        self._current_event: Optional[str] = None
        self._current_form: Optional[str] = None
        self._current_group: Optional[str] = None

        # Register namespaces to prevent ugly 'ns0:' prefixes in output
        ET.register_namespace("", "http://www.cdisc.org/ns/odm/v1.3")
        ET.register_namespace("mdsol", "http://www.mdsol.com/ns/odm/metadata")

    def subject(self, subject_key: str, site_oid: str, action: ActionType = ActionType.UPSERT) -> RaveTransaction:
        """Sets the active Subject context."""
        if subject_key not in self._subjects:
            self._subjects[subject_key] = {
                "SiteOID": site_oid,
                "Action": action.value,
                "Events": {}
            }
        self._current_subject = subject_key
        self._current_site = site_oid
        # Reset child tracking context
        self._current_event = None
        self._current_form = None
        self._current_group = None
        return self

    def event(self, event_oid: str) -> RaveTransaction:
        """Sets the active StudyEvent context under the current Subject."""
        if not self._current_subject:
            raise HierarchyError("Cannot define an event context without an active subject.")
        
        events = self._subjects[self._current_subject]["Events"]
        if event_oid not in events:
            events[event_oid] = {"Forms": {}}
            
        self._current_event = event_oid
        self._current_form = None
        self._current_group = None
        return self

    def form(self, form_oid: str) -> RaveTransaction:
        """Sets the active Form context under the current StudyEvent."""
        if not self._current_event:
            raise HierarchyError("Cannot define a form context without an active event.")
            
        forms = self._subjects[self._current_subject]["Events"][self._current_event]["Forms"]
        if form_oid not in forms:
            forms[form_oid] = {"ItemGroups": {}}
            
        self._current_form = form_oid
        self._current_group = None
        return self

    def item_group(self, item_group_oid: str, repeat_key: str = "1") -> RaveTransaction:
        """Sets the active ItemGroup context under the current Form."""
        if not self._current_form:
            raise HierarchyError("Cannot define an item group context without an active form.")
            
        groups = self._subjects[self._current_subject]["Events"][self._current_event]["Forms"][self._current_form]["ItemGroups"]
        group_key = f"{item_group_oid}_{repeat_key}"
        
        if group_key not in groups:
            groups[group_key] = {
                "OID": item_group_oid,
                "RepeatKey": repeat_key,
                "Items": {}
            }
            
        self._current_group = group_key
        return self

    def item(self, item_oid: str, value: str) -> RaveTransaction:
        """Injects a single data point into the current active ItemGroup context."""
        if not self._current_group:
            raise HierarchyError("Cannot add an item without an active item group context.")
            
        items = self._subjects[self._current_subject]["Events"][self._current_event]["Forms"][self._current_form]["ItemGroups"][self._current_group]["Items"]
        items[item_oid] = value
        return self

    def batch_items(self, data_dict: Dict[str, str]) -> RaveTransaction:
        """Helper to quickly inject multiple key-value item pairs into the active context."""
        for item_oid, value in data_dict.items():
            self.item(item_oid, value)
        return self

    def build(self, encoding: str = "UTF-8") -> bytes:
        """
        Compiles the internal structured state into structured, RWS-compliant ODM XML.
        Returns bytes optimized for transport payloads.
        """
        # Create standard ODM envelope root
        root = ET.Element(
            "ODM",
            {
                "xmlns": "http://www.cdisc.org/ns/odm/v1.3",
                "{http://www.mdsol.com/ns/odm/metadata}X-MDSOL-Beta": "True",  # Placeholder for tracking namespaces
                "FileType": "Transactional",
                "FileOID": self.file_oid,
                "CreationDateTime": datetime.datetime.utcnow().isoformat() + "Z",
                "ODMVersion": "1.3",
            }
        )
        
        clinical_data = ET.SubElement(
            root, 
            "ClinicalData", 
            {"StudyOID": self.study_oid, "MetaDataVersionOID": self.metadata_version_oid}
        )
        
        # Walk down the constructed memory tree
        for subj_key, subj_data in self._subjects.items():
            subj_node = ET.SubElement(
                clinical_data, 
                "SubjectData", 
                {
                    "SubjectKey": subj_key, 
                    "SiteOID": subj_data["SiteOID"],
                    "{http://www.mdsol.com/ns/odm/metadata}Action": subj_data["Action"]
                }
            )
            
            for event_oid, event_data in subj_data["Events"].items():
                event_node = ET.SubElement(subj_node, "StudyEventData", {"StudyEventOID": event_oid})
                
                for form_oid, form_data in event_data["Forms"].items():
                    form_node = ET.SubElement(event_node, "FormData", {"FormOID": form_oid})
                    
                    for group_id, group_data in form_data["ItemGroups"].items():
                        group_node = ET.SubElement(
                            form_node, 
                            "ItemGroupData", 
                            {"ItemGroupOID": group_data["OID"], "ItemGroupRepeatKey": group_data["RepeatKey"]}
                        )
                        
                        for item_oid, item_value in group_data["Items"].items():
                            ET.SubElement(group_node, "ItemData", {"ItemOID": item_oid, "Value": str(item_value)})
                            
        # Generate the XML tree representation
        return ET.tostring(root, encoding=encoding, xml_declaration=True)