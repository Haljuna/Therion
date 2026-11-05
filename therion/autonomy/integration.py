"""Integração ao Orchestrator; o catálogo não cria um executor paralelo ao ciclo."""
from pathlib import Path
import functools
import hashlib
import time

from .apps import ApplicationCatalog, CatalogLauncher
from .policy import fingerprint
from .closing import CloseSupport


@functools.cache
def _code_digest():
    # Uma vez por processo: o código em execução só muda reiniciando, e aí o hash é refeito.
    root = Path(__file__).resolve().parents[1]
    # Novos caminhos de decisão/transporte também invalidam pilotos antigos.
    # Interface e documentação não entram no fingerprint de execução.
    files = sorted(path for folder in ('autonomy','agent','integrations','voice','calendar',
        'core','memory','governance','context','skills','config') for path in (root/folder).rglob('*.py'))
    digest=hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode());digest.update(path.read_bytes())
    return digest.hexdigest()


def implementation_version(runtime, scope):
    config=runtime.loader()
    return fingerprint(dict(implementation=_code_digest(),
        ai=config.get('ai',{}),agent=config.get('agent',{}),stt=config.get('voice',{}),tts=config.get('tts',{}),scope=scope))


class CatalogSupport(CloseSupport):
    def _remember_status_prompt(self):
        self._pending_status_query=(self.session_id,self._language_clock()+120)

    def _catalog_status_followup(self,command):
        from therion.context.language import application_control,control
        pending=getattr(self,'_pending_status_query',None)
        if pending is None:return None
        if pending[0]!=self.session_id or self._language_clock()>pending[1]:
            self._pending_status_query=None;return None
        target=application_control(command)
        try:
            entries=self.application_catalog.entries() if self.application_catalog else []
            matches=[a for a in entries if target in {control(a.name),control(a.id),*(control(s) for s in a.aliases)}]
            if len(matches)==1:return f'{target} esta aberto'
        except (OSError,ValueError,TypeError):pass
        self._pending_status_query=None
        return None

    def _verify_new_browser_window(self,app,before,timeout=10.0):
        deadline=time.monotonic()+timeout
        while True:
            if self.catalog_launcher.windows(app.path)-before:return True
            remaining=deadline-time.monotonic()
            if remaining<=0:return False
            time.sleep(min(0.25,remaining))

    def _catalog_status(self,command):
        """Consulta atual pelo caminho cadastrado, sem lançar ou contar abertura."""
        from therion.context.conversation_frame import app_status_request
        from therion.context.language import control
        from therion.core.orchestrator import OrchestrationResult
        target=app_status_request(command)
        if target is None:
            followup=self._catalog_status_followup(command)
            target=app_status_request(followup) if followup else None
        if target is None:return None
        self._pending_status_query=None
        if self.application_catalog is None or self.catalog_launcher is None:
            return OrchestrationResult(status='clarification',message='O catálogo de aplicativos não está disponível para conferir o processo.')
        try:
            entries=self.application_catalog.entries()
            matches=[app for app in entries if target in {control(app.name),control(app.id),*(control(alias) for alias in app.aliases)}]
            if not matches and self.voice_conversation and target in {'obsidio','obzinho'}:
                matches=[app for app in entries if control(app.name)=='obsidian']
            if not matches and self.voice_conversation and target in {'cronico','tronco'}:
                matches=[app for app in entries if control(app.name)=='chrome' or 'chrome' in {control(alias) for alias in app.aliases}]
            if len(matches)!=1:
                self._remember_status_prompt()
                return OrchestrationResult(status='clarification',message='Qual aplicativo do catálogo você quer conferir? Diga o nome cadastrado no painel Autonomia.')
            app=matches[0]
            # Preserva a mesma permissão do catálogo, sem oferecer outro executor.
            from therion.core.intent import Intent
            if not self.permission_manager.is_allowed(Intent(action='abrir aplicativo',target=app.id,raw_command=command,requires_confirmation=False)):
                return OrchestrationResult(status='forbidden',message='A consulta desse aplicativo não está permitida pelo catálogo atual.')
            if not self.application_catalog.valid(app):
                return OrchestrationResult(status='verification_failed',message=f'Não confirmei o cadastro atual de {app.name}. Revise o executável no painel Autonomia.')
            running=self.catalog_launcher.is_running(app)
            message=(f'Confirmei pelo processo: {app.name} está aberto.' if running else
                     f'Não encontrei um processo acessível de {app.name} pelo caminho cadastrado neste momento. Não abri o aplicativo.')
            return OrchestrationResult(status='success',message=message,speech_message=message)
        except (OSError,ValueError,TypeError):
            return OrchestrationResult(status='verification_failed',message='Não consegui conferir o processo agora. Isso não confirma que o aplicativo esteja fechado.')

    def _verify_catalog_process(self, app, timeout=10.0):
        """Espera limitada pelo executável exato, sem repetir a abertura."""
        deadline = time.monotonic() + timeout
        while True:
            if self.catalog_launcher.is_running(app):
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.25, remaining))

    def _catalog_simulated(self,default=None):
        mode=self.autonomy.section().get('app_opening_mode','inherit')
        if mode not in {'inherit','real','simulation'}:
            raise ValueError('Modo de abertura de aplicativos inválido.')
        return mode=='simulation' if mode!='inherit' else (self.simulate if default is None else default)

    def _init_autonomy(self, runtime):
        self.autonomy = runtime
        self.application_catalog = ApplicationCatalog(runtime) if runtime else None
        self.permission_manager.application_catalog = self.application_catalog
        self.catalog_launcher = CatalogLauncher(self.application_catalog) if runtime else None
        self._pending_catalog_app = None
        self._pending_catalog_decision = None
        self._force_supervised_catalog = False
        self._pending_close_app = None
        self._pending_status_query = None

    def _catalog_request(self, intent, resolved_target):
        from therion.core.orchestrator import OrchestrationResult
        from therion.core.intent import Intent
        if self.application_catalog is None or intent.action != 'abrir aplicativo':
            return None
        try:
            choices=self.application_catalog.resolve(resolved_target)
            if not choices:
                # A rota antiga preserva Obsidian e os diálogos legados de aliases.
                if resolved_target == 'Obsidian':return None
                return OrchestrationResult(status='forbidden',message=
                    'Esse aplicativo não está no catálogo aprovado. Abra Autonomia → Aplicativos '
                    'para descobrir ou cadastrar o executável e revisar sua permissão.')
            if len(choices)>1:
                return OrchestrationResult(status='unknown_intent',message=
                    'Há mais de um aplicativo com esse nome. Use um alias exclusivo ou o ID:\n'+
                    '\n'.join(a.name+' — '+a.id for a in choices))
            app=choices[0]
            new_window=bool((intent.entities or {}).get('new_window'))
            if new_window and Path(app.path).name.casefold()!='chrome.exe':
                return OrchestrationResult(status='clarification',message='A abertura de nova janela está disponível para o Chrome cadastrado. Para este aplicativo, peça a abertura normal.')
            if not self.application_catalog.valid(app):
                raise ValueError('O executável mudou ou está ausente. Revise seu cadastro no painel Autonomia.')
            resolved=Intent(action='abrir aplicativo',target=app.id,raw_command=intent.raw_command,
                requires_confirmation=True,entities={'new_window':True} if new_window else None)
            if not self.permission_manager.is_allowed(resolved):
                raise ValueError('A abertura deste aplicativo foi bloqueada pelo gerenciador de permissões.')
            plan=self.planner.create_plan(resolved)
            plan.steps[:]=[f'Abrir {app.name} pelo executável cadastrado.',
                'Verificar o processo pelo caminho completo.']
            if new_window:plan.steps[:]=[f'Abrir nova janela de {app.name} com página em branco.','Verificar uma nova janela visível pelo executável cadastrado.']
            self._pending_catalog_app=app
            self._pending_action_plan=plan
            self._pending_action_fingerprint=self._plan_fingerprint(plan)
            self.memory.record_plan(plan.steps)
            version=implementation_version(self.autonomy,app.as_dict())
            simulated=self._catalog_simulated()
            decision=self.autonomy.decide('open_app',app.id,version,permitted=True)
            local=self.intent_recognizer.parse(intent.raw_command)
            explicit=bool(local and local.action=='abrir aplicativo'
                and app in self.application_catalog.resolve(self.alias_manager.resolve(local.target)))
            if not explicit or self._force_supervised_catalog:
                from .policy import AutonomyDecision
                decision=AutonomyDecision('confirmation','Confirme a abertura interpretada.')
            self._pending_catalog_decision=(decision,version,simulated)
            if decision.mode=='autonomous':
                return self.confirm_and_execute(plan,confirmed=True)
            self.memory.record_awaiting_confirmation()
            return OrchestrationResult(status='awaiting_confirmation',intent=resolved,plan=plan,
                message=(f'Simular a abertura de {app.name}? Nenhum aplicativo será aberto.' if simulated else
                    f'Abrir uma nova janela de {app.name}?' if new_window else f'Abrir {app.name} de verdade?')+f'\nExecutável cadastrado: {app.path}\n{decision.reason}',
                speech_message=f'Posso simular a abertura de {app.name}? Nenhum aplicativo será aberto.' if simulated else
                    f'Posso abrir uma nova janela de {app.name}?' if new_window else f'Posso abrir {app.name}?')
        except (OSError,ValueError,TypeError) as error:
            return OrchestrationResult(status='forbidden',message=str(error))

    def _execute_catalog(self, plan, simulated):
        from therion.core.orchestrator import OrchestrationResult
        app=self._pending_catalog_app
        if app is None or app.id != plan.intent.target:
            return None
        self._pending_catalog_app=None
        planned=self._pending_catalog_decision
        self._pending_catalog_decision=None
        attempt=None
        launched=False
        new_window=bool((plan.intent.entities or {}).get('new_window'))
        try:
            simulated=self._catalog_simulated(simulated)
            if planned and simulated!=planned[2]:
                raise ValueError('O modo de abertura mudou. Faça um novo pedido para revisar a prévia.')
            if not self.application_catalog.valid(app):
                raise ValueError('Cadastro ou executável mudou desde a prévia. Não abri o aplicativo.')
            if not self.permission_manager.is_allowed(plan.intent):
                raise ValueError('A permissão de abertura foi revogada.')
            version=implementation_version(self.autonomy,app.as_dict())
            decision=self.autonomy.decide('open_app',app.id,version,permitted=True)
            if planned and planned[0].mode=='autonomous' and (decision,version)!=planned[:2]:
                raise ValueError('A autorização automática mudou; não executei.')
            if planned and planned[0].mode!='autonomous':
                # Uma confirmação humana continua sendo evidência supervisionada,
                # mesmo se uma política tiver sido ativada após a prévia.
                from .policy import AutonomyDecision
                decision=AutonomyDecision('confirmation','Confirmação individual recebida.')
            if not simulated and not new_window and self.catalog_launcher.is_running(app):
                result=OrchestrationResult(status='success',intent=plan.intent,plan=plan,
                    message=f'{app.name} já está aberto. Não contei uma nova abertura.')
                result.speech_message=result.message
                self.memory.record_execution_result(result.message,success=True)
                self._complete_task();self._finalize_session_result(result)
                return result
            attempt=self.autonomy.begin('open_app',app.id,version,decision,permitted=True,simulation=simulated)
            if self.memory.current_task is not None and decision.mode=='autonomous':
                self.memory.current_task.confirmation_status='dispensada_por_politica:'+decision.policy_id
            def guard():
                if self._catalog_simulated()!=simulated:
                    raise ValueError('O modo de abertura mudou antes da execução.')
                if not self.permission_manager.is_allowed(plan.intent):
                    raise ValueError('A permissão de abertura foi revogada.')
                if not self.application_catalog.valid(app):
                    raise ValueError('Cadastro do aplicativo mudou antes da execução.')
                if decision.mode=='autonomous' and self.autonomy.decide('open_app',app.id,version,
                        permitted=True)!=decision:
                    raise ValueError('Autorização revogada, pausada ou alterada antes da abertura.')
            if simulated:
                self.autonomy.store.finish(attempt,'success',False)
                result=OrchestrationResult(status='executed_simulated',intent=plan.intent,plan=plan,
                    message=(f'Simulei uma nova janela de {app.name}; nenhuma janela foi aberta.' if new_window else
                             f'Simulei a abertura de {app.name}; nenhum aplicativo foi aberto.'))
            else:
                if new_window:
                    launched=True
                    before=self.catalog_launcher.open_new_window(app,guard)
                    verified=self._verify_new_browser_window(app,before)
                else:
                    launched=self.catalog_launcher.open(app,guard)
                    verified=self._verify_catalog_process(app) if launched else False
                self.autonomy.store.finish(attempt,'cancelled' if not launched else
                    'success' if verified else 'uncertain',verified)
                result=OrchestrationResult(status='success' if verified or not launched else 'verification_failed',
                    intent=plan.intent,plan=plan,message=(
                        f'Abri uma nova janela de {app.name} e confirmei a janela.' if new_window and verified else
                        f'Enviei o pedido de nova janela de {app.name}, mas não confirmei a janela. Não repeti.' if new_window else
                        f'{app.name} já está aberto. Não contei uma nova abertura.' if not launched else
                        f'Abri {app.name} e confirmei o processo.' if verified else
                        f'Enviei a abertura de {app.name}, mas não confirmei o processo. Não repeti.'))
            self.memory.record_execution_result(result.message,success=result.status in {'success','executed_simulated'})
            self.memory.record_verification_result(result.message,success=result.status=='success')
            result.speech_message = result.message
        except Exception:
            # Falha operacional nunca autoriza outro caminho de execução.
            if attempt:
                try:
                    self.autonomy.store.finish(attempt,'uncertain' if launched else 'failed')
                except Exception:
                    pass  # A tentativa durável continua running e bloqueia repetição.
            result=OrchestrationResult(status='execution_failed',intent=plan.intent,plan=plan,
                message='Não confirmei a abertura segura ou o registro da operação. Revise o catálogo e as evidências; não repeti a ação.')
            self.memory.record_error(result.message)
        self._complete_task()
        self._finalize_session_result(result)
        return result

