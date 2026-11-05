"""Seleção de janelas fictícias; não envia mensagens ao Discord real."""
from types import SimpleNamespace

from therion.autonomy import browser_windows as module


class Function:
    def __init__(self, callback):self.callback=callback
    def __call__(self,*args):return self.callback(*args)


def test_discord_selects_only_titled_hidden_app_widgets(monkeypatch):
    calls=[]
    def enumerate_windows(path,*,visible_only=True):
        calls.append(visible_only)
        return {1} if visible_only else {1,2,3,4}
    def window_class(hwnd,buffer,size):
        buffer.value='Chrome_WidgetWin_1' if hwnd in {2,3} else 'Chrome_MessageWindow'
        return len(buffer.value)
    user=SimpleNamespace(GetClassNameW=Function(window_class),
                         GetWindowTextLengthW=Function(lambda hwnd:10 if hwnd in {2,4} else 0))
    monkeypatch.setattr(module,'browser_windows',enumerate_windows)
    monkeypatch.setattr(module.ctypes,'WinDLL',lambda *a,**k:user)
    assert module.closeable_windows('Discord.exe')=={1,2}
    assert calls==[True,False]


def test_other_apps_keep_visible_windows_only(monkeypatch):
    def enumerate_windows(path,*,visible_only=True):
        assert visible_only
        return {1}
    monkeypatch.setattr(module,'browser_windows',enumerate_windows)
    assert module.closeable_windows('Obsidian.exe')=={1}


def test_close_revalidates_selected_handles_without_expanding_targets(monkeypatch):
    sent=[]
    def enumerate_windows(path,*,visible_only=True):
        assert not visible_only
        return {2,3}
    user=SimpleNamespace(PostMessageW=Function(lambda *args:sent.append(args) or True))
    monkeypatch.setattr(module,'browser_windows',enumerate_windows)
    monkeypatch.setattr(module.ctypes,'WinDLL',lambda *a,**k:user)
    module.close_windows('Discord.exe',{1,2})
    assert sent==[(2,0x0010,0,0)]
