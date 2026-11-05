"""Coordenação volátil. Executores são injetados; este módulo não concede acesso."""
from dataclasses import dataclass, replace
import threading
import uuid


@dataclass(frozen=True)
class StepReceipt:
    index: int
    action: str
    state: str = 'pending'
    message: str = ''
    speech: str = ''
    evidence: object = None


@dataclass(frozen=True)
class WorkflowSnapshot:
    id: str
    session_id: str
    state: str
    receipts: tuple[StepReceipt, ...]


class WorkflowRuntime:
    def __init__(self):
        self._lock = threading.RLock()
        self._active = None
        self._last = None
        self._cancel = threading.Event()

    def snapshot(self):
        with self._lock:
            return self._active or self._last

    @property
    def active(self):
        with self._lock:
            return self._active is not None

    def cancel(self):
        self._cancel.set()  # Não adquire o bloqueio da operação principal.

    def clear(self):
        self.cancel()
        with self._lock:
            self._active = self._last = None

    def _update(self, snapshot):
        with self._lock:
            if self._active is not None and self._active.id == snapshot.id:
                self._active = snapshot

    def _finish(self, snapshot):
        with self._lock:
            if self._active is not None and self._active.id == snapshot.id:
                self._last, self._active = snapshot, None
        return snapshot

    def run(self, spec, session_id, execute, cancelled=None):
        with self._lock:
            if self._active is not None:
                raise ValueError('Já há um pedido composto ativo nesta sessão.')
            self._cancel = threading.Event()
            cancellation = self._cancel
            snapshot = WorkflowSnapshot(uuid.uuid4().hex, session_id, 'running',
                tuple(StepReceipt(i, step.action) for i, step in enumerate(spec.steps)))
            self._active = snapshot
        for i, step in enumerate(spec.steps):
            rows = list(snapshot.receipts)
            if cancellation.is_set() or (cancelled is not None and cancelled.is_set()):
                rows[i:] = [replace(row, state='cancelled') for row in rows[i:]]
                return self._finish(replace(snapshot, state='cancelled', receipts=tuple(rows)))
            if any(rows[index].state != 'completed' for index in step.depends_on):
                rows[i] = replace(rows[i], state='blocked', message='Não executei: a etapa de origem não forneceu resultado válido.')
                snapshot = replace(snapshot, receipts=tuple(rows))
                self._update(snapshot)
                continue
            rows[i] = replace(rows[i], state='running')
            snapshot = replace(snapshot, receipts=tuple(rows))
            self._update(snapshot)
            try:
                result, evidence = execute(step, i, tuple(rows))
                state = ('completed' if result.status == 'success' else
                    'awaiting_confirmation' if result.status == 'awaiting_confirmation' else
                    'awaiting_clarification' if result.status == 'clarification' else
                    'uncertain' if result.status == 'uncertain' else 'failed')
                receipt = replace(rows[i], state=state, message=result.message,
                    speech=result.speech_message or '', evidence=evidence)
            except Exception:
                receipt = replace(rows[i], state='failed', message='Não consegui concluir esta etapa.')
            rows[i] = receipt
            snapshot = replace(snapshot, receipts=tuple(rows))
            self._update(snapshot)
            if receipt.state == 'awaiting_confirmation':
                if cancellation.is_set() or (cancelled is not None and cancelled.is_set()):
                    rows[i] = replace(rows[i], state='cancelled')
                    return self._finish(replace(snapshot, state='cancelled', receipts=tuple(rows)))
                snapshot = replace(snapshot, state='awaiting_confirmation')
                self._update(snapshot)
                return snapshot
            if receipt.state in {'uncertain', 'awaiting_clarification'}:
                rows[i+1:] = [replace(row, state='blocked') for row in rows[i+1:]]
                return self._finish(replace(snapshot, state=receipt.state, receipts=tuple(rows)))
        state = 'completed' if all(row.state == 'completed' for row in snapshot.receipts) else 'partial'
        if cancellation.is_set() or (cancelled is not None and cancelled.is_set()):
            state = 'cancelled'
        return self._finish(replace(snapshot, state=state))

    def calendar_result(self, result):
        with self._lock:
            current = self._active
            if current is None or current.state != 'awaiting_confirmation':
                return None
            rows = list(current.receipts)
            state = ('awaiting_confirmation' if result.status == 'awaiting_confirmation' else
                'completed' if result.status == 'success' else
                'cancelled' if result.status == 'cancelled' else
                'uncertain' if 'pode ter sido criado' in result.message else 'failed')
            rows[-1] = replace(rows[-1], state=state, message=result.message, speech=result.speech_message or '')
            snapshot = replace(current, receipts=tuple(rows), state=state)
            if state == 'completed' and any(row.state != 'completed' for row in rows):
                snapshot = replace(snapshot, state='partial')
            if state == 'awaiting_confirmation':
                self._active = snapshot
            else:
                self._last, self._active = snapshot, None
            return snapshot

    def abandon(self):
        self.cancel()
        with self._lock:
            if self._active is not None:
                rows = tuple(replace(row, state='cancelled') if row.state in {'pending', 'running', 'awaiting_confirmation'} else row
                    for row in self._active.receipts)
                self._last = replace(self._active, state='cancelled', receipts=rows)
                self._active = None


def render_workflow(snapshot):
    labels = {'completed':'concluída', 'failed':'falhou', 'blocked':'bloqueada', 'cancelled':'cancelada',
        'awaiting_confirmation':'aguardando confirmação', 'awaiting_clarification':'precisa de esclarecimento',
        'uncertain':'resultado incerto', 'running':'em andamento', 'pending':'pendente'}
    heading = {'completed':'Concluí as etapas deste pedido.', 'partial':'Concluí parte do pedido.',
        'cancelled':'Cancelei as etapas restantes. Operações concluídas não foram desfeitas.',
        'awaiting_confirmation':'Preparei o pedido; a criação do evento aguarda sua confirmação.',
        'uncertain':'O resultado da operação é incerto. Não vou repeti-la automaticamente.',
        'awaiting_clarification':'Preciso de esclarecimento para concluir o pedido.'}.get(snapshot.state, 'Pedido em andamento.')
    detail = '\n\n'.join(f'{row.index+1}. {labels[row.state]}\n{row.message}' for row in snapshot.receipts)
    speech = heading
    for row in snapshot.receipts:
        if row.speech:
            # Reservar espaço para a pergunta da proposta final, mesmo com cinco etapas.
            if row.state == 'awaiting_confirmation':
                speech += ' ' + row.speech[:450]
                if not speech.rstrip().endswith('?'):
                    speech += ' Confirmar?'
            else:
                speech += ' ' + row.speech[:220]
        elif row.state in {'failed','blocked','uncertain'}:
            speech += f' A etapa {row.index+1} {labels[row.state]}.'
    return heading + '\n\n' + detail, speech[:1800]
