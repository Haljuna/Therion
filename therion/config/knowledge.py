"""Ativação explícita do contrato V3, preservando os demais campos do host."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import uuid
from therion.memory.knowledge import MemoryError, safe_path
from therion.memory.runtime import access_from_config


def configuration_proposal(path, vault, authorization, expires_at, *, read_all, supervised_memory):
    path=Path(path).absolute()
    safe_path(path,(str(path.parent),))
    if not path.is_file() or path.stat().st_nlink != 1 or path.stat().st_size > 1000000:
        raise MemoryError('Configuração existente não é arquivo regular dentro do limite.')
    original=path.read_bytes()
    config=json.loads(original)
    if not isinstance(config,dict):
        raise MemoryError('A configuração precisa ser um objeto JSON válido; não apliquei defaults.')
    updated=deepcopy(config)
    revision=config.get('knowledge_access',{}).get('revision',0) if isinstance(config.get('knowledge_access',{}),dict) else 0
    updated['knowledge_access']=dict(read_all=read_all,supervised_memory=supervised_memory,
        authorization=authorization,expires_at=expires_at,revision=revision+1 if type(revision) is int else 1)
    access=access_from_config(updated,vault,datetime.now(timezone.utc))
    if not access.authorized:
        raise MemoryError('Contrato de acesso inválido ou vencido; nada foi alterado.')
    return dict(path=str(path),vault=str(Path(vault).absolute()),
        sha256=hashlib.sha256(original).hexdigest(),original=original,updated=updated,
        policy=updated['knowledge_access'])


def apply_configuration(proposal, expected_sha256):
    path=Path(proposal['path'])
    safe_path(path,(str(path.parent),))
    if expected_sha256 != proposal['sha256'] or path.read_bytes() != proposal['original']:
        raise MemoryError('A configuração mudou desde a prévia. Prepare outra proposta.')
    # Validar também a expiração antes da publicação.
    if not access_from_config(proposal['updated'],proposal['vault'],datetime.now(timezone.utc)).authorized:
        raise MemoryError('A proposta venceu; nada foi alterado.')
    backup=path.with_name('config-before-v3-'+uuid.uuid4().hex+'.json')
    with backup.open('xb') as output:
        output.write(proposal['original'])
    descriptor,temp=tempfile.mkstemp(dir=path.parent,prefix='.knowledge-v3-',suffix='.tmp')
    try:
        with os.fdopen(descriptor,'w',encoding='utf-8') as output:
            json.dump(proposal['updated'],output,ensure_ascii=False,indent=2)
            output.flush();os.fsync(output.fileno())
        if path.read_bytes()!=proposal['original']:
            raise MemoryError('Configuração alterada durante o preparo; não publiquei a mudança.')
        os.replace(temp,path)
        if json.loads(path.read_bytes()) != proposal['updated']:
            raise MemoryError('Não confirmei a configuração publicada; não repeti.')
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return str(backup)
