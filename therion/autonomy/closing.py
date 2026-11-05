"""Fechamento normal e supervisionado; sem kill, shell ou resposta a diálogos."""
import time
import sqlite3

from therion.context.conversation_frame import app_close_request
from therion.context.language import control
from therion.core.intent import Intent
from therion.core.planner import Plan


class CloseSupport:
    def _close_permitted(self,app,command):
        return self.permission_manager.is_allowed(Intent('abrir aplicativo',app.id,command))

    def _close_request(self,command):
        from therion.core.orchestrator import OrchestrationResult
        target=app_close_request(command)
        if target is None:return None
        if self.application_catalog is None:return OrchestrationResult(status='clarification',message='O catálogo não está disponível para preparar o fechamento.')
        try:
            entries=self.application_catalog.entries()
            matches=[a for a in entries if target in {control(a.name),control(a.id),*(control(s) for s in a.aliases)}]
            if not matches and self.voice_conversation and target=='obsidio':
                matches=[a for a in entries if control(a.name)=='obsidian']
            if not matches and self.voice_conversation and target in {'jaminai','geminai','gemeo'}:
                matches=[a for a in entries if control(a.name)=='gemini']
            if len(matches)!=1:return OrchestrationResult(status='clarification',message='Não identifiquei um único aplicativo aprovado para fechar. Diga o nome cadastrado; nada foi fechado.')
            app=matches[0]
            try:valid=self.application_catalog.valid(app)
            except (OSError,ValueError):
                return OrchestrationResult(status='verification_failed',message=f'O executável cadastrado de {app.name} está ausente ou não pôde ser conferido. O aplicativo pode ter sido atualizado. Revise o caminho no painel Autonomia; nada foi fechado.')
            if not valid:
                # Atualização automática (ex.: Chrome) troca o executável; o cadastro precisa ser revisto.
                return OrchestrationResult(status='forbidden',message=f'O executável de {app.name} mudou desde o cadastro, provavelmente por uma atualização. Revise {app.name} no painel Autonomia; nada foi fechado.')
            if not self._close_permitted(app,command):
                return OrchestrationResult(status='forbidden',message=f'{app.name} não tem permissão ativa no painel Autonomia. Nada foi fechado.')
            plan=Plan(Intent('fechar aplicativo',app.id,command,True),[
                f'Solicitar fechamento normal das janelas de {app.name}.','Verificar janelas e processo; não forçar encerramento nem responder diálogos de salvamento.'])
            self._pending_close_app=app
            self._pending_action_plan=plan;self._pending_action_fingerprint=self._plan_fingerprint(plan)
            self.memory.record_plan(plan.steps);self.memory.record_awaiting_confirmation()
            return OrchestrationResult(status='awaiting_confirmation',intent=plan.intent,plan=plan,
                message=f'Fechar as janelas de {app.name}?')
        except (OSError,ValueError,TypeError,sqlite3.Error):
            return OrchestrationResult(status='verification_failed',message='Não consegui preparar o fechamento. Nada foi fechado.')

    def _wait_close(self,app,timeout=10):
        deadline=time.monotonic()+timeout
        while True:
            if not self.catalog_launcher.windows(app.path) and not self.catalog_launcher.is_running(app):return True
            remaining=deadline-time.monotonic()
            if remaining<=0:return False
            time.sleep(min(.25,remaining))

    def _execute_close(self,plan,simulated):
        from therion.core.orchestrator import OrchestrationResult
        if plan.intent.action!='fechar aplicativo':return None
        app=self._pending_close_app;self._pending_close_app=None;attempt=None;sent=False
        try:
            if app is None or plan.intent.target!=app.id or not self.application_catalog.valid(app) or not self._close_permitted(app,plan.intent.raw_command):
                raise ValueError('Permissão ou cadastro mudou')
            simulated=self._catalog_simulated(simulated)
            if not simulated:
                windows=self.catalog_launcher.closeable_windows(app)
                if not windows:
                    message=(f'{app.name} continua com processo ativo, mas não encontrei janela acessível para fechar. Não forcei o encerramento.' if self.catalog_launcher.is_running(app) else
                             f'Não encontrei processo ou janela acessível de {app.name}; não enviei fechamento.')
                    return OrchestrationResult(status='success',message=message)
            from .integration import implementation_version
            attempt=self.autonomy.store.begin('close_app',app.id,implementation_version(self.autonomy,app.as_dict()),'simulation' if simulated else 'supervised')
            if simulated:
                self.autonomy.store.finish(attempt,'success',False)
                return OrchestrationResult(status='executed_simulated',message=f'Simulei o fechamento de {app.name}; nenhuma janela foi fechada.')
            if not self.application_catalog.valid(app) or not self._close_permitted(app,plan.intent.raw_command):raise ValueError('Permissão revogada')
            sent=True;self.catalog_launcher.close_windows(app.path,windows)
            verified=self._wait_close(app)
            self.autonomy.store.finish(attempt,'success' if verified else 'uncertain',verified)
            return OrchestrationResult(status='success' if verified else 'verification_failed',
                message=f'Fechei {app.name} e confirmei o encerramento das janelas e do processo.' if verified else
                f'Solicitei o fechamento de {app.name}, mas ele ainda tem janela ou processo ativo. Confira se há pedido de salvamento ou se ficou na bandeja. Não forcei nem repeti.')
        except (OSError,ValueError,TypeError,sqlite3.Error):
            if attempt:
                try:self.autonomy.store.finish(attempt,'uncertain' if sent else 'failed')
                except (OSError,ValueError,sqlite3.Error):pass
            return OrchestrationResult(status='execution_failed',message='Não confirmei o fechamento. Não anunciei encerramento nem repeti a ação.')
