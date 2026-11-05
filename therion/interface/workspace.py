"""Painéis organizados sobre a cena do Therion, independentes de serviços pessoais.

Novas superfícies (por exemplo, uma caixa de entrada) registram um QWidget.
Abrir ou recolher um painel não executa ações no serviço correspondente.
"""
from PySide6.QtCore import Qt, QObject, Signal, QEvent, QPoint, QRect, QSize
from PySide6.QtGui import QShortcut, QKeySequence, QPainter, QPen, QColor
from PySide6.QtWidgets import QFrame, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout
from .design_system import PANEL_STYLE


class _TitleBar(QFrame):
    def __init__(self, panel, title):
        super().__init__(panel)
        self.panel=panel
        self.origin=None
        self.setObjectName('panelTitleBar')
        self.setToolTip('Arraste pelo título para mover o painel. Use Organizar para restaurar o layout.')
        self.setCursor(Qt.OpenHandCursor)
        row=QHBoxLayout(self); row.setContentsMargins(16,8,10,8); row.setSpacing(8)
        text=QLabel(title); text.setObjectName('panelTitle');self.label=text
        text.setAttribute(Qt.WA_TransparentForMouseEvents)
        row.addWidget(text); row.addStretch()
        self.controls={}
        for key,glyph,name,hint,callback in [
                ('minimize','–','Recolher','Recolher para o menu · Ctrl+Tab reabre',panel.minimize),
                ('close','×','Fechar','Fechar · o conteúdo da sessão é mantido (Esc)',panel.dismiss)]:
            control=QPushButton(glyph)
            control.setObjectName('panelWindowControl'); control.setFixedSize(36,36)
            control.setAccessibleName(name+' '+title)
            control.setToolTip(hint)
            control.clicked.connect(callback)
            row.addWidget(control);self.controls[key]=control

    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton:
            self.panel.manually_placed=True
            self.panel.activated.emit(self.panel.key)
            self.origin=(event.globalPosition().toPoint(),QRect(self.panel.geometry()))
            self.setCursor(Qt.ClosedHandCursor);event.accept()
        else:super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        if self.origin is None:return super().mouseMoveEvent(event)
        point,geometry=self.origin
        moved=QRect(geometry);moved.moveTopLeft(geometry.topLeft()+event.globalPosition().toPoint()-point)
        self.panel.place(moved,manual=True);event.accept()

    def mouseReleaseEvent(self,event):
        if self.origin is None:return super().mouseReleaseEvent(event)
        self.origin=None;self.setCursor(Qt.OpenHandCursor)
        self.panel.settled.emit(self.panel.key);event.accept()


class _ResizeHandle(QWidget):
    def __init__(self,panel):
        super().__init__(panel);self.panel=panel;self.origin=None
        self.setFixedSize(24,20);self.setCursor(Qt.SizeFDiagCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName('Redimensionar '+panel.title)
        self.setToolTip('Arraste para redimensionar · setas ajustam o tamanho pelo teclado')

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor('#C4B5FD' if self.hasFocus() else '#A78BFA'),1.5))
        for offset in (4,9,14):p.drawLine(20-offset,16,20,16-offset)

    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton:
            self.panel.manually_placed=True
            self.panel.activated.emit(self.panel.key)
            self.origin=(event.globalPosition().toPoint(),QRect(self.panel.geometry()));event.accept()

    def mouseMoveEvent(self,event):
        if self.origin is None:return super().mouseMoveEvent(event)
        point,geometry=self.origin;delta=event.globalPosition().toPoint()-point
        resized=QRect(geometry);resized.setSize(QSize(geometry.width()+delta.x(),geometry.height()+delta.y()))
        self.panel.place(resized,manual=True);event.accept()

    def mouseReleaseEvent(self,event):
        if self.origin is not None:
            self.origin=None;self.panel.settled.emit(self.panel.key);event.accept()

    def keyPressEvent(self,event):
        deltas={Qt.Key_Left:(-16,0),Qt.Key_Right:(16,0),Qt.Key_Up:(0,-16),Qt.Key_Down:(0,16)}
        if event.key() not in deltas:return super().keyPressEvent(event)
        x,y=deltas[event.key()];rect=QRect(self.panel.geometry())
        rect.setSize(QSize(rect.width()+x,rect.height()+y))
        self.panel.place(rect,manual=True);self.panel.settled.emit(self.panel.key);event.accept()


class ScenePanel(QFrame):
    activated=Signal(str)
    dismissed=Signal(str)
    settled=Signal(str)

    def __init__(self,key,title,content,parent,bounds):
        super().__init__(parent)
        self.key,self.title,self.content,self.bounds=key,title,content,bounds
        self.positioned=False
        self.manually_placed=False
        self.window_state='closed';self.restore_rect=None
        self.setObjectName('workspacePanel')
        self.setMinimumSize(300,240)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName('Painel: '+title)
        self.setStyleSheet(PANEL_STYLE)
        layout=QVBoxLayout(self); layout.setContentsMargins(0,0,0,3); layout.setSpacing(0)
        self.title_bar=_TitleBar(self,title); layout.addWidget(self.title_bar)
        content.setParent(self); layout.addWidget(content,1)
        content.show()
        self.resize_handle=_ResizeHandle(self)
        self.escape=QShortcut(QKeySequence('Esc'),self)
        self.escape.setContext(Qt.WidgetWithChildrenShortcut)
        self.escape.activated.connect(self.dismiss)
        for child in [content,*content.findChildren(QWidget)]: child.installEventFilter(self)
        self.hide()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'resize_handle'):
            self.resize_handle.move(self.width()-28,self.height()-22)
            self.resize_handle.raise_()

    def eventFilter(self,watched,event):
        # Keyboard focus in the main content must not dismiss its detail pane.
        return super().eventFilter(watched,event)

    def place(self,geometry,*,manual=False):
        limits=self.bounds()
        width=min(max(300,geometry.width()),max(300,limits.width()))
        height=min(max(240,geometry.height()),max(240,limits.height()))
        x=max(limits.left(),min(geometry.x(),limits.right()-width+1))
        y=max(limits.top(),min(geometry.y(),limits.bottom()-height+1))
        self.setGeometry(x,y,width,height)
        self.positioned=True
        self.manually_placed=self.manually_placed or manual

    def dismiss(self):
        self.window_state='closed'
        self.hide(); self.dismissed.emit(self.key)

    def minimize(self):
        self.window_state='minimized';self.hide();self.dismissed.emit(self.key)



class SceneWorkspace(QObject):
    """Registro reutilizável de janelas; uma única instância por chave."""
    changed=Signal(str)

    def __init__(self,parent,bounds,opening_bounds=None):
        super().__init__(parent)
        self.host,self.bounds=parent,bounds
        self.opening_bounds=opening_bounds or bounds
        self.panels={}; self.preferred={}; self.order=[];self.anchors={}
        self.origins={};self._return_to={};self._primary='';self._reflowing=False
        self.primary_keys={'conversations','calendar','tasks','knowledge','tools','settings','mail'}
        self.cycle_shortcut=QShortcut(QKeySequence('Ctrl+Tab'),parent)
        self.cycle_shortcut.activated.connect(self.cycle)
        self.close_shortcut=QShortcut(QKeySequence('Ctrl+W'),parent)
        self.close_shortcut.activated.connect(lambda:self.panels[self.order[-1]].dismiss() if self.order else None)

    def cycle(self):
        keys=[key for key,panel in self.panels.items() if panel.window_state!='closed']
        if not keys:return
        current=self.order[-1] if self.order else ''
        self.open(keys[(keys.index(current)+1)%len(keys)] if current in keys else keys[0])

    def register(self,key,title,content,preferred=QSize(560,480),anchor='top',bounds=None):
        if key in self.panels: raise ValueError('Esta janela já está registrada.')
        panel=ScenePanel(key,title,content,self.host,self.bounds)
        panel.activated.connect(self.activate)
        panel.dismissed.connect(self._dismissed)
        panel.settled.connect(lambda item:self.changed.emit(item))
        self.panels[key]=panel; self.preferred[key]=QSize(preferred)
        self.anchors[key]=anchor
        self.origins[key]=bounds or self.opening_bounds
        return panel

    def open(self,key,*,restore=False):
        panel=self.panels[key]
        free=any(p.manually_placed for p in self.panels.values() if not p.isHidden())
        if free:
            if not panel.positioned:
                area=self.opening_bounds();size=self.preferred[key]
                width=min(size.width(),area.width());height=min(size.height(),area.height())
                offset=min(24*len(self.visible_keys()),72)
                panel.place(QRect(area.x()+offset,area.y()+offset,width,height))
            panel.window_state='open';panel.show();self.activate(key)
            self.reflow();panel.setFocus(Qt.OtherFocusReason)
            return panel
        if panel.window_state=='open' and not panel.isHidden():
            self.reflow()
            return panel
        if not restore:self._return_to.pop(key,None)
        previous=self.order[-1] if self.order else ''
        if not restore and key not in self.primary_keys and previous and previous!=key:
            self._return_to[key]=previous
            self._primary=previous
        else:
            self._primary=key
        for other in self.visible_keys():
            self.panels[other].window_state='minimized';self.panels[other].hide()
        self.order=[]
        panel.window_state='open';panel.show()
        self.activate(key);self.reflow();panel.setFocus(Qt.OtherFocusReason)
        return panel

    def toggle(self,key):
        panel=self.panels[key]
        if not panel.isHidden(): panel.dismiss()
        else: self.open(key)

    def activate(self,key):
        if key not in self.panels: return
        for item,panel in self.panels.items():
            active=item==key
            if panel.property('active')!=active:
                panel.setProperty('active',active);panel.style().unpolish(panel);panel.style().polish(panel)
        self.order=[item for item in self.order if item!=key]+[key]
        self.panels[key].raise_(); self.changed.emit(key)

    def _dismissed(self,key):
        previous=self._return_to.pop(key,'')
        self.order=[item for item in self.order if item!=key]
        if previous and previous in self.panels and self.panels[previous].window_state!='closed':
            self.open(previous,restore=True)
        else:
            self.changed.emit(self.order[-1] if self.order else '')

    def visible_keys(self):
        return [key for key,panel in self.panels.items() if not panel.isHidden()]

    def hide_all(self):
        for panel in self.panels.values():
            if panel.window_state=='open':panel.window_state='minimized'
            panel.hide()
        self.order.clear(); self.changed.emit('')

    def organize(self,keys=None):
        keys=list(keys or self.visible_keys())
        if not keys:return
        for panel in self.panels.values():panel.manually_placed=False
        # At most one main panel plus one detail; navigation retains all content.
        primary='mail' if 'mail' in keys else keys[0]
        self.hide_all();self.open(primary)
        if len(keys)>1:
            detail=next(key for key in keys if key!=primary)
            self._return_to[detail]=primary
            self.panels[detail].window_state='open';self.panels[detail].show()
            self.activate(detail);self.reflow()

    def reflow(self):
        if self._reflowing:return
        self._reflowing=True
        try:
            keys=[key for key in self.order if self.panels[key].window_state=='open']
            if not keys:return
            if any(panel.manually_placed for panel in self.panels.values() if not panel.isHidden()):
                for panel in self.panels.values():
                    if not panel.isHidden():panel.place(panel.geometry())
                return
            area=self.opening_bounds();active=keys[-1]
            previous=self._return_to.get(active,'')
            split=bool(previous in self.panels and self.host.width()>=1000 and area.width()>=860)
            for key,panel in self.panels.items():
                panel.setVisible(key==active or (split and key==previous))
            if split:
                side=max(340,round(area.width()*.38));gap=16
                self.panels[previous].place(QRect(area.x(),area.y(),area.width()-side-gap,area.height()))
                self.panels[active].place(QRect(area.right()-side+1,area.y(),side,area.height()))
            else:self.panels[active].place(area)
        finally:self._reflowing=False
