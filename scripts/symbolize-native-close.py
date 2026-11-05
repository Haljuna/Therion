"""Resolve offsets de módulos Windows usando DbgHelp existente e PDBs públicos.

Download explícito de dados de símbolos para Temp; não instala ferramentas,
não altera DLLs/configurações e não anexa a processos de outros aplicativos.
"""
import argparse,ctypes,json,re,struct,tempfile,uuid,urllib.request,hashlib
from ctypes import wintypes
from pathlib import Path


def codeview(path):
    data=path.read_bytes();pe=struct.unpack_from('<I',data,0x3c)[0]
    sections=struct.unpack_from('<H',data,pe+6)[0];size=struct.unpack_from('<H',data,pe+20)[0]
    opt=pe+24;magic=struct.unpack_from('<H',data,opt)[0]
    directory=opt+(112 if magic==0x20b else 96)+6*8
    rva,length=struct.unpack_from('<II',data,directory)
    table=opt+size
    def offset(value):
        for i in range(sections):
            virtual_size,virtual,raw_size,raw=struct.unpack_from('<IIII',data,table+i*40+8)
            if virtual<=value<virtual+max(virtual_size,raw_size):return raw+value-virtual
        raise ValueError('RVA de símbolos não encontrado.')
    start=offset(rva)
    for i in range(length//28):
        _,_,_,_,kind,count,_,pointer=struct.unpack_from('<IIHHIIII',data,start+i*28)
        raw=data[pointer:pointer+count]
        if kind==2 and raw[:4]==b'RSDS':
            guid=uuid.UUID(bytes_le=raw[4:20]).hex.upper();age=struct.unpack_from('<I',raw,20)[0]
            name=Path(raw[24:].split(b'\0',1)[0].decode('utf-8')).name
            if not re.fullmatch(r'[\w.-]+\.pdb',name,re.I):raise ValueError('Nome PDB inválido.')
            return name,guid+format(age,'X')
    raise ValueError('Identidade CodeView não encontrada.')


class SYMBOL_INFO(ctypes.Structure):
    _fields_=[('SizeOfStruct',wintypes.ULONG),('TypeIndex',wintypes.ULONG),('Reserved',ctypes.c_ulonglong*2),
        ('Index',wintypes.ULONG),('Size',wintypes.ULONG),('ModBase',ctypes.c_ulonglong),('Flags',wintypes.ULONG),
        ('Value',ctypes.c_ulonglong),('Address',ctypes.c_ulonglong),('Register',wintypes.ULONG),('Scope',wintypes.ULONG),
        ('Tag',wintypes.ULONG),('NameLen',wintypes.ULONG),('MaxNameLen',wintypes.ULONG),('Name',ctypes.c_char*1)]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--report',required=True)
    parser.add_argument('--module',choices=['UIAutomationCore.DLL','combase.dll','RPCRT4.dll'],default='UIAutomationCore.DLL')
    parser.add_argument('--download',action='store_true');parser.add_argument('--cache')
    args=parser.parse_args();source=Path(args.report).resolve()
    temp=Path(tempfile.gettempdir()).resolve()
    if not source.is_relative_to(temp) or not source.parent.name.startswith('therion-native-close-'):
        raise ValueError('Use somente relatório temporário deste diagnóstico.')
    report=json.loads(source.read_text(encoding='utf-8'))
    cache=Path(args.cache).resolve() if args.cache else Path(tempfile.mkdtemp(prefix='therion-native-symbols-'))
    if not cache.is_relative_to(temp) or not cache.name.startswith('therion-native-symbols-'):
        raise ValueError('Cache precisa estar em temporários próprios.')
    cache.mkdir(exist_ok=True)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True);library=ctypes.WinDLL(args.module)
    kernel.GetModuleFileNameW.argtypes=(ctypes.c_void_p,wintypes.LPWSTR,wintypes.DWORD)
    name=ctypes.create_unicode_buffer(1024);kernel.GetModuleFileNameW(library._handle,name,1024)
    image=Path(name.value);pdb,identity=codeview(image);target=cache/pdb
    if not target.exists() and args.download:
        url=f'https://msdl.microsoft.com/download/symbols/{pdb}/{identity}/{pdb}'
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        print('Obtendo símbolo público '+pdb+' '+identity,flush=True)
        with opener.open(url,timeout=30) as response:
            data=response.read(64*1024*1024+1)
        if len(data)>64*1024*1024:raise ValueError('PDB excedeu limite de 64 MB.')
        with target.open('xb') as output:output.write(data)
        print('PDB obtido: '+str(len(data))+' bytes',flush=True)
    dbg=ctypes.WinDLL('dbghelp',use_last_error=True)
    dbg.SymSetOptions.argtypes=(wintypes.DWORD,);dbg.SymSetOptions(0x2|0x400|0x200|0x80000)
    dbg.SymInitializeW.argtypes=(ctypes.c_void_p,wintypes.LPCWSTR,wintypes.BOOL)
    # Identificador exclusivo de sessão, sem invadir/enumerar processos.
    session=ctypes.c_void_p(id(report))
    if not dbg.SymInitializeW(session,str(cache),False):raise ctypes.WinError(ctypes.get_last_error())
    try:
        dbg.SymLoadModuleExW.argtypes=(ctypes.c_void_p,ctypes.c_void_p,wintypes.LPCWSTR,wintypes.LPCWSTR,ctypes.c_ulonglong,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD)
        dbg.SymLoadModuleExW.restype=ctypes.c_ulonglong
        base=dbg.SymLoadModuleExW(session,None,str(image),None,0x10000000,0,None,0)
        if not base:raise ctypes.WinError(ctypes.get_last_error())
        dbg.SymFromAddr.argtypes=(ctypes.c_void_p,ctypes.c_ulonglong,ctypes.POINTER(ctypes.c_ulonglong),ctypes.POINTER(SYMBOL_INFO))
        rows=[]
        for stack in report['stacks']:
            for frame in stack:
                if frame['module'].casefold()!=args.module.casefold():continue
                buffer=ctypes.create_string_buffer(ctypes.sizeof(SYMBOL_INFO)+1024)
                symbol=ctypes.cast(buffer,ctypes.POINTER(SYMBOL_INFO));symbol.contents.SizeOfStruct=ctypes.sizeof(SYMBOL_INFO)
                symbol.contents.MaxNameLen=1024;displacement=ctypes.c_ulonglong()
                ok=dbg.SymFromAddr(session,base+int(frame['offset'],16),ctypes.byref(displacement),symbol)
                resolved=ctypes.string_at(ctypes.addressof(buffer)+SYMBOL_INFO.Name.offset,symbol.contents.NameLen).decode('utf-8','replace') if ok else ''
                rows.append(dict(frame,symbol=resolved,displacement=hex(displacement.value),resolved=bool(ok)))
        output=dict(module=args.module,image_sha256=hashlib.sha256(image.read_bytes()).hexdigest(),pdb=pdb,identity=identity,
            pdb_present=target.exists(),pdb_bytes=target.stat().st_size if target.exists() else 0,frames=rows)
        (cache/'symbols.json').write_text(json.dumps(output,indent=2),encoding='utf-8')
        print(json.dumps(output,indent=2));print('Evidência: '+str(cache/'symbols.json'))
    finally:
        dbg.SymCleanup.argtypes=(ctypes.c_void_p,);dbg.SymCleanup(session)


if __name__=='__main__':main()
