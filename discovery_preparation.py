"""Offline authorized dataset/ABN adapters. No network discovery is performed."""
import json
import xml.etree.ElementTree as ET
from datetime import datetime,timezone
from phase3_store import WorkflowError
from phase4_data import parse_dataset,STATES


DEFAULTS=dict(states=list(STATES),cities=[],industries=[],daily_leads=10,research_budget_cents=0,minimum_score=50,provider='licensed_csv')


def migrate(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS prep_discovery(user_id INTEGER PRIMARY KEY,config_json TEXT NOT NULL,updated_at TEXT NOT NULL)''')


def validate_plan(value):
    value=dict(value)
    if not isinstance(value.get('states'),list) or not value['states'] or not set(value['states'])<=set(STATES):raise WorkflowError('Choose valid Australian states/territories.')
    for field in ('cities','industries'):
        if not isinstance(value.get(field),list) or len(value[field])>10 or any(not isinstance(v,str) or not 1<=len(v)<=100 or any(ord(c)<32 for c in v) for v in value[field]):raise WorkflowError('Use up to ten bounded city/industry names.')
    if value.get('provider') not in ('licensed_csv','abn_validation','osm_review_required'):raise WorkflowError('Select a supported authorized data boundary.')
    for field,low,high in (('daily_leads',1,20),('research_budget_cents',0,10000),('minimum_score',0,100)):
        if type(value.get(field)) is not int or not low<=value[field]<=high:raise WorkflowError('Discovery volume, research ceiling or qualification score is outside its bound.')
    return value


def filter_authorized_csv(raw,plan):
    plan=validate_plan(plan)
    if len(raw)>2_000_000:raise WorkflowError('Dataset exceeds the import limit.')
    rows=parse_dataset(raw)
    selected=[]
    for row in rows:
        if row['state'] not in plan['states']:continue
        if plan['cities'] and row['city'].casefold() not in {v.casefold() for v in plan['cities']}:continue
        if plan['industries'] and row['data']['industry'].casefold() not in {v.casefold() for v in plan['industries']}:continue
        selected.append(row)
        if len(selected)>=plan['daily_leads']:break
    return dict(candidates=selected,source_count=len(rows),automatic_import=False,permission='Separate current source licence/owner review required before CRM import.')


def parse_abn_fragment(raw):
    """Bounded bulk-schema fragment parser for licensed/offline validation fixtures.

    ABN location is state/postcode, not proof of a street location. No
    email, website or marketing consent is inferred from a registration.
    """
    if len(raw)>1_000_000 or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise WorkflowError('ABN XML input is unsafe or oversized.')
    try:
        root=ET.fromstring(raw)
        records=[root] if root.tag=='ABR' else root.findall('.//ABR')
        output=[]
        for node in records[:1000]:
            number=node.findtext('ABN','')
            if not number.isdigit() or len(number)!=11:raise ValueError()
            name=node.findtext('.//NonIndividualNameText','')
            state=node.findtext('.//AddressDetails/State','')
            postcode=node.findtext('.//AddressDetails/Postcode','')
            if not name or state not in STATES:continue
            output.append(dict(abn=number,business_name=name[:200],state=state,postcode=postcode[:10],email='',website='',city='',marketing_consent=False))
        return output
    except (ET.ParseError,ValueError):raise WorkflowError('Invalid ABN extract fragment.') from None
