"""Componentes visuais do painel. Não executam aplicativos nem concedem autoridade."""
import os
import weakref
from pathlib import Path

from PySide6.QtCore import Qt,Signal,QTimer,QFileInfo,QEvent
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QFrame,QLabel,QVBoxLayout,QHBoxLayout,QToolButton,
    QCheckBox,QWidget,QFileIconProvider,QStyle,QDialog,QLineEdit,QPushButton,
    QScrollArea,QGridLayout,QSizePolicy)
from shiboken6 import isValid
from .surface_dialogs import Dialog as QDialog


PANEL_STYLE='''
QDialog { background:#09090F; color:#F1F0F7; font-family:"Segoe UI"; font-size:13px; }
QWidget { color:#F1F0F7; font-family:"Segoe UI"; font-size:13px; }
QLabel { background:transparent; }
QLabel[role="title"] { font-size:22px; font-weight:600; }
QLabel[role="muted"] { color:#B5B1C5; }
QLabel[role="section"] { font-size:14px; font-weight:600; }
QLabel[role="notice"] { color:#A084E3; padding:10px; background:#14131E; border-radius:8px; }
QListWidget#navigation { background:transparent; border:none; outline:none; }
QListWidget#navigation::item { padding:13px 10px; border-radius:7px; margin:3px 0; }
QListWidget#navigation::item:selected { background:#1C1430; color:#A387E8; }
QListWidget#navigation::item:hover { background:#14131E; }
QListWidget#navigation:focus { border:1px solid #4C22B4; border-radius:7px; }
QFrame[role="card"] { background:rgba(20,19,30,184); border:1px solid rgba(255,255,255,23); border-radius:14px; }
QFrame[role="card"][selected="true"],QFrame[role="card"][chosen="true"] { border:1px solid #4C22B4; background:#14131E; }
QFrame[role="card"]:focus { border:1px solid #6536D9; }
QPushButton,QToolButton { background:#14131E; border:1px solid #302B3D; border-radius:10px; padding:6px 12px; }
QPushButton:hover,QToolButton:hover { background:#2C2739; border-color:#666; }
QPushButton:focus,QToolButton:focus,QLineEdit:focus,QCheckBox:focus { border:1px solid #6536D9; }
QPushButton[primary="true"] { background:#6536D9; color:#111; border:none; font-weight:600; }
QPushButton[primary="true"]:hover { background:#7F58DF; }
QPushButton:disabled,QToolButton:disabled { color:#777; background:#14131E; }
QPushButton[role="rowtitle"] { text-align:left; background:transparent; border:none; padding:0; font-weight:600; font-size:14px; }
QPushButton[role="rowtitle"]:focus { border:1px solid #6536D9; }
QLabel[role="rowtitle"] { font-weight:600; font-size:14px; }
QToolButton[role="remove"] { background:transparent; border:none; color:#aaa; font-size:17px; padding:2px 9px; }
QToolButton[role="remove"]:hover { color:#B49EEC; background:#211935; }
QCheckBox { spacing:7px; background:transparent; padding:3px; }
QCheckBox::indicator { width:17px; height:17px; border:1px solid #777; border-radius:4px; background:#14131E; }
QCheckBox::indicator:checked { background:#6536D9; border:1px solid #AA90EA; image:url("__CHECK_ICON__"); }
QCheckBox::indicator:disabled { border-color:#444; }
QLineEdit,QTimeEdit,QComboBox { background:#14131E; border:1px solid #373147; border-radius:6px; padding:7px; }
QScrollArea { background:transparent; border:none; }
QScrollArea>QWidget>QWidget { background:transparent; }
QStackedWidget { background:transparent; }
QScrollBar:vertical { width:9px; background:#09090F; }
QScrollBar::handle:vertical { background:#444; border-radius:4px; min-height:30px; }
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical { height:0; }
QScrollBar::add-page,QScrollBar::sub-page { background:transparent; }
'''.replace('__CHECK_ICON__',Path(__file__).with_name('autonomy_check.svg').as_posix())


def label(text='',role=None):
    widget=QLabel(text);widget.setTextFormat(Qt.PlainText);widget.setWordWrap(True)
    if role:widget.setProperty('role',role)
    return widget


def button(text,callback,primary=False):
    widget=QPushButton(text);widget.setProperty('primary',primary);widget.clicked.connect(callback)
    return widget


def scroll_column():
    area=QScrollArea();area.setWidgetResizable(True)
    content=QWidget();layout=QVBoxLayout(content);layout.setContentsMargins(0,0,6,0)
    layout.setSpacing(10);layout.setAlignment(Qt.AlignTop);area.setWidget(content)
    return area,content,layout


class IconCache(QWidget):
    """Ícones nativos carregados um por evento, exclusivamente na thread Qt."""
    def __init__(self,parent):
        super().__init__(parent);self.hide()
        self.provider=QFileIconProvider();self.cache={};self.pending=[];self.scheduled=False
        self.fallback=parent.style().standardIcon(QStyle.SP_ComputerIcon)

    def fill(self,target,path,size=32):
        key=os.path.normcase(str(path));target.setPixmap(self.cache.get(key,self.fallback).pixmap(size,size))
        if key not in self.cache:
            self.pending.append((weakref.ref(target),key,size))
            if not self.scheduled:self.scheduled=True;QTimer.singleShot(0,self.pump)

    def pump(self):
        if not isValid(self):return
        if not self.pending:self.scheduled=False;return
        target,key,size=self.pending.pop(0)
        try:
            if key not in self.cache:
                icon=self.provider.icon(QFileInfo(key)) if Path(key).is_file() else self.fallback
                self.cache[key]=icon if not icon.isNull() else self.fallback
            widget=target()
            if widget is not None and isValid(widget):widget.setPixmap(self.cache[key].pixmap(size,size))
        except (OSError,RuntimeError):pass
        QTimer.singleShot(5,self.pump)


class ExpandableRow(QFrame):
    selected=Signal(str)

    def __init__(self,identifier,title,check_text='',remove=False,parent=None):
        super().__init__(parent);self.identifier=identifier;self.pinned_details=False;self.setProperty('role','card')
        self.expandable=bool(check_text or remove)
        self.setProperty('selected',False);self.setFocusPolicy(Qt.StrongFocus if self.expandable else Qt.NoFocus)
        root=QVBoxLayout(self);root.setContentsMargins(14,12,14,12);root.setSpacing(10)
        header=QHBoxLayout();header.setSpacing(12);root.addLayout(header)
        self.icon=QLabel();self.icon.setFixedSize(32,32);header.addWidget(self.icon)
        texts=QVBoxLayout();texts.setSpacing(4);header.addLayout(texts,1)
        self.title=QPushButton(title) if self.expandable else label(title)
        self.title.setProperty('role','rowtitle')
        self.title.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred);self.title.setMinimumWidth(0)
        self.title.setToolTip(title)
        self.title.setAccessibleName('Detalhes de '+title if self.expandable else title)
        if self.expandable:self.title.clicked.connect(lambda:self.selected.emit(identifier))
        texts.addWidget(self.title)
        self.subtitle=label('', 'muted');texts.addWidget(self.subtitle)
        if self.expandable:
            self.subtitle.installEventFilter(self);self.icon.installEventFilter(self)
        else:self.icon.hide()
        self.check=QCheckBox(check_text,self);self.check.setVisible(bool(check_text))
        self.check.setAccessibleName(check_text+' — '+title);header.addWidget(self.check)
        self.remove=QToolButton(self);self.remove.setText('×');self.remove.setProperty('role','remove')
        self.remove.setAccessibleName('Remover '+title);self.remove.setToolTip('Remover cadastro de '+title)
        self.remove.setVisible(remove);header.addWidget(self.remove)
        self.body=QWidget();self.body_layout=QVBoxLayout(self.body);self.body_layout.setContentsMargins(44 if self.expandable else 0,0,0,0)
        self.body_layout.setSpacing(9);root.addWidget(self.body);self.body.hide()
        self.info=label('', 'muted');self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.body_layout.addWidget(self.info)
        self.actions=QHBoxLayout();self.actions.setSpacing(8);self.actions.addStretch()
        self.body_layout.addLayout(self.actions)

    def add_action(self,text,callback):
        action=button(text,callback);self.actions.insertWidget(self.actions.count()-1,action);return action

    def expand(self,value):
        self.setProperty('selected',value);self.body.setVisible(value or self.pinned_details)
        self.style().unpolish(self);self.style().polish(self)

    def eventFilter(self,obj,event):
        if event.type()==QEvent.MouseButtonPress:
            self.selected.emit(self.identifier)
            return True
        return super().eventFilter(obj,event)

    def mousePressEvent(self,event):
        if self.expandable:self.selected.emit(self.identifier)
        super().mousePressEvent(event)

    def keyPressEvent(self,event):
        if self.expandable and event.key() in (Qt.Key_Return,Qt.Key_Enter,Qt.Key_Space):
            self.selected.emit(self.identifier);event.accept()
        else:super().keyPressEvent(event)


class BatchReview(QDialog):
    def __init__(self,panel,rows,on_added=None):
        super().__init__(panel);self.panel=panel;self.on_added=on_added
        self.phase='idle';self.cancelled=False
        self.setWindowTitle('Revisar aplicativos');self.resize(660,530);self.setStyleSheet(PANEL_STYLE)
        root=QVBoxLayout(self);root.addWidget(label('Revisar cadastro','title'))
        root.addWidget(label('Confira nomes e apelidos. Aberturas continuarão exigindo confirmação.','muted'))
        area,_,column=scroll_column();root.addWidget(area,1);self.fields=[]
        for row in rows:
            frame=QFrame();frame.setProperty('role','card');box=QVBoxLayout(frame)
            name=QLineEdit(row['name']);name.setAccessibleName('Nome do aplicativo')
            aliases=QLineEdit(', '.join(row.get('aliases',())));aliases.setPlaceholderText('Apelidos separados por vírgula')
            aliases.setAccessibleName('Apelidos de '+row['name'])
            box.addWidget(name);box.addWidget(label(row['path'],'muted'));box.addWidget(aliases)
            column.addWidget(frame);self.fields.append((row,name,aliases))
        self.error=label('', 'notice');self.error.hide();root.addWidget(self.error)
        footer=QHBoxLayout();root.addLayout(footer)
        self.cancel=button('Cancelar',self.reject);footer.addWidget(self.cancel);footer.addStretch()
        self.submit=button('Adicionar aplicativos',self.publish,True);footer.addWidget(self.submit)

    def publish(self):
        if self.phase!='idle':return
        rows=[dict(row,name=name.text(),aliases=tuple(a.strip() for a in aliases.text().split(',') if a.strip()))
            for row,name,aliases in self.fields]
        self.phase='validating';self.cancelled=False
        self.submit.setEnabled(False);self.error.setText('Validando a seleção…');self.error.show()
        for _,name,aliases in self.fields:name.setReadOnly(True);aliases.setReadOnly(True)
        def failed(message):
            self.phase='idle';self.cancel.setEnabled(True)
            if self.cancelled:return
            self.submit.setEnabled(True);self.error.setText(message);self.error.show()
            for _,name,aliases in self.fields:name.setReadOnly(False);aliases.setReadOnly(False)
        def prepared(proposal):
            if self.cancelled:return
            self.phase='publishing';self.cancel.setEnabled(False)
            self.error.setText('Publicando os cadastros. Aguarde a confirmação…')
            def done(apps):
                self.phase='idle'
                self.accept()
                if self.on_added:self.on_added(apps)
            if not self.panel.job(lambda:self.panel.catalog.commit_many(proposal),done,on_error=failed):
                failed('Aguarde a operação atual e tente novamente.')
        if not self.panel.job(lambda:self.panel.catalog.preview_many(rows),prepared,on_error=failed):
            failed('Aguarde a operação atual e tente novamente.')

    def reject(self):
        if self.phase=='publishing':return
        self.cancelled=True;super().reject()

    def closeEvent(self,event):
        if self.phase=='publishing':event.ignore();return
        self.cancelled=True;super().closeEvent(event)


class GalleryTile(QFrame):
    def __init__(self,row,registered,icons,changed):
        super().__init__();self.row=row;self.setProperty('role','card');self.setProperty('chosen',False)
        self.setMinimumWidth(145);box=QVBoxLayout(self);box.setContentsMargins(12,12,12,12)
        top=QHBoxLayout();box.addLayout(top)
        image=QLabel();image.setFixedSize(40,40);icons.fill(image,row['path'],40);top.addWidget(image);top.addStretch()
        self.check=QCheckBox();self.check.setAccessibleName('Selecionar '+row['name'])
        self.check.setEnabled(not registered);top.addWidget(self.check)
        title=label(row['name']);title.setMinimumHeight(38);box.addWidget(title)
        self.caption=label('Já cadastrado' if registered else 'Disponível','muted');box.addWidget(self.caption)
        self.setToolTip(row['path']);self.check.toggled.connect(lambda value:self.toggle(value,changed))
        self.setFocusPolicy(Qt.StrongFocus)
        image.installEventFilter(self);title.installEventFilter(self)

    def toggle(self,value,changed):
        self.setProperty('chosen',value);self.style().unpolish(self);self.style().polish(self);changed()

    def eventFilter(self,obj,event):
        if event.type()==QEvent.MouseButtonPress and self.check.isEnabled():self.check.toggle();return True
        return super().eventFilter(obj,event)

    def mousePressEvent(self,event):
        if self.check.isEnabled():self.check.toggle()
        super().mousePressEvent(event)

    def keyPressEvent(self,event):
        if event.key() in (Qt.Key_Space,Qt.Key_Return) and self.check.isEnabled():self.check.toggle()
        else:super().keyPressEvent(event)


class ApplicationGallery(QDialog):
    def __init__(self,panel,rows):
        super().__init__(panel);self.panel=panel;self.setStyleSheet(PANEL_STYLE)
        self.setWindowTitle('Aplicativos encontrados');self.resize(850,630);self.setMinimumSize(620,440)
        root=QVBoxLayout(self);root.addWidget(label('Aplicativos encontrados','title'))
        root.addWidget(label('Selecione os aplicativos que deseja adicionar ao Therion.','muted'))
        self.search=QLineEdit();self.search.setPlaceholderText('Buscar aplicativo…');root.addWidget(self.search)
        self.area=QScrollArea();self.area.setWidgetResizable(True);root.addWidget(self.area,1)
        self.content=QWidget();self.grid=QGridLayout(self.content);self.grid.setAlignment(Qt.AlignTop)
        self.grid.setSpacing(12);self.area.setWidget(self.content)
        registered={a.identity['path'] for a in panel.catalog.entries()}
        self.tiles=[GalleryTile(row,os.path.normcase(os.path.realpath(row['path'])) in registered,
            panel.icons,self.count_selection) for row in rows]
        self.search.textChanged.connect(self.relayout)
        self.message=label('', 'muted');root.addWidget(self.message)
        footer=QHBoxLayout();root.addLayout(footer)
        self.count=label();footer.addWidget(self.count);footer.addStretch()
        footer.addWidget(button('Fechar',self.reject))
        self.review=button('Revisar seleção',self.review_selection,True);footer.addWidget(self.review)
        self.count_selection();self.relayout()

    def count_selection(self):
        count=sum(tile.check.isChecked() for tile in self.tiles) if hasattr(self,'tiles') else 0
        if hasattr(self,'count'):self.count.setText(f'{count} selecionado(s)');self.review.setEnabled(count>0)

    def relayout(self):
        from therion.context.language import control
        query=control(self.search.text());visible=[]
        while self.grid.count():self.grid.takeAt(0)
        for tile in self.tiles:
            show=query in control(tile.row['name']);tile.setVisible(show)
            if show:visible.append(tile)
        columns=max(2,min(5,self.area.viewport().width()//175))
        for i,tile in enumerate(visible):self.grid.addWidget(tile,i//columns,i%columns)
        if hasattr(self,'message'):
            if not visible:self.message.setText('Nenhum aplicativo corresponde à busca.')
            elif self.message.text()=='Nenhum aplicativo corresponde à busca.':self.message.clear()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'tiles'):self.relayout()

    def review_selection(self):
        rows=[tile.row for tile in self.tiles if tile.check.isChecked()]
        if not rows:return
        self.review_dialog=BatchReview(self.panel,rows,self.added)
        self.review_dialog.setWindowModality(Qt.WindowModal);self.review_dialog.show()

    def added(self,apps):
        paths={app.identity['path'] for app in apps}
        for tile in self.tiles:
            if os.path.normcase(os.path.realpath(tile.row['path'])) in paths:
                tile.check.setChecked(False);tile.check.setEnabled(False)
                tile.caption.setText('Já cadastrado')
                tile.setToolTip(tile.row['path']+' — já cadastrado')
        self.message.setText(f'{len(apps)} aplicativo(s) adicionado(s). Nenhuma autonomia foi concedida.')
        self.count_selection()
