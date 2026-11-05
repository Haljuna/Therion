"""Contratos determinísticos: conteúdo do modelo nunca é autorização."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json


OPERATIONS = frozenset({'open_app', 'close_app', 'remember_procedure', 'daily_summary', 'review_notes'})
VERSION = 'v4.1'


def utcnow():
    return datetime.now(timezone.utc)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':')).encode('utf-8')).hexdigest()


def timestamp(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError('Data de autorização sem fuso horário.')
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class AutonomyPolicy:
    id: str
    operation: str
    target: str
    revision: int
    authorization: str
    created_at: datetime
    expires_at: datetime
    context_version: str
    per_day: int = 10
    enabled: bool = False
    agent: str = 'Therion'

    @classmethod
    def parse(cls, row):
        if not isinstance(row, dict):
            raise ValueError('Política inválida.')
        required = ('id', 'operation', 'target', 'authorization', 'context_version')
        if any(not isinstance(row.get(k), str) or not row[k].strip() for k in required):
            raise ValueError('Política sem identificação, escopo ou autorização.')
        if (row['operation'] not in OPERATIONS or row.get('agent') != 'Therion'
                or type(row.get('enabled')) is not bool
                or type(row.get('revision')) is not int or row['revision'] < 1
                or type(row.get('per_day')) is not int or not 1 <= row['per_day'] <= 10):
            raise ValueError('Operação ou limites inválidos.')
        created, expires = timestamp(row['created_at']), timestamp(row['expires_at'])
        if not timedelta(0) < expires - created <= timedelta(days=7):
            raise ValueError('A autorização deve durar no máximo sete dias.')
        return cls(**{k: row[k] for k in required}, revision=row['revision'],
            created_at=created, expires_at=expires, per_day=row['per_day'],
            enabled=row['enabled'], agent=row['agent'])

    def as_dict(self):
        return dict(self.__dict__, created_at=self.created_at.isoformat(),
            expires_at=self.expires_at.isoformat())


@dataclass(frozen=True)
class AutonomyDecision:
    mode: str  # blocked | confirmation | autonomous
    reason: str
    policy_id: str = ''
    revision: int = 0
    snapshot: str = ''


@dataclass(frozen=True)
class ExecutionEvidence:
    id: str
    operation: str
    target: str
    context_version: str
    mode: str
    started_at: str
    status: str
    verified: bool
    policy_id: str = ''
    revision: int = 0

