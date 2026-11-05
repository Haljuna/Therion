"""Políticas locais explícitas, sem concessão por texto ou pelo modelo."""
from copy import deepcopy
from datetime import timedelta
import threading
import uuid
import sqlite3

from .policy import AutonomyPolicy, AutonomyDecision, fingerprint, utcnow


class AutonomyRuntime:
    def __init__(self, store, config_loader, config_writer=None, clock=utcnow):
        self.store, self.loader, self.writer, self.clock = store, config_loader, config_writer, clock
        self.lock = threading.RLock()

    def section(self):
        config = self.loader()
        section = config.get('autonomy', {}) if isinstance(config, dict) else {}
        if not isinstance(section, dict):
            raise ValueError('Configuração de autonomia inválida.')
        return section

    def policies(self):
        rows = self.section().get('policies', [])
        if not isinstance(rows, list):
            raise ValueError('Lista de políticas inválida.')
        policies = [AutonomyPolicy.parse(row) for row in rows]
        keys = [(p.operation, p.target) for p in policies]
        if len(set(keys)) != len(keys):
            raise ValueError('Políticas duplicadas para a mesma operação.')
        return policies

    def decide(self, operation, target, version, *, permitted, explicit=True):
        if not permitted:
            return AutonomyDecision('blocked', 'Operação ou acesso não autorizado.')
        if not explicit:
            return AutonomyDecision('blocked', 'O gatilho não foi autorizado.')
        try:
            policies = self.policies()
            if self.store.state('paused') == '1':
                return AutonomyDecision('confirmation', 'Autonomia pausada.')
            if self.store.state('incident:'+operation+':'+target):
                return AutonomyDecision('confirmation', 'Incidente requer revisão visual.')
            policy = next((p for p in policies if p.operation == operation and p.target == target), None)
            if policy is None or not policy.enabled:
                return AutonomyDecision('confirmation', 'Operação supervisionada.')
            if not policy.created_at <= self.clock() < policy.expires_at:
                return AutonomyDecision('confirmation', 'Autorização vencida ou ainda não válida.')
            if policy.context_version != version:
                return AutonomyDecision('confirmation', 'Implementação, modelo ou escopo mudou.')
            if operation != 'open_app' and not self.store.ready(operation, target, version):
                return AutonomyDecision('confirmation', 'Evidências insuficientes para autonomia.')
            return AutonomyDecision('autonomous', 'Autorização específica vigente.',
                policy.id, policy.revision, fingerprint(self.section()))
        except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
            return AutonomyDecision('confirmation', 'Não confirmei a política de autonomia.')

    def begin(self, operation, target, version, decision, *, permitted, explicit=True, simulation=False):
        with self.lock:
            if simulation:
                return self.store.begin(operation, target, version, 'simulation')
            if decision.mode == 'blocked' or not permitted:
                raise ValueError('Operação não autorizada.')
            policy = None
            if decision.mode == 'autonomous':
                current = self.decide(operation, target, version, permitted=permitted, explicit=explicit)
                if current != decision:
                    raise ValueError('A autorização mudou; a execução foi interrompida.')
                policy = next(p for p in self.policies() if p.id == decision.policy_id)
            return self.store.begin(operation, target, version,
                'autonomous' if policy else 'supervised', policy, policy.per_day if policy else 10)

    def _update(self, update):
        if self.writer is None:
            raise ValueError('Este host não permite persistir alterações de autonomia.')
        with self.lock:
            config = deepcopy(self.loader())
            if not isinstance(config, dict):
                raise ValueError('Configuração inválida.')
            original = deepcopy(config)
            section = config.setdefault('autonomy', {})
            if not isinstance(section, dict):
                raise ValueError('Configuração de autonomia inválida.')
            update(section)
            if self.loader() != original:
                raise ValueError('A configuração mudou durante o preparo. Não publiquei a alteração.')
            self.writer(config)
            if self.loader().get('autonomy') != section:
                raise ValueError('Não confirmei a persistência da configuração.')

    def grant(self, operation, target, version, authorization, per_day=10):
        """Chamado somente pelo painel após confirmação visual da prévia."""
        if operation != 'open_app' and not self.store.ready(operation, target, version):
            raise ValueError('São necessários dez sucessos supervisionados ao longo de sete dias.')
        if self.store.state('incident:'+operation+':'+target):
            raise ValueError('Revise o incidente antes de autorizar.')
        now = self.clock()
        previous = next((p for p in self.policies() if (p.operation,p.target)==(operation,target)), None)
        policy = AutonomyPolicy(uuid.uuid4().hex, operation, target,
            previous.revision+1 if previous else 1, authorization, now, now+timedelta(days=7),
            version, per_day, True)
        AutonomyPolicy.parse(policy.as_dict())
        def update(section):
            rows = section.setdefault('policies', [])
            rows[:] = [p for p in rows if (p['operation'],p['target']) != (operation,target)] + [policy.as_dict()]
        self._update(update)
        return policy

    def revoke(self, operation, target):
        def update(section):
            for row in section.get('policies', []):
                if (row.get('operation'),row.get('target')) == (operation,target):
                    row['enabled'] = False
                    row['revision'] += 1
        self._update(update)

    def pause(self, paused=True):
        with self.lock:
            self.store.set_state('paused', '1' if paused else '0')

