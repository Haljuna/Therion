"""Camada de acesso e leitura seletiva do Segundo Cérebro para a V0."""

import os
import re
import hashlib
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional

from therion.context.read_scope import ReadScope, effective_roots
from therion.context.source_education import formation_context


@dataclass
class ReadResult:
    """Resultado estruturado de uma operação de leitura seletiva."""

    success: bool
    path: str
    canonical_path: Optional[str] = None
    content: Optional[str] = None
    error: Optional[str] = None
    matched_root: Optional[str] = None


@dataclass
class SearchResult:
    """Resultado de uma busca textual no Segundo Cérebro."""

    path: str
    snippet: str
    version: str = ''
    context: str = ''
    formation_context: str = ''


@dataclass
class SearchTrace:
    """Registro passivo das raízes cuja varredura foi iniciada nesta busca."""

    used_roots: List[str] = field(default_factory=list)
    unavailable_files: int = 0


class SecondBrainReader:
    """Leitor controlado e seletivo do Segundo Cérebro."""

    DEFAULT_VAULT_ROOT = r"C:\Users\marcu\Downloads\Segundo-Cerebro"

    def __init__(
        self,
        vault_root: Optional[str] = None,
        allowed_roots: Optional[List[str]] = None,
    ) -> None:
        self.vault_root = os.path.abspath(vault_root or self.DEFAULT_VAULT_ROOT)
        self.access_guard = None

        if allowed_roots is None:
            self.allowed_roots = [
                os.path.abspath(
                    os.path.join(self.vault_root, "90 - Sistema da IA")
                ),
                os.path.abspath(
                    os.path.join(self.vault_root, "10 - Projetos", "Therion")
                ),
            ]
        else:
            self.allowed_roots = [os.path.abspath(r) for r in allowed_roots]

    def _is_subpath(self, target: str, parent: str) -> bool:
        """Verifica de forma segura se target é subcaminho estrito de parent."""
        norm_target = os.path.normcase(os.path.abspath(target))
        norm_parent = os.path.normcase(os.path.abspath(parent))
        try:
            return os.path.commonpath([norm_target, norm_parent]) == norm_parent
        except ValueError:
            return False

    def resolve_and_validate(
        self, requested_path: str, scope: Optional[ReadScope] = None
    ) -> str:
        """Mantém a API de resolução e validação que retorna apenas o caminho."""
        candidate, _matched_root = self._resolve_and_match_root(requested_path, scope)
        return candidate

    def _resolve_and_match_root(
        self, requested_path: str, scope: Optional[ReadScope] = None
    ) -> tuple[str, str]:
        """Valida o caminho e identifica a primeira raiz efetiva que o autoriza."""
        clean_path = requested_path.strip()

        # 1. Validação estrita de extensão permitida (somente .md)
        if not clean_path.lower().endswith(".md"):
            raise ValueError(
                f"Tipo de arquivo não permitido: '{clean_path}'. Apenas arquivos .md são autorizados."
            )

        # 2. Resolução do caminho canônico
        if os.path.isabs(clean_path):
            candidate = os.path.abspath(clean_path)
        else:
            therion_root = os.path.abspath(
                os.path.join(self.vault_root, "10 - Projetos", "Therion")
            )
            candidate_therion = os.path.abspath(
                os.path.join(therion_root, clean_path)
            )
            candidate_vault = os.path.abspath(
                os.path.join(self.vault_root, clean_path)
            )

            # Se for um nome simples de arquivo sem separador de pasta que exista em Therion
            if ("/" not in clean_path and "\\" not in clean_path) and os.path.exists(candidate_therion):
                candidate = candidate_therion
            else:
                candidate = candidate_vault

        # 3. Verificação de contenção dentro de uma das raízes autorizadas
        if scope is None:
            roots = self.allowed_roots
        else:
            roots = effective_roots(scope, self.allowed_roots)
        validated_path = os.path.realpath(candidate)
        if not validated_path.lower().endswith('.md'):
            raise ValueError('O destino do link não é um arquivo .md autorizado.')

        matched_root = next(
            (root for root in roots if self._is_subpath(validated_path, root)
             and any(self._is_subpath(validated_path, allowed) for allowed in self.allowed_roots)),
            None,
        )
        if matched_root is None:
            raise PermissionError(
                f"Acesso negado: o caminho '{clean_path}' está fora das raízes autorizadas do Segundo Cérebro."
            )

        return validated_path, matched_root

    def _check_access(self):
        if self.access_guard is not None:
            try:
                self.access_guard()
            except (ValueError, OSError, TypeError) as error:
                raise PermissionError('A política de leitura mudou ou foi revogada.') from error

    def read_note(
        self, requested_path: str, scope: Optional[ReadScope] = None, *, constrained: bool = False
    ) -> ReadResult:
        """Lê o conteúdo de uma nota Markdown dentro do escopo autorizado."""
        try:
            self._check_access()
            canonical_path, matched_root = self._resolve_and_match_root(
                requested_path, scope
            )
        except (ValueError, PermissionError) as err:
            return ReadResult(
                success=False,
                path=requested_path,
                error=str(err),
            )

        if not os.path.exists(canonical_path):
            return ReadResult(
                success=False,
                path=requested_path,
                canonical_path=canonical_path,
                error=f"Arquivo não encontrado: '{requested_path}'.",
            )

        if not os.path.isfile(canonical_path):
            return ReadResult(
                success=False,
                path=requested_path,
                canonical_path=canonical_path,
                error=f"O caminho especificado não é um arquivo regular: '{requested_path}'.",
            )

        try:
            # Leitura estritamente em modo leitura com codificação UTF-8
            if constrained:
                info=os.stat(canonical_path)
                if info.st_nlink!=1 or info.st_size>20_000_000:raise ValueError('Nota acima do limite de20MB ou com múltiplos vínculos.')
            with open(canonical_path, "r", encoding="utf-8") as file_handle:
                content = file_handle.read(20_000_001) if constrained else file_handle.read()
            if constrained and len(content)>20_000_000:raise ValueError('Nota acima do limite de leitura.')

            self._check_access()

            return ReadResult(
                success=True,
                path=requested_path,
                canonical_path=canonical_path,
                content=content,
                matched_root=matched_root,
            )
        except Exception as err:
            return ReadResult(
                success=False,
                path=requested_path,
                canonical_path=canonical_path,
                error=f"Erro ao ler arquivo: {err}",
            )

    def search_notes(
        self,
        term: str,
        max_results: int = 5,
        snippet_length: int = 200,
        scope: Optional[ReadScope] = None,
        trace: Optional[SearchTrace] = None,
        normalize_accents: bool = False,
        constrained: bool = False,
        context_hint: str = '',
        cancel_check=None,
    ) -> List[SearchResult]:
        """Ordena títulos exatos, nomes e conteúdo, sem índice persistente.

        Percorre as raízes efetivas antes de limitar os resultados para que uma
        correspondência relevante no fim da varredura não seja descartada.
        """
        cleaned = term.strip()
        quoted = len(cleaned) > 1 and (cleaned[0], cleaned[-1]) in {('"','"'), ("'","'"), ('“','”')}
        if quoted:
            cleaned = cleaned[1:-1]
        normalize_accents=normalize_accents and not quoted
        def fold(value):
            return ''.join(char for char in unicodedata.normalize('NFD',value) if not unicodedata.combining(char)) if normalize_accents else value
        cleaned=fold(cleaned)
        self._check_access()
        if not cleaned or max_results <= 0:
            return []

        word_pattern = re.compile(
            r"(?<!\w)" + re.escape(cleaned) + r"(?!\w)", re.IGNORECASE
        )
        # Relação explícita assunto/projeto: todos os termos devem ocorrer;
        # não expandir por OR nem corrigir nomes próprios silenciosamente.
        related_words = [] if quoted or not re.search(r'\b(?:do|da|dos|das|sobre)\b', cleaned, re.I) else [
            word for word in re.findall(r'[^\W_]+', cleaned, re.UNICODE)
            if word.casefold() not in {'do','da','dos','das','de','sobre','o','a','os','as'}]
        patterns = [re.compile(r'(?<!\w)'+re.escape(word)+r'(?!\w)', re.I) for word in related_words]
        lexical_words=[] if quoted or not constrained else list(dict.fromkeys(word for word in re.findall(r'[^\W_]+',cleaned,re.UNICODE)
            if len(word)>1 and word.casefold() not in {'do','da','dos','das','de','sobre','os','as','um','uma','para','por','com','que','qual','como','em','no','na'}))[:12]
        lexical=[re.compile(r'(?<!\w)'+re.escape(word)+r'(?!\w)',re.I) for word in lexical_words] if len(lexical_words)>1 else []
        hint=fold(context_hint[:16000]) if constrained and isinstance(context_hint,str) else ''
        ranked = []
        visited_files = set()
        technical_roots = {os.path.normcase(os.path.join(self.vault_root,'10 - Projetos','Therion',name))
                           for name in ('tmp','tests')}

        if scope is None:
            roots = self.allowed_roots
        else:
            roots = effective_roots(scope, self.allowed_roots)

        for root in roots:
            canonical_root = os.path.realpath(root)
            if not any(self._is_subpath(canonical_root, allowed) for allowed in self.allowed_roots):
                continue
            if trace is not None:
                trace.used_roots.append(root)
            visited_dirs = set()
            for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
                self._check_access()
                if cancel_check:cancel_check()
                canonical_dir = os.path.realpath(dirpath)
                directory_id = os.path.normcase(canonical_dir)
                if not self._is_subpath(canonical_dir, canonical_root) or directory_id in visited_dirs:
                    dirnames[:] = []
                    continue
                visited_dirs.add(directory_id)
                # Junctions do Windows também podem atravessar raízes ou criar ciclos.
                dirnames[:] = sorted(
                    name for name in dirnames
                    # tmp guarda fixtures de teste (~22 mil .md em 04/11) e estourava o limite de 30 s da busca.
                    if name.casefold() not in {'.git','.venv','venv','node_modules','__pycache__',
                                              '.pytest_cache','.mypy_cache','.ruff_cache','tmp','.obsidian','.trash'}
                    and os.path.normcase(os.path.join(dirpath,name)) not in technical_roots
                    and not os.path.islink(os.path.join(dirpath, name))
                    and not getattr(os.path, 'isjunction', lambda _: False)(os.path.join(dirpath, name))
                    and self._is_subpath(os.path.realpath(os.path.join(dirpath, name)), canonical_root)
                )
                for filename in sorted(filenames):
                    self._check_access()
                    if cancel_check:cancel_check()
                    if not filename.lower().endswith(".md"):
                        continue

                    file_path = os.path.join(dirpath, filename)

                    checked_path = os.path.realpath(file_path)
                    if not self._is_subpath(checked_path, canonical_root) or not checked_path.lower().endswith('.md'):
                        continue
                    identity = os.path.normcase(checked_path)
                    if identity in visited_files:
                        continue
                    visited_files.add(identity)
                    relative_path = os.path.relpath(checked_path, self.vault_root).replace("\\", "/")

                    # Ler conteudo do arquivo
                    try:
                        if constrained:
                            info=os.stat(checked_path)
                            if info.st_nlink!=1 or info.st_size>20_000_000:
                                if trace is not None:trace.unavailable_files+=1
                                continue
                        with open(checked_path, "r", encoding="utf-8") as f:
                            content = f.read(20_000_001) if constrained else f.read()
                        if constrained and len(content)>20_000_000:
                            if trace is not None:trace.unavailable_files+=1
                            continue
                    except Exception:
                        if constrained and trace is not None:trace.unavailable_files+=1
                        continue

                    searchable=fold(content)
                    name=fold(os.path.splitext(os.path.basename(checked_path))[0])
                    content_match = word_pattern.search(searchable)
                    filename_match = word_pattern.search(fold(os.path.basename(checked_path)))
                    title_exact = fold(self._note_title(content)).casefold() == cleaned.casefold()
                    related_match = (2 <= len(patterns) <= 8 and all(
                        pattern.search(searchable) or pattern.search(fold(relative_path)) for pattern in patterns))
                    name_hits=0;body_hits=0
                    for pattern in lexical:
                        if cancel_check:cancel_check()
                        name_hits+=bool(pattern.search(name));body_hits+=bool(pattern.search(searchable))
                    lexical_match=bool(lexical and (name_hits or body_hits))
                    if not (title_exact or content_match or filename_match or related_match or lexical_match):
                        continue
                    category=0 if title_exact else 1 if filename_match else 2 if content_match else 3 if related_match else 4
                    hinted=bool(hint and len(name)>1 and re.search(r'(?<!\w)'+re.escape(name)+r'(?!\w)',hint,re.I))
                    rank=(category,-int(hinted),-name_hits,-body_hits)
                    context = ''
                    def original_span(match):
                        if not normalize_accents or len(searchable)==len(content):return match.start(),len(match[0])
                        cursor=0;start=None
                        for index,char in enumerate(content):
                            width=len(fold(char))
                            if start is None and cursor+width>match.start():start=index
                            cursor+=width
                            if cursor>=match.end():return start,index+1-start
                        raise ValueError('Não consegui mapear o trecho à fonte original.')
                    if content_match is not None:
                        start,length=original_span(content_match)
                        snippet = self._build_snippet(content, start, length, snippet_length)
                        context = self._section_context(content, start, length)
                    elif related_match and any(pattern.search(searchable) for pattern in patterns):
                        match = next(pattern.search(searchable) for pattern in patterns if pattern.search(searchable))
                        start,length=original_span(match)
                        snippet = self._build_snippet(content, start, length, snippet_length)
                        context = self._section_context(content, start, length)
                    elif lexical_match and body_hits:
                        # O nome já está no caminho. O trecho deve privilegiar
                        # o assunto buscado, em vez de repetir só o título.
                        match=next((pattern.search(searchable) for pattern in lexical if not pattern.search(name) and pattern.search(searchable)),None)
                        if match is None:match=next(pattern.search(searchable) for pattern in lexical if pattern.search(searchable))
                        start,length=original_span(match)
                        snippet=self._build_snippet(content,start,length,snippet_length)
                        context=self._section_context(content,start,length)
                    else:
                        snippet = "[Correspondencia no nome do arquivo]"
                    ranked.append((rank, relative_path.casefold(), relative_path,
                                   SearchResult(relative_path, snippet, hashlib.sha256(content.encode('utf-8')).hexdigest(), context, formation_context(content))))

        self._check_access()
        ranked.sort(key=lambda item: item[:3])
        return [item[3] for item in ranked[:max_results]]

    @staticmethod
    def _note_title(content: str) -> str:
        """Primeiro H1 fora de frontmatter e blocos de código."""
        frontmatter = False
        fence = None
        for index, line in enumerate(content.splitlines()):
            stripped = line.strip()
            if index == 0 and stripped == '---':
                frontmatter = True
                continue
            if frontmatter:
                if stripped in {'---', '...'}:
                    frontmatter = False
                continue
            marker = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
            if marker:
                run = marker.group(1)
                if fence is None:
                    fence = run
                elif run[0] == fence[0] and len(run) >= len(fence):
                    fence = None
                continue
            if fence is None:
                heading = re.match(r'^\s{0,3}#\s+(.+?)\s*$', line)
                if heading:
                    return re.sub(r'\s+#+\s*$', '', heading.group(1)).strip()
        return ''

    @staticmethod
    def _section_context(content, idx, term_length, budget=700):
        """Trecho com hierarquia Markdown, sem misturar a seção vizinha."""
        headings = list(re.finditer(r'(?m)^ {0,3}(#{1,6})\s+([^\n]+)', content))
        before = [heading for heading in headings if heading.start() <= idx]
        if not before:
            return ''
        selected = before[-1]
        depth = len(selected[1])
        end = next((heading.start() for heading in headings
                    if heading.start() > idx and len(heading[1]) <= depth), len(content))
        stack = []
        for heading in before:
            while stack and len(stack[-1][1]) >= len(heading[1]):
                stack.pop()
            stack.append(heading)
        prefix = '\n'.join(heading[0] for heading in stack[:-1])
        prefix = (prefix + '\n') if prefix else ''
        if len(prefix) > budget // 3:
            prefix = ''
        section = content[selected.start():end].strip()
        if len(prefix) + len(section) <= budget:
            return prefix + section
        # Se a seção for extensa, mantém o título e linhas ao redor da ocorrência.
        prefix += selected[0] + '\n'
        available = max(0, budget - len(prefix) - 8)
        start = max(selected.end(), idx - available // 2)
        stop = min(end, start + available)
        start = content.find('\n', start, idx) + 1 if '\n' in content[start:idx] else start
        return (prefix + '…\n' + content[start:stop].strip() + '\n…')[:budget]

    def _build_snippet(
        self,
        content: str,
        idx: int,
        term_length: int,
        snippet_length: int = 200,
    ) -> str:
        """Constroi um snippet legivel ao redor da ocorrencia encontrada."""
        start = max(0, idx - snippet_length // 2)
        end = min(len(content), idx + term_length + snippet_length // 2)

        # Ajustar start para nao comecar no meio de uma palavra
        if start > 0:
            space_pos = content.find(" ", start, start + 20)
            if space_pos != -1:
                start = space_pos + 1

        # Ajustar end para nao terminar no meio de uma palavra
        if end < len(content):
            space_pos = content.rfind(" ", end - 20, end)
            if space_pos != -1:
                end = space_pos

        snippet = content[start:end]
        snippet = " ".join(snippet.split())

        if start > 0:
            snippet = "..." + snippet
        if end < len(content):
            snippet = snippet + "..."

        return snippet
