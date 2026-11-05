"""Revisão humana de procedimentos locais; não altera Skills oficiais do cofre."""
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QListWidget,QLineEdit,QPlainTextEdit,
    QLabel,QPushButton,QMessageBox,QInputDialog)
from therion.agent.procedures import ProcedureLibrary
from PySide6.QtCore import Qt
from .surface_dialogs import Dialog as QDialog, MessageBox as QMessageBox, InputDialog as QInputDialog

LABELS={'title':'Título','goal':'Objetivo','preconditions':'Pré-condições','tools':'Ferramentas',
        'steps':'Passos','verification':'Como verificar','limitations':'Limitações'}
STATES={'proposed':'Proposta','testing':'Em teste','active':'Ativa','review':'Em revisão','retired':'Desativada'}


class ProcedurePanel(QDialog):
    def __init__(self,store,parent=None):
        super().__init__(parent)
        self.store=store;self.library=ProcedureLibrary(store);self.rows=[];self.current=None
        self.setWindowTitle('Procedimentos técnicos');self.resize(760,760)
        layout=QVBoxLayout(self)
        layout.addWidget(QLabel('Procedimentos orientam tarefas. Não concedem acesso, autonomia ou execução de código.'))
        self.list=QListWidget();self.list.currentRowChanged.connect(self.select);layout.addWidget(self.list)
        self.provenance=QLabel();self.provenance.setTextFormat(Qt.PlainText);self.provenance.setWordWrap(True)
        layout.addWidget(self.provenance)
        self.fields={}
        for key,label in LABELS.items():
            layout.addWidget(QLabel(label))
            field=QLineEdit() if key=='title' else QPlainTextEdit()
            if key!='title':field.setMaximumHeight(65)
            self.fields[key]=field;layout.addWidget(field)
        buttons=QHBoxLayout()
        actions=[('Propor revisão',self.revise),('Iniciar testes',lambda:self.transition('testing')),
            ('Associar teste',self.record_test),('Ativar',lambda:self.transition('active')),
            ('Pausar',lambda:self.transition('review')),('Desativar',lambda:self.transition('retired'))]
        for label,handler in actions:
            button=QPushButton(label);button.clicked.connect(handler);buttons.addWidget(button)
        layout.addLayout(buttons);self.refresh()

    def refresh(self):
        self.rows=self.library.index();self.list.clear()
        self.list.addItems([row['title']+' — '+STATES[row['state']]+f" (revisão {row['revision']})" for row in self.rows])

    def select(self,index):
        self.current=self.library.get(self.rows[index]['id']) if 0<=index<len(self.rows) else None
        self.provenance.setText(('Origem da proposta: '+self.current['source']) if self.current else '')
        for key,field in self.fields.items():
            text=self.current['body'][key] if self.current else ''
            field.setText(text) if key=='title' else field.setPlainText(text)

    def revise(self):
        body={key:field.text() if key=='title' else field.toPlainText() for key,field in self.fields.items()}
        try:
            import difflib,json
            before=json.dumps(self.current['body'] if self.current else {},ensure_ascii=False,indent=2).splitlines()
            after=json.dumps(body,ensure_ascii=False,indent=2).splitlines()
            diff='\n'.join(difflib.unified_diff(before,after,fromfile='Revisão atual',tofile='Proposta',lineterm=''))
            if not diff:return
            question=QMessageBox(self)
            question.setWindowTitle('Revisar procedimento')
            question.setText('Salvar esta proposta de revisão? Ela precisa de testes antes de ser ativada.')
            question.setDetailedText(diff)
            question.setStandardButtons(QMessageBox.Yes|QMessageBox.No)
            question.setDefaultButton(QMessageBox.No)
            if question.exec()!=QMessageBox.Yes:return
            if self.current and self.current['state'] in {'active','review'}:
                self.library.propose_revision(self.current['id'],self.current['digest'],body,{'kind':'human_review'})
            else:
                self.library.propose(body,{'kind':'human_review'},self.current['id'] if self.current else None,
                    self.current['digest'] if self.current else None)
            self.refresh()
        except ValueError as error:QMessageBox.information(self,'Procedimento',str(error))

    def transition(self,state):
        if not self.current:return
        if QMessageBox.question(self,'Revisar estado',f"Alterar este procedimento para {STATES[state]}?")!=QMessageBox.Yes:return
        try:
            self.library.transition(self.current['id'],state,self.current['digest']);self.refresh()
        except ValueError as error:QMessageBox.information(self,'Procedimento',str(error))

    def record_test(self):
        if not self.current:return
        with self.store.connection() as db:
            receipts=[dict(row) for row in db.execute("SELECT call_id,tool FROM receipts WHERE state='success' AND verified=1 ORDER BY created DESC LIMIT 50")]
        labels=[row['tool']+' — '+row['call_id'] for row in receipts]
        label,ok=QInputDialog.getItem(self,'Associar evidência','Execução verificada deste procedimento:',labels,editable=False)
        if not ok or label not in labels:return
        try:self.library.record_test(self.current['id'],receipts[labels.index(label)]['call_id'])
        except ValueError as error:QMessageBox.information(self,'Procedimento',str(error))
