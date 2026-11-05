"""Memória supervisionada no runtime, sem enviar prévias ao modelo.

O pedido humano é interpretado pelo parser existente. Um provider determinístico
escolhe somente o adapter fixo; conteúdo/segredos ficam no executor e na UI.
Confirmações e revogações continuam controles da aplicação.
"""
import asyncio
from .contracts import AgentDecision,ToolCall,ToolResult,ToolSpec,CancellationToken,TurnBudget
from .registry import ToolRegistry,object_schema
from .runtime import AgentRuntime


class ControlProvider:
    def __init__(self,operation):self.operation=operation;self.started=False
    async def decide(self,messages,schemas,budget,token,event):
        token.check()
        if not self.started:
            self.started=True
            return AgentDecision('tools',calls=(ToolCall('memory_control',{'operation':self.operation}),))
        return AgentDecision('final','Controle supervisionado processado; confira o resultado na interface.')


def run_memory_control(host,command,request,cancelled=None):
    from therion.core.orchestrator import OrchestrationResult
    operation=request['operation'];session=host.session_id;original=[]
    try:store=host._get_agent_store();store.purge()
    except (ValueError,OSError):return OrchestrationResult(status='ai_unavailable',message='Recibos indisponíveis; não iniciei a operação de memória.')
    token=CancellationToken(cancelled);registry=ToolRegistry(control_tools=False)
    def allowed(args):return args['operation']==operation and host.session_id==session and host._agent_original_request==command
    async def execute(args,cancel):
        cancel.check()
        result=host._process_command(command,cancelled=cancel)
        original.append(result)
        # O conteúdo da prévia não entra em mensagens, eventos ou histórico do
        # runtime. A interface recebe o resultado original por canal separado.
        status={'success':'success','clarification':'awaiting_clarification','awaiting_confirmation':'awaiting_confirmation',
            'cancelled':'cancelled','forbidden':'blocked'}.get(result.status,'uncertain')
        return ToolResult(status,message='Controle de memória: '+operation,
            side_effect_state='verified' if status=='success' else 'pending' if status=='awaiting_confirmation' else 'uncertain' if status=='uncertain' else 'none')
    registry.register(ToolSpec('memory_control','Adapter fixo de pedido humano de memória; não interpreta confirmação do modelo.',
        object_schema(operation={'type':'string','enum':[operation]}),execute,effect='external',authorize=allowed,
        verify=lambda args,result:bool(original and original[-1].status=='success')))
    host._agent_events.clear()
    runtime=AgentRuntime(ControlProvider(operation),registry,store=store,emit=host._agent_events.append)
    host._agent_runtime=runtime;host._agent_turn_token=token
    try:
        result=asyncio.run(runtime.run('Controle supervisionado de memória: '+operation,session_id=session,
            token=token,budget=TurnBudget(seconds=60,iterations=2),temporary=True))
    finally:
        if host._agent_turn_token is token:host._agent_turn_token=None
    if host.session_id!=session:return OrchestrationResult(status='cancelled',message='A conversa foi encerrada; descartei a prévia anterior.')
    if result.status in {'cancelled','failed','partial','uncertain'}:
        host._cancel_memory_save()
        return OrchestrationResult(status='cancelled' if result.status=='cancelled' else 'uncertain',message=result.message)
    if result.status=='awaiting_confirmation' and host._confirmation_id:
        call=next((call for call,row in result.results if call.name=='memory_control'),None)
        if call:host._agent_legacy_pending[host._confirmation_id]={'call_id':call.id,'session':session,'plan':None}
    if original:return original[-1]
    return OrchestrationResult(status='cancelled' if result.status=='cancelled' else 'ai_unavailable',message=result.message)
