"""Leitura de atalhos locais dentro do processo, sem console ou execução do alvo."""
import ctypes
import os
import uuid
from itertools import islice
from pathlib import Path


class _GUID(ctypes.Structure):
    _fields_ = [('data1', ctypes.c_uint32), ('data2', ctypes.c_uint16),
        ('data3', ctypes.c_uint16), ('data4', ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, value):
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


def _method(pointer, index, result, *args):
    table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(result, ctypes.c_void_p, *args)(table[index])


def _check(result):
    if result < 0:
        raise OSError(f'Não consegui ler o atalho do Windows (0x{result & 0xffffffff:08X}).')


class ShellLinks:
    """Apartment COM por worker; Load/GetPath não chama Resolve ou ShellExecute."""
    def __enter__(self):
        self.ole = ctypes.WinDLL('ole32')
        self.ole.CoInitializeEx.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
        self.ole.CoInitializeEx.restype = ctypes.c_long
        self.ole.CoUninitialize.argtypes = ()
        self.ole.CoUninitialize.restype = None
        result = self.ole.CoInitializeEx(None, 2)
        # Uma thread já inicializada com outro apartment continua utilizável.
        if result & 0xffffffff != 0x80010106:
            _check(result)
        self.uninitialize = result >= 0
        self.ole.CoCreateInstance.argtypes = (ctypes.POINTER(_GUID), ctypes.c_void_p,
            ctypes.c_uint32, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p))
        self.ole.CoCreateInstance.restype = ctypes.c_long
        return self

    def __exit__(self, *_):
        if self.uninitialize:
            self.ole.CoUninitialize()

    def _open(self):
        link, persist = ctypes.c_void_p(), ctypes.c_void_p()
        clsid = _GUID.parse('00021401-0000-0000-C000-000000000046')
        iid = _GUID.parse('000214F9-0000-0000-C000-000000000046')
        _check(self.ole.CoCreateInstance(ctypes.byref(clsid), None, 1, ctypes.byref(iid), ctypes.byref(link)))
        try:
            iid_file = _GUID.parse('0000010B-0000-0000-C000-000000000046')
            _check(_method(link, 0, ctypes.c_long, ctypes.POINTER(_GUID),
                ctypes.POINTER(ctypes.c_void_p))(link, ctypes.byref(iid_file), ctypes.byref(persist)))
            return link, persist
        except Exception:
            _method(link, 2, ctypes.c_ulong)(link)
            raise

    def read(self, path):
        link, persist = self._open()
        try:
            # IPersistFile.Load, STGM_READ. Não resolve/repara atalhos anunciados.
            _check(_method(persist, 5, ctypes.c_long, ctypes.c_wchar_p, ctypes.c_uint32)(persist, str(path), 0))
            target, arguments = ctypes.create_unicode_buffer(32768), ctypes.create_unicode_buffer(32768)
            _check(_method(link, 3, ctypes.c_long, ctypes.c_wchar_p, ctypes.c_int,
                ctypes.c_void_p, ctypes.c_uint32)(link, target, len(target), None, 4))  # SLGP_RAWPATH
            _check(_method(link, 10, ctypes.c_long, ctypes.c_wchar_p, ctypes.c_int)(link, arguments, len(arguments)))
            return os.path.expandvars(target.value), arguments.value
        finally:
            _method(persist, 2, ctypes.c_ulong)(persist)
            _method(link, 2, ctypes.c_ulong)(link)


def start_menu_roots():
    shell = ctypes.WinDLL('shell32')
    shell.SHGetFolderPathW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p,
        ctypes.c_uint32, ctypes.c_wchar_p)
    shell.SHGetFolderPathW.restype = ctypes.c_long
    roots = []
    for folder in (0x0b, 0x16):  # CSIDL_STARTMENU, CSIDL_COMMON_STARTMENU
        buffer = ctypes.create_unicode_buffer(260)
        if shell.SHGetFolderPathW(None, folder, None, 0, buffer) == 0 and buffer.value:
            roots.append(Path(buffer.value))
    return roots


def discover_shortcuts(roots=None):
    if os.name != 'nt':
        return []
    candidates = []
    try:
        with ShellLinks() as reader:
            for root in start_menu_roots() if roots is None else roots:
                try:
                    for path in islice(Path(root).rglob('*.lnk'), 2000):
                        try:
                            target, arguments = reader.read(path)
                            if target and not arguments.strip():
                                candidates.append(dict(name=path.stem, path=target, source='Menu Iniciar'))
                        except OSError:
                            continue  # Um atalho inválido não interrompe a galeria.
                except OSError:
                    continue
    except OSError:
        pass  # App Paths continua disponível se a consulta COM não puder iniciar.
    return candidates
