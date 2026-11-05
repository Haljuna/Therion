"""Sistema visual Obsidiana: tokens e componentes compartilhados."""
import re

COLORS = {}
# Shared tokens for new surfaces and procedural drawing.
COLORS.update(background='#09090F', surface='#14131E', text='#F1F0F7',
              muted='#B5B1C5', accent='#A78BFA', copper='#7761AE',
              border='#373244', danger='#FCA5A5', warning='#FCD34D', success='#86EFAC')
SPACING = 8
RADIUS = 14
COMPONENT_STYLE = """
QWidget { background:transparent; }
QLabel { background:transparent; }
QDialog, QMenu, QToolTip { background:#14131E; color:#F1F0F7; }
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QTimeEdit, QDoubleSpinBox { color:#F1F0F7; background:#0E0D16; border:1px solid #443B58; border-radius:12px; padding:8px; selection-background-color:#51426A; }
QComboBox QAbstractItemView { background:#14131E; color:#F1F0F7; selection-background-color:#51426A; }
QListWidget, QListView, QTreeView { color:#F1F0F7; background:#14131E; border:0; border-radius:12px; }
QListWidget::item { padding:9px 8px; border-bottom:1px solid #292333; }
QListWidget::item:selected { color:#F1F0F7; background:#30283F; }
QTabWidget::pane { border:0; background:transparent; }
QTabBar::tab { color:#B5B1C5; background:transparent; padding:6px 12px; font-size:12px; border-bottom:2px solid transparent; }
QTabBar::tab:selected { color:#DDD6FE; border-bottom:2px solid #A78BFA; }
QScrollArea { border:0; background:transparent; }
QScrollBar:vertical { width:8px; background:transparent; }
QScrollBar:horizontal { height:8px; background:transparent; }
QScrollBar::handle { background:#625080; border-radius:4px; min-width:24px; min-height:24px; }
QScrollBar::add-line, QScrollBar::sub-line { height:0; width:0; }
QScrollBar::add-page, QScrollBar::sub-page { background:transparent; }
QCheckBox { spacing:8px; padding:4px 2px; }
QGroupBox { border:1px solid #373244; border-radius:14px; margin-top:16px; padding:16px 12px 12px; }
QGroupBox::title { color:#C4B5FD; subcontrol-origin:margin; left:12px; padding:0 8px; }
QWidget { color:#F1F0F7; font-family:"Segoe UI Variable", "Segoe UI"; font-size:13px; }
QLabel#muted, QLabel[role="muted"], QLabel#clock { color:#B5B1C5; font-size:12px; }
QLabel#brand { color:#F1F0F7; font-size:18px; font-weight:600; letter-spacing:5px; }
QLabel#state { color:#DDD6FE; font-size:13px; }
QLabel#heading, QLabel[role="title"] { font-size:22px; font-weight:600; }
QPushButton, QToolButton { border-radius:10px; color:#E5E1F0; background:#211D30; border:1px solid #443B58; padding:6px 12px; }
QPushButton:hover, QToolButton:hover { color:#F1F0F7; background:#30283F; border-color:#A78BFA; }
QPushButton:disabled, QToolButton:disabled { color:#B5B1C5; background:#17151F; border-color:#373244; }
QPushButton:focus, QToolButton:focus, QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
QComboBox:focus, QSpinBox:focus, QCheckBox:focus, QListWidget:focus { border:2px solid #C4B5FD; }
QPushButton[primary="true"] { color:#100C1A; background:#A78BFA; border-color:#C4B5FD; }
QPushButton#nav { border:1px solid transparent; background:transparent; color:#B5B1C5; padding:8px 12px; text-align:left; font-size:13px; }
QPushButton#nav:hover { background:#1B1727; color:#F1F0F7; }
QPushButton#nav:checked { background:#282036; color:#DDD6FE; border-color:#625080; }
QPushButton#nav[windowOpen="true"] { border-left:2px solid #A78BFA; }
QFrame#composer { background:rgba(20,19,30,184); border:1px solid #625080; border-radius:16px; }
QFrame#composer[focused="true"] { border:2px solid #A78BFA; background:rgba(25,22,36,214); }
QPlainTextEdit#input { font-size:14px; border:0; padding:4px; background:transparent; }
QPlainTextEdit#input:focus { border:0; }
QFrame#responsePreview { background:rgba(20,19,30,184); border:1px solid rgba(255,255,255,23); border-radius:14px; }
QTextEdit#lastResponse { color:#F1F0F7; font-size:14px; border:0; background:transparent; }
QFrame#proposal { background:rgba(33,28,46,214); border:2px solid #C4B5FD; border-radius:16px; }
QPushButton#sessionButton { font-size:12px; padding:6px 10px; background:#14131E; }
QPushButton#textLink { color:#C4B5FD; background:transparent; border:0; padding:6px 2px; }
QPushButton#btnSend, QPushButton#btnVoice { padding:0; border:0; background:transparent; }
QToolButton#headerAction { padding:4px; background:#14131E; border-color:#373244; }
QTextEdit#conversationHistory { background:rgba(20,19,30,184); border:0; padding:14px; font-size:14px; }
"""
PANEL_STYLE = """
QFrame#workspacePanel { background:rgba(20,19,30,214); border:1px solid rgba(255,255,255,23); border-radius:14px; }
QFrame#workspacePanel[active="true"] { border-color:#625080; }
QFrame#panelTitleBar { background:transparent; border:0; border-bottom:1px solid rgba(255,255,255,20); border-top-left-radius:14px; border-top-right-radius:14px; }
QLabel#panelTitle { color:#F1F0F7; font-size:17px; font-weight:600; letter-spacing:0px; }
QPushButton#panelWindowControl { background:transparent; border:0; border-radius:10px; color:#C4B5FD; font-size:17px; padding:0; }
QPushButton#panelWindowControl:hover { background:#30283F; color:#F1F0F7; }
QPushButton#panelWindowControl:focus { border:2px solid #C4B5FD; }
"""


_HISTORY_COLORS = {'#fb923c':'#C4B5FD', '#21170e':'#282036', '#171717':'#1B1826',
                   '#f5f5f5':'#F1F0F7', '#6b3a14':'#625080', '#242424':'#373244'}

def history_html(markup, *, classic=False):
    """Theme HTML styles only; message text and escaped markup remain untouched."""
    palette={v.lower():k for k,v in _HISTORY_COLORS.items()} if classic else _HISTORY_COLORS
    def tag(match):
        value=match[0]
        value=re.sub(r'#[0-9a-fA-F]{6}\b',lambda color:palette.get(color[0].lower(),color[0]),value)
        if not classic:
            value=re.sub(r'font-size:\s*(?:13|16)px', 'font-size:14px',value)
            value=re.sub(r'font-size:\s*11px', 'font-size:12px',value)
        else:
            value=re.sub(r'font-size:\s*14px','font-size:13px',value)
        return value
    return re.sub(r'<[^>]+>',tag,markup)
