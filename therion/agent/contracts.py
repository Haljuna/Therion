"""Contratos operacionais; conteúdo do modelo não representa autoridade."""
from dataclasses import dataclass, field
from typing import Any, Callable
import json
import threading
import time
import uuid


class AgentError(ValueError):
    pass


class ProviderUnavailable(AgentError):
    """Falha operacional do provider, não uma decisão malformada do modelo."""
    pass


class Cancelled(AgentError):
    pass


class CancellationToken:
    def __init__(self, event=None, *, parent=None):
        self.event = event if event is not None else threading.Event()
        self.parent = parent

    def cancel(self):
        self.event.set()

    def set(self):self.cancel()

    def is_set(self):return self.cancelled

    @property
    def cancelled(self):
        return self.event.is_set() or bool(self.parent and self.parent.cancelled)

    def check(self):
        if self.cancelled:
            raise Cancelled('Pedido cancelado.')


@dataclass(frozen=True)
class TurnBudget:
    seconds: float = 180
    iterations: int = 8
    context_tokens: int = 8192
    output_tokens: int = 2048
    calls: int = 32

    def __post_init__(self):
        if not (0 < self.seconds <= 1800 and 1 <= self.iterations <= 32
                and 1024 <= self.context_tokens <= 32768
                and 0 < self.output_tokens < self.context_tokens
                and type(self.calls) is int and 1 <= self.calls <= 128):
            raise AgentError('Orçamento de turno inválido.')


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    @property
    def fingerprint(self):
        return json.dumps([self.name, self.arguments], sort_keys=True, ensure_ascii=False, allow_nan=False)


@dataclass(frozen=True)
class AgentDecision:
    kind: str
    message: str = ''
    calls: tuple[ToolCall, ...] = ()

    @classmethod
    def parse(cls, row):
        if not isinstance(row, dict) or set(row) - {'kind', 'message', 'calls'}:
            raise AgentError('Decisão com campos inválidos.')
        kind, message = row.get('kind'), row.get('message', '')
        if kind not in {'final', 'clarification', 'tools'} or not isinstance(message, str) or len(message) > 16000:
            raise AgentError('Decisão inválida.')
        calls = row.get('calls', [])
        if not isinstance(calls, list) or len(calls) > 4:
            raise AgentError('Lista de chamadas inválida.')
        result = []
        for item in calls:
            if (not isinstance(item, dict) or set(item) != {'name', 'arguments'}
                    or not isinstance(item['name'], str) or not isinstance(item['arguments'], dict)):
                raise AgentError('Chamada de ferramenta inválida.')
            result.append(ToolCall(item['name'], item['arguments']))
        if (kind == 'tools') != bool(result) or (kind != 'tools' and not message.strip()):
            raise AgentError('Decisão sem conteúdo correspondente.')
        return cls(kind, message, tuple(result))


@dataclass(frozen=True)
class ToolResult:
    status: str
    data: Any = None
    evidence: tuple[dict, ...] = ()
    message: str = ''
    side_effect_state: str = 'none'
    issue_key: str = ''
    resolves: tuple[str,...] = ()

    def __post_init__(self):
        if self.status not in {'success', 'failed', 'unavailable', 'blocked', 'cancelled', 'uncertain', 'awaiting_confirmation','awaiting_clarification'}:
            raise AgentError('Estado de resultado inválido.')
        if self.side_effect_state not in {'none', 'pending', 'verified', 'uncertain'}:
            raise AgentError('Estado de efeito inválido.')
        if not isinstance(self.issue_key,str) or len(self.issue_key)>256 or not isinstance(self.resolves,tuple) or len(self.resolves)>10 or any(not isinstance(key,str) or len(key)>256 for key in self.resolves):
            raise AgentError('Identificador de recuperação inválido.')

    def observation(self):
        return dict(status=self.status, data=self.data, evidence=list(self.evidence),
                    message=self.message, side_effect_state=self.side_effect_state,issue_key=self.issue_key,resolves=list(self.resolves))


def current_evidence(references):
    """Conserva IDs das versões atuais; não publica fonte substituída no turno."""
    rows=[row for row in references if isinstance(row,dict)]
    versions={row.get('source'):row.get('version') for row in rows if row.get('version')}
    selected={}
    for row in rows:
        if row.get('version') and versions.get(row.get('source'))!=row['version']:continue
        selected[json.dumps(row,sort_keys=True,ensure_ascii=False)]=row
    return tuple(selected.values())


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict
    handler: Callable
    effect: str = 'read'
    version: str = '1'
    available: Callable = lambda: True
    authorize: Callable = lambda arguments: False
    verify: Callable | None = None
    timeout: float = 30
    parameters_factory: Callable | None = None

    def __post_init__(self):
        import re
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',self.name) or not isinstance(self.description,str) or len(self.description)>1000:
            raise AgentError('Identidade de ferramenta inválida.')
        if not callable(self.handler) or not isinstance(self.parameters,dict) or not 0<self.timeout<=300:
            raise AgentError('Contrato de ferramenta inválido.')

    def argument_schema(self):
        return self.parameters_factory() if self.parameters_factory else self.parameters

    def schema(self):
        return {'type': 'function', 'function': {
            'name': self.name, 'description': self.description, 'parameters': self.argument_schema()}}


@dataclass(frozen=True)
class AgentEvent:
    sequence: int
    session_id: str
    turn_id: str
    generation: int
    type: str
    payload: dict


@dataclass(frozen=True)
class TurnResult:
    status: str
    message: str
    turn_id: str
    results: tuple[tuple[ToolCall, ToolResult], ...] = ()
    elapsed: float = 0
