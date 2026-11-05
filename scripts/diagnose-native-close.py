"""Diagnóstico nativo somente leitura: registra pilha COM e preserva a exceção.

Executa o teste isolado conhecido. Não desativa acessibilidade/faulthandler,
não trata offscreen como solução e nunca marca a exceção como atendida.
"""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import sys
import tempfile
import argparse
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--case',choices=['original','minimal','event-loop'],default='original')
    parser.add_argument('--prewarm-host',action='store_true',help='Experimento: preparar provider host fora de WM_GETOBJECT, sem desativar UIA.')
    parser.add_argument('--prewarm-automation',action='store_true',help='Experimento: instanciar cliente COM UIA fora da mensagem, sem consultar desktop.')
    parser.add_argument('--retain-prewarm',action='store_true',help='Manter referências COM preparadas até encerrar o experimento.')
    parser.add_argument('--prime-provider-api',action='store_true',help='Preparar API pública de eventos UIA antes de mostrar janela.')
    parser.add_argument('--prime-layout-event',action='store_true',help='Experimento de evento de layout do próprio HWND antes da exibição.')
    parser.add_argument('--prime-own-node',action='store_true',help='Experimento: preparar nó UIA somente do HWND fictício antes da exibição.')
    parser.add_argument('--prime-com-element',action='store_true',help='Experimento: preparar apenas o próprio HWND pela interface COM atual.')
    parser.add_argument('--skip-product-preparation',action='store_true',help='Controle diagnóstico: restaurar apenas o caminho anterior, sem desligar UIA.')
    args=parser.parse_args()
    import pytest
    from PySide6.QtCore import QAbstractNativeEventFilter
    class MSG(ctypes.Structure):
        _fields_=[('hwnd',ctypes.c_void_p),('message',wintypes.UINT),('wParam',ctypes.c_size_t),
            ('lParam',ctypes.c_ssize_t),('time',wintypes.DWORD),('pt',wintypes.POINT)]
    messages=[]
    user=ctypes.WinDLL('user32');user.InSendMessageEx.argtypes=(ctypes.c_void_p,)
    class Observer(QAbstractNativeEventFilter):
        def nativeEventFilter(self,event_type,message):
            msg=MSG.from_address(int(message))
            if msg.message==0x003d:
                messages.append(dict(message='WM_GETOBJECT',object_id=msg.lParam,wparam=msg.wParam,
                    synchronous_flags=user.InSendMessageEx(None)))
            return False,0
    observer=Observer()
    prewarm=[]
    retained=[]
    # O host real mantém a janela viva durante app.exec(). O pytest pode coletar
    # o wrapper no teardown, enquanto a ponte UIA ainda possui callbacks nativos.
    # Reter até a saída do teste e destruir pela fila Qt reproduz essa vida útil.
    live_windows=[]
    disposed=0
    def release(pointer):
        vtable=ctypes.cast(pointer,ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        ctypes.WINFUNCTYPE(wintypes.ULONG,ctypes.c_void_p)(vtable[2])(pointer)
    def prewarm_host(window):
        if args.prime_own_node:
            uia=ctypes.WinDLL('UIAutomationCore')
            uia.UiaNodeFromHandle.argtypes=(ctypes.c_void_p,ctypes.POINTER(ctypes.c_void_p))
            uia.UiaNodeFromHandle.restype=ctypes.c_long
            node=ctypes.c_void_p()
            result=uia.UiaNodeFromHandle(int(window.winId()),ctypes.byref(node))
            prewarm.append(dict(own_node_hresult=result,node_obtained=bool(node.value)))
            if node.value:
                uia.UiaNodeRelease.argtypes=(ctypes.c_void_p,)
                uia.UiaNodeRelease(node)
        if args.prime_provider_api:
            uia=ctypes.WinDLL('UIAutomationCore')
            uia.UiaClientsAreListening.argtypes=()
            uia.UiaClientsAreListening.restype=wintypes.BOOL
            prewarm.append(dict(provider_api_initialized=True,listeners=bool(uia.UiaClientsAreListening())))
        if args.prewarm_automation or args.prime_com_element:
            class GUID(ctypes.Structure):
                _fields_=[('Data1',wintypes.DWORD),('Data2',wintypes.WORD),('Data3',wintypes.WORD),('Data4',ctypes.c_ubyte*8)]
            clsid=GUID.from_buffer_copy(uuid.UUID('ff48dba4-60ef-4201-aa87-54103eef594e').bytes_le)
            iid=GUID.from_buffer_copy(uuid.UUID('30cbe57d-d9d0-452a-ab13-7ac5ac4825ee').bytes_le)
            ole=ctypes.WinDLL('ole32');ole.CoCreateInstance.argtypes=(ctypes.POINTER(GUID),ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(GUID),ctypes.POINTER(ctypes.c_void_p))
            ole.CoCreateInstance.restype=ctypes.c_long
            client=ctypes.c_void_p();result=ole.CoCreateInstance(ctypes.byref(clsid),None,1,ctypes.byref(iid),ctypes.byref(client))
            prewarm.append(dict(automation_hresult=result,client_obtained=bool(client.value)))
            if client.value:
                if args.prime_com_element:
                    vtable=ctypes.cast(client,ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
                    element=ctypes.c_void_p()
                    get_element=ctypes.WINFUNCTYPE(ctypes.c_long,ctypes.c_void_p,ctypes.c_void_p,ctypes.POINTER(ctypes.c_void_p))(vtable[6])
                    result=get_element(client,int(window.winId()),ctypes.byref(element))
                    prewarm.append(dict(own_element_hresult=result,element_obtained=bool(element.value)))
                    if element.value:release(element)
                if args.retain_prewarm:retained.append(client)
                else:release(client)
        if not (args.prewarm_host or args.prime_layout_event):return
        uia=ctypes.WinDLL('UIAutomationCore')
        uia.UiaHostProviderFromHwnd.argtypes=(ctypes.c_void_p,ctypes.POINTER(ctypes.c_void_p))
        uia.UiaHostProviderFromHwnd.restype=ctypes.c_long
        provider=ctypes.c_void_p()
        result=uia.UiaHostProviderFromHwnd(int(window.winId()),ctypes.byref(provider))
        prewarm.append(dict(hresult=result,provider_obtained=bool(provider.value)))
        if provider.value:
            if args.prime_layout_event:
                uia.UiaRaiseAutomationEvent.argtypes=(ctypes.c_void_p,ctypes.c_int)
                uia.UiaRaiseAutomationEvent.restype=ctypes.c_long
                prewarm.append(dict(layout_event_hresult=uia.UiaRaiseAutomationEvent(provider,20008)))
            if args.retain_prewarm:retained.append(provider)
            else:release(provider)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    capture=kernel.RtlCaptureStackBackTrace
    capture.argtypes=(wintypes.DWORD,wintypes.DWORD,ctypes.POINTER(ctypes.c_void_p),ctypes.c_void_p)
    capture.restype=wintypes.WORD
    frames=[]
    CALLBACK=ctypes.WINFUNCTYPE(ctypes.c_long,ctypes.c_void_p)
    @CALLBACK
    def handler(pointer):
        record=ctypes.cast(pointer,ctypes.POINTER(ctypes.c_void_p))[0]
        code=ctypes.cast(record,ctypes.POINTER(wintypes.DWORD))[0]
        if code==0x8001010d:
            stack=(ctypes.c_void_p*128)()
            count=capture(0,128,stack,None)
            frames.append([stack[i] for i in range(count)])
        return 0 # EXCEPTION_CONTINUE_SEARCH: não suprimir nem tratar.
    kernel.AddVectoredExceptionHandler.argtypes=(wintypes.ULONG,CALLBACK)
    kernel.AddVectoredExceptionHandler.restype=ctypes.c_void_p
    token=kernel.AddVectoredExceptionHandler(1,handler)
    try:
        if args.case=='original':
            from unittest.mock import patch
            from PySide6.QtWidgets import QApplication
            from therion.interface.desktop import MainWindow
            initialize=MainWindow.__init__
            def observed_initialize(window,*arguments,**keywords):
                live_windows.append(window)
                QApplication.instance().installNativeEventFilter(observer)
                result=initialize(window,*arguments,**keywords)
                prewarm.append(dict(product_state=getattr(window,'_native_accessibility_state',None)))
                prewarm_host(window)
                return result
            with patch.object(MainWindow,'__init__',observed_initialize):
                if args.skip_product_preparation:
                    with patch('therion.interface.desktop.prepare_native_accessibility',return_value={'state':'diagnostic_control'}):
                        result=pytest.main(['tests/test_desktop_integration.py::TestDesktopAsyncCommand::test_close_without_tray_waits_for_active_command','-q'])
                else:
                    result=pytest.main(['tests/test_desktop_integration.py::TestDesktopAsyncCommand::test_close_without_tray_waits_for_active_command','-q'])
        else:
            import faulthandler,time
            faulthandler.enable()
            from PySide6.QtWidgets import QApplication,QMainWindow,QPlainTextEdit
            from PySide6.QtCore import QTimer,QEventLoop
            app=QApplication([]);app.installNativeEventFilter(observer)
            window=QMainWindow();live_windows.append(window);field=QPlainTextEdit();window.setCentralWidget(field)
            field.setPlainText('Diagnóstico fictício, sem modelo ou dados pessoais.');prewarm_host(window);window.show()
            if args.case=='minimal':
                end=time.monotonic()+.5
                while time.monotonic()<end:
                    app.processEvents();time.sleep(.005)
            else:
                loop=QEventLoop();QTimer.singleShot(500,loop.quit);loop.exec()
            window.close();result=0
    finally:
        from PySide6.QtCore import QCoreApplication,QEvent
        from shiboken6 import isValid
        for window in live_windows:
            if isValid(window):window.deleteLater()
        # O observador permanece ativo durante a destruição: exceções não são
        # suprimidas nem excluídas da contagem para conseguir um resultado verde.
        QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
        disposed=sum(not isValid(window) for window in live_windows)
        app=QCoreApplication.instance()
        if app is not None:app.removeNativeEventFilter(observer)
        for pointer in reversed(retained):release(pointer)
        kernel.RemoveVectoredExceptionHandler.argtypes=(ctypes.c_void_p,)
        kernel.RemoveVectoredExceptionHandler(token)
    kernel.GetModuleHandleExW.argtypes=(wintypes.DWORD,ctypes.c_void_p,ctypes.POINTER(ctypes.c_void_p))
    kernel.GetModuleFileNameW.argtypes=(ctypes.c_void_p,wintypes.LPWSTR,wintypes.DWORD)
    mapped=[]
    for stack in frames:
        rows=[]
        for address in stack:
            module=ctypes.c_void_p();name=ctypes.create_unicode_buffer(1024)
            if kernel.GetModuleHandleExW(6,address,ctypes.byref(module)):
                kernel.GetModuleFileNameW(module,name,1024)
                rows.append(dict(module=Path(name.value).name,offset=hex(address-module.value)))
        mapped.append(rows)
    report=dict(case=args.case,exit_code=int(result),com_exceptions=len(mapped),prewarm=prewarm,messages=messages,stacks=mapped,
        qt_windows_disposed=disposed)
    target=Path(tempfile.mkdtemp(prefix='therion-native-close-'))/'report.json'
    target.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(dict(report,stacks=[s[36:70] for s in mapped]),indent=2));print('Evidência: '+str(target))
    print('NATIVE_CLOSE_RESULT='+json.dumps(dict(exit_code=int(result),com_exceptions=len(mapped),
        native_requests=len(messages),prewarm=prewarm,qt_windows_disposed=disposed,report=str(target)),ensure_ascii=True))
    return int(result)


if __name__=='__main__':
    sys.exit(main())
