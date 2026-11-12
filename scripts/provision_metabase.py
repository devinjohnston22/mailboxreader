"""Provision a private dashboard after completing Metabase's local first-run UI."""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
import httpx


def restrict_default_access(client,collection_id,database_id):
    """Remove broad All Users access; explicitly granted reviewer groups are preserved."""
    def call(method,path,**kwargs):
        response=client.request(method,path,**kwargs);response.raise_for_status();return response.json()
    groups=call('GET','/api/permissions/group')
    everyone=next((g for g in groups if g.get('magic_group_type')=='all-internal-users' or g['name']=='All Users'),None)
    if not everyone: raise RuntimeError('Cannot identify All Users group; review permissions manually')
    group=str(everyone['id'])
    graph=call('GET','/api/collection/graph')
    graph['groups'].setdefault(group,{})[str(collection_id)]='none'
    call('PUT','/api/collection/graph',json=graph)
    graph=call('GET','/api/permissions/graph')
    perms=graph['groups'].setdefault(group,{}).setdefault(str(database_id),{})
    # OSS supports no self-service queries. Data blocking/download controls require
    # a commercial license; collection permissions protect saved finance content.
    perms['create-queries']='no'
    call('PUT','/api/permissions/graph',json=graph)


def provision(client, database_id):
    def call(method,path,**kwargs):
        response = client.request(method,path,**kwargs)
        response.raise_for_status()
        return response.json()
    name = 'Mailbox Reader — finance review'
    collections = call('GET','/api/collection')
    collection = next((c for c in collections if c['name']==name),None)
    if not collection:
        collection = call('POST','/api/collection',json={'name':name,'color':'#509EE3','description':'Private finance candidates; not a ledger.'})
    restrict_default_access(client,collection['id'],database_id)
    items = call('GET',f"/api/collection/{collection['id']}/items")['data']
    dashboard = next((x for x in items if x['name']==name and x['model']=='dashboard'),None)
    if not dashboard:
        dashboard = call('POST','/api/dashboard',json={'name':name,'collection_id':collection['id'],'description':'Possible overdue only. Review exact source evidence before action. No currency conversion.'})
    dashboard = call('GET',f"/api/dashboard/{dashboard['id']}")
    cards=[]
    specs = json.loads((Path(__file__).resolve().parent.parent/'dashboards/cards.json').read_text())
    for i,spec in enumerate(specs):
        card = next((x for x in items if x['name']==spec['name'] and x['model']=='card'),None)
        payload = {'name':spec['name'],'collection_id':collection['id'],'display':spec['display'],
                   'dataset_query':{'database':database_id,'type':'native','native':{'query':spec['sql'],'template-tags':{}}},
                   'visualization_settings':{}}
        card = call('PUT',f"/api/card/{card['id']}",json=payload) if card else call('POST','/api/card',json=payload)
        old = next((x for x in dashboard.get('dashcards',[]) if x.get('card_id')==card['id']),None)
        cards.append({'id':old['id'] if old else -(i+1),'card_id':card['id'],'row':i*5,'col':0,'size_x':24,'size_y':5,'parameter_mappings':[],'visualization_settings':{}})
    call('PUT',f"/api/dashboard/{dashboard['id']}",json={'dashcards':cards})
    return dashboard['id']


if __name__=='__main__':
    url = os.getenv('METABASE_URL','http://127.0.0.1:3000')
    parsed = urlsplit(url)
    if parsed.scheme!='https' and parsed.hostname not in ('127.0.0.1','localhost','metabase'):
        raise ValueError('Metabase API credentials require HTTPS outside loopback/compose')
    with httpx.Client(base_url=url,headers={'x-api-key':os.environ['METABASE_API_KEY']},timeout=60) as client:
        dashboard_id = provision(client,int(os.environ['METABASE_DATABASE_ID']))
    print('Provisioned dashboard',dashboard_id)
