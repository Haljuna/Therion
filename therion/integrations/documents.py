"""Documentos locais em raízes escolhidas; leitura não executa conteúdo."""
from pathlib import Path
import csv
import hashlib
import io
import os
import tempfile
from xml.sax.saxutils import escape

from therion.memory.knowledge import safe_path

READ_TYPES={'.txt','.md','.pdf','.docx','.csv','.xlsx'}
WRITE_TYPES={'.txt','.md','.pdf','.docx','.xlsx'}


class DocumentSession:
    def __init__(self,config):
        self.adapter=DocumentAdapter(config.get('read_roots',()),config.get('write_roots',()))
        self.cache_enabled=config.get('cache_enabled') is True
        from collections import OrderedDict
        self.cache=OrderedDict()

    def dispatch(self,operation,args):
        if operation=='read':
            from copy import deepcopy
            offset,limit=args.get('offset',0),args.get('limit',6000)
            from .excerpts import validate_interval
            validate_interval(offset,limit)
            # Acesso e conteúdo são relidos mesmo em hit. Revogação, versão e
            # mudança do destino não são atendidos por um resultado antigo.
            version=self.adapter.version(args['path']) if self.cache_enabled else None
            key=(str(self.adapter._path(args['path'])),version,offset,limit)
            if self.cache_enabled and key in self.cache:
                result=deepcopy(self.cache[key])
                if self.adapter.version(args['path'])!=version:raise ValueError('Documento mudou durante a consulta do cache.')
                self.cache.move_to_end(key)
                return dict(result,cache_hit=True)
            result=self.adapter.read(args['path'],offset,limit)
            if self.cache_enabled:
                import json
                for old in list(self.cache):
                    if old[0]==key[0] and old[1]!=result['version']:self.cache.pop(old)
                if len(json.dumps(result,ensure_ascii=False).encode('utf-8'))<=64000:
                    key=(key[0],result['version'],offset,limit)
                    self.cache[key]=deepcopy(result)
                    while len(self.cache)>16:self.cache.popitem(last=False)
                return dict(result,cache_hit=False)
            return result
        if operation=='write':
            self.cache.clear()
            return self.adapter.write(args['path'],args['text'],args['expected_version'])
        raise ValueError('Operação de documento não suportada.')

    def close(self):self.cache.clear()


class DocumentAdapter:
    def __init__(self,read_roots=(),write_roots=()):
        self.read_roots=tuple(str(Path(root).resolve()) for root in read_roots)
        self.write_roots=tuple(str(Path(root).resolve()) for root in write_roots)

    def _path(self,value,write=False):
        path=safe_path(value,self.write_roots if write else self.read_roots)
        if path.suffix.lower() not in (WRITE_TYPES if write else READ_TYPES):raise ValueError('Formato de documento não suportado.')
        if path.exists() and (not path.is_file() or path.stat().st_nlink!=1 or path.stat().st_size>20_000_000):
            raise ValueError('Documento fora dos limites ou com vínculo não permitido.')
        return path

    def version(self,value,write=False):
        path=self._path(value,write)
        return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None

    def read(self,value,offset=0,limit=6000):
        from .excerpts import validate_interval
        validate_interval(offset,limit)
        path=self._path(value)
        data=path.read_bytes();version=hashlib.sha256(data).hexdigest();suffix=path.suffix.lower()
        sections=[];warnings=[]
        if suffix in {'.txt','.md'}:sections=[{'section':'texto','text':data.decode('utf-8-sig')}]
        elif suffix=='.csv':
            import itertools
            rows=list(csv.reader(io.StringIO(data.decode('utf-8-sig'))))
            sections=[{'section':'tabela','text':'\n'.join(' | '.join(row) for row in rows)}]
        elif suffix=='.pdf':
            from pypdf import PdfReader
            reader=PdfReader(io.BytesIO(data))
            if reader.is_encrypted:raise ValueError('PDF protegido requer abertura explícita pelo usuário.')
            if len(reader.pages)>100:warnings.append('Leitura limitada às primeiras 100 páginas; o restante não foi consultado.')
            for index,page in enumerate(reader.pages[:100],1):
                text=page.extract_text() or ''
                sections.append({'section':f'página {index}','text':text})
            if not any(section['text'].strip() for section in sections):warnings.append('PDF sem texto extraível; precisa de OCR. Não equivale a documento vazio.')
        elif suffix=='.docx':
            self._validate_zip(data)
            from docx import Document
            document=Document(io.BytesIO(data))
            sections=[{'section':'parágrafos','text':'\n'.join(p.text for p in document.paragraphs)}]
            sections.extend({'section':f'tabela {index}','text':'\n'.join(' | '.join(cell.text for cell in row.cells) for row in table.rows)} for index,table in enumerate(document.tables,1))
        elif suffix=='.xlsx':
            self._validate_zip(data)
            from openpyxl import load_workbook
            workbook=load_workbook(io.BytesIO(data),read_only=True,data_only=False,keep_links=False)
            try:
                for sheet in workbook.worksheets[:10]:
                    if (sheet.max_row or 0)>100 or (sheet.max_column or 0)>30:warnings.append('Planilha '+sheet.title+': leitura limitada a 100 linhas e 30 colunas.')
                    rows=[]
                    for row in sheet.iter_rows(max_row=100,max_col=30,values_only=True):
                        if any(isinstance(item,str) and item.startswith('=') for item in row):warnings.append('Fórmulas não executadas; valores calculados não foram verificados.')
                        rows.append(' | '.join('' if item is None else str(item) for item in row))
                    sections.append({'section':sheet.title,'text':'\n'.join(rows)})
                if len(workbook.worksheets)>10:warnings.append('Leitura limitada às primeiras dez planilhas.')
            finally:workbook.close()
        result={'path':str(path),'version':version,'sections':sections,'warnings':list(dict.fromkeys(warnings))}
        from .excerpts import excerpt
        result.update(excerpt(sections,offset,limit))
        result['coverage_limited']=any('limitada' in warning or 'limitado' in warning for warning in warnings)
        if self.version(value)!=version:raise ValueError('Documento mudou durante a leitura.')
        return result

    @staticmethod
    def _validate_zip(data):
        import zipfile
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members=archive.infolist()
            if len(members)>10000 or sum(row.file_size for row in members)>100_000_000:
                raise ValueError('Documento compactado acima do limite de expansão.')
            if any(row.flag_bits&1 for row in members):raise ValueError('Documento protegido não suportado.')

    def write(self,value,text,expected_version):
        path=self._path(value,True)
        if self.version(value,True)!=expected_version:raise ValueError('Destino mudou desde a prévia.')
        if not isinstance(text,str) or len(text)>100000:raise ValueError('Conteúdo de documento acima do limite.')
        suffix=path.suffix.lower()
        if suffix in {'.txt','.md'}:data=text.encode('utf-8')
        else:
            buffer=io.BytesIO()
            if suffix=='.docx':
                from docx import Document
                document=Document()
                for line in text.splitlines():document.add_paragraph(line)
                document.save(buffer)
            elif suffix=='.pdf':
                from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
                from reportlab.lib.styles import getSampleStyleSheet
                styles=getSampleStyleSheet()
                SimpleDocTemplate(buffer).build([Paragraph(escape(line) or ' ',styles['BodyText']) for line in text.splitlines()])
            else:
                from openpyxl import Workbook
                workbook=Workbook();sheet=workbook.active
                for row in csv.reader(io.StringIO(text)):
                    # Conteúdo produzido é texto, nunca fórmula executável.
                    sheet.append(["'"+item if item.startswith(('=','+','-','@')) else item for item in row])
                workbook.save(buffer);workbook.close()
            data=buffer.getvalue()
        descriptor,temporary=tempfile.mkstemp(dir=path.parent,prefix='.therion-document-',suffix='.tmp')
        try:
            with os.fdopen(descriptor,'wb') as output:output.write(data);output.flush();os.fsync(output.fileno())
            if self.version(value,True)!=expected_version:raise ValueError('Destino mudou antes da publicação.')
            original_path=None
            if expected_version is not None:
                original=path.read_bytes()
                if hashlib.sha256(original).hexdigest()!=expected_version:raise ValueError('Original mudou antes de preservar a cópia.')
                original_path=self._path(path.with_name(path.stem+'.therion-original-'+expected_version[:12]+path.suffix),True)
                try:
                    with original_path.open('xb') as saved:saved.write(original);saved.flush();os.fsync(saved.fileno())
                except FileExistsError:
                    if self.version(original_path,True)!=expected_version:raise ValueError('A cópia do original já existe com conteúdo diferente.')
                if self.version(value,True)!=expected_version:raise ValueError('Destino mudou antes da substituição.')
            os.replace(temporary,path)
        finally:
            if os.path.exists(temporary):os.unlink(temporary)
        version=self.version(value,True)
        if version!=hashlib.sha256(data).hexdigest():raise ValueError('Arquivo publicado não pôde ser verificado.')
        return {'path':str(path),'version':version,**({'original_path':str(original_path),'original_version':expected_version} if original_path else {})}
