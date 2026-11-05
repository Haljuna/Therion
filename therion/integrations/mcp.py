"""Cliente MCP stdio de leitura, para programas cadastrados e fixados por hash.

Implementa o subconjunto initialize/notifications/initialized/tools/list/call
da especificação 2025-06-18. Não instala servidores, não oferece sampling,
elicitation, shell, HTTP ou execução de código dentro do processo principal.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import threading
import time

from therion.agent.registry import validate
from therion.agent.proposals import fingerprint


def validate_schema(schema,depth=0):
    if depth>6 or not isinstance(schema,dict) or schema.get('type') not in {'object','array','string','integer','number','boolean','null'}:
        raise ValueError('Schema MCP fora do subconjunto suportado.')
    allowed={'type','description','properties','required','additionalProperties','items','maxItems','enum','minLength','maxLength','minimum','maximum'}
    if set(schema)-allowed:raise ValueError('Schema MCP contém restrição não suportada.')
    for key in ('minLength','maxLength','maxItems'):
        if key in schema and (type(schema[key]) is not int or not 0<=schema[key]<=16000):raise ValueError('Limite de schema MCP inválido.')
    for key in ('minimum','maximum'):
        if key in schema and type(schema[key]) not in (int,float):raise ValueError('Limite numérico MCP inválido.')
    if 'enum' in schema and (not isinstance(schema['enum'],list) or not 1<=len(schema['enum'])<=50):raise ValueError('Enum MCP inválido.')
    if schema['type']=='object':
        properties=schema.get('properties',{});required=schema.get('required',[])
        if not isinstance(properties,dict) or len(properties)>20 or any(not isinstance(key,str) or len(key)>100 for key in properties) or not isinstance(required,list) or any(not isinstance(key,str) for key in required) or not set(required)<=set(properties):raise ValueError('Objeto MCP inválido.')
        for child in properties.values():validate_schema(child,depth+1)
    if schema['type']=='array':validate_schema(schema.get('items'),depth+1)


def validate_registry(rows):
    if not isinstance(rows,list) or len(rows)>4:raise ValueError('Cadastre no máximo quatro servidores MCP.')
    if len(json.dumps(rows,allow_nan=False).encode('utf-8'))>128000:raise ValueError('Cadastro MCP acima do limite.')
    result=[];identifiers=set()
    for row in rows:
        if not isinstance(row,dict) or set(row)!={'id','command','args','pinned_files','tools'}:raise ValueError('Cadastro MCP precisa de id, command, args, pinned_files e tools.')
        if not isinstance(row['id'],str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,11}',row['id']) or row['id'] in identifiers:raise ValueError('ID MCP inválido ou duplicado.')
        identifiers.add(row['id'])
        if not isinstance(row['command'],str):raise ValueError('Executável MCP inválido.')
        command=Path(row['command'])
        if not command.is_absolute() or command.suffix.lower()!='.exe' or command.name.casefold() in {'cmd.exe','powershell.exe','pwsh.exe','wscript.exe','cscript.exe','mshta.exe','rundll32.exe','regsvr32.exe','bash.exe','uv.exe','npx.exe','npm.exe'}:
            raise ValueError('Use executável local explícito; shells e instaladores não são servidores cadastráveis.')
        if not isinstance(row['args'],list) or len(row['args'])>20 or any(not isinstance(arg,str) or len(arg)>2000 for arg in row['args']):raise ValueError('Argumentos MCP inválidos.')
        pins=row['pinned_files']
        if not isinstance(pins,dict) or not 1<=len(pins)<=20 or any(not Path(path).is_absolute() or not isinstance(value,str) or not re.fullmatch(r'[0-9a-f]{64}',value) for path,value in pins.items()):raise ValueError('Fixe os arquivos locais por SHA-256.')
        pinned={os.path.normcase(os.path.abspath(path)) for path in pins}
        if os.path.normcase(str(command)) not in pinned:raise ValueError('O executável MCP precisa de hash fixado.')
        if command.name.casefold().startswith(('python','node')):
            if not row['args'] or not Path(row['args'][0]).is_absolute() or Path(row['args'][0]).suffix.lower() not in {'.py','.js','.mjs'} or os.path.normcase(row['args'][0]) not in pinned:
                raise ValueError('Interpretador MCP exige arquivo de servidor absoluto e fixado; código inline não é aceito.')
        tools=row['tools']
        if not isinstance(tools,list) or not 1<=len(tools)<=10:raise ValueError('Cadastre de uma a dez ferramentas de leitura por servidor.')
        names=set()
        for tool in tools:
            if not isinstance(tool,dict) or set(tool)!={'name','description','inputSchema','effect'} or tool['effect']!='read':raise ValueError('Esta versão MCP aceita somente ferramentas revisadas de leitura.')
            if not isinstance(tool['name'],str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,31}',tool['name']) or tool['name'] in names:raise ValueError('Nome de ferramenta MCP inválido ou duplicado.')
            names.add(tool['name'])
            if not isinstance(tool['description'],str) or not 1<=len(tool['description'])<=500:raise ValueError('Descreva a ferramenta MCP revisada.')
            validate_schema(tool['inputSchema'])
            if tool['inputSchema']['type']!='object':raise ValueError('Ferramenta MCP exige argumentos objeto.')
        result.append(deepcopy(row))
    return result


def verify_pins(config):
    for name,expected in config['pinned_files'].items():
        from therion.memory.knowledge import safe_path
        path=Path(name);path=safe_path(path,(str(path.parent.resolve()),))
        if not path.is_file() or path.stat().st_nlink!=1 or path.stat().st_size>100_000_000:
            raise ValueError('Arquivo MCP fora dos limites ou com vínculo não permitido.')
        with path.open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
        if actual!=expected:raise ValueError('Arquivo do servidor MCP mudou desde a revisão.')


class MCPSession:
    def __init__(self,config):
        self.config=validate_registry([config])[0];self.process=None;self.messages=queue.Queue();self.sequence=0

    def _send(self,row):
        self.process.stdin.write(json.dumps(dict(jsonrpc='2.0',**row),ensure_ascii=False)+'\n');self.process.stdin.flush()

    def _request(self,method,params):
        self.sequence+=1;identifier=self.sequence;self._send({'id':identifier,'method':method,'params':params})
        deadline=time.monotonic()+15
        for _ in range(64):
            try:row=self.messages.get(timeout=max(.01,deadline-time.monotonic()))
            except queue.Empty:raise TimeoutError('Servidor MCP excedeu o prazo.') from None
            if row is None:raise OSError('Servidor MCP encerrou ou excedeu o limite de mensagem.')
            if not isinstance(row,dict) or row.get('jsonrpc')!='2.0':raise ValueError('Resposta MCP inválida.')
            if 'method' in row:
                if 'id' in row:self._send({'id':row['id'],'error':{'code':-32601,'message':'Capacidade do cliente não disponível.'}})
                continue
            if row.get('id')!=identifier:raise ValueError('Resposta MCP não corresponde ao pedido ativo.')
            if 'error' in row:raise OSError('Servidor MCP recusou a solicitação; nenhum resultado foi confirmado.')
            if not isinstance(row.get('result'),dict):raise ValueError('Resultado MCP inválido.')
            return row['result']
        raise ValueError('Servidor MCP enviou mensagens auxiliares além do limite.')

    def _start(self):
        if self.process is not None and self.process.poll() is None:return
        verify_pins(self.config)
        env={key:value for key,value in os.environ.items() if key.upper() in {'PATH','SYSTEMROOT','WINDIR','TEMP','TMP','LOCALAPPDATA','APPDATA','USERPROFILE'}}
        self.messages=queue.Queue(maxsize=64)
        self.process=subprocess.Popen([self.config['command'],*self.config['args']],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,text=True,encoding='utf-8',env=env,cwd=str(Path(self.config['command']).parent),creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        process=self.process;messages=self.messages
        def reader():
            try:
                while True:
                    line=process.stdout.readline(128001)
                    if not line or len(line)>128000:break
                    try:messages.put(json.loads(line),timeout=.1)
                    except (ValueError,queue.Full):break
            finally:
                try:messages.put(None,timeout=.1)
                except queue.Full:pass
        threading.Thread(target=reader,daemon=True).start()
        initialized=self._request('initialize',{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'Therion','version':'1'}})
        if initialized.get('protocolVersion') not in {'2024-11-05','2025-03-26','2025-06-18'} or not isinstance(initialized.get('capabilities',{}).get('tools'),dict):
            raise ValueError('Versão ou capacidade MCP não suportada.')
        self._send({'method':'notifications/initialized'})

    def dispatch(self,operation,args):
        if operation!='call':raise ValueError('Operação MCP não registrada.')
        tool=next((row for row in self.config['tools'] if row['name']==args.get('name')),None)
        if tool is None:raise ValueError('Ferramenta MCP fora do cadastro.')
        validate(args.get('arguments'),tool['inputSchema'])
        try:
            verify_pins(self.config)
            self._start();found={};cursor=None
            for _ in range(4):
                page=self._request('tools/list',{'cursor':cursor} if cursor else {})
                if not isinstance(page.get('tools'),list) or len(page['tools'])>100:raise ValueError('Catálogo MCP acima do limite.')
                found.update({row['name']:row for row in page['tools'] if isinstance(row,dict) and isinstance(row.get('name'),str)})
                cursor=page.get('nextCursor')
                if not cursor:break
            actual=found.get(tool['name'])
            if actual is None or fingerprint(actual.get('inputSchema'))!=fingerprint(tool['inputSchema']):raise ValueError('Schema MCP mudou; revise novamente o cadastro.')
            result=self._request('tools/call',{'name':tool['name'],'arguments':args['arguments']})
            if result.get('isError') is True:raise OSError('A ferramenta MCP informou falha; resultado não confirmado.')
            if not isinstance(result.get('content'),list) or any(not isinstance(item,dict) or item.get('type')!='text' or not isinstance(item.get('text'),str) for item in result['content']):
                raise ValueError('Somente conteúdo textual MCP é suportado nesta entrega.')
            if len(json.dumps(result,ensure_ascii=False).encode('utf-8'))>8000:raise ValueError('Resposta MCP grande demais; refine a consulta ou use paginação da ferramenta cadastrada.')
            return result
        except Exception:
            self.close();raise

    def close(self):
        process,self.process=self.process,None
        if process is None:return
        if process.poll() is None:
            process.stdin.close()
            try:process.wait(timeout=.2)
            except subprocess.TimeoutExpired:
                if os.name=='nt':subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW,timeout=10,check=False)
                else:process.kill()
                process.wait(timeout=5)
        for stream in (process.stdin,process.stdout):
            if stream and not stream.closed:stream.close()
