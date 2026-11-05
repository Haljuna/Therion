"""Revisão pós-turno limitada a propostas, cancelável pelo próximo pedido."""
import asyncio
import threading
from .contracts import CancellationToken, ToolSpec, ToolResult, TurnBudget
from .registry import ToolRegistry, object_schema, TEXT
from .runtime import AgentRuntime


class LearningReviewer:
    def __init__(self,library):
        self.library=library
        self.token=None;self.thread=None
        self.lock=threading.Lock()

    def cancel(self):
        token=self.token
        if token:token.cancel()

    def start(self,provider,observations):
        self.cancel()
        if self.thread and self.thread.is_alive():return False
        token=CancellationToken()
        with self.lock:self.token=token
        background_copy=getattr(provider,'background_copy',None)
        if callable(background_copy):provider=background_copy()
        registry=ToolRegistry(control_tools=False)
        consulted=[];read_versions={}
        async def index(args,cancel):
            cancel.check()
            rows=self.library.index()
            consulted[:]=[rows]
            return ToolResult('success',data=rows)
        async def read(args,cancel):
            cancel.check()
            if not consulted or args['id'] not in {row['id'] for row in consulted[0]}:return ToolResult('blocked',message='Consulte o índice e selecione o procedimento.')
            row=self.library.get(args['id']);read_versions[row['id']]=row['digest']
            return ToolResult('success',data=row)
        async def revise(args,cancel):
            with self.lock:
                cancel.check()
                if self.token is not token:return ToolResult('cancelled')
                digest=read_versions.get(args['id'])
                if digest is None:return ToolResult('blocked',message='Leia o procedimento atual antes de propor a correção.')
                identifier=self.library.propose_revision(args['id'],digest,args['body'],{'kind':'operational_review','observations':observations},token=cancel)
                return ToolResult('success',data={'proposal_id':identifier,'state':'proposed'})
        async def propose(args,cancel):
            with self.lock:
                if self.token is not token:return ToolResult('cancelled')
                cancel.check()
                if not consulted:return ToolResult('blocked',message='Consulte o índice atual antes de propor um procedimento.')
                import unicodedata
                normalize=lambda text:' '.join(unicodedata.normalize('NFKC',text).casefold().split())
                if any(normalize(row['title'])==normalize(args['title']) for row in consulted[0]):
                    return ToolResult('blocked',message='Já existe procedimento com este título. Leia a revisão atual e proponha a alteração na revisão supervisionada.')
                identifier=self.library.propose(args,{'kind':'verified_turn','observations':observations},token=cancel)
            return ToolResult('success',data={'proposal_id':identifier,'state':'proposed'})
        registry.register(ToolSpec('procedure_index','Verificar procedimentos existentes antes de criar.',object_schema(),index,authorize=lambda args:True))
        registry.register(ToolSpec('procedure_read','Ler a revisão atual e sua proveniência antes de propor correção.',object_schema(id=TEXT),read,authorize=lambda args:True))
        body_schema=object_schema(**{key:TEXT for key in ('title','goal','preconditions','tools','steps','verification','limitations')})
        registry.register(ToolSpec('procedure_revise','Propor candidata de substituição com diff, mantendo a versão ativa até revisão e testes.',object_schema(id=TEXT,body=body_schema),revise,effect='prepare',authorize=lambda args:True))
        registry.register(ToolSpec('procedure_propose','Propor procedimento genérico, sem dados pessoais; nenhuma ativação.',
            object_schema(**{key:TEXT for key in ('title','goal','preconditions','tools','steps','verification','limitations')}),propose,effect='prepare',authorize=lambda args:True))
        async def review():
            import json
            prompt=('Revise somente os resultados operacionais fictícios/técnicos abaixo. Se houver procedimento reutilizável, '
                'consulte o índice e proponha um procedimento genérico. Se já existir, leia a revisão atual e proponha a correção. Não copie dados pessoais, e-mails ou notas. '
                'Se não houver aprendizado útil, finalize sem proposta.\n'+json.dumps(observations,ensure_ascii=False))
            await AgentRuntime(provider,registry,store=self.library.store).run(prompt,session_id='review',token=token,budget=TurnBudget(seconds=30,iterations=4),temporary=True)
        def run():
            try:asyncio.run(review())
            except Exception:return
        self.thread=threading.Thread(target=run,daemon=True)
        self.thread.start()
