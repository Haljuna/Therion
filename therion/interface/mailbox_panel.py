"""Janela de correio da cena: leitura assíncrona, sem mensagens artificiais no chat."""
from datetime import datetime
from html import escape
import time
from PySide6.QtCore import Qt,Signal,QThread,QSize,QRect,QEvent
from PySide6.QtGui import QColor,QFont,QPen,QTextCursor,QTextBlockFormat
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QLineEdit,
    QComboBox,QListWidget,QListWidgetItem,QSplitter,QTextEdit,QAbstractItemView,QStyledItemDelegate,QStyle,QStackedWidget,QBoxLayout)
from therion.agent.contracts import CancellationToken
from therion.integrations.mail_text import clean_mail_text,mail_priority,sender_name
from .surface_dialogs import SURFACE_STYLE

SYNC_SECONDS=30
BACKGROUND_SYNC_SECONDS=120
ROW_DATA=Qt.UserRole+1


MAIL_BACKGROUND='#09090f'


_WHITE=[f'[style*="{prop}{color}" i]' for prop in ('background-color:','background-color: ','background:','background: ')
    for color in ('#fff','white','rgb(255,255,255)','rgb(255, 255, 255)')]+[f'[bgcolor="{c}" i]' for c in ('#fff','#ffffff','white')]
MAIL_THEME_CSS=('<style>html,body{background:'+MAIL_BACKGROUND+'!important}'+','.join(_WHITE)+'{background:transparent!important}'
    '::-webkit-scrollbar{width:10px;background:transparent}::-webkit-scrollbar-thumb{background:#3a3550;border-radius:5px}</style>')


def themed_mail_html(html):
    """Só o fundo branco do e-mail fica transparente; caixas coloridas continuam (escurecidas)."""
    import re
    # No fim do <head>, para vencer regras !important do próprio e-mail em empate.
    themed,count=re.subn(r'</head\s*>',lambda m:MAIL_THEME_CSS+m.group(0),html,count=1,flags=re.I)
    return themed if count else MAIL_THEME_CSS+html


def mail_web_view(parent):
    """HTML do e-mail sem JavaScript nem cookies; links abrem no navegador do sistema."""
    try:
        from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile,QWebEngineSettings
        from PySide6.QtWebEngineWidgets import QWebEngineView
    except ImportError:return None
    from PySide6.QtGui import QDesktopServices
    kinds=QWebEnginePage.NavigationType
    class Page(QWebEnginePage):
        def acceptNavigationRequest(self,url,kind,main_frame):
            if kind==kinds.NavigationTypeLinkClicked and url.scheme() in {'http','https','mailto'}:QDesktopServices.openUrl(url)
            return kind not in {kinds.NavigationTypeLinkClicked,kinds.NavigationTypeFormSubmitted,kinds.NavigationTypeRedirect}
        def createWindow(self,kind):return None
    view=QWebEngineView(parent);profile=QWebEngineProfile(view)  # sem nome = sem cookies/cache em disco
    page=Page(profile,view);view.setPage(page)
    settings=page.settings();settings.setAttribute(QWebEngineSettings.JavascriptEnabled,False)
    settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls,True)
    # Escurece o e-mail pelo algoritmo do Chromium e usa o fundo do painel.
    settings.setAttribute(QWebEngineSettings.ForceDarkMode,True);page.setBackgroundColor(QColor(MAIL_BACKGROUND))
    view.setContextMenuPolicy(Qt.NoContextMenu);view.setAccessibleName('E-mail no formato original')
    return view


def received_label(row,tz):
    try:return datetime.fromtimestamp(int(row.get('received'))/1000,tz).strftime('%d/%m · %H:%M')
    except (ValueError,TypeError,OverflowError,OSError):return 'Data não informada'


class MailDelegate(QStyledItemDelegate):
    def sizeHint(self,option,index):
        return QSize(240,max(100,option.fontMetrics.lineSpacing()*3+32))

    def paint(self,painter,option,index):
        row=index.data(ROW_DATA)
        if not isinstance(row,dict):return super().paint(painter,option,index)
        painter.save();rect=option.rect
        selected=bool(option.state & QStyle.State_Selected)
        if selected:painter.fillRect(rect,QColor('#1C1430'))
        elif option.state & QStyle.State_MouseOver:painter.fillRect(rect,QColor(155,125,230,12))
        if selected:painter.fillRect(QRect(rect.x(),rect.y()+9,3,rect.height()-18),QColor('#9574E5'))
        box=rect.adjusted(14,10,-12,-10);font=QFont(option.font);font.setPixelSize(12);font.setWeight(QFont.Normal)
        painter.setFont(font);painter.setPen(QColor('#B5B1C5'))
        date=row.get('display_date','');date_width=min(108,painter.fontMetrics().horizontalAdvance(date)+10)
        painter.drawText(QRect(box.x(),box.y(),max(1,box.width()-date_width),18),Qt.AlignLeft|Qt.AlignVCenter,
            painter.fontMetrics().elidedText(sender_name(row['sender']),Qt.ElideRight,max(1,box.width()-date_width)))
        painter.setPen(QColor('#B5B1C5'));painter.drawText(QRect(box.right()-date_width,box.y(),date_width,18),Qt.AlignRight|Qt.AlignVCenter,date)
        font.setPixelSize(14);font.setWeight(QFont.DemiBold if row.get('unread') else QFont.Medium);painter.setFont(font)
        painter.setPen(QColor('#F1F0F7' if row.get('unread') else '#F1F0F7'))
        subject=('● ' if row.get('unread') else '')+row['subject']
        painter.drawText(QRect(box.x(),box.y()+24,box.width(),22),Qt.AlignVCenter,
            painter.fontMetrics().elidedText(subject,Qt.ElideRight,box.width()))
        font.setPixelSize(12);font.setWeight(QFont.Normal);painter.setFont(font);painter.setPen(QColor('#B5B1C5'))
        priority=mail_priority(row);prefix=(priority['label']+' · ') if priority['label'] else ''
        preview=prefix+' '.join(row.get('snippet','').split())
        painter.drawText(QRect(box.x(),box.y()+52,box.width(),18),Qt.AlignVCenter,
            painter.fontMetrics().elidedText(preview,Qt.ElideRight,box.width()))
        painter.setPen(QPen(QColor(108,81,175,32),1));painter.drawLine(rect.left()+14,rect.bottom(),rect.right()-12,rect.bottom())
        painter.restore()


class MailJob(QThread):
    def __init__(self,function,parent):
        super().__init__(parent);self.function=function;self.token=CancellationToken();self.result=None
    def run(self):
        try:self.result=self.function(self.token)
        except Exception:self.result=dict(state='error',message='Não consegui consultar o Gmail. Confira a conexão e tente atualizar.')


class MailPreview(QWidget):
    activated=Signal(str)
    def __init__(self,parent=None):
        super().__init__(parent)
        # Cartão próprio: e-mails ficam visualmente separados dos compromissos.
        self.setObjectName('mailPreview');self.setAttribute(Qt.WA_StyledBackground,True)
        self.setStyleSheet('QWidget#mailPreview { background:rgba(20,19,30,184); border:1px solid rgba(255,255,255,23); border-radius:12px; }')
        layout=QVBoxLayout(self);layout.setContentsMargins(12,10,12,10);layout.setSpacing(6)
        title=QLabel('E-mails recentes');title.setStyleSheet('font-weight:600;')
        heading=QHBoxLayout();heading.addWidget(title,1)
        link=QPushButton('Ver caixa');link.setObjectName('textLink');link.clicked.connect(lambda:self.activated.emit(''))
        heading.addWidget(link);layout.addLayout(heading)
        self.status=QLabel('Preparando caixa…');self.status.setWordWrap(True);self.status.setMaximumHeight(44)
        self.status.setTextFormat(Qt.PlainText);self.status.setObjectName('muted');layout.addWidget(self.status)
        self.list=QListWidget();self.list.setAccessibleName('Prévia da caixa de entrada na agenda')
        self.list.setFixedHeight(82)
        self.list.itemClicked.connect(lambda item:self.activated.emit(item.data(Qt.UserRole)))
        layout.addWidget(self.list)

    def render(self,result,tz):
        all_items=result.get('items',[]);items=[r for r in all_items if mail_priority(r)['essential']]
        self.list.clear();self.list.setVisible(bool(items))
        state=result.get('state')
        suffix={'stale':' · cache desatualizado','error':' · falha na atualização','loading':' · atualizando'}.get(state,'')
        self.status.setText(((result.get('account_email') or 'Gmail')+' · '+str(len(items))+(' essencial' if len(items)==1 else ' essenciais')+suffix)
            if items else result.get('message') or 'Nenhum e-mail na caixa de entrada carregada.')
        if all_items and not items:self.status.setText('Só promoções ou avisos sociais nesta página. Use Ver caixa → Caixa de entrada.')
        for row in items[:2]:
            text=('● ' if row.get('unread') else '')+row['subject']
            item=QListWidgetItem(text);item.setData(Qt.UserRole,row['id']);item.setSizeHint(QSize(100,32))
            item.setToolTip('<qt>'+escape(row['sender']+' · '+received_label(row,tz))+'</qt>');self.list.addItem(item)


class MailboxPanel(QWidget):
    """Workers independentes da conversa; só o orquestrador consulta o serviço."""
    def __init__(self,dashboard):
        super().__init__();self.dashboard=dashboard;self.setMinimumSize(300,320)
        self.compact=False
        self.setStyleSheet(SURFACE_STYLE+'''
            QTextEdit#mailBody, QListWidget#mailList { background:rgba(9,9,15,235); }
            QTextEdit#mailBody { font-size:14px; padding:17px; border-radius:10px; }
            QListWidget#mailList { padding:0; border-radius:10px; }
            QListWidget#mailList::item { padding:0; border:0; }
            QLabel#mailSubject { font-size:17px; font-weight:600; color:#F1F0F7; }
            QLabel#mailMeta { color:#B5B1C5; font-size:12px; }
        ''')
        self.jobs={};self.pending={};self.generation=0;self.selection_epoch=0
        self.account=None;self.query='in:inbox';self.items=[];self.loaded_items=[];self.next_page=None;self.selected=None
        self.previews=[];self.last_check=0.;self.last_refresh=0.;self.last_revision=-1
        self.open_requested=False;self.pending_select=None;self.active=False;self._rendering=False
        self.retry_after=0.;self.connection_error=False
        self.current_body=None;self.inbox_ids=None;self.new_received=0
        self._layout_ui()

    def request(self,operation,args=None,token=None):
        return self.dashboard.source.mailbox(operation,args or {},token or CancellationToken())

    def status(self):
        result=self.dashboard.source.mailbox_status()
        return result if isinstance(result,dict) else dict(state='disabled',account=None,items=[],message='Gmail não configurado.')

    def _layout_ui(self):
        root=QVBoxLayout(self);root.setContentsMargins(18,10,18,16);root.setSpacing(12)
        heading=QHBoxLayout();self.heading_layout=heading;title=QLabel('Caixa de entrada');self.mail_heading=title;title.setProperty('role','title');title.setWordWrap(True);heading.addWidget(title,1)
        self.refresh_button=QPushButton('Atualizar');self.refresh_button.clicked.connect(lambda:self.reload(force=True));heading.addWidget(self.refresh_button)
        self.configure=QPushButton('Configurar Gmail');self.configure.clicked.connect(lambda:self.dashboard.agent_tab(0));heading.addWidget(self.configure)
        root.addLayout(heading)
        self.notice=QLabel('Preparando caixa…');self.notice.setWordWrap(True);self.notice.setAccessibleName('Estado da conexão de e-mail')
        self.notice.setTextFormat(Qt.PlainText);self.notice.setMaximumHeight(48)
        self.notice.setProperty('role','muted')
        status_row=QHBoxLayout();status_row.addWidget(self.notice,1)
        self.show_all=QPushButton('Ver todos');self.show_all.setObjectName('textLink');self.show_all.hide()
        self.show_all.clicked.connect(lambda:self.filter.setCurrentIndex(1));status_row.addWidget(self.show_all);root.addLayout(status_row)
        self.sync_note=QLabel('Atualização automática · a cada 30 segundos');self.sync_note.setProperty('role','muted')
        self.sync_note.setTextFormat(Qt.PlainText);root.addWidget(self.sync_note)
        self.briefing_note=QLabel('');self.briefing_note.setWordWrap(True);self.briefing_note.setTextFormat(Qt.PlainText)
        self.briefing_note.setProperty('role','notice');self.briefing_note.hide();root.addWidget(self.briefing_note)
        tools=QHBoxLayout();self.tools_layout=tools;self.filter=QComboBox();self.filter.setAccessibleName('Pasta de e-mail')
        for title,query in [('Essenciais','in:inbox'),('Caixa de entrada','in:inbox'),('Não lidos','in:inbox is:unread'),('Todos os e-mails','-in:trash -in:spam')]:self.filter.addItem(title,query)
        self.filter.setToolTip('Essenciais recolhe promoções e avisos sociais. Mensagens marcadas ou com possíveis prazos e ações são mantidas. Nenhuma mensagem é excluída.')
        self.filter.currentIndexChanged.connect(self.search)
        tools.addWidget(self.filter)
        self.search_field=QLineEdit();self.search_field.setPlaceholderText('Buscar por assunto, remetente ou palavra-chave…')
        self.search_field.setMaxLength(700);self.search_field.setAccessibleName('Buscar e-mails');self.search_field.returnPressed.connect(self.search)
        tools.addWidget(self.search_field,1);find=QPushButton('Buscar');self.find_button=find;find.clicked.connect(self.search);tools.addWidget(find);root.addLayout(tools)
        self.splitter=QSplitter(Qt.Horizontal)
        left=QWidget();self.list_page=left;column=QVBoxLayout(left);column.setContentsMargins(0,0,0,0);column.setSpacing(8)
        self.list=QListWidget();self.list.setObjectName('mailList');self.list.setAccessibleName('E-mails da consulta');self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.setItemDelegate(MailDelegate(self.list));self.list.setMouseTracking(True)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list.currentRowChanged.connect(self.select_row);self.list.verticalScrollBar().valueChanged.connect(self.scrolled)
        column.addWidget(self.list,1)
        self.more=QPushButton('Carregar mais');self.more.clicked.connect(self.load_more);column.addWidget(self.more)
        self.splitter.addWidget(left);left.setMinimumWidth(255)
        right=QWidget();self.reader_page=right;reader=QVBoxLayout(right);reader.setContentsMargins(8,0,0,0);reader.setSpacing(8)
        self.back=QPushButton('← Voltar à lista');self.back.clicked.connect(self.show_list)
        self.back.hide();reader.addWidget(self.back)
        self.subject=QLabel('Selecione um e-mail');self.subject.setWordWrap(True);self.subject.setProperty('role','section')
        self.subject.setObjectName('mailSubject')
        self.subject.setMaximumHeight(70)
        self.subject.setTextFormat(Qt.PlainText);self.subject.setTextInteractionFlags(Qt.TextSelectableByMouse);reader.addWidget(self.subject)
        self.sender=QLabel('');self.sender.setWordWrap(True);self.sender.setTextFormat(Qt.PlainText)
        self.sender.setObjectName('mailMeta');self.sender.setMaximumHeight(66)
        self.sender.setTextInteractionFlags(Qt.TextSelectableByMouse);self.sender.setProperty('role','muted');reader.addWidget(self.sender)
        reading=QHBoxLayout();self.read_mode=QComboBox();self.read_mode.addItems(['Leitura limpa','Mensagem completa','Original (com imagens)']);self.web=None;self.read_mode.setCurrentIndex(2)
        self.read_mode.setAccessibleName('Modo de leitura do e-mail');self.read_mode.currentIndexChanged.connect(self._present_body)
        reading.addWidget(self.read_mode);reading.addStretch();reader.addLayout(reading)
        self.content_note=QLabel('');self.content_note.setWordWrap(True);self.content_note.setTextFormat(Qt.PlainText)
        self.content_note.setProperty('role','muted');self.content_note.hide();reader.addWidget(self.content_note)
        self.body=QTextEdit();self.body.setObjectName('mailBody');self.body.setReadOnly(True);self.body.setAcceptRichText(False)
        self.body.setPlaceholderText('Abra uma mensagem na lista para ler aqui.')
        self.body.setAccessibleName('Conteúdo do e-mail selecionado');reader.addWidget(self.body,1)
        self.attachments=QLabel('');self.attachments.setWordWrap(True);self.attachments.setTextFormat(Qt.PlainText)
        self.attachments.setProperty('role','muted');reader.addWidget(self.attachments)
        movement=QHBoxLayout();self.previous=QPushButton('← Anterior');self.previous.clicked.connect(lambda:self.move_selection(-1))
        self.following=QPushButton('Próximo →');self.following.clicked.connect(lambda:self.move_selection(1))
        movement.addWidget(self.previous);movement.addWidget(self.following);reader.addLayout(movement)
        self.splitter.addWidget(right);self.splitter.setSizes([330,650])
        root.addWidget(self.splitter,1)
        self.footnote=QLabel('Leitura no painel · a seleção não marca mensagens como lidas no Gmail.')
        self.footnote.setProperty('role','muted');self.footnote.setWordWrap(True);root.addWidget(self.footnote)
        self._navigation()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if not hasattr(self,'splitter'):return
        compact=self.width()<900
        self.tools_layout.setDirection(QBoxLayout.TopToBottom if self.width()<600 else QBoxLayout.LeftToRight)
        self.heading_layout.setDirection(QBoxLayout.TopToBottom if self.width()<500 else QBoxLayout.LeftToRight)
        if compact==self.compact:return
        self.compact=compact;self.back.setVisible(compact)
        if compact:
            if self.selected:self.show_reader()
            else:self.show_list()
        else:
            self.list_page.show();self.reader_page.show();self.splitter.setSizes([330,650]);self.reading_chrome(False)

    def minimumSizeHint(self):return QSize(300,320)

    def _available_height(self):
        viewport=self.parentWidget()
        return viewport.height() if viewport is not None else self.height()

    def showEvent(self,event):
        super().showEvent(event)
        viewport=self.parentWidget()
        if viewport is not None and not getattr(self,'_watching_viewport',False):
            viewport.installEventFilter(self);self._watching_viewport=True
        self.reading_chrome(self.compact and self.list_page.isHidden())

    def eventFilter(self,watched,event):
        if watched is self.parentWidget() and event.type()==QEvent.Resize:
            roomy=self._available_height()>=700
            if self.sync_note.isHidden()==(roomy and not self.compact):
                self.reading_chrome(self.compact and self.list_page.isHidden())
        return super().eventFilter(watched,event)

    def reading_chrome(self,reader):
        reading=self.compact and reader
        self.mail_heading.setVisible(not self.compact);self.refresh_button.setVisible(not reading)
        # Linhas informativas só aparecem quando sobra altura; o conteúdo continua no tooltip.
        roomy=self._available_height()>=700
        self.sync_note.setVisible(not self.compact and roomy);self.footnote.setVisible(not self.compact and roomy)
        self.notice.setToolTip(self.sync_note.text()+'\n'+self.footnote.text())
        self.notice.setVisible(not reading or self.connection_error)
        self.briefing_note.setVisible(not reading and bool(self.briefing_note.text()))
        self.previous.setVisible(not reading);self.following.setVisible(not reading)
        for widget in (self.filter,self.search_field,self.find_button,self.show_all):widget.setVisible(not reading)
        self.show_all.setVisible(not reading and len(self.loaded_items)>len(self.items))
        self.subject.setMaximumHeight(44 if self.compact else 70);self.sender.setMaximumHeight(36 if self.compact else 66)
        if self.compact:self.content_note.hide()

    def show_list(self):
        self.list_page.show()
        if self.compact:self.reader_page.hide()
        self.reading_chrome(False)

    def show_reader(self):
        self.reader_page.show()
        if self.compact:self.list_page.hide()
        self.reading_chrome(True)

    def attach_preview(self,preview):
        self.previews.append(preview);preview.activated.connect(self.dashboard.open_mail)

    def _publish_previews(self,result=None):
        result=result or self.status()
        for preview in self.previews:preview.render(result,self.dashboard.window._orchestrator._calendar_now().tzinfo)

    def _clear(self):
        self.generation+=1;self.selection_epoch+=1;self.items=[];self.loaded_items=[];self.next_page=None;self.selected=None
        self.retry_after=0.;self.connection_error=False
        self.current_body=None;self.inbox_ids=None;self.new_received=0;self.content_note.hide();self.show_all.hide()
        self.briefing_note.clear();self.briefing_note.hide()
        self.pending.clear()
        for worker in self.jobs.values():worker.token.cancel()
        self.list.clear();self._text_view();self.body.clear();self.subject.setText('Selecione um e-mail');self.sender.clear();self.attachments.clear();self._navigation()

    def poll(self,*,force=False):
        if not self.active:return
        now=time.monotonic()
        if not force and now-self.last_check<1:return
        self.last_check=now;status=self.status();account=status.get('account')
        if account!=self.account:
            self._clear();self.account=account;self.last_revision=-1
        self.configure.setVisible(status.get('state') in {'disabled','disconnected'} or self.connection_error)
        self.refresh_button.setEnabled(bool(account));self.more.setVisible(bool(self.next_page))
        if status.get('revision')!=self.last_revision:
            self.last_revision=status.get('revision');self._publish_previews(status)
        if not account:
            self.notice.setText(status.get('message','Gmail indisponível.'));return
        interval=BACKGROUND_SYNC_SECONDS if self.dashboard.window.isMinimized() else SYNC_SECONDS
        suffix=(' · '+str(self.new_received)+(' novo e-mail' if self.new_received==1 else ' novos e-mails')+' na última consulta') if self.new_received else ''
        self.sync_note.setText('Atualização automática · a cada '+str(interval)+' segundos'+suffix)
        if self.inbox_ids is None and status.get('state') in {'ready','stale'}:self.inbox_ids={r['id'] for r in status.get('items',[])}
        due=status.get('state')=='missing' or (status.get('age_seconds') or 0)>=interval
        if due and now>=self.retry_after and 'inbox' not in self.jobs and not ('page' in self.jobs and self.query=='in:inbox'):
            self._publish_previews(dict(status,state='loading',message='Carregando e-mails…'))
            self._queue('inbox',dict(query='in:inbox',page=None,force=status.get('state')!='missing',automatic=True),0)
        if self.isVisible() and self.open_requested and self.query!='in:inbox' and now-self.last_refresh>=interval and now>=self.retry_after and 'page' not in self.jobs:
            self._queue('page',dict(query=self.query,page=None,force=True,automatic=True),self.generation)

    def activate(self,active):
        self.active=active
        if active:self.poll(force=True)

    def focus(self,*,touch=True):
        if self.open_requested and not self.isHidden():
            self.request('focus',dict(query=self.query,ids=[r['id'] for r in self.items],selected=self.selected,touch=touch))

    def opened(self,identifier=None):
        self.open_requested=True;self.pending_select=identifier or None;self.poll(force=True)
        if identifier and not any(row['id']==identifier for row in self.items):
            self.filter.blockSignals(True);self.filter.setCurrentIndex(1);self.filter.blockSignals(False)
            self.search_field.clear();self.query='in:inbox';self.items=[];self.loaded_items=[];self.selected=None;self.generation+=1
        if self.account and not self.items:self._load_page(None,False)
        self.focus()
        if identifier and any(row['id']==identifier for row in self.items):
            self.pending_select=None;self._select_identifier(identifier)

    def hideEvent(self,event):
        if self.active and self.dashboard.active and self.dashboard.window.isVisible() and not self.dashboard.window.isMinimized():self.request('hide')
        super().hideEvent(event)

    def showEvent(self,event):
        super().showEvent(event)
        if self.open_requested:self.focus()

    def search(self):
        term=self.search_field.text().strip();self.query=self.filter.currentData()+(' ('+term+')' if term else '')
        self.generation+=1;self.items=[];self.loaded_items=[];self.next_page=None;self.selected=None;self.selection_epoch+=1
        self.current_body=None;self.content_note.hide()
        self.list.clear();self._text_view();self.body.clear();self.sender.clear();self.attachments.clear();self.subject.setText('Selecione um e-mail')
        if self.compact:self.show_list()
        if 'body' in self.jobs:self.jobs['body'].token.cancel()
        self.pending.pop('body',None);self.focus();self._load_page(None,False)

    def reload(self,*,force=True):
        self.generation+=1;self.focus();self._load_page(None,force)

    def _load_page(self,page,force):
        if not self.active or not self.account:return
        if page is not None:
            self._page_scroll=(self.generation,page,self.list.verticalScrollBar().value())
        args=dict(query=self.query,page=page,force=force)
        self.notice.setText('Atualizando caixa…' if force else 'Carregando e-mails…')
        self.more.setEnabled(False)
        self._queue('page',args,self.generation)

    def _queue(self,kind,args,epoch):
        if kind in self.jobs:
            if args==self.jobs[kind].args and epoch==self.jobs[kind].epoch:return
            self.pending[kind]=(args,epoch)
            if kind=='body' or epoch!=self.jobs[kind].epoch:self.jobs[kind].token.cancel()
            return
        operation='body' if kind=='body' else 'page'
        worker=MailJob(lambda token:self.request(operation,args,token),self)
        worker.epoch=epoch;worker.account=self.account;worker.args=args;self.jobs[kind]=worker
        worker.finished.connect(lambda:self._finished(kind,worker));worker.start()

    def _finished(self,kind,worker):
        if self.jobs.get(kind) is not worker:return
        self.jobs.pop(kind);result=worker.result or {};current=self.status().get('account')
        epoch=self.selection_epoch if kind=='body' else self.generation
        valid=self.active and not worker.token.cancelled and worker.account==current==self.account and (kind=='inbox' or worker.epoch==epoch)
        if valid:
            if kind=='inbox':
                if result.get('state')=='ready':
                    self.retry_after=0.;self.connection_error=False;self._publish_previews()
                    incoming={r['id'] for r in result.get('items',[])}
                    self.new_received=len(incoming-self.inbox_ids) if self.inbox_ids is not None else 0;self.inbox_ids=incoming
                    if self.query=='in:inbox' and self.open_requested and 'page' not in self.jobs:self._render_page(result,worker.args)
                else:
                    self.retry_after=time.monotonic()+60;self.connection_error=True;self.configure.show()
                    self._publish_previews(dict(result,items=self.status().get('items',[])))
                    if self.query=='in:inbox':self.notice.setText(result.get('message','Gmail indisponível.'))
            elif kind=='page':self._render_page(result,worker.args)
            elif result.get('state')=='ready' and result.get('id')==self.selected:self._render_body(result)
            elif result.get('state')=='error':
                self.connection_error=True;self.configure.show();self._text_view();self.body.setPlainText(result['message'])
        worker.deleteLater()
        pending=self.pending.pop(kind,None)
        if pending and self.active:self._queue(kind,*pending)

    def _render_page(self,result,args):
        if result.get('state')!='ready':
            self.retry_after=time.monotonic()+60;self.connection_error=True;self.configure.show()
            self.notice.setText(result.get('message','Consulta indisponível; não significa caixa vazia.')+(' A lista anterior foi mantida.' if self.items else ''))
            self.more.setEnabled(bool(self.next_page))
            self._publish_previews(dict(self.status(),state='error',message=result.get('message','Não consegui atualizar a caixa.')) if args['query']=='in:inbox' else None)
            return
        self.connection_error=False
        old_scroll=self.list.verticalScrollBar().value();anchor=self.list.itemAt(8,8)
        saved=getattr(self,'_page_scroll',None)
        if args['page'] is not None and saved and saved[:2]==(self.generation,args['page']):
            old_scroll=saved[2]
            self._page_scroll=None
        anchor_id=anchor.data(Qt.UserRole) if anchor else None;anchor_offset=self.list.visualItemRect(anchor).top() if anchor else 0
        automatic=args.get('automatic',False);incoming=result.get('items',[])
        if automatic and incoming and result.get('next_page'):
            incoming_ids={r['id'] for r in incoming}
            self.loaded_items=incoming+[r for r in self.loaded_items if r['id'] not in incoming_ids]
        else:
            if args['page'] is None:self.loaded_items=[]
            seen={r['id'] for r in self.loaded_items}
            self.loaded_items.extend(row for row in incoming if row['id'] not in seen)
        self.loaded_items=self.loaded_items[:500]
        essentials=self.filter.currentIndex()==0 and not self.search_field.text().strip()
        self.items=[r for r in self.loaded_items if not essentials or mail_priority(r)['essential']]
        self.next_page=result.get('next_page') if len(self.loaded_items)<500 else None
        self.last_refresh=time.monotonic();self._rendering=True
        self.list.clear();tz=self.dashboard.window._orchestrator._calendar_now().tzinfo
        for row in self.items:
            item=QListWidgetItem(row['subject']+'\n'+sender_name(row['sender'])+'\n'+received_label(row,tz))
            date=received_label(row,tz);row_view=dict(row,display_date=date.split(' · ')[0])
            item.setData(Qt.UserRole,row['id']);item.setData(ROW_DATA,row_view)
            item.setToolTip('<qt>'+escape(row['sender']+' · '+date+'\n'+row.get('snippet','')+'\n'+mail_priority(row)['reason'])+'</qt>');self.list.addItem(item)
        self._rendering=False
        when=datetime.fromtimestamp(result['refreshed_at']).astimezone().strftime('%H:%M')
        hidden=len(self.loaded_items)-len(self.items)
        self.notice.setText(((result.get('account_email') or 'Gmail')+' · '+str(len(self.items))+' exibidos · atualizado às '+when) if self.items else
                           ('Nenhum essencial nesta página.' if hidden else 'Nenhum e-mail nesta consulta.'))
        if hidden:self.notice.setText(self.notice.text()+' · '+str(hidden)+(' mensagem secundária recolhida' if hidden==1 else ' mensagens secundárias recolhidas'))
        self.show_all.setVisible(bool(hidden))
        if len(self.loaded_items)==500:self.notice.setText(self.notice.text()+' · refine a busca para continuar')
        self.more.setVisible(bool(self.next_page));self.more.setEnabled(bool(self.next_page))
        target=self.pending_select or self.selected
        self.pending_select=None
        if target and not any(row['id']==target for row in self.items):
            self.selected=None;self.selection_epoch+=1;target=None
            if 'body' in self.jobs:self.jobs['body'].token.cancel()
            self.pending.pop('body',None);self.subject.setText('Selecione um e-mail')
            self._text_view();self.body.clear();self.sender.clear();self.attachments.clear();self.current_body=None;self.content_note.hide()
        refresh_body=args['force'] and not automatic
        if target:self._select_identifier(target,force=refresh_body,touch=False,preserve_reader=not refresh_body)
        if args['page'] is not None or automatic:
            self._rendering=True
            anchored=next((self.list.item(i) for i in range(self.list.count()) if self.list.item(i).data(Qt.UserRole)==anchor_id),None)
            if args['page'] is not None:
                # Appending a page never inserts rows before the current viewport.
                # Preserve its pixel offset, including the styled viewport inset.
                self.list.verticalScrollBar().setValue(old_scroll)
            elif old_scroll>0 and anchored:
                self.list.scrollToItem(anchored,QAbstractItemView.PositionAtTop)
                self.list.verticalScrollBar().setValue(self.list.verticalScrollBar().value()-anchor_offset)
            else:self.list.verticalScrollBar().setValue(old_scroll)
            self._rendering=False
        self.focus(touch=False);self._navigation();self._publish_previews()
        if self.compact and self.selected is None:self.show_list()
        self.reading_chrome(self.compact and self.list_page.isHidden())

    def _select_identifier(self,identifier,*,force=False,touch=True,preserve_reader=False):
        index=next((i for i,row in enumerate(self.items) if row['id']==identifier),None)
        if index is None:return
        old=self.list.currentRow();self._rendering=True;self.list.setCurrentRow(index);self._rendering=False
        if (old!=index or force) and not (preserve_reader and self.selected==identifier):
            self.select_row(index,force=force,touch=touch)

    def select_row(self,index,*,force=False,touch=True):
        if self._rendering or not 0<=index<len(self.items):return
        row=self.items[index];self.selected=row['id'];self.selection_epoch+=1
        if self.compact:self.show_reader()
        self.subject.setText(row['subject'])
        self.sender.setText(row['sender']+'\nRecebido em '+received_label(row,self.dashboard.window._orchestrator._calendar_now().tzinfo))
        self.sender.setToolTip('Para: '+row['headers'].get('to',''))
        self.current_body=None;self.content_note.hide()
        self._text_view();self.body.setPlainText('Carregando mensagem…');self.attachments.clear();self.focus(touch=touch);self._navigation()
        self._queue('body',dict(id=self.selected,force=force),self.selection_epoch)

    def _render_body(self,result):
        # Somente texto: HTML de e-mail não executa scripts nem carrega imagens.
        self.current_body=result;self._present_body()
        files=result.get('attachments',[])
        notice='Anexos: '+', '.join(str(row.get('name','Arquivo'))[:80] for row in files[:8]) if files else ''
        if len(files)>8:notice+=' · mais '+str(len(files)-8)+' anexo(s)'
        if result.get('partial'):notice+=' · Texto longo: esta é uma prévia de até 200 mil caracteres.'
        self.attachments.setText(notice)

    def _text_view(self):
        if self.web:self.web.hide();self.web.setHtml('')
        self.body.show()

    def _present_body(self):
        if not self.current_body:return
        html=self.current_body.get('html') if self.read_mode.currentIndex()==2 else ''
        if html and self.web is None:
            self.web=mail_web_view(self)
            if self.web:layout=self.body.parentWidget().layout();layout.insertWidget(layout.indexOf(self.body)+1,self.web,1)
        if html and self.web:
            self.web.setHtml(themed_mail_html(html));self.body.hide();self.web.show();self.content_note.hide();return
        self._text_view()
        text=self.current_body['text'];cleaned=clean_mail_text(text)
        compact=self.read_mode.currentIndex()!=1  # Original sem HTML cai na leitura limpa
        self.body.setPlainText((cleaned['text'].replace('\n\n','\n') if compact else text) or '(Mensagem sem texto.)')
        cursor=self.body.textCursor();cursor.select(QTextCursor.Document)
        block=QTextBlockFormat();block.setLineHeight(130.,QTextBlockFormat.ProportionalHeight.value);block.setBottomMargin(6 if compact else 0)
        cursor.beginEditBlock();cursor.mergeBlockFormat(block);cursor.endEditBlock()
        cursor.clearSelection();cursor.setPosition(0);self.body.setTextCursor(cursor)
        self.content_note.setText('Visualização simplificada · original em Mensagem completa.')
        self.content_note.setToolTip('Recolhido: '+', '.join(cleaned['reasons']))
        self.content_note.setVisible(compact and bool(cleaned['reasons']) and not self.compact)

    def _navigation(self):
        index=next((i for i,r in enumerate(self.items) if r['id']==self.selected),-1)
        self.previous.setEnabled(index>0);self.following.setEnabled(0<=index<len(self.items)-1)

    def move_selection(self,delta):
        index=next((i for i,r in enumerate(self.items) if r['id']==self.selected),-1)
        if 0<=index+delta<len(self.items):self.list.setCurrentRow(index+delta)

    def scrolled(self,value):
        bar=self.list.verticalScrollBar()
        if not self._rendering and bar.maximum()>0 and value>=bar.maximum()-2:self.load_more()

    def load_more(self):
        if self.next_page and 'page' not in self.jobs:self._load_page(self.next_page,False)

    @property
    def busy(self):return bool(self.jobs)

    def cancel(self):
        self.active=False;self.generation+=1;self.selection_epoch+=1;self.pending.clear()
        for worker in self.jobs.values():worker.token.cancel()
        self.request('hide')
