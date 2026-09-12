"""Camada de acesso e leitura seletiva do Segundo Cérebro para a V0."""

import os
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class ReadResult:
    """Resultado estruturado de uma operação de leitura seletiva."""

    success: bool
    path: str
    canonical_path: Optional[str] = None
    content: Optional[str] = None
    error: Optional[str] = None


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

    def resolve_and_validate(self, requested_path: str) -> str:
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
        if not any(
            self._is_subpath(candidate, root) for root in self.allowed_roots
        ):
            raise PermissionError(
                f"Acesso negado: o caminho '{clean_path}' está fora das raízes autorizadas do Segundo Cérebro."
            )

        return candidate

    def read_note(self, requested_path: str) -> ReadResult:
        """Lê o conteúdo de uma nota Markdown dentro do escopo autorizado."""
        try:
            canonical_path = self.resolve_and_validate(requested_path)
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
