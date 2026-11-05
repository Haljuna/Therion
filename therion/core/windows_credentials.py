"""Leitura de uma credencial genérica do usuário; nenhum segredo em configuração."""
import ctypes
from ctypes import wintypes
import os
import re

GEMINI_CREDENTIAL = 'Therion/Gemini'


class CredentialUnavailable(ValueError):
    pass


class Credential(ctypes.Structure):
    _fields_ = [('Flags', wintypes.DWORD), ('Type', wintypes.DWORD),
        ('TargetName', wintypes.LPWSTR), ('Comment', wintypes.LPWSTR),
        ('LastWritten', wintypes.FILETIME), ('CredentialBlobSize', wintypes.DWORD),
        ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)), ('Persist', wintypes.DWORD),
        ('AttributeCount', wintypes.DWORD), ('Attributes', ctypes.c_void_p),
        ('TargetAlias', wintypes.LPWSTR), ('UserName', wintypes.LPWSTR)]


def read_gemini_key():
    if os.name != 'nt':
        raise CredentialUnavailable('A credencial Gemini requer o cofre do Windows.')
    api = ctypes.WinDLL('Advapi32.dll', use_last_error=True)
    api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                             ctypes.POINTER(ctypes.POINTER(Credential))]
    api.CredReadW.restype = wintypes.BOOL
    api.CredFree.argtypes = [ctypes.c_void_p]
    record = ctypes.POINTER(Credential)()
    if not api.CredReadW(GEMINI_CREDENTIAL, 1, 0, ctypes.byref(record)):
        raise CredentialUnavailable('Credencial Therion/Gemini não encontrada.')
    try:
        item = record.contents
        if item.UserName != 'api-key' or not 40 <= item.CredentialBlobSize <= 1024:
            raise CredentialUnavailable('Confira usuário api-key e chave no campo senha da credencial Therion/Gemini.')
        try:
            value = ctypes.string_at(item.CredentialBlob, item.CredentialBlobSize).decode('utf-16-le').rstrip('\0')
        except UnicodeError:
            raise CredentialUnavailable('Formato da credencial Gemini inválido.') from None
        if re.fullmatch(r'[A-Za-z0-9_-]{20,256}', value) is None:
            raise CredentialUnavailable('Formato da credencial Gemini inválido.')
        return value
    finally:
        api.CredFree(record)
