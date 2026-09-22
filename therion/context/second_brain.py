"""Camada de acesso e leitura seletiva do Segundo Cérebro para a V0."""

import os
from dataclasses import dataclass
from typing import List, Optional

from therion.context.read_scope import ReadScope, effective_roots


@dataclass
class ReadResult:
    """Resultado estruturado de uma operação de leitura seletiva."""

    success: bool
    path: str
    canonical_path: Optional[str] = None
    content: Optional[str] = None
    error: Optional[str] = None


@dataclass
class SearchResult:
    """Resultado de uma busca textual no Segundo Cérebro."""

    path: str
    snippet: str


class SecondBrainReader:
    """Leitor controlado e seletivo do Segundo Cérebro."""

    DEFAULT_VAULT_ROOT = r"C:\Users\marcu\Downloads\Segundo-Cerebro"

    def __init__(
        self,
        vault_root: Optional[str] = None,
        allowed_roots: Optional[List[str]] = None,
    ) -> None:
        self.vault_root = os.path.abspath(vault_root or self.DEFAULT_VAULT_ROOT)

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
        """Normaliza e valida o caminho, aplicando as regras de contenção e tipo."""
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
            validated_path = candidate
        else:
            roots = effective_roots(scope, self.allowed_roots)
            validated_path = os.path.realpath(candidate)

        if not any(
            self._is_subpath(validated_path, root) for root in roots
        ):
            raise PermissionError(
                f"Acesso negado: o caminho '{clean_path}' está fora das raízes autorizadas do Segundo Cérebro."
            )

        return candidate

    def read_note(
        self, requested_path: str, scope: Optional[ReadScope] = None
    ) -> ReadResult:
        """Lê o conteúdo de uma nota Markdown dentro do escopo autorizado."""
        try:
            canonical_path = self.resolve_and_validate(requested_path, scope)
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
            with open(canonical_path, "r", encoding="utf-8") as file_handle:
                content = file_handle.read()

            return ReadResult(
                success=True,
                path=requested_path,
                canonical_path=canonical_path,
                content=content,
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
    ) -> List[SearchResult]:
        """Busca termo em nomes e conteúdo de arquivos .md dentro das raízes autorizadas.

        Busca literal e case-insensitive. Retorna no máximo max_results resultados.
        Interrrompe varredura assim que max_results são encontrados.
        """
        cleaned = term.strip()
        if not cleaned:
            return []

        term_lower = cleaned.lower()
        results: List[SearchResult] = []

        if scope is None:
            roots = self.allowed_roots
        else:
            roots = effective_roots(scope, self.allowed_roots)

        for root in roots:
            if len(results) >= max_results:
                break
            for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
                if len(results) >= max_results:
                    break
                for filename in filenames:
                    if len(results) >= max_results:
                        break
                    if not filename.lower().endswith(".md"):
                        continue

                    file_path = os.path.join(dirpath, filename)

                    if scope is None:
                        checked_path = file_path
                    else:
                        checked_path = os.path.realpath(file_path)
                    if not self._is_subpath(checked_path, root):
                        continue

                    relative_path = os.path.relpath(file_path, self.vault_root).replace("\\", "/")

                    # Ler conteudo do arquivo
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            content = f.read()
                    except Exception:
                        continue

                    content_lower = content.lower()
                    content_idx = content_lower.find(term_lower)

                    # Match no conteudo (prioridade)
                    if content_idx != -1:
                        snippet = self._build_snippet(content, content_idx, len(cleaned))
                        results.append(
                            SearchResult(path=relative_path, snippet=snippet)
                        )
                        continue

                    # Match somente no nome do arquivo (fallback)
                    if term_lower in filename.lower():
                        results.append(
                            SearchResult(
                                path=relative_path,
                                snippet="[Correspondencia no nome do arquivo]",
                            )
                        )

        return results

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
