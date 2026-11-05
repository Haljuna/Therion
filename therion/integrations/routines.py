"""Rotinas V4 sob confirmação central; regras e recibos antigos preservados."""
from therion.agent.contracts import ToolResult,ToolSpec
from therion.agent.execution import cooperative_call
from therion.agent.registry import object_schema,TEXT
from therion.autonomy.routines import RoutineService


def register_routine_tools(registry,host):
    runtime=getattr(host,'autonomy',None)
    if runtime is None:return
    service=RoutineService(host,runtime)
    def enabled():return host._agent_config.get('enabled') is True and host.autonomy is runtime
    async def listing(args,token):
        token.check()
        data=[dict(spec.as_dict(),version=service.version(spec)) for spec in service.entries()]
        return ToolResult('success',data=data)
    async def prepare(args,token):
        token.check()
        spec=next((row for row in service.entries() if row.id==args['id']),None)
        if spec is None:return ToolResult('blocked',message='Selecione uma rotina existente; o modelo não cadastra nem habilita rotinas.')
        version=service.version(spec)
        def current(row,cancel):
            return enabled() and not cancel.cancelled and spec in service.entries() and service.version(spec)==version
        def execute(row,cancel):
            execution_service=service
            from therion.calendar.google_adapter import GoogleCalendarAdapter
            if isinstance(host.calendar_adapter,GoogleCalendarAdapter):
                from .calendar import RuntimeCalendarReadAdapter
                class ReadHost:
                    calendar_adapter=RuntimeCalendarReadAdapter(host,cancel)
                    def __getattr__(self,name):return getattr(host,name)
                execution_service=RoutineService(ReadHost(),runtime)
            result=execution_service.run(spec,supervised=True,cancelled=cancel)
            if result.status=='success':return {'id':result.attempt,'message':result.message}
            return ToolResult('cancelled' if cancel.cancelled else 'blocked',message=result.message)
        def verify(row,value,cancel):
            if cancel.cancelled or not current(row,cancel):return False
            with runtime.store.connection() as db:
                receipt=db.execute('SELECT * FROM evidence WHERE id=?',(value['id'],)).fetchone()
            return bool(receipt and receipt['operation']==spec.operation and receipt['target']==spec.id
                and receipt['context_version']==version and receipt['status']=='success' and receipt['verified']==1)
        preview=('Executar uma vez a rotina existente, como teste supervisionado V4.\n'
            'Rotina: '+spec.id+'\nOperação: '+spec.operation+'\nFontes selecionadas: '+str(list(spec.sources))+
            '\nVersão: '+version+'\nNão habilita agendamento nem concede autonomia. Os critérios de dez sucessos e sete dias permanecem.')
        row=host._agent_proposals.prepare('routines.run',{'id':spec.id,'expected_version':version},preview,
            execute,verify,current,token_aware=True,preparation_token=token)
        return ToolResult('awaiting_confirmation',data={'proposal_id':row.id},message='Revise a execução supervisionada da rotina no painel Capacidades.',side_effect_state='pending')
    registry.register(ToolSpec('routine_list','Listar rotinas V4 existentes e versões. Não cria políticas.',object_schema(),listing,authorize=lambda args:enabled(),available=enabled))
    registry.register(ToolSpec('routine_prepare_run','Preparar execução única supervisionada de rotina V4 existente, sem habilitar agendamento ou autonomia.',object_schema(id=TEXT),prepare,
        effect='prepare',authorize=lambda args:enabled(),available=enabled))
