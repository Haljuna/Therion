"""Diálogos com os mesmos contratos Qt, apresentados dentro da cena ativa."""
from PySide6.QtCore import Qt,QEventLoop,QSize,QRect,QPoint,QObject
from PySide6.QtWidgets import (QDialog as NativeDialog,QMessageBox as NativeMessageBox,
    QInputDialog as NativeInputDialog,QFileDialog as NativeFileDialog,QLineEdit,
    QWidget,QScrollArea,QPushButton,QApplication)
from PySide6.QtGui import QPixmap,QPainter,QPen,QColor,QFont,QShortcut
from shiboken6 import isValid
from .workspace import ScenePanel


SURFACE_STYLE='''
QDialog, QMessageBox, QInputDialog, QFileDialog { background:transparent; color:#F1F0F7; }
QWidget { color:#F1F0F7; font-family:"Segoe UI"; font-size:13px; }
QLabel { background:transparent; }
QLabel[role="title"] { font-size:17px; font-weight:500; color:#F1F0F7; }
QLabel[role="muted"] { color:#B5B1C5; }
QLabel[role="section"], QLabel[role="rowtitle"] { font-size:14px; font-weight:500; }
QLabel[role="notice"] { color:#BFABEF; background:rgba(60,27,140,28); border-radius:8px; padding:10px; }
QFrame[role="card"] { background:rgba(20,19,30,184); border:1px solid rgba(255,255,255,23); border-radius:14px; }
QFrame[role="card"][selected="true"], QFrame[role="card"][chosen="true"] { border-color:#7045D9; background:rgba(41,19,97,75); }
QPushButton, QToolButton { background:rgba(30,19,56,90); border:1px solid rgba(103,66,192,95); border-radius:10px; padding:6px 12px; color:#F1F0F7; }
QPushButton:hover, QToolButton:hover { background:rgba(56,25,132,80); border-color:#794FDE; }
QPushButton:focus, QToolButton:focus, QLineEdit:focus, QCheckBox:focus, QComboBox:focus { border:1px solid #8964E2; }
QPushButton:disabled, QToolButton:disabled { color:#756C60; border-color:rgba(90,75,126,40); }
QPushButton[primary="true"] { background:#6231D8; color:#09090F; font-weight:600; }
QPushButton[role="rowtitle"] { text-align:left; background:transparent; border:0; padding:2px; font-size:14px; }
QToolButton[role="remove"] { background:transparent; border:0; font-size:17px; padding:2px 9px; }
QCheckBox { background:transparent; spacing:9px; padding:5px 2px; }
QCheckBox::indicator { width:16px; height:16px; border:1px solid #5C498C; border-radius:4px; background:rgba(9,9,15,160); }
QCheckBox::indicator:checked { background:#7045D9; border-color:#BFABEF; image:url("__CHECK_ICON__"); }
QLineEdit, QTimeEdit, QSpinBox, QDoubleSpinBox, QComboBox { background:rgba(9,9,15,170); border:1px solid rgba(88,57,164,100); border-radius:7px; padding:7px; }
QComboBox QAbstractItemView { background:#09090F; color:#F1F0F7; selection-background-color:#281653; }
QTextEdit, QPlainTextEdit, QListWidget, QTreeView, QListView { background:rgba(9,9,15,90); border:1px solid rgba(88,57,164,55); border-radius:8px; padding:7px; selection-background-color:#2A1855; }
QTabWidget::pane { border:0; background:transparent; }
QTabBar::tab { background:transparent; color:#B5B1C5; padding:11px 18px; border-bottom:1px solid transparent; }
QTabBar::tab:selected { color:#BFABEF; border-bottom:2px solid #8059DF; }
QTabBar::tab:hover { color:#F1F0F7; background:rgba(55,26,126,30); }
QListWidget#navigation { background:transparent; border:0; }
QListWidget#navigation::item { padding:12px 10px; border-left:1px solid transparent; }
QListWidget#navigation::item:selected { color:#BFABEF; background:rgba(55,26,126,35); border-left:1px solid #8059DF; }
QScrollArea, QScrollArea>QWidget>QWidget, QStackedWidget { background:transparent; border:0; }
QScrollBar:vertical { background:transparent; width:7px; }
QScrollBar:horizontal { background:transparent; height:7px; }
QScrollBar::handle { background:rgba(84,49,170,135); border-radius:3px; min-width:22px; min-height:22px; }
QScrollBar::add-line, QScrollBar::sub-line { width:0; height:0; }
QScrollBar::add-page, QScrollBar::sub-page { background:transparent; }
QMenu, QToolTip { background:#09090F; color:#F1F0F7; border:1px solid #3A266C; }
'''
from pathlib import Path
SURFACE_STYLE=SURFACE_STYLE.replace('__CHECK_ICON__',Path(__file__).with_name('autonomy_check.svg').as_posix())
from .design_system import COMPONENT_STYLE
SURFACE_STYLE += COMPONENT_STYLE


def dashboard_for(widget):
    while isinstance(widget,QWidget):
        dashboard=getattr(widget,'_surface_dashboard',None) or getattr(widget,'_dashboard',None)
        if dashboard is not None and dashboard.active:return dashboard
        widget=widget.parentWidget()
    return None


def exec_in_scene(dialog):
    dashboard=dashboard_for(dialog)
    return dashboard.surfaces.exec(dialog) if dashboard is not None else None


class Dialog(NativeDialog):
    def exec(self):
        result=exec_in_scene(self)
        return super().exec() if result is None else result


class MessageBox(NativeMessageBox):
    def exec(self):
        result=exec_in_scene(self)
        return super().exec() if result is None else result

    @classmethod
    def _message(cls,icon,parent,title,text,buttons,default):
        if dashboard_for(parent) is None:
            method={cls.Information:'information',cls.Warning:'warning',cls.Critical:'critical',cls.Question:'question'}[icon]
            return getattr(NativeMessageBox,method)(parent,title,text,buttons,default)
        box=cls(icon,title,text,buttons,parent)
        if default!=cls.NoButton:box.setDefaultButton(default)
        return cls.StandardButton(box.exec())

    @classmethod
    def information(cls,parent,title,text,buttons=NativeMessageBox.Ok,defaultButton=NativeMessageBox.NoButton):
        return cls._message(cls.Information,parent,title,text,buttons,defaultButton)

    @classmethod
    def warning(cls,parent,title,text,buttons=NativeMessageBox.Ok,defaultButton=NativeMessageBox.NoButton):
        return cls._message(cls.Warning,parent,title,text,buttons,defaultButton)

    @classmethod
    def critical(cls,parent,title,text,buttons=NativeMessageBox.Ok,defaultButton=NativeMessageBox.NoButton):
        return cls._message(cls.Critical,parent,title,text,buttons,defaultButton)

    @classmethod
    def question(cls,parent,title,text,buttons=NativeMessageBox.Yes|NativeMessageBox.No,defaultButton=NativeMessageBox.NoButton):
        if defaultButton==cls.NoButton:defaultButton=cls.No
        return cls._message(cls.Question,parent,title,text,buttons,defaultButton)


class InputDialog(NativeInputDialog):
    def exec(self):
        result=exec_in_scene(self)
        return super().exec() if result is None else result

    @classmethod
    def getText(cls,parent,title,label,echo=QLineEdit.Normal,text='',**kwargs):
        if dashboard_for(parent) is None:return NativeInputDialog.getText(parent,title,label,echo,text,**kwargs)
        dialog=cls(parent);dialog.setWindowTitle(title);dialog.setLabelText(label)
        dialog.setTextEchoMode(echo);dialog.setTextValue(text)
        result=dialog.exec()
        return dialog.textValue(),result==cls.Accepted

    @classmethod
    def getItem(cls,parent,title,label,items,current=0,editable=True,**kwargs):
        if dashboard_for(parent) is None:return NativeInputDialog.getItem(parent,title,label,items,current,editable,**kwargs)
        dialog=cls(parent);dialog.setWindowTitle(title);dialog.setLabelText(label)
        dialog.setComboBoxItems(items);dialog.setComboBoxEditable(editable)
        if items:dialog.setTextValue(items[max(0,min(current,len(items)-1))])
        result=dialog.exec()
        return dialog.textValue(),result==cls.Accepted


class FileDialog(NativeFileDialog):
    def exec(self):
        result=exec_in_scene(self)
        return super().exec() if result is None else result

    @classmethod
    def _choose(cls,parent,caption,directory,filters,mode,accept,selectedFilter='',options=NativeFileDialog.Options()):
        dialog=cls(parent,caption,directory,filters)
        dialog.setOptions(options|cls.DontUseNativeDialog);dialog.setFileMode(mode);dialog.setAcceptMode(accept)
        if accept==cls.AcceptSave:dialog.setOption(cls.DontConfirmOverwrite,True)
        if selectedFilter:dialog.selectNameFilter(selectedFilter)
        result=dialog.exec()
        return (dialog.selectedFiles(),dialog.selectedNameFilter()) if result==cls.Accepted else ([], '')

    def accept(self):
        if dashboard_for(self) is not None and self.acceptMode()==NativeFileDialog.AcceptMode.AcceptSave:
            files=self.selectedFiles()
            if files and Path(files[0]).exists():
                if MessageBox.question(self,'Substituir arquivo','Este arquivo já existe. Deseja substituí-lo?')!=MessageBox.Yes:return
        super().accept()

    @classmethod
    def getOpenFileName(cls,parent=None,caption='',dir='',filter='',selectedFilter='',options=NativeFileDialog.Options()):
        if dashboard_for(parent) is None:return NativeFileDialog.getOpenFileName(parent,caption,dir,filter,selectedFilter,options)
        rows,chosen=cls._choose(parent,caption,dir,filter,cls.ExistingFile,cls.AcceptOpen,selectedFilter,options)
        return (rows[0] if rows else ''),chosen

    @classmethod
    def getOpenFileNames(cls,parent=None,caption='',dir='',filter='',selectedFilter='',options=NativeFileDialog.Options()):
        if dashboard_for(parent) is None:return NativeFileDialog.getOpenFileNames(parent,caption,dir,filter,selectedFilter,options)
        return cls._choose(parent,caption,dir,filter,cls.ExistingFiles,cls.AcceptOpen,selectedFilter,options)

    @classmethod
    def getSaveFileName(cls,parent=None,caption='',dir='',filter='',selectedFilter='',options=NativeFileDialog.Options()):
        if dashboard_for(parent) is None:return NativeFileDialog.getSaveFileName(parent,caption,dir,filter,selectedFilter,options)
        rows,chosen=cls._choose(parent,caption,dir,filter,cls.AnyFile,cls.AcceptSave,selectedFilter,options)
        return (rows[0] if rows else ''),chosen

    @classmethod
    def getExistingDirectory(cls,parent=None,caption='',dir='',options=NativeFileDialog.ShowDirsOnly):
        if dashboard_for(parent) is None:return NativeFileDialog.getExistingDirectory(parent,caption,dir,options)
        rows,_=cls._choose(parent,caption,dir,'',cls.Directory,cls.AcceptOpen,options=options)
        return rows[0] if rows else ''


class SurfaceHost(QObject):
    """Reutiliza conteúdo real, sem iniciar serviços nem duplicar donos da sessão."""
    def __init__(self,dashboard):
        super().__init__(dashboard);self.dashboard=dashboard;self.views={};self.modals=[]

    def _embed(self,view):
        view._surface_dashboard=self.dashboard
        view.setWindowFlags(Qt.Widget);view.setWindowModality(Qt.NonModal)
        view.setStyleSheet(SURFACE_STYLE)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet('background:transparent;border:0;')
        scroll.setWidget(view)
        return scroll

    def open(self,key,title,factory,preferred=QSize(850,650)):
        if key not in self.views:
            view=factory();scroll=self._embed(view)
            panel=self.dashboard.workspace.register(key,title,scroll,preferred)
            view.finished.connect(lambda result:panel.dismiss())
            self.views[key]=view
        view=self.views[key];view.show()
        self.dashboard.workspace.open(key)
        return view

    def exec(self,dialog):
        dashboard=self.dashboard;parent=dialog.parentWidget();flags=dialog.windowFlags();style=dialog.styleSheet()
        previous_focus=QApplication.focusWidget()
        compact=isinstance(dialog,(NativeMessageBox,NativeInputDialog))
        if isinstance(dialog,NativeMessageBox):
            for standard,text in [(NativeMessageBox.Yes,'Confirmar'),(NativeMessageBox.No,'Cancelar'),
                    (NativeMessageBox.Ok,'Entendi'),(NativeMessageBox.Cancel,'Cancelar'),
                    (NativeMessageBox.Close,'Fechar'),(NativeMessageBox.Save,'Salvar'),
                    (NativeMessageBox.Discard,'Descartar'),(NativeMessageBox.Retry,'Tentar novamente')]:
                button=dialog.button(standard)
                if button is not None:button.setText(text)
            if dialog.icon()!=NativeMessageBox.NoIcon:
                badge=QPixmap(32,32);badge.fill(Qt.transparent)
                painter=QPainter(badge);painter.setRenderHint(QPainter.Antialiasing)
                color='#FCA5A5' if dialog.icon()==NativeMessageBox.Critical else '#FCD34D' if dialog.icon()==NativeMessageBox.Warning else '#C4B5FD'
                painter.setPen(QPen(QColor(color),1.3));painter.drawEllipse(3,3,26,26)
                painter.setFont(QFont('Segoe UI',16));painter.drawText(badge.rect(),Qt.AlignCenter,
                    '?' if dialog.icon()==NativeMessageBox.Question else ('!' if dialog.icon() in (NativeMessageBox.Warning,NativeMessageBox.Critical) else 'i'))
                painter.end();dialog.setIconPixmap(badge)
        if isinstance(dialog,NativeInputDialog):
            dialog.setOkButtonText('Confirmar');dialog.setCancelButtonText('Cancelar')
        # Uma camada bloqueia cliques fora da confirmação, sem criar janela nativa.
        layer=QWidget(dashboard);layer.setGeometry(dashboard.rect())
        layer.setObjectName('internalModalLayer')
        layer.setAttribute(Qt.WA_StyledBackground)
        layer.setStyleSheet('#internalModalLayer { background:rgba(9,9,15,85); }')
        scroll=self._embed(dialog)
        panel=ScenePanel('internal-dialog',dialog.windowTitle() or 'Therion',scroll,layer,
                         lambda:layer.rect().adjusted(16,16,-16,-16))
        requested=dialog.sizeHint() if compact else dialog.sizeHint().expandedTo(dialog.size())
        width=min(max(480,requested.width()+24),dashboard.width()-32)
        height=min(max(240 if compact else 260,requested.height()+76),dashboard.height()-32)
        for button in panel.title_bar.findChildren(QPushButton):
            if button.text()=='−' or (compact and button.text()=='□'):button.hide()
        panel.place(QRect(QPoint((dashboard.width()-width)//2,(dashboard.height()-height)//2),QSize(width,height)))
        panel.dismissed.connect(lambda key:dialog.reject())
        loop=QEventLoop();dialog.finished.connect(loop.quit)
        frozen=[(widget,widget.isEnabled()) for widget in dashboard.findChildren(QWidget,options=Qt.FindDirectChildrenOnly)
                if widget is not layer and widget is not dashboard.constellation]
        shortcuts=[(item,item.isEnabled()) for item in dashboard.window.findChildren(QShortcut)
                   if not isinstance(item.parent(),QWidget) or not layer.isAncestorOf(item.parent())]
        for widget,_ in frozen:widget.setEnabled(False)
        for item,_ in shortcuts:item.setEnabled(False)
        self.modals.append((dialog,layer,loop))
        layer.show();panel.show();dialog.show();layer.raise_();dialog.setFocus()
        try:
            loop.exec()
            return dialog.result()
        finally:
            dialog.finished.disconnect(loop.quit)
            self.modals.remove((dialog,layer,loop))
            dialog.hide();scroll.takeWidget();dialog.setParent(parent,flags);dialog.setStyleSheet(style)
            layer.hide();layer.deleteLater()
            for widget,enabled in frozen:
                if isValid(widget):widget.setEnabled(enabled)
            for item,enabled in shortcuts:
                if isValid(item):item.setEnabled(enabled)
            if previous_focus is not None and isValid(previous_focus) and previous_focus.isVisible() and previous_focus.isEnabled():
                previous_focus.setFocus(Qt.OtherFocusReason)

    def reflow(self):
        for dialog,layer,loop in self.modals:
            layer.setGeometry(self.dashboard.rect());layer.raise_()
            for panel in layer.findChildren(ScenePanel):panel.place(panel.geometry())

    @property
    def busy(self):return bool(self.modals) or any(bool(getattr(v,'busy',False)) for v in self.views.values())

    def cancel(self):
        for dialog,layer,loop in self.modals[:]:dialog.reject()
        for view in self.views.values():
            cancel=getattr(view,'cancel_operations',None)
            if callable(cancel):cancel()
