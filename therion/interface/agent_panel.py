"""Painel de ativação e histórico; ações pessoais têm confirmação própria."""
from copy import deepcopy
from pathlib import Path
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QCheckBox, QLabel, QPushButton,
    QListWidget, QTextEdit, QMessageBox, QFileDialog, QComboBox, QHBoxLayout, QLineEdit, QInputDialog,
    QTabWidget,QWidget,QScrollArea,QSpinBox,QGroupBox)
from therion.agent.settings import validate_settings
from therion.agent.store import SessionStore
from therion.agent.contracts import CancellationToken
from PySide6.QtCore import QThread, Signal,QTimer
from PySide6.QtCore import Qt
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from .surface_dialogs import Dialog as QDialog, MessageBox as QMessageBox, InputDialog as QInputDialog, FileDialog as QFileDialog


class ApprovalWorker(QThread):
    completed = Signal(object)
    def __init__(self, proposals, row, parent=None):
        super().__init__(parent)
        self.proposals, self.row = proposals, row
        self.token = CancellationToken()

    def run(self):
        try:
            result = self.proposals.approve_visual(self.row.id,self.row.digest,self.token)
        except Exception:
            from therion.agent.contracts import ToolResult
            result = ToolResult('uncertain',message='Operação não pôde ser confirmada; não repeti.',side_effect_state='uncertain')
        self.completed.emit(result)


class DiscoveryWorker(QThread):
    completed = Signal(object)
    def run(self):
        from therion.integrations.rpc import OwnedWorker
        import os
        worker=OwnedWorker('desktop',{'targets':{},'blocked_pids':[os.getpid()]})
        try:self.completed.emit(worker.call('inventory',{},CancellationToken(),timeout=30))
        except Exception as error:self.completed.emit({'error':str(error)})
        finally:worker.close()


class GmailAuthorizationWorker(QThread):
    completed = Signal(str)
    def __init__(self,credentials,mode,root,parent=None):
        super().__init__(parent)
        self.credentials,self.mode,self.root=credentials,mode,root
        self.token=CancellationToken()

    def run(self):
        import subprocess,sys,os,time
        script=Path(__file__).resolve().parents[2]/'scripts'/'configure-gmail.py'
        process=None
        message='Conexão não concluída. Confira as credenciais OAuth, a autorização escolhida ou tente novamente.'
        try:
            self.token.check()
            process=subprocess.Popen([sys.executable,str(script),'--credentials',self.credentials,'--mode',self.mode,
                '--state-root',str(self.root)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            deadline=time.monotonic()+190
            while process.poll() is None and not self.token.cancelled and time.monotonic()<deadline:time.sleep(.05)
            if process.poll() is None:process.terminate()
            code=process.wait(timeout=5)
            if code==0 and not self.token.cancelled:message='Gmail conectado. Nenhuma mensagem foi lida ou enviada.'
        except Exception:
            message='Não consegui concluir a conexão com Gmail. Nenhuma operação em mensagens foi iniciada.'
        finally:
            try:
                if process is not None and process.poll() is None:process.kill();process.wait(timeout=5)
            finally:self.completed.emit(message)


class AgentPanel(QDialog):
    def __init__(self, host, config, writer, parent=None):
        super().__init__(parent)
        self.owner=parent
        self.host, self.config, self.writer = host, config, writer
        self.setWindowTitle('Capacidades e histórico')
        self.resize(740, 650)
        root_layout = QVBoxLayout(self)
        tabs=QTabWidget(self);self.tabs=tabs;root_layout.addWidget(tabs)
        capabilities=QWidget();layout=QVBoxLayout(capabilities)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(capabilities)
        tabs.addTab(scroll,'Capacidades')
        history=QWidget();history_layout=QVBoxLayout(history);tabs.addTab(history,'Histórico')
        pending=QWidget();pending_layout=QVBoxLayout(pending);tabs.addTab(pending,'Propostas')
        layout.addWidget(QLabel('Ative capacidades individualmente. Autorizações de ações permanecem separadas.'))
        current = validate_settings(config.get('agent'))
        self.checks = {}
        capabilities_layout=layout
        def group(title):
            box=QGroupBox(title);part=QVBoxLayout(box);part.setSpacing(8);capabilities_layout.addWidget(box);return part
        general=group('Assistente e histórico');integrations=group('Integrações disponíveis');advanced=group('Recursos avançados')
        for key, label in [('enabled','Núcleo de ferramentas local (experimental)'),
                ('history_enabled','Guardar conversas por 30 dias'), ('gmail_enabled','Gmail'),('tasks_enabled','Tarefas locais (funciona sem conta Google)'),
                ('browser_enabled','Navegador controlado'), ('desktop_enabled','Aplicativos com acessibilidade'),
                ('documents_enabled','Documentos locais'), ('web_enabled','Pesquisa pública na web, sem conta pessoal'),
                ('learning_enabled','Propor procedimentos após tarefas'),('source_cache_enabled','Cache de trechos de documentos (experimental)'),
                ('mcp_enabled','Servidores MCP de leitura cadastrados (experimental)')]:
            check = QCheckBox(label)
            check.setChecked(current[key])
            self.checks[key] = check
            target=general if key in {'enabled','history_enabled','learning_enabled'} else advanced if key in {'source_cache_enabled','mcp_enabled'} else integrations
            target.addWidget(check)
        layout=group('Runtime local')
        self.protocol = QComboBox()
        self.mcp_servers=deepcopy(current.get('mcp_servers',[]))
        mcp=QPushButton('Revisar cadastro local de servidores MCP…');mcp.clicked.connect(self.import_mcp);advanced.addWidget(mcp)
        self.protocol.addItems(['json','native'])
        self.protocol.setCurrentText(current['protocol'])
        layout.addWidget(self.protocol)
        layout.addWidget(QLabel('Perfil do runtime local (o modelo padrão é preservado):'))
        self.thinking=QComboBox()
        self.thinking.addItems(['Herdar pensamento do perfil atual','Pensamento desligado','Pensamento ligado'])
        self.thinking.setCurrentIndex([None,False,True].index(current['think']))
        layout.addWidget(self.thinking)
        self.context_tokens=QSpinBox();self.context_tokens.setRange(1024,16384);self.context_tokens.setSingleStep(1024)
        self.context_tokens.setValue(current['context_tokens']);self.context_tokens.setPrefix('Contexto: ')
        self.output_tokens=QSpinBox();self.output_tokens.setRange(128,current['context_tokens']-1);self.output_tokens.setSingleStep(128)
        self.output_tokens.setValue(current['output_tokens']);self.output_tokens.setPrefix('Saída máxima: ')
        self.context_tokens.valueChanged.connect(lambda value:self.output_tokens.setMaximum(value-1))
        layout.addWidget(self.context_tokens);layout.addWidget(self.output_tokens)
        layout=group('Acesso ao navegador e documentos')
        self.browser_channel=QComboBox()
        self.browser_channel.addItem('Chromium incluído — perfil próprio','chromium')
        self.browser_channel.addItem('Microsoft Edge instalado — perfil próprio','msedge')
        self.browser_channel.setCurrentIndex(self.browser_channel.findData(current['browser_channel']))
        layout.addWidget(self.browser_channel)
        self.domains=QLineEdit(', '.join(current.get('browser_domains',[])))
        self.domains.setPlaceholderText('Domínios permitidos, separados por vírgula: exemplo.com')
        layout.addWidget(self.domains)
        self.scopes={key:list(current.get(key,[])) for key in ('document_read_roots','document_write_roots')}
        self.scope_label=QLabel(self.scope_text())
        layout.addWidget(self.scope_label)
        for key,label in [('document_read_roots','Escolher pasta de leitura'),('document_write_roots','Escolher pasta para salvar documentos')]:
            button=QPushButton(label)
            button.clicked.connect(lambda checked=False,key=key:self.choose_folder(key))
            layout.addWidget(button)
        self.desktop_targets=dict(current.get('desktop_targets',{}))
        self.discovery_worker=None
        self.oauth_worker=None
        choose=QPushButton('Escolher janela de aplicativo para controlar')
        choose.clicked.connect(self.discover_windows)
        layout.addWidget(choose)
        connect=QPushButton('Conectar Gmail / rever permissões')
        connect.clicked.connect(self.connect_gmail);layout.addWidget(connect)
        procedures=QPushButton('Revisar procedimentos técnicos')
        procedures.clicked.connect(self.show_procedures);layout.addWidget(procedures)
        save = QPushButton('Salvar preferências')
        save.clicked.connect(self.save)
        layout.addWidget(save)
        temporary = QCheckBox('Conversa atual temporária (não guardar novas mensagens)')
        temporary.setChecked(host._agent_temporary)
        temporary.toggled.connect(lambda value:setattr(host, '_agent_temporary', value))
        layout.addWidget(temporary)
        layout=pending_layout
        layout.addWidget(QLabel('Propostas pendentes — prévia de uso único, válida por cinco minutos'))
        self.proposal_list = QListWidget()
        self.proposal_preview = QTextEdit()
        self.proposal_preview.setReadOnly(True)
        self.proposal_list.currentRowChanged.connect(self.show_proposal)
        layout.addWidget(self.proposal_list)
        layout.addWidget(self.proposal_preview)
        self.approve_button = QPushButton('Confirmar esta operação')
        self.approve_button.clicked.connect(self.approve)
        layout.addWidget(self.approve_button)
        stop=QPushButton('Parar operação em andamento')
        stop.clicked.connect(self.cancel_operations);layout.addWidget(stop)
        self.last_artifact=None
        self.open_artifact_button=QPushButton('Abrir arquivo gerado')
        self.open_artifact_button.setEnabled(False)
        self.open_artifact_button.clicked.connect(self.open_generated_artifact)
        layout.addWidget(self.open_artifact_button)
        self.approval_worker = None
        layout=history_layout
        self.history_query=QLineEdit();self.history_query.setPlaceholderText('Buscar no histórico autorizado')
        self.history_query.returnPressed.connect(self.search_history);layout.addWidget(self.history_query)
        self.list = QListWidget()
        layout.addWidget(self.list)
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        layout.addWidget(self.preview)
        self.list.currentRowChanged.connect(self.show_session)
        buttons = QHBoxLayout()
        for label, handler in [('Atualizar',self.refresh),('Reabrir',self.reopen),
                ('Excluir conversa',self.delete),('Excluir histórico',self.delete_all),('Exportar',self.export)]:
            button = QPushButton(label)
            button.clicked.connect(handler)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.rows = []
        self.proposals = []
        self.refresh()
        if self.proposals:tabs.setCurrentIndex(2);self.proposal_list.setCurrentRow(0)
        self.proposal_timer=QTimer(self)
        self.proposal_timer.timeout.connect(self.refresh_proposals)
        self.proposal_timer.start(250)

    def refresh_proposals(self):
        if self.approval_worker is not None:return
        rows=self.host._agent_proposals.list() if self.host._agent_proposals else []
        if [row.id for row in rows]!=[row.id for row in self.proposals]:
            self.proposals=rows
            self.proposal_list.clear()
            self.proposal_list.addItems([row.operation for row in rows])

    def showEvent(self,event):
        super().showEvent(event)
        if hasattr(self,'proposal_timer'):self.proposal_timer.start()

    def hideEvent(self,event):
        if hasattr(self,'proposal_timer'):self.proposal_timer.stop()
        super().hideEvent(event)

    def search_history(self):
        rows=self.store().search(self.history_query.text())
        from datetime import datetime
        self.preview.setPlainText('\n\n'.join('Mensagem '+str(row['id'])+' — '+datetime.fromtimestamp(row['created']).astimezone().isoformat(timespec='seconds')+' — '+row['role']+': '+row['content'] for row in rows))

    def store(self):
        return self.host._get_agent_store()

    @property
    def busy(self):
        return self.approval_worker is not None or self.discovery_worker is not None or self.oauth_worker is not None

    def cancel_operations(self):
        runtime=getattr(self.host,'_agent_runtime',None)
        if getattr(runtime,'active',False):self.host.cancel_agent()
        if self.approval_worker:self.approval_worker.token.cancel()
        if self.oauth_worker:self.oauth_worker.token.cancel()

    def show_procedures(self):
        if getattr(self.owner,'_processing',False):return
        from .surface_dialogs import dashboard_for
        dashboard=dashboard_for(self)
        if dashboard is not None:
            dashboard.procedures();return
        from .procedure_panel import ProcedurePanel
        ProcedurePanel(self.store(),self).exec()

    def connect_gmail(self):
        if self.busy or getattr(self.owner,'_processing',False):return
        credentials,_=QFileDialog.getOpenFileName(self,'Escolher credenciais OAuth do seu aplicativo Google','','JSON (*.json)')
        if not credentials:return
        labels=['Somente leitura','Leitura e rascunhos/envio (cada ação exige confirmação)','Leitura e organização da caixa (cada alteração exige confirmação)']
        label,ok=QInputDialog.getItem(self,'Permissões Gmail','Acesso a solicitar ao Google:',labels,editable=False)
        if not ok:return
        mode=['read','compose','modify'][labels.index(label)]
        self.host.close_agent()
        self.oauth_worker=GmailAuthorizationWorker(credentials,mode,self.host._agent_root/'credentials',self)
        self.oauth_worker.completed.connect(self.gmail_connected);self.oauth_worker.start()

    def gmail_connected(self,message):
        self.oauth_worker.wait();self.oauth_worker.deleteLater();self.oauth_worker=None
        QMessageBox.information(self,'Gmail',message)

    def save(self):
        if getattr(self.owner, '_processing', False) or self.busy:
            QMessageBox.information(self,'Pedido ativo','Pare ou conclua o pedido antes de alterar capacidades.')
            return
        loader=getattr(self.owner,'_agent_config_loader',None)
        updated = deepcopy(loader() if callable(loader) else self.config)
        settings = validate_settings(updated.get('agent'))
        settings.update({key:check.isChecked() for key,check in self.checks.items()})
        settings['protocol'] = self.protocol.currentText()
        settings['think']=[None,False,True][self.thinking.currentIndex()]
        settings['context_tokens']=self.context_tokens.value()
        settings['output_tokens']=self.output_tokens.value()
        settings['browser_channel']=self.browser_channel.currentData()
        settings['browser_domains']=[item.strip().lower() for item in self.domains.text().split(',') if item.strip()]
        settings.update(self.scopes)
        settings['desktop_targets']=self.desktop_targets
        settings['mcp_servers']=deepcopy(self.mcp_servers)
        if settings.get('mcp_enabled'):
            from therion.integrations.mcp import validate_registry
            try:validate_registry(settings['mcp_servers'])
            except (ValueError,TypeError,KeyError) as error:
                QMessageBox.information(self,'Cadastro MCP',str(error));return
        updated['agent'] = settings
        self.writer(updated)
        self.config.clear()
        self.config.update(updated)
        self.host.close_agent()
        self.host._agent_config = settings
        if self.host._agent_store:
            self.host._agent_store.enabled = settings['history_enabled']
        self.refresh()

    def import_mcp(self):
        if self.busy or getattr(self.owner,'_processing',False):return
        filename,_=QFileDialog.getOpenFileName(self,'Escolher cadastro MCP revisado','','JSON (*.json)')
        if not filename:return
        try:
            import json
            from therion.integrations.mcp import validate_registry
            if Path(filename).stat().st_size>128000:raise ValueError('Cadastro MCP acima do limite.')
            text=Path(filename).read_text(encoding='utf-8');rows=validate_registry(json.loads(text))
            question=QMessageBox(self);question.setWindowTitle('Revisar cadastro MCP');question.setTextFormat(Qt.PlainText)
            question.setText('Cadastrar '+str(len(rows))+' servidor(es) de leitura? Confira executáveis, argumentos, hashes e ferramentas em Detalhes. O cadastro não inicia processos. A ativação e o salvamento são separados.')
            question.setDetailedText(json.dumps(rows,ensure_ascii=False,indent=2));question.setStandardButtons(QMessageBox.Yes|QMessageBox.No);question.setDefaultButton(QMessageBox.No)
            if question.exec()==QMessageBox.Yes:self.mcp_servers=rows
        except (OSError,ValueError,TypeError,KeyError) as error:QMessageBox.information(self,'Cadastro MCP',str(error))

    def scope_text(self):
        return 'Pastas de leitura: '+', '.join(self.scopes['document_read_roots'])+'\nPastas de escrita: '+', '.join(self.scopes['document_write_roots'])

    def choose_folder(self,key):
        folder=QFileDialog.getExistingDirectory(self,'Escolher pasta autorizada')
        if folder:
            self.scopes[key]=[folder]
            self.scope_label.setText(self.scope_text())

    def discover_windows(self):
        if self.discovery_worker is not None:return
        self.discovery_worker=DiscoveryWorker(self)
        self.discovery_worker.completed.connect(self.windows_found)
        self.discovery_worker.start()

    def windows_found(self,rows):
        self.discovery_worker.wait()
        self.discovery_worker.deleteLater();self.discovery_worker=None
        if isinstance(rows,dict):
            QMessageBox.information(self,'Aplicativos',rows.get('error','Não foi possível consultar janelas.'));return
        labels=[row['title']+' — '+row['path'] for row in rows]
        label,ok=QInputDialog.getItem(self,'Escolher aplicativo','Permitir leitura e preparar cliques/preenchimento nesta janela:',labels,editable=False)
        if ok and label in labels:
            import uuid
            row=rows[labels.index(label)]
            self.desktop_targets={uuid.uuid4().hex:row}

    def refresh(self):
        store = self.store()
        store.purge()
        self.rows = store.sessions()
        self.list.clear()
        self.list.addItems([f"{row['session']} — {row['messages']} mensagens" for row in self.rows])
        self.proposals = self.host._agent_proposals.list() if self.host._agent_proposals else []
        self.proposal_list.clear()
        self.proposal_list.addItems([row.operation for row in self.proposals])

    def show_proposal(self, index):
        self.proposal_preview.setPlainText(self.proposals[index].preview if 0 <= index < len(self.proposals) else '')

    def approve(self):
        index = self.proposal_list.currentRow()
        if self.approval_worker is not None or not 0 <= index < len(self.proposals):
            return
        row = self.proposals[index]
        question=QMessageBox(self)
        question.setWindowTitle('Confirmar operação')
        question.setTextFormat(Qt.PlainText)
        if len(row.preview)<=4000:question.setText(row.preview)
        else:
            question.setText('\n'.join(row.preview.splitlines()[:10])[:1200]+'\n\nConfira a prévia completa em Detalhes antes de confirmar.')
            question.setDetailedText(row.preview)
        question.setStandardButtons(QMessageBox.Yes|QMessageBox.No)
        question.setDefaultButton(QMessageBox.No)
        if question.exec() != QMessageBox.Yes:
            return
        self.approve_button.setEnabled(False)
        if self.owner is not None:
            runtime=getattr(self.host,'_agent_runtime',None)
            if not getattr(runtime,'active',False):self.owner._end_conversation()
            self.owner._set_processing(True)
        self.approval_worker = ApprovalWorker(self.host._agent_proposals,row,self)
        self.approval_worker.completed.connect(self.approval_done)
        self.approval_worker.start()

    def approval_done(self, result):
        session=self.approval_worker.row.session
        operation=self.approval_worker.row.operation
        self.approval_worker.wait()
        self.approval_worker.deleteLater()
        self.approval_worker = None
        self.approve_button.setEnabled(True)
        if session!=self.host.session_id:
            self.refresh();return
        if operation=='documents.write' and result.status=='success' and result.side_effect_state=='verified' and isinstance(result.data,dict):
            self.last_artifact={key:result.data.get(key) for key in ('path','version')}
            self.open_artifact_button.setText('Abrir arquivo gerado: '+Path(str(self.last_artifact['path'])).name)
            self.open_artifact_button.setEnabled(True)
        if self.owner is not None:
            # O worker principal pode estar aguardando este recibo para decidir
            # a próxima etapa. Só ele encerra o estado ocupado nesse caso.
            foreground=getattr(self.owner,'_command_worker',None)
            if foreground is None:self.owner._set_processing(False)
            details={key:result.data[key] for key in ('id','path','version') if isinstance(result.data,dict) and key in result.data}
            message=result.message+('\n'+str(details) if details else '')
            self.owner._append('Therion',message)
            runtime=getattr(self.host,'_agent_runtime',None)
            active=getattr(runtime,'active',False)
            if active or foreground is not None:
                self.refresh()
                return
            self.host.memory.add_turn('therion',message)
            sources=list(result.evidence)+[{'id':'legacy:access','source':'política local','version':self.host._history_access_key()}]
            self.host._agent_turn_sources[(self.host.session_id,self.host.memory.turns[-1].turn_id)]=sources
            if self.host._agent_store and not self.host._agent_temporary:
                self.host._agent_store.append(self.host.session_id,'assistant',message,sources=sources)
        QMessageBox.information(self,'Resultado',result.message)
        self.refresh()

    def open_generated_artifact(self):
        from therion.integrations.documents import DocumentAdapter,WRITE_TYPES
        row=self.last_artifact
        try:
            if not row or self.host._agent_config.get('documents_enabled') is not True:raise ValueError('Capacidade de documentos desativada.')
            path=Path(row['path'])
            if path.suffix.lower() not in WRITE_TYPES:raise ValueError('Este formato não oferece prévia neste painel.')
            adapter=DocumentAdapter((),self.host._agent_config.get('document_write_roots',()))
            if adapter.version(path,True)!=row['version']:raise ValueError('O arquivo mudou desde a geração. Confira a versão atual antes de abrir.')
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.absolute()))):raise ValueError('Não há aplicativo disponível para abrir este formato.')
            return True
        except (ValueError,OSError,TypeError) as error:
            QMessageBox.warning(self,'Prévia do arquivo',str(error));return False

    def reject(self):
        if self.oauth_worker is not None:
            self.oauth_worker.token.cancel()
            QMessageBox.information(self,'Gmail','Cancelando a conexão. Aguarde o encerramento do processo de autorização.');return
        if self.discovery_worker is not None:
            QMessageBox.information(self,'Consulta ativa','Aguarde a consulta de aplicativos.');return
        if self.approval_worker is not None:
            self.approval_worker.token.cancel()
            QMessageBox.information(self,'Operação ativa','Aguarde o resultado da operação antes de fechar a prévia.')
            return
        super().reject()

    def selected(self):
        index = self.list.currentRow()
        return self.rows[index]['session'] if 0 <= index < len(self.rows) else None

    def show_session(self, index):
        session = self.selected()
        if not session:self.preview.clear();return
        from itertools import islice
        rows=list(islice(self.store().iter_messages(session),51))
        text='\n\n'.join(row['role']+': '+row['content'] for row in rows[:50])
        if len(rows)>50:text+='\n\nPrévia limitada a 50 mensagens. Reabra a conversa, use a busca ou exporte para consultar os demais originais.'
        self.preview.setPlainText(text)

    def reopen(self):
        session = self.selected()
        if not session or getattr(self.owner, '_processing', False):
            return
        rows = list(self.store().iter_messages(session))
        self.host.clear_session()
        self.host._session_id = session
        for row in rows:
            self.host.memory.add_turn('user' if row['role']=='user' else 'therion', row['content'])
            if row['role']=='assistant':
                import json
                self.host._agent_turn_sources[(self.host.session_id,self.host.memory.turns[-1].turn_id)]=json.loads(row['sources'])
        if self.owner is not None:
            self.owner._pending_plan = None
            self.owner._history.clear()
            for row in rows:
                self.owner._append('Você' if row['role']=='user' else 'Therion',row['content'])
            self.owner._update_confirm_panel()
        self.accept()

    def delete(self):
        if self.approval_worker is not None or getattr(self.owner,'_processing',False):return
        session = self.selected()
        if session and QMessageBox.question(self,'Excluir','Excluir esta conversa e seu índice?') == QMessageBox.Yes:
            self.store().delete(session)
            if session==self.host.session_id:
                self.host.clear_session()
                if self.owner is not None:self.owner._history.clear();self.owner._pending_plan=None;self.owner._update_confirm_panel()
            self.refresh()

    def delete_all(self):
        if self.approval_worker is not None or getattr(self.owner,'_processing',False):return
        if QMessageBox.question(self,'Excluir histórico','Excluir todas as conversas e seus índices?') == QMessageBox.Yes:
            self.store().delete()
            self.host.clear_session()
            if self.owner is not None:self.owner._history.clear();self.owner._pending_plan=None;self.owner._update_confirm_panel()
            self.refresh()

    def export(self):
        session = self.selected()
        if session:
            filename,_ = QFileDialog.getSaveFileName(self,'Exportar conversa','','JSON (*.json)')
            if filename:
                Path(filename).write_text(self.store().export(session),encoding='utf-8')
