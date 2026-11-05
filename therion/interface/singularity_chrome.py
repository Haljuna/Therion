"""Acabamento vetorial da Singularidade; preserva os widgets e seus sinais."""
import math
from .design_system import COLORS
from PySide6.QtCore import QObject,QEvent,QRectF,QSize,Qt,QPointF
from PySide6.QtGui import QColor,QPainter,QPen,QRadialGradient,QFont
from PySide6.QtWidgets import QWidget,QToolButton,QToolTip,QStyledItemDelegate,QStyle
from PySide6.QtSvg import QSvgRenderer


class OrbBrand(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent);self.setFixedSize(48,48)
        self.setAccessibleName('Símbolo do Therion')

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        for i in range(21):
            angle=i*2.39996;radius=3.+math.sqrt(i)*3.5
            x,y=24+math.cos(angle)*radius,24+math.sin(angle)*radius
            color=QColor(COLORS['accent']);color.setAlpha(100+i*7)
            p.setBrush(color);p.drawEllipse(QRectF(x-1.2,y-1.2,2.4,2.4))
        p.setBrush(QColor(COLORS['text']));p.drawEllipse(QRectF(21.5,21.5,5,5))


class OrbShortcut(QToolButton):
    def paintEvent(self,event):
        super().paintEvent(event)
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing)
        glow=QRadialGradient(self.width()-5,7,4)
        glow.setColorAt(0,QColor(145,111,228,190 if self.isChecked() else 100));glow.setColorAt(1,QColor(107,62,218,0))
        p.setPen(Qt.NoPen);p.setBrush(glow);p.drawEllipse(QRectF(self.width()-9,3,8,8))
        p.setBrush(QColor('#AD93EB' if self.isChecked() else '#5C38B5'))
        p.drawEllipse(QRectF(self.width()-7,5,4,4))


class GlyphSkin(QObject):
    """Pinta o botão original, sem interceptar clique, pressão ou teclado."""
    def __init__(self,button,path,*,send=False):
        super().__init__(button);self.button=button;self.path=path;self.send=send
        self.original=(button.minimumSize(),button.maximumSize(),button.sizePolicy())
        button.setFixedSize(32,32)
        button.installEventFilter(self)

    def detach(self):
        self.button.removeEventFilter(self)
        minimum,maximum,policy=self.original
        self.button.setMinimumSize(minimum);self.button.setMaximumSize(maximum);self.button.setSizePolicy(policy)
        self.deleteLater()

    def eventFilter(self,widget,event):
        if event.type()==QEvent.ToolTip:
            QToolTip.showText(event.globalPos(),widget.text() or widget.accessibleName(),widget);return True
        if event.type()!=QEvent.Paint:return False
        p=QPainter(widget);p.setRenderHint(QPainter.Antialiasing)
        if not widget.isEnabled():p.setOpacity(.48)
        rect=QRectF(widget.rect()).adjusted(1,1,-1,-1)
        if self.send:
            halo=QRadialGradient(rect.center(),rect.width()/2)
            halo.setColorAt(0,QColor(117,74,221,12));halo.setColorAt(.8,QColor(120,79,221,28));halo.setColorAt(1,QColor(120,79,221,0))
            p.setBrush(halo);p.setPen(Qt.NoPen);p.drawEllipse(rect.adjusted(-3,-3,3,3))
            p.setPen(QPen(QColor('#B7A1ED' if widget.underMouse() else '#815AE0'),1.1))
            p.setBrush(QColor(COLORS['accent']));p.drawRoundedRect(rect,11,11)
        elif widget.underMouse() or widget.hasFocus():
            p.setPen(QPen(QColor('#583C9B'),1));p.setBrush(QColor(29,18,55,100));p.drawEllipse(rect)
        if widget.hasFocus():
            p.setPen(QPen(QColor('#B7A1ED'),1,Qt.DashLine));p.setBrush(Qt.NoBrush);p.drawEllipse(rect.adjusted(-2,-2,2,2))
        color=('#14131E' if self.send else '#CABAF2') if not widget.isDown() else '#F1F0F7'
        svg=('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="'+self.path+'" fill="none" stroke="'+color+'" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>')
        target=QRectF(widget.width()/2-10,widget.height()/2-10,20,20)
        QSvgRenderer(svg.encode()).render(p,target)
        return True


class AgendaDelegate(QStyledItemDelegate):
    def sizeHint(self,option,index):
        return QSize(240,46) if isinstance(index.data(Qt.UserRole),dict) else super().sizeHint(option,index)

    def paint(self,painter,option,index):
        row=index.data(Qt.UserRole)
        if not isinstance(row,dict):return super().paint(painter,option,index)
        painter.save();painter.setRenderHint(QPainter.Antialiasing)
        rect=option.rect;mid=rect.center().y()
        if option.state & QStyle.State_Selected:painter.fillRect(rect,QColor(56,28,123,36))
        painter.setPen(QPen(QColor(83,49,166,60),1));painter.drawLine(rect.x()+8,rect.top(),rect.x()+8,rect.bottom())
        painter.setBrush(QColor('#9D7FE7'));painter.setPen(Qt.NoPen);painter.drawEllipse(QRectF(rect.x()+4.5,mid-3.5,7,7))
        font=QFont('Segoe UI',10);painter.setFont(font);painter.setPen(QColor('#9271E4'))
        painter.drawText(rect.adjusted(28,0,0,0),Qt.AlignVCenter,str(row['time']))
        painter.setPen(QColor('#F1F0F7'))
        text=painter.fontMetrics().elidedText(str(row['title']),Qt.ElideRight,max(0,rect.width()-114))
        painter.drawText(rect.adjusted(104,0,-4,0),Qt.AlignVCenter,text)
        painter.setPen(QPen(QColor(91,65,155,28),1));painter.drawLine(rect.x()+28,rect.bottom(),rect.right(),rect.bottom())
        painter.restore()


class TaskDelegate(QStyledItemDelegate):
    """Controle de conclusão na linha; a ação continua passando pelo orquestrador."""
    def __init__(self,listing,callback):
        super().__init__(listing);self.listing=listing;self.callback=callback

    def sizeHint(self,option,index):return QSize(240,52)

    def paint(self,painter,option,index):
        row=index.data(Qt.UserRole)
        if not isinstance(row,dict):return super().paint(painter,option,index)
        painter.save();painter.setRenderHint(QPainter.Antialiasing);rect=option.rect
        done=row.get('state')=='completed' or row.get('completed') is True
        if option.state & QStyle.State_Selected:painter.fillRect(rect,QColor('#201930'))
        check=QRectF(rect.x()+8,rect.center().y()-8,16,16)
        painter.setPen(QPen(QColor('#7155B5' if done else '#9C9387'),1.2))
        painter.setBrush(QColor('#32205D') if done else Qt.NoBrush);painter.drawRoundedRect(check,4,4)
        if done:
            painter.setPen(QPen(QColor('#BCA8EE'),1.5));painter.drawLine(check.topLeft()+QPointF(3,8),check.topLeft()+QPointF(7,12))
            painter.drawLine(check.topLeft()+QPointF(7,12),check.topLeft()+QPointF(13,4))
        font=QFont(option.font);font.setPixelSize(14);font.setStrikeOut(done);painter.setFont(font)
        painter.setPen(QColor('#B5B1C5' if done else '#F1F0F7'))
        title=painter.fontMetrics().elidedText(row['title'],Qt.ElideRight,max(0,rect.width()-48))
        painter.drawText(rect.adjusted(38,0,-8,0),Qt.AlignVCenter,title)
        painter.setPen(QPen(QColor('#25202F'),1));painter.drawLine(rect.left()+8,rect.bottom(),rect.right()-8,rect.bottom());painter.restore()

    def editorEvent(self,event,model,option,index):
        click=event.type()==QEvent.MouseButtonRelease and event.button()==Qt.LeftButton and event.position().x()<option.rect.left()+34
        key=event.type()==QEvent.KeyPress and event.key()==Qt.Key_Space
        if (click or key) and isinstance(index.data(Qt.UserRole),dict):
            self.callback(self.listing.item(index.row()));return True
        return super().editorEvent(event,model,option,index)
