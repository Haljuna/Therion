"""Publica somente ferramentas MCP de leitura do cadastro revisado pelo usuário."""
from therion.agent.contracts import ToolSpec,ToolResult
from therion.agent.execution import cooperative_call
from therion.agent.proposals import fingerprint
from .mcp import validate_registry,verify_pins
from .rpc import OwnedWorker


def register_mcp_tools(registry,host):
    if host._agent_config.get('mcp_enabled') is not True:return
    servers=validate_registry(host._agent_config.get('mcp_servers',[]))
    def register(server):
        digest=fingerprint(server)
        def allowed(args):
            if host._agent_config.get('mcp_enabled') is not True:return False
            return any(row.get('id')==server['id'] and fingerprint(row)==digest for row in host._agent_config.get('mcp_servers',[]))
        key='mcp:'+server['id'];worker=host._agent_workers.get(key)
        if worker is not None and worker.config!=server:worker.close();worker=None
        if worker is None:worker=OwnedWorker('mcp',server,max_response_chars=16000);host._agent_workers[key]=worker
        def tool(spec):
            def available():
                try:verify_pins(server)
                except (OSError,ValueError):return False
                return True
            def verified(args,result):
                try:verify_pins(server)
                except (OSError,ValueError):return False
                return allowed(args)
            async def read(arguments,token):
                data=await cooperative_call(worker.call,'call',{'name':spec['name'],'arguments':arguments},token,token=token)
                token.check()
                if not allowed(arguments):return ToolResult('blocked',message='Cadastro MCP foi revogado durante a consulta.')
                return ToolResult('success',data=data,evidence=({'id':'mcp:'+server['id']+':'+spec['name'],
                    'source':'Servidor MCP cadastrado: '+server['id'],'version':fingerprint(data),'registration':digest},))
            registry.register(ToolSpec('mcp_'+server['id']+'_'+spec['name'],spec['description'],spec['inputSchema'],read,authorize=allowed,
                verify=verified,available=available))
        for spec in server['tools']:tool(spec)
    for server in servers:register(server)
