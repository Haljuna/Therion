import asyncio
import hashlib
from types import SimpleNamespace

import pytest

from therion.agent.builtin import build_read_registry
from therion.agent.contracts import CancellationToken,ToolCall
from therion.agent.store import SessionStore
from therion.agent.procedures import ProcedureLibrary
from therion.integrations.documents import DocumentAdapter
from therion.integrations.excerpts import excerpt


def test_document_pages_reconstruct_original(tmp_path):
    original='começo\n'+'ABCDEF'*3000+'\nfim'
    path=tmp_path/'fixture.md';path.write_bytes(original.encode('utf-8'))
    adapter=DocumentAdapter([tmp_path]);offset=0;parts=[]
    while True:
        page=adapter.read(path,offset,1024)
        parts.extend(row['text'] for row in page['sections'])
        assert sum(len(row['text']) for row in page['sections'])<=1024
        if page['next_offset'] is None:break
        assert page['next_offset']>offset
        offset=page['next_offset']
    assert ''.join(parts)==original and page['partial']


def test_many_small_sections_are_bounded_and_recoverable():
    sections=[{'section':str(i),'text':'x\n'} for i in range(80)]
    rows=[];offset=0
    while True:
        page=excerpt(sections,offset)
        assert len(page['sections'])<=20
        rows.extend(row['section'] for row in page['sections'])
        if page['next_offset'] is None:break
        offset=page['next_offset']
    assert rows==[str(i) for i in range(80)]


def test_substitution_preserves_original_bytes(tmp_path):
    adapter=DocumentAdapter([tmp_path],[tmp_path]);path=tmp_path/'fixture.md'
    path.write_bytes(b'original\r\nconteudo')
    version=adapter.version(path)
    result=adapter.write(path,'novo',version)
    from pathlib import Path
    assert Path(result['original_path']).read_bytes()==b'original\r\nconteudo'
    assert result['original_version']==version and path.read_text()=='novo'


def test_conflicting_original_backup_is_preserved(tmp_path):
    adapter=DocumentAdapter([tmp_path],[tmp_path]);path=tmp_path/'fixture.md';path.write_text('original')
    version=adapter.version(path);copy=tmp_path/('fixture.therion-original-'+version[:12]+'.md');copy.write_text('diferente')
    with pytest.raises(ValueError,match='cópia'):adapter.write(path,'novo',version)
    assert path.read_text()=='original' and copy.read_text()=='diferente'


def test_two_searches_do_not_reassign_source_ids(tmp_path):
    paths={name:tmp_path/(name+'.md') for name in ('Aurora','Lótus')}
    for name,path in paths.items():path.write_text(name,encoding='utf-8')
    reader=SimpleNamespace(vault_root=str(tmp_path),allowed_roots=[str(tmp_path)],_check_access=lambda:None)
    reader.search_notes=lambda query,**kwargs:[SimpleNamespace(path=paths[query].name,version=hashlib.sha256(query.encode()).hexdigest(),snippet=query)]
    reader.read_note=lambda name,**kwargs:SimpleNamespace(success=True,content=(tmp_path/name).read_text(encoding='utf-8'),canonical_path=str(tmp_path/name))
    host=SimpleNamespace(second_brain=reader,_sync_knowledge_access=lambda:None,_knowledge_repository=None,calendar_adapter=None,_history_sources_allowed=lambda evidence:True)
    tools=build_read_registry(host)
    async def call(name,args):
        spec,rejected=tools.prepare(ToolCall(name,args));assert rejected is None
        return await spec.handler(args,CancellationToken())
    async def scenario():
        one=await call('search_notes',{'query':'Aurora'});two=await call('search_notes',{'query':'Lótus'})
        assert one.data[0]['id']!=two.data[0]['id']
        assert (await call('read_source',{'source_id':one.data[0]['id']})).data['text']=='Aurora'
        assert (await call('read_source',{'source_id':two.data[0]['id']})).data['text']=='Lótus'
    asyncio.run(scenario())


def test_procedure_duplicate_does_not_skip_revision_check(tmp_path):
    library=ProcedureLibrary(SessionStore(tmp_path/'history.sqlite3'))
    body={key:'Procedimento técnico '+key for key in ('title','goal','preconditions','tools','steps','verification','limitations')}
    identifier=library.propose(body,{})
    with pytest.raises(ValueError,match='revisão atual'):library.propose(body,{},identifier,'digest antigo')
    digest=library.get(identifier)['digest'];body['steps']='Passos corrigidos'
    library.propose(body,{},identifier,digest)
    assert library.get(identifier)['revision']==2
