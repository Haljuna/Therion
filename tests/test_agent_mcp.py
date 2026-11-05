import hashlib
import json
from pathlib import Path
import sys

import pytest

from therion.agent.contracts import CancellationToken
from therion.integrations.mcp import validate_registry
from therion.integrations.rpc import OwnedWorker


@pytest.fixture
def registration(tmp_path):
    server=tmp_path/'fixture_mcp.py'
    server.write_text('''import json,sys
schema={'type':'object','properties':{'query':{'type':'string','maxLength':100}},'required':['query'],'additionalProperties':False}
for line in sys.stdin:
 row=json.loads(line)
 if 'id' not in row:continue
 method=row['method']
 if method=='initialize':result={'protocolVersion':'2025-06-18','capabilities':{'tools':{}},'serverInfo':{'name':'fixture','version':'1'}}
 elif method=='tools/list':result={'tools':[{'name':'lookup','inputSchema':schema}]}
 elif method=='tools/call':result={'content':[{'type':'text','text':'PONTE-42 '+row['params']['arguments']['query']}]}
 else:raise ValueError('unexpected')
 print(json.dumps({'jsonrpc':'2.0','id':row['id'],'result':result}),flush=True)
''',encoding='utf-8')
    return {'id':'fixture','command':sys.executable,'args':[str(server)],
        'pinned_files':{name:hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in (sys.executable,str(server))},
        'tools':[{'name':'lookup','description':'Consulta fictícia de leitura','effect':'read',
            'inputSchema':{'type':'object','properties':{'query':{'type':'string','maxLength':100}},'required':['query'],'additionalProperties':False}}]}


def test_mcp_stdio_owned_worker_read_schema_and_file_revalidation(registration):
    worker=OwnedWorker('mcp',registration);token=CancellationToken()
    try:
        result=worker.call('call',{'name':'lookup','arguments':{'query':'Aurora'}},token)
        assert result['content'][0]['text']=='PONTE-42 Aurora'
        with pytest.raises(ValueError,match='cadastro'):worker.call('call',{'name':'send','arguments':{}},token)
        with pytest.raises(ValueError,match='limite'):worker.call('call',{'name':'lookup','arguments':{'query':'x'*101}},token)
        Path(registration['args'][0]).write_text('alterado',encoding='utf-8')
        with pytest.raises(ValueError,match='mudou'):worker.call('call',{'name':'lookup','arguments':{'query':'Aurora'}},token)
    finally:worker.close()
    assert worker.process is None


def test_mcp_schema_change_is_not_trusted(registration):
    registration['tools'][0]['inputSchema']['properties']['query']['maxLength']=99
    worker=OwnedWorker('mcp',registration)
    try:
        with pytest.raises(ValueError,match='Schema'):worker.call('call',{'name':'lookup','arguments':{'query':'Aurora'}},CancellationToken())
    finally:worker.close()


@pytest.mark.parametrize('mutation',[lambda row:row.update(command='cmd.exe'),
    lambda row:row['tools'][0].update(effect='external'),
    lambda row:row.update(args=['-c','print(1)']),
    lambda row:row['tools'][0]['inputSchema'].update(oneOf=[]),
    lambda row:row['tools'][0]['inputSchema'].update(required=[{}])])
def test_mcp_registration_rejects_unsupported_execution_and_schema(registration,mutation):
    mutation(registration)
    with pytest.raises(ValueError):validate_registry([registration])
