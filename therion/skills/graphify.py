"""Graphify local: código do Therion, sem rede ou modelos externos."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

from therion.agent.contracts import ToolResult, ToolSpec
from therion.agent.registry import TEXT, object_schema
from therion.agent.execution import cooperative_call

HOME = Path(r"F:\Graphify")
CODE_ROOT = Path(__file__).resolve().parents[2]
EXTENSIONS = {'.py', '.js', '.ts', '.tsx', '.jsx', '.html', '.css', '.ps1', '.cmd'}
SKIP = {'.git', '.venv', '__pycache__', '.pytest_cache', 'tmp', 'logs', 'node_modules', 'graphify-out'}
GUIDE = """Graphify está disponível para mapear e consultar o código do Therion.
Para gerar o mapa, use graphify_prepare_build e aguarde confirmação visual.
Para consultar um mapa existente, use graphify_query com question.
O mapa é uma cópia derivada local: inferências não são fatos confirmados.
Somente código de therion/, tests/ e scripts/ é incluído. Não lê notas pessoais.
Não usa Cloud, API, Ollama, hooks, vigilância ou alteração automática do código.
A skill oficial está em ~/.codex/skills/graphify/SKILL.md.
Outros projetos ou documentos exigem uma integração e escopo próprios.
"""


def linked(path):
    return path.is_symlink() or bool(path.lstat().st_file_attributes & 1024) if os.name == 'nt' else path.is_symlink()


class GraphifySkill:
    SKILL_ID = 'graphify'

    def __init__(self, root=None, home=None):
        self.root = Path(root) if root else CODE_ROOT
        self.home = Path(home) if home else HOME
        self.python = self.home/'venv'/'Scripts'/'python.exe'

    def available(self):
        return self.python.is_file()

    def sources(self):
        if linked(self.root):
            raise ValueError('Raiz de código contém redirecionamento.')
        rows = {}
        for folder in ('therion', 'tests', 'scripts'):
            base = self.root/folder
            if not base.exists():
                continue
            if linked(base):
                raise ValueError('Pasta de código contém redirecionamento.')
            for current, dirs, files in os.walk(base, followlinks=False):
                dirs[:] = sorted(d for d in dirs if d not in SKIP and not linked(Path(current)/d))
                for name in sorted(files):
                    path = Path(current)/name
                    if path.suffix.lower() not in EXTENSIONS or linked(path) or not path.is_file():
                        continue
                    if path.stat().st_size > 2_000_000:
                        raise ValueError('Arquivo de código acima do limite de 2 MB.')
                    rows[path.relative_to(self.root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
                    if len(rows) > 10000:
                        raise ValueError('Projeto acima do limite de 10000 arquivos.')
        if not rows:
            raise ValueError('Nenhum código elegível encontrado.')
        return rows

    def version(self):
        return hashlib.sha256(json.dumps(self.sources(), sort_keys=True).encode()).hexdigest()

    def run(self, args, token, cwd):
        token.check()
        env = dict(os.environ, GRAPHIFY_NO_TIPS='1', GRAPHIFY_NO_CTA='1', PYTHONUTF8='1')
        # Saída em arquivo temporário evita bloqueio de pipe e crescimento de memória.
        with tempfile.TemporaryFile() as output:
            process = subprocess.Popen([str(self.python), '-m', 'graphify', *args], cwd=cwd,
                env=env, stdout=output, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            deadline = time.monotonic()+120
            try:
                while process.poll() is None:
                    token.check()
                    if time.monotonic() > deadline:
                        raise TimeoutError('Graphify excedeu 120 segundos.')
                    time.sleep(.05)
                token.check()
                output.seek(0)
                text = output.read(12000).decode('utf-8', errors='replace')
                if process.returncode:
                    raise ValueError('Graphify falhou: '+text[-2000:])
                return text
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)

    def build(self, expected, token):
        if self.version() != expected:
            raise ValueError('Código mudou após a prévia. Prepare uma nova.')
        destination = self.home/'graphs'/uuid.uuid4().hex
        destination.mkdir(parents=True)
        with tempfile.TemporaryDirectory(prefix='graphify-code-') as staging:
            staging = Path(staging)
            for relative, digest in self.sources().items():
                token.check()
                data = (self.root/relative).read_bytes()
                if hashlib.sha256(data).hexdigest() != digest:
                    raise ValueError('Código mudou durante a cópia.')
                target = staging/relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            if self.version() != expected:
                raise ValueError('Código mudou durante a cópia.')
            self.run(['extract', str(staging), '--code-only', '--max-workers', '1', '--out', str(destination)], token, staging)
        graph = destination/'graphify-out'/'graph.json'
        if not graph.is_file():
            raise ValueError('Graphify não produziu graph.json.')
        token.check()
        if self.version() != expected:
            raise ValueError('Código mudou durante a geração. Mapa não publicado.')
        manifest = {'graph':str(graph), 'source':str(self.root), 'version':expected,
            'mode':'code-only', 'source_paths':'relative to source root; snapshot paths are temporary'}
        pending = self.home/('current-'+uuid.uuid4().hex+'.tmp')
        pending.write_text(json.dumps(manifest), encoding='utf-8')
        pending.replace(self.home/'therion-current.json')
        return manifest

    def query(self, question, token):
        manifest_path = self.home/'therion-current.json'
        if not manifest_path.is_file():
            return ToolResult('unavailable', message='Ainda não existe mapa. Peça para gerar o mapa Graphify do Therion e confirme a prévia.')
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        graph = Path(manifest['graph']).resolve()
        if not graph.is_relative_to((self.home/'graphs').resolve()) or not graph.is_file():
            return ToolResult('blocked', message='Mapa fora do armazenamento Graphify.')
        if manifest['version'] != self.version():
            return ToolResult('unavailable', message='Mapa desatualizado. Gere uma nova prévia; não trate resultados antigos como atuais.')
        text = self.run(['query', question, '--graph', str(graph)], token, self.home)
        token.check()
        if manifest['version'] != self.version():
            return ToolResult('unavailable', message='Código mudou durante a consulta.')
        return ToolResult('success', data={'result':text, 'source_root':str(self.root),
            'snapshot_paths_are_temporary':True}, message='Relações INFERRED são inferências do Graphify.',
            evidence=({'id':'graphify:therion','source':str(graph),'version':manifest['version']},))


def register_graphify_tools(registry, host, *, requested=False):
    skill = GraphifySkill()
    async def guide(args, token):
        token.check()
        return ToolResult('success', data={'instructions':GUIDE, 'installed':skill.available()})
    registry.register(ToolSpec('graphify_skill', 'Ler instruções e disponibilidade da skill Graphify local.', object_schema(), guide,
        authorize=lambda args:True))
    if not requested or not skill.available():
        return
    async def prepare(args, token):
        token.check()
        version = await cooperative_call(skill.version, token=token)
        preview = 'Gerar mapa Graphify do código do Therion\nFonte: '+str(skill.root)+'\nDestino: '+str(skill.home/'graphs')+'\nSomente código local; sem modelos ou envio externo. Cópia derivada; código original preservado.'
        row = host._agent_proposals.prepare('graphify.build', {'version':version}, preview,
            lambda row, cancel:skill.build(row['version'], cancel),
            lambda row, value, cancel:Path(value['graph']).is_file() and skill.version()==row['version'],
            lambda row, cancel:skill.available() and skill.version()==row['version'],
            token_aware=True, preparation_token=token)
        return ToolResult('awaiting_confirmation', data={'proposal_id':row.id},
            message='Revise a prévia Graphify no painel Capacidades.', side_effect_state='pending')
    async def query(args, token):
        return await cooperative_call(skill.query, args['question'], token, token=token)
    registry.register(ToolSpec('graphify_prepare_build', 'Preparar mapa local do código do Therion para confirmação visual.',
        object_schema(), prepare, effect='prepare', authorize=lambda args:True, timeout=150))
    registry.register(ToolSpec('graphify_query', 'Consultar o mapa Graphify atual do código do Therion; se ausente, preparar geração.',
        object_schema(question=TEXT), query, authorize=lambda args:True, timeout=150))
