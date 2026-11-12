"""Generate n8n JSON without credentials or executable email content."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def node(name, kind, parameters, x, version=1, credentials=None):
    result = {'id':name.lower().replace(' ','-'), 'name':name,
              'type':'n8n-nodes-base.'+kind, 'typeVersion':version,
              'position':[x,0], 'parameters':parameters}
    if credentials:
        result['credentials'] = credentials
    return result


def api(name, path, x, method='POST', body=None):
    params = {'method':method,'url':'http://api:8000'+path,
              'authentication':'genericCredentialType','genericAuthType':'httpHeaderAuth',
              'options':{'timeout':120000}}
    if body:
        params.update({'sendBody':True,'specifyBody':'json','jsonBody':body})
    return node(name,'httpRequest',params,x,4.2,{'httpHeaderAuth':{'id':'CONFIGURE_API_HEADER_CREDENTIAL','name':'Mailbox Reader API'}})


def workflow(name,nodes,edges):
    connections = {}
    for source,target,index in edges:
        connections.setdefault(source,{'main':[[]]})
        while len(connections[source]['main'])<=index:
            connections[source]['main'].append([])
        connections[source]['main'][index].append({'node':target,'type':'main','index':0})
    return {'name':name,'active':False,'nodes':nodes,'connections':connections,
            'settings':{'executionOrder':'v1','saveDataErrorExecution':'none',
                        'saveDataSuccessExecution':'none','saveManualExecutions':False,
                        'saveExecutionProgress':False,'executionTimeout':300},
            'pinData':{},'tags':[]}


def generate():
    output = {}
    for stream,minutes in [('live',2),('history',1)]:
        nodes = [node('Schedule','scheduleTrigger',{'rule':{'interval':[{'field':'minutes','minutesInterval':minutes}]}},0,1.2),
                 api('Claim page',f'/sync/{stream}/claim',220),
                 node('Page ready','if',{'conditions':{'options':{'caseSensitive':True,'typeValidation':'strict','version':2},
                     'conditions':[{'id':'ready','leftValue':'={{ $json.ready }}','rightValue':True,
                                    'operator':{'type':'boolean','operation':'true','singleValue':True}}],
                     'combinator':'and'},'options':{}},440,2.2)]
        graph = node('Read Outlook page','httpRequest',{
            'method':'GET','url':'={{ $json.url }}',
            'authentication':'genericCredentialType','genericAuthType':'oAuth2Api',
            'sendHeaders':True,'headerParameters':{'parameters':[
                {'name':'Prefer','value':'IdType="ImmutableId", outlook.body-content-type="text"'},
                {'name':'Accept','value':'application/json'}]},
            'options':{'timeout':90000,
                       'redirect':{'redirect':{'followRedirects':False}},
                       'response':{'response':{'fullResponse':True,'neverError':True,'responseFormat':'json'}}}},660,4.2,
            {'oAuth2Api':{'id':'CONFIGURE_OUTLOOK_READ_ONLY_OAUTH','name':'Outlook Mail.Read only'}})
        nodes += [graph,api('Commit page',f'/sync/{stream}/page',880,body='={{ { lease: $("Claim page").first().json.lease, status: $json.statusCode, body: $json.body, headers: $json.headers } }}')]
        edges = [('Schedule','Claim page',0),('Claim page','Page ready',0),('Page ready','Read Outlook page',0),('Read Outlook page','Commit page',0)]
        output[f'outlook_{stream}.json'] = workflow(f'Mailbox Reader — Outlook {stream} (read only)',nodes,edges)
    output['extract_and_monitor.json'] = workflow('Mailbox Reader — AI extraction and possible overdue review',[
        node('Schedule','scheduleTrigger',{'rule':{'interval':[{'field':'minutes','minutesInterval':1}]}},0,1.2),
        api('Extract one message','/extract',220),api('Refresh review findings','/monitor',440,'GET')],
        [('Schedule','Extract one message',0),('Extract one message','Refresh review findings',0)])
    return output


if __name__=='__main__':
    (ROOT/'workflows').mkdir(exist_ok=True)
    for filename,data in generate().items():
        (ROOT/'workflows'/filename).write_text(json.dumps(data,indent=2)+'\n')
