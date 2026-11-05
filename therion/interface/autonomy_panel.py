"""Autonomia: navegação lateral e controles ligados a cada item."""
from pathlib import Path
from zoneinfo import ZoneInfo
from PySide6.QtCore import QThread,Signal,Qt,QTimer,QTime,QEvent,QSignalBlocker
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QDialog,QWidget,QVBoxLayout,QHBoxLayout,QLabel,QListWidget,
    QListWidgetItem,QStackedWidget,QFrame,QCheckBox,QFileDialog,QInputDialog,QMessageBox,
    QTimeEdit,QComboBox,QApplication,QPlainTextEdit,QStyle)

from therion.autonomy.apps import discover_applications
from therion.autonomy.integration import implementation_version
from therion.autonomy.windows import StartupShortcut
from therion.interface.autonomy_widgets import (PANEL_STYLE,IconCache,ExpandableRow,
    ApplicationGallery,BatchReview,label,button,scroll_column)
from .surface_dialogs import Dialog as QDialog, MessageBox as QMessageBox, InputDialog as QInputDialog, FileDialog as QFileDialog


class V4Job(QThread):
    completed=Signal(object)
    def __init__(self,task,parent=None):super().__init__(parent);self.task=task
    def run(self):
        try:self.completed.emit((True,self.task()))
        except Exception as error:self.completed.emit((False,str(error)))


class AutonomyPanel(QDialog):
    def __init__(self,owner,runtime,routines,procedures):
        super().__init__(owner)
        self.owner,self.runtime,self.routines,self.procedures=owner,runtime,routines,procedures
        self.catalog=owner._orchestrator.application_catalog
        self.setWindowTitle('Autonomia — Therion');self.resize(1000,720);self.setMinimumSize(860,640)
        available=self.screen().availableGeometry()
        self.resize(max(860,min(1000,available.width()-40)),max(640,min(720,available.height()-48)))
        self.setFont(QFont('Segoe UI',10));self.setStyleSheet(PANEL_STYLE)
        self.icons=IconCache(self);self.snapshot=None;self.app_cards={};self.routine_cards={}
        self.memory_cards={};self.expanded={'apps':None,'routines':None};self._snapshot_busy=False
        self._queued_action=None
        self._pending_refresh=False;self._rendering=False;self._last_signature=None
        layout=QHBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(0)
        side=QWidget();side.setFixedWidth(180);side_layout=QVBoxLayout(side)
        side_layout.setContentsMargins(16,24,12,18);side_layout.setSpacing(20)
        brand=label('●  THERION','section');brand.setStyleSheet('color:#6536D9');side_layout.addWidget(brand)
        self.nav=QListWidget();self.nav.setObjectName('navigation');self.nav.setAccessibleName('Seções de autonomia')
        for text in ('Aplicativos','Rotinas','Memória técnica','Evidências e Windows'):
            self.nav.addItem(QListWidgetItem(text))
        self.nav.setWordWrap(True);side_layout.addWidget(self.nav,1)
        side_layout.addWidget(label('Autorizações por 7 dias','muted'))
        side_layout.addWidget(button('Como funciona',self.help));layout.addWidget(side)
        content=QWidget();content_layout=QVBoxLayout(content)
        content_layout.setContentsMargins(24,22,24,20);content_layout.setSpacing(12);layout.addWidget(content,1)
        self.feedback_box=QWidget();feedback_layout=QHBoxLayout(self.feedback_box)
        feedback_layout.setContentsMargins(0,0,0,0)
        self.feedback=label('', 'notice');feedback_layout.addWidget(self.feedback,1)
        self.result_button=button('Ver resultado',self.show_result);feedback_layout.addWidget(self.result_button)
        self.feedback_box.hide();content_layout.addWidget(self.feedback_box);self.result_text=''
        self.pause_banner=QFrame();pause_box=QHBoxLayout(self.pause_banner)
        pause_box.addWidget(label('Há uma pausa global anterior. As autorizações estão suspensas.','muted'),1)
        pause_box.addWidget(button('Retomar',self.resume));self.pause_banner.hide();content_layout.addWidget(self.pause_banner)
        self.pages=QStackedWidget();content_layout.addWidget(self.pages,1)
        self._apps_page();self._routines_page();self._memory_page();self._evidence_page()
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex);self.nav.setCurrentRow(0)
        self.timer=QTimer(self);self.timer.setInterval(5000);self.timer.timeout.connect(self.refresh)
        QApplication.instance().installEventFilter(self)

    def help(self):
        QMessageBox.information(self,'Como funciona',
            'Selecionar uma linha mostra seus detalhes. Marcar uma caixa solicita autonomia específica; '
            'desmarcar revoga essa autorização. Aplicativos desmarcados continuam disponíveis com confirmação.\n\n'
            'Aplicativos: você escolhe quando autorizar, sem quantidade mínima de testes nem período de observação. '
            'Rotinas e memória: dez sucessos supervisionados ao longo de sete dias. Incidentes pendentes exigem revisão. '
            'A autorização dura sete dias e não é renovada automaticamente.')

    def _page(self,title,description):
        page=QWidget();root=QVBoxLayout(page);root.setContentsMargins(0,0,0,0);root.setSpacing(14)
        header=QHBoxLayout();text=QVBoxLayout();text.setSpacing(6)
        text.addWidget(label(title,'title'));text.addWidget(label(description,'muted'));header.addLayout(text,1)
        root.addLayout(header);self.pages.addWidget(page)
        return root,header

    def _apps_page(self):
        root,header=self._page('Aplicativos','Escolha o que o Therion pode abrir quando você pedir.')
        # Duas ações principais, em uma linha própria para caber em 860 px.
        actions=QHBoxLayout();root.addLayout(actions)
        actions.addWidget(button('Descobrir instalados',self.discover,True))
        actions.addWidget(button('Adicionar manualmente',self.manual));actions.addStretch()
        self.mode_banner=QFrame();box=QHBoxLayout(self.mode_banner)
        box.addWidget(label('Abertura real ainda não ativada. As ações deste ambiente são simuladas.','muted'),1)
        box.addWidget(button('Ativar abertura real',self.activate_real));root.addWidget(self.mode_banner)
        area,self.app_content,self.app_column=scroll_column();root.addWidget(area,1)
        self.app_empty=label('Carregando aplicativos…','muted');self.app_column.addWidget(self.app_empty)

    def _routines_page(self):
        root,_=self._page('Rotinas','Resumos e revisões nos horários que você escolher.')
        area,self.routine_content,self.routine_column=scroll_column();root.addWidget(area,1)

    def _memory_page(self):
        root,_=self._page('Memória técnica','Procedimentos comprovados, guardados como rascunhos para revisão.')
        area,self.memory_content,self.memory_column=scroll_column();root.addWidget(area,1)
        destination=QFrame();destination.setProperty('role','card');box=QVBoxLayout(destination)
        line=QHBoxLayout();line.addWidget(label('Destino dos rascunhos','section'),1)
        line.addWidget(button('Alterar',self.memory_destination));box.addLayout(line)
        self.destination=label('Nenhum destino selecionado.','muted');self.destination.setTextInteractionFlags(Qt.TextSelectableByMouse)
        box.addWidget(self.destination);self.memory_column.addWidget(destination)
        automatic=QFrame();automatic.setProperty('role','card');box=QVBoxLayout(automatic)
        self.memory_check=QCheckBox('Guardar procedimentos técnicos automaticamente')
        self.memory_check.toggled.connect(self.toggle_memory);box.addWidget(self.memory_check)
        self.memory_state=label('', 'muted');box.addWidget(self.memory_state);self.memory_column.addWidget(automatic)
        self.memory_empty=label('Ainda não há procedimentos elegíveis. São necessárias duas execuções técnicas distintas e verificadas.','muted')
        self.memory_column.addWidget(self.memory_empty)

    def _evidence_page(self):
        root,_=self._page('Evidências e Windows','Histórico de resultados e início opcional do Therion.')
        actions=QHBoxLayout();root.addLayout(actions)
        actions.addWidget(button('Revisar incidente selecionado',self.review_incident));actions.addStretch()
        self.evidence=QListWidget();self.evidence.setAccessibleName('Histórico de execuções');root.addWidget(self.evidence,1)
        startup=QFrame();startup.setProperty('role','card');box=QVBoxLayout(startup)
        box.addWidget(label('Inicialização com Windows','section'))
        box.addWidget(label('Inicia na bandeja, sem ligar o microfone automaticamente.','muted'))
        controls=QHBoxLayout();box.addLayout(controls)
        controls.addWidget(button('Habilitar',lambda:self.startup(True)))
        controls.addWidget(button('Desabilitar',lambda:self.startup(False)));controls.addStretch();root.addWidget(startup)

    def showEvent(self,event):
        super().showEvent(event);self.timer.start();self.refresh()

    def hideEvent(self,event):
        self.timer.stop();super().hideEvent(event)

    def eventFilter(self,obj,event):
        if event.type()==QEvent.MouseButtonPress and self.isVisible() and QApplication.activeModalWidget() is None:
            widget=obj
            inside=False
            while isinstance(widget,QWidget):
                if isinstance(widget,ExpandableRow):return False
                if widget is self:inside=True;break
                widget=widget.parentWidget()
            if inside:self.clear_selection()
        return super().eventFilter(obj,event)

    def clear_selection(self):
        for section,cards in (('apps',self.app_cards),('routines',self.routine_cards)):
            self.expanded[section]=None
            for card in cards.values():card.expand(False)

    def select_row(self,section,identifier):
        self.expanded[section]=None if self.expanded[section]==identifier else identifier
        cards=self.app_cards if section=='apps' else self.routine_cards
        for key,card in cards.items():card.expand(key==self.expanded[section])

    def confirm(self,text,accept='Autorizar',title='Confirmar alteração'):
        dialog=QMessageBox(QMessageBox.Question,title,text,parent=self)
        yes=dialog.addButton(accept,QMessageBox.AcceptRole)
        no=dialog.addButton('Cancelar',QMessageBox.RejectRole);dialog.setDefaultButton(no)
        dialog.exec();return dialog.clickedButton() is yes

    def notify(self,text):
        self.result_text=str(text)
        self.feedback.setText(self.result_text[:260]+('…' if len(self.result_text)>260 else ''))
        self.result_button.setVisible(len(self.result_text)>260);self.feedback_box.setVisible(bool(text))

    def show_result(self):
        dialog=QDialog(self);dialog.setWindowTitle('Resultado da operação');dialog.resize(720,520)
        box=QVBoxLayout(dialog);content=QPlainTextEdit();content.setReadOnly(True);content.setPlainText(self.result_text)
        box.addWidget(content);box.addWidget(button('Fechar',dialog.accept));dialog.exec()

    def action(self,task):
        try:result=task();self.refresh();return result
        except Exception as error:self.notify(error);self.refresh();return None

    def job(self,task,callback=None,on_error=None,background=False):
        if self.owner._v4_worker is not None or self.owner._processing or self.owner._pending_plan is not None:
            if self._snapshot_busy and self.owner._v4_worker is not None and not background and self._queued_action is None:
                self._queued_action=(task,callback,on_error);return True
            if background:self._pending_refresh=True
            else:self.notify('Aguarde a operação atual antes de continuar.')
            return False
        if not background:self.nav.setEnabled(False);self.pages.setEnabled(False)
        worker=V4Job(task,self.owner);self.owner._v4_worker=worker;payloads=[]
        worker.completed.connect(payloads.append)
        def finished():
            self.owner._v4_worker=None;worker.deleteLater()
            if not background:self.nav.setEnabled(True);self.pages.setEnabled(True)
            ok,value=payloads[0] if payloads else (False,'A operação terminou sem resultado confirmado.')
            if ok:
                if callback:callback(value)
                elif value is not None:self.notify(value)
            elif on_error:on_error(str(value))
            else:self.notify(value)
            queued=self._queued_action;self._queued_action=None
            if queued:
                QTimer.singleShot(0,lambda:self.job(queued[0],queued[1],queued[2]))
            elif not background or self._pending_refresh:
                self._pending_refresh=False;QTimer.singleShot(0,self.refresh)
        worker.finished.connect(finished);worker.start();return True

    def _state(self,operation,target,version,permitted,policies,scheduled=True):
        decision=self.runtime.decide(operation,target,version,permitted=permitted)
        progress=self.runtime.store.progress(operation,target,version)
        policy=next((p for p in policies if (p.operation,p.target)==(operation,target)),None)
        checked=decision.mode=='autonomous' and scheduled
        manual_app=operation=='open_app'
        eligible=permitted and (manual_app or progress['ready']) and not self.runtime.store.state('incident:'+operation+':'+target)
        if self.runtime.store.state('paused')=='1':eligible=False
        title='Autorizado até '+policy.expires_at.astimezone(ZoneInfo('America/Sao_Paulo')).strftime('%d/%m') if checked else 'Com confirmação'
        if not checked:
            if policy and policy.enabled and self.runtime.clock()>=policy.expires_at:title='Expirada'
            elif policy and policy.enabled and policy.context_version!=version:title='Revisão necessária'
            elif not permitted:title='Revisão necessária'
            elif not manual_app and progress['count']:title='Em teste'
            if 'Incidente' in decision.reason:title='Revisão necessária'
        detail=('Você escolhe quando abrir sem confirmação, sem mínimo de testes ou dias de observação.\n'+decision.reason if manual_app else
            f"{min(progress['count'],10)}/10 execuções verificadas · {min(progress['days'],7)}/7 dias de observação.\n"+decision.reason)
        if not manual_app and not progress['ready']:
            detail+='\nPara autorizar: dez sucessos supervisionados ao longo de sete dias. Simulações não contam.'
        verified_openings=self.runtime.store.verified_openings(target) if operation=='open_app' else None
        if verified_openings is not None:
            detail+=f'\nHistórico: {verified_openings} aberturas verificadas automaticamente.'
            detail+='\nMudanças de implementação ou escopo exigem nova autorização visual, sem apagar o histórico.'
        if policy:detail+='\nValidade: '+policy.expires_at.astimezone(ZoneInfo('America/Sao_Paulo')).strftime('%d/%m/%Y %H:%M')
        return dict(checked=checked,eligible=eligible,title=title,detail=detail,
            version=version,operation=operation,target=target,policy=policy,verified_openings=verified_openings)

    def _collect_snapshot(self):
        orch=self.owner._orchestrator
        if not orch._operation_lock.acquire(False):return None
        try:
            orch._sync_knowledge_access()
            policies=self.runtime.policies();section=self.runtime.section();apps=self.catalog.entries()
            app_states={a.id:self._state('open_app',a.id,implementation_version(self.runtime,a.as_dict()),
                Path(a.path).is_file(),policies) for a in apps}
            routines=self.routines.entries();routine_states={}
            for spec in routines:
                permitted=orch.calendar_adapter is not None if spec.operation=='daily_summary' else True
                if spec.operation=='review_notes':
                    try:
                        orch.second_brain._check_access()
                        for path in spec.sources:orch.second_brain.resolve_and_validate(path)
                    except (OSError,ValueError):permitted=False
                state=self._state(spec.operation,spec.id,self.routines.version(spec),permitted,policies,spec.enabled)
                if not state['checked'] and not state['policy']:state['title']='Manual'
                routine_states[spec.id]=state
            memory=section.get('procedure_memory',{})
            root=memory.get('root','') if isinstance(memory,dict) else ''
            try:
                target,version,_=self.procedures.scope()
                memory_state=self._state('remember_procedure',target,version,True,policies)
            except (OSError,ValueError) as error:
                memory_state=dict(checked=False,eligible=False,title='Destino ou acesso pendente',detail=str(error),target=root)
            return dict(apps=apps,app_states=app_states,routines=routines,routine_states=routine_states,
                candidates=self.procedures.candidates(),memory_root=root,memory_state=memory_state,
                evidence=self.runtime.store.recent(),paused=self.runtime.store.state('paused')=='1',
                simulated=orch._catalog_simulated())
        finally:orch._operation_lock.release()

    def refresh(self):
        if self._snapshot_busy or QApplication.activeModalWidget() is not None:return
        if self.owner._v4_worker is not None:
            self._pending_refresh=True;return
        self._snapshot_busy=True
        def done(data):
            self._snapshot_busy=False
            if data is not None:self.snapshot=data;self.render(data)
        def failed(message):self._snapshot_busy=False;self.notify('Não confirmei o estado de autonomia: '+message)
        if not self.job(self._collect_snapshot,done,failed,background=True):self._snapshot_busy=False

    @staticmethod
    def _set_check(check,state):
        blocker=QSignalBlocker(check)
        check.setChecked(state['checked']);check.setEnabled(state.get('interactive',True))
        check.setToolTip(state['detail']);check.setAccessibleDescription(state['detail']);del blocker

    def _reconcile(self,cards,identifiers,column):
        for identifier in list(cards):
            if identifier not in identifiers:
                widget=cards.pop(identifier);column.removeWidget(widget);widget.hide();widget.deleteLater()

    def render(self,data):
        self._rendering=True
        try:
            self.pause_banner.setVisible(data['paused']);self.mode_banner.setVisible(data['simulated'])
            self.app_empty.setText('Nenhum aplicativo cadastrado. Descubra os instalados ou adicione um executável.')
            self.app_empty.setVisible(not data['apps'])
            self._reconcile(self.app_cards,{a.id for a in data['apps']},self.app_column)
            for app in data['apps']:
                state=data['app_states'][app.id];card=self.app_cards.get(app.id)
                if card is None:
                    card=ExpandableRow(app.id,app.name,'Sem confirmação',True)
                    card.selected.connect(lambda identifier:self.select_row('apps',identifier))
                    card.check.toggled.connect(lambda value,key=app.id:self.toggle_app(key,value))
                    card.remove.clicked.connect(lambda _=False,key=app.id:self.remove_app(key))
                    card.add_action('Abrir',lambda _=False,key=app.id:self.open_app(key))
                    card.add_action('Editar apelidos',lambda _=False,key=app.id:self.edit_aliases(key))
                    self.app_cards[app.id]=card;self.app_column.addWidget(card);self.icons.fill(card.icon,app.path)
                count=state['verified_openings']
                counted='1 abertura verificada' if count==1 else f'{count} aberturas verificadas'
                card.title.setText(app.name);card.subtitle.setText(state['title']+' · '+counted)
                card.info.setText('Executável: '+app.path+'\nApelidos: '+(', '.join(app.aliases) or 'nenhum')+
                    '\n\n'+state['detail']);self._set_check(card.check,state)
                card.expand(self.expanded['apps']==app.id)
            self._render_routines(data)
            self.destination.setText(data['memory_root'] or 'Selecione a área temporária já autorizada.')
            self._set_check(self.memory_check,data['memory_state'])
            self.memory_state.setText(data['memory_state']['title']+'\n'+data['memory_state']['detail'])
            self.memory_empty.setVisible(not data['candidates'])
            self._reconcile(self.memory_cards,{c.id for c in data['candidates']},self.memory_column)
            for candidate in data['candidates']:
                card=self.memory_cards.get(candidate.id)
                if card is None:
                    card=ExpandableRow(candidate.id,candidate.title)
                    card.pinned_details=True;card.expand(False);card.info.hide()
                    card.add_action('Revisar e guardar',lambda _=False,key=candidate.id:self.save_memory(key))
                    self.memory_cards[candidate.id]=card;self.memory_column.addWidget(card)
                card.subtitle.setText(candidate.summary)
            selected=self.evidence.currentItem().data(Qt.UserRole) if self.evidence.currentItem() else None
            blocker=QSignalBlocker(self.evidence);self.evidence.clear()
            modes={'simulation':'Simulação','supervised':'Supervisionada','autonomous':'Autônoma'}
            results={'success':'Concluída','failed':'Falhou','uncertain':'Resultado incerto',
                'running':'Em andamento','cancelled':'Cancelada','partial':'Parcial'}
            names={'open_app':'Abrir aplicativo','daily_summary':'Resumo diário','review_notes':'Revisão semanal','remember_procedure':'Memória técnica'}
            app_names={a.id:a.name for a in data['apps']}
            for row in data['evidence']:
                text=f"{row.started_at[:16].replace('T',' ')} · {names.get(row.operation,row.operation)}"
                if row.target in app_names:text+=' · '+app_names[row.target]
                text+='\n'+modes.get(row.mode,row.mode)+' · '+results.get(row.status,row.status)
                item=QListWidgetItem(text);item.setData(Qt.UserRole,row.id);item.setToolTip('ID: '+row.id)
                self.evidence.addItem(item)
                if row.id==selected:self.evidence.setCurrentItem(item)
            del blocker
        finally:self._rendering=False

    def _render_routines(self,data):
        for operation,title,default in (('daily_summary','Resumo diário','Todos os dias, 08:00'),
                ('review_notes','Revisão semanal de notas','Domingos, 18:00')):
            spec=next((r for r in data['routines'] if r.operation==operation),None)
            card=self.routine_cards.get(operation)
            if card is None:
                card=ExpandableRow(operation,title,'Automática')
                card.icon.setPixmap(self.style().standardIcon(QStyle.SP_FileDialogDetailedView).pixmap(28,28))
                card.selected.connect(lambda key:self.select_row('routines',key))
                card.check.toggled.connect(lambda value,op=operation:self.toggle_routine(op,value))
                card.edit=card.add_action('Configurar',lambda _=False,op=operation:self.configure_routine(op))
                card.run=card.add_action('Executar agora',lambda _=False,op=operation:self.run_routine(op))
                self.routine_cards[operation]=card;self.routine_column.addWidget(card)
            if spec:
                state=data['routine_states'][spec.id]
                day=('Todos os dias' if spec.weekday is None else ('Segundas','Terças','Quartas','Quintas','Sextas','Sábados','Domingos')[spec.weekday])
                card.subtitle.setText(f'{day}, {spec.hour:02}:{spec.minute:02} · '+state['title'])
                last=next((e for e in data['evidence'] if e.operation==operation and e.target==spec.id),None)
                results={'success':'Concluída','failed':'Falhou','uncertain':'Resultado incerto','running':'Em andamento',
                    'cancelled':'Cancelada','partial':'Parcial','blocked':'Bloqueada'}
                card.info.setText('Fuso: America/Sao_Paulo\nFontes: '+('\n'.join(spec.sources) or 'Calendário autorizado')+
                    '\n\n'+state['detail']+('\nÚltimo resultado: '+results.get(last.status,last.status) if last else '\nAinda sem execuções registradas.'))
                card.edit.setText('Editar');card.run.show();self._set_check(card.check,state)
            else:
                card.subtitle.setText(default+' · Ainda não configurada')
                card.info.setText('Escolha horário e fontes para iniciar os testes supervisionados.')
                self._set_check(card.check,dict(checked=False,eligible=False,interactive=False,detail='Configure a rotina primeiro.'))
                card.edit.setText('Configurar');card.run.hide()
                # Configurar fica disponível mesmo com os detalhes recolhidos.
            card.pinned_details=spec is None
            card.expand(self.expanded['routines']==operation)

    def _app(self,identifier):
        return next(a for a in self.catalog.entries() if a.id==identifier)

    def _routine(self,operation):
        return next(r for r in self.routines.entries() if r.operation==operation)

    def _reset_check(self,check,checked):
        blocker=QSignalBlocker(check);check.setChecked(checked);del blocker

    def _grant(self,operation,target,version,text):
        if not self.confirm(text+'\n\nValidade: sete dias. Até dez execuções por dia.'):return False
        self.runtime.grant(operation,target,version,'Confirmação visual específica no painel Autonomia.')
        return True

    def _explain_blocked_check(self,value,state):
        if value and not state['eligible']:
            self.notify('Ainda não é possível ativar esta autorização.\n'+state['detail'])
            return True
        return False

    def toggle_app(self,identifier,value):
        if self._rendering or not self.snapshot:return
        self._reset_check(self.app_cards[identifier].check,self.snapshot['app_states'][identifier]['checked'])
        if self._explain_blocked_check(value,self.snapshot['app_states'][identifier]):return
        def task():
            app=self._app(identifier)
            if value:self._grant('open_app',identifier,implementation_version(self.runtime,app.as_dict()),
                f'Abrir {app.name} sem confirmação individual, somente quando você pedir?\n{app.path}')
            else:self.runtime.revoke('open_app',identifier)
        self.action(task)

    def toggle_routine(self,operation,value):
        if self._rendering or not self.snapshot:return
        spec=self._routine(operation);state=self.snapshot['routine_states'][spec.id]
        self._reset_check(self.routine_cards[operation].check,state['checked'])
        if self._explain_blocked_check(value,state):return
        def task():
            current=self._routine(operation)
            if value:
                text=f'Executar {self.routine_cards[operation].title.text()} automaticamente às {current.hour:02}:{current.minute:02}?'
                text+='\nFontes: '+('\n'.join(current.sources) or 'Calendário autorizado')
                if self._grant(operation,current.id,self.routines.version(current),text):self.routines.enable(current,True)
            else:self.runtime.revoke(operation,current.id);self.routines.enable(current,False)
        self.action(task)

    def toggle_memory(self,value):
        if self._rendering or not self.snapshot:return
        self._reset_check(self.memory_check,self.snapshot['memory_state']['checked'])
        if self._explain_blocked_check(value,self.snapshot['memory_state']):return
        def task():
            if value:
                root,version,_=self.procedures.scope()
                self._grant('remember_procedure',root,version,'Guardar procedimentos técnicos verificados automaticamente como rascunhos?\n'+
                    root+'\nAté três por sessão, dez por dia e revisão em até trinta dias.')
            else:
                root=self.runtime.section().get('procedure_memory',{}).get('root')
                if root:self.runtime.revoke('remember_procedure',root)
        self.action(task)

    def resume(self):
        if self.confirm('Retomar somente políticas ainda vigentes e sem incidente?',accept='Retomar'):
            self.action(lambda:self.runtime.pause(False))

    def activate_real(self):
        if self.confirm('Ativar abertura REAL dos aplicativos cadastrados? Pedidos continuarão exigindo confirmação '
                'quando não houver política específica. Agenda, memória e outras ações não serão habilitadas.',accept='Ativar abertura real'):
            self.action(lambda:self.runtime._update(lambda section:section.update(app_opening_mode='real')))

    def discover(self):
        def found(rows):
            if not rows:self.notify('Nenhum aplicativo compatível encontrado. Você pode adicionar manualmente.');return
            self.gallery=ApplicationGallery(self,rows);self.gallery.show()
        self.job(discover_applications,found)

    def manual(self):
        path,_=QFileDialog.getOpenFileName(self,'Selecione o executável local','','Aplicativos (*.exe)')
        if path:
            self.review_dialog=BatchReview(self,[dict(name=Path(path).stem,path=path,source='manual')])
            self.review_dialog.setWindowModality(Qt.WindowModal);self.review_dialog.show()

    def edit_aliases(self,identifier):
        app=self._app(identifier)
        aliases,ok=QInputDialog.getText(self,'Apelidos de '+app.name,
            'Separe por vírgulas. Alterar apelidos exigirá revisar uma eventual autonomia.',text=', '.join(app.aliases))
        if ok:self.job(lambda:self.catalog.update_aliases(app,tuple(a.strip() for a in aliases.split(',') if a.strip())),
            lambda _:self.notify('Apelidos atualizados. O aplicativo e seu histórico foram preservados.'))

    def remove_app(self,identifier):
        app=self._app(identifier)
        if self.confirm(f'Remover {app.name} do catálogo do Therion?\nIsso não desinstala nem fecha o aplicativo.',accept='Remover'):
            self.job(lambda:self.catalog.remove(identifier),lambda _:self.notify('Cadastro removido.'))

    def open_app(self,identifier):
        orch=self.owner._orchestrator
        def execute():
            with orch._operation_lock:
                return orch.process_command('abra '+identifier)
        def result_ready(result):
            if result.status!='awaiting_confirmation' or result.plan is None:
                self.notify(result.message);return
            confirmed=(self.isVisible() and not self.owner._closing and
                self.confirm(result.message,accept='Simular' if orch._catalog_simulated() else 'Abrir'))
            def finish():
                with orch._operation_lock:
                    return orch.confirm_and_execute(result.plan,confirmed)
            self.job(finish,lambda value:self.notify(value.message))
        self.job(execute,result_ready)

    def configure_routine(self,operation):
        existing=next((r for r in self.routines.entries() if r.operation==operation),None)
        dialog=QDialog(self);dialog.setWindowTitle('Configurar rotina');dialog.setStyleSheet(PANEL_STYLE)
        box=QVBoxLayout(dialog);box.addWidget(label('Horário local — America/Sao_Paulo','muted'))
        time=QTimeEdit(QTime(existing.hour,existing.minute) if existing else QTime(8,0) if operation=='daily_summary' else QTime(18,0))
        time.setAccessibleName('Horário da rotina')
        box.addWidget(time);weekday=QComboBox();weekday.addItems(['Segunda','Terça','Quarta','Quinta','Sexta','Sábado','Domingo'])
        weekday.setCurrentIndex(existing.weekday if existing and existing.weekday is not None else 6)
        weekday.setAccessibleName('Dia da revisão semanal')
        if operation=='review_notes':box.addWidget(weekday)
        sources=list(existing.sources) if existing else []
        source_label=label('\n'.join(sources) or 'Escolha de uma a cinco notas autorizadas.','muted')
        if operation=='review_notes':
            box.addWidget(source_label)
            def choose():
                paths,_=QFileDialog.getOpenFileNames(dialog,'Selecione de uma a cinco notas','','Notas (*.md)')
                if paths:sources[:]=paths;source_label.setText('\n'.join(paths))
            box.addWidget(button('Escolher notas',choose))
        buttons=QHBoxLayout();box.addLayout(buttons)
        buttons.addWidget(button('Cancelar',dialog.reject));buttons.addWidget(button('Revisar',dialog.accept,True))
        if dialog.exec()!=QDialog.Accepted:return
        hour,minute=time.time().hour(),time.time().minute();day=weekday.currentIndex() if operation=='review_notes' else None
        if self.confirm(f'Configurar a rotina às {hour:02}:{minute:02}?\n'+('\n'.join(sources) or 'Calendário autorizado')+
                '\nEla ficará supervisionada até receber autorização específica.',accept='Salvar configuração'):
            self.job(lambda:self.routines.configure(operation,hour,minute,sources,day),lambda _:self.notify('Rotina configurada.'))

    def run_routine(self,operation):
        spec=self._routine(operation)
        if self.confirm('Consultar agora as fontes desta rotina, sem modificar notas ou agenda?',accept='Executar agora'):
            self.job(lambda:self.routines.run(spec,supervised=True),lambda result:self.notify(result.message))

    def memory_destination(self):
        root=QFileDialog.getExistingDirectory(self,'Selecione a área temporária já autorizada')
        if root and self.confirm('Usar este destino para rascunhos técnicos?\n'+root,accept='Usar destino'):
            self.job(lambda:self.procedures.configure(root),lambda _:self.notify('Destino atualizado.'))

    def save_memory(self,identifier):
        candidate=next(c for c in self.procedures.candidates() if c.id==identifier)
        def prepare():
            root,_,_=self.procedures.scope()
            if self.confirm(candidate.title+'\n\n'+candidate.summary+'\n\n'+candidate.evidence+'\n\nDestino: '+root,
                    accept='Guardar rascunho',title='Revisar procedimento'):
                self.job(lambda:self.procedures.save(candidate,supervised=True))
        self.action(prepare)

    def review_incident(self):
        item=self.evidence.currentItem()
        if item is None:self.notify('Selecione uma execução do histórico.');return
        row=next(r for r in self.runtime.store.recent() if r.id==item.data(Qt.UserRole))
        if row.status=='running':self.notify('Execução pendente requer diagnóstico. O bloqueio de resultado incerto foi preservado.');return
        if self.confirm('Marcar o incidente deste fluxo como revisado? Isso não cria nem renova autorizações. Rotinas e memória continuam exigindo observação.',accept='Registrar revisão'):
            self.action(lambda:self.runtime.store.review_incident(row.operation,row.target))

    def startup(self,enabled):
        if self.confirm(('Criar' if enabled else 'Remover')+' somente o atalho gerenciado de início com Windows?\n'
                'Therion iniciará na bandeja, com microfone desligado.',accept='Habilitar' if enabled else 'Desabilitar'):
            self.job(lambda:StartupShortcut().set_enabled(enabled),lambda _:self.notify('Inicialização atualizada.'))
