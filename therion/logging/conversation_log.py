"""Nota local da conversa, para analisar erros de interpretação e voz depois.

Fica fora do Segundo Cérebro (%LOCALAPPDATA%\\Therion\\conversas), uma nota por sessão,
gravada a cada mensagem para sobreviver a quedas. Falha de disco nunca afeta o Therion.
"""
import os
import re
import time
from datetime import datetime
from pathlib import Path

_NAME = re.compile(r'\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}(?:-\d+)?\.md')


def default_folder():
    base = os.environ.get('LOCALAPPDATA') or str(Path.home())
    return Path(base) / 'Therion' / 'conversas'


def _quote(text):
    """Primeira linha junto do rótulo; demais como citação, para listas não virarem títulos."""
    lines = str(text).replace('\r\n', '\n').strip().split('\n')
    return lines[0] + ''.join('\n> ' + line for line in lines[1:])


class ConversationLog:
    def __init__(self, folder=None, *, enabled=True, keep_days=60, now=datetime.now):
        self.folder = Path(folder) if folder is not None else default_folder()
        self.enabled = enabled
        self.now = now
        self.failed = False
        self.path = None
        self._last_screen = None
        if enabled:
            self._guard(self._prune, keep_days)

    def _guard(self, function, *args):
        try:
            function(*args)
        except Exception:  # registro é auxiliar: nunca interrompe a conversa
            self.failed = True

    def _prune(self, keep_days):
        if not self.folder.is_dir():
            return
        limit = time.time() - keep_days * 86400
        for path in self.folder.iterdir():
            # Só apaga notas com o nome deste registro; nada mais na pasta é tocado.
            if path.is_file() and _NAME.fullmatch(path.name) and path.stat().st_mtime < limit:
                path.unlink()

    def _open_note(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        try:
            from therion.agent.security import restrict_directory
            restrict_directory(self.folder)
        except Exception:
            pass  # a pasta já fica no perfil do usuário; permissões extras são opcionais
        stamp = self.now()
        name = stamp.strftime('%Y-%m-%d_%H-%M-%S')
        path, index = self.folder / (name + '.md'), 1
        while path.exists():
            path, index = self.folder / f'{name}-{index}.md', index + 1
        path.write_text(f"# Conversa com o Therion — {stamp.strftime('%d/%m/%Y %H:%M')}\n\n"
                        "Registro local para análise de erros. Não é nota oficial.\n", encoding='utf-8')
        self.path = path

    def _write(self, block):
        if self.path is None:
            self._open_note()
        with self.path.open('a', encoding='utf-8') as stream:
            stream.write(block)

    def user(self, text, *, channel):
        if not self.enabled:
            return
        self._last_screen = None
        stamp = self.now().strftime('%H:%M:%S')
        self._guard(self._write, f"\n## {stamp} · {channel}\n**Você:** {_quote(text)}\n")

    def therion(self, text):
        if not self.enabled:
            return
        self._last_screen = str(text).strip()
        self._guard(self._write, f"**Therion (tela):** {_quote(text)}\n")

    def result(self, *, spoken, status, route, seconds):
        if not self.enabled:
            return
        lines = ''
        if spoken and str(spoken).strip() != self._last_screen:
            lines += f"**Therion (falou):** {_quote(spoken)}\n"
        timing = f'{seconds:.1f}'.replace('.', ',') + ' s' if isinstance(seconds, (int, float)) else '—'
        lines += f"`rota: {route or 'IA/conversa'} · status: {status} · {timing}`\n"
        self._guard(self._write, lines)

    def rotate(self):
        """Encerra a nota atual; a próxima mensagem abre outra (ex.: Limpar conversa)."""
        self.path = None
        self._last_screen = None
