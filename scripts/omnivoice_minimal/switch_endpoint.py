"""Troca temporária de um único campo, com backup e reversão sem perder outras opções."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from urllib.request import build_opener, ProxyHandler

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from therion.config.local import _validate_config

OLD = 'http://127.0.0.1:3900/v1/audio/speech'
NEW = 'http://127.0.0.1:3901/v1/audio/speech'


def switch(mode, config, runtime):
    config, runtime = Path(config), Path(runtime)
    backup = runtime/'config-before-minimal.json'
    before = config.read_bytes()
    data = json.loads(before.decode('utf-8-sig'))
    if data['tts']['provider'] != 'voicestudio' or data['tts']['voicestudio_voice'] != '120f734a':
        raise ValueError('Provedor/perfil mudou; a troca automática foi bloqueada')
    current = data['tts']['voicestudio_endpoint']
    expected, target = (OLD, NEW) if mode == 'activate' else (NEW, OLD)
    if current == target:
        return {'status':'already_selected', 'endpoint': target}
    if current != expected:
        raise ValueError('Endpoint inesperado; nenhuma configuração foi alterada')
    if mode == 'activate':
        client = build_opener(ProxyHandler({}))
        with client.open('http://127.0.0.1:3901/health', timeout=5) as response:
            if json.load(response).get('status') != 'ready':
                raise ValueError('Backend mínimo ainda não está pronto')
        with client.open('http://127.0.0.1:3901/profiles/120f734a', timeout=5) as response:
            if json.load(response).get('id') != '120f734a':
                raise ValueError('Perfil não confirmado no backend')
        runtime.mkdir(parents=True, exist_ok=True)
        with backup.open('xb') as output:
            output.write(before)
    elif not backup.is_file() or json.loads(backup.read_text(encoding='utf-8-sig'))['tts']['voicestudio_endpoint'] != OLD:
        raise ValueError('Backup original não confirmado; reversão bloqueada')
    # Preserva formatação e todos os outros campos; a substituição precisa ser única.
    old, new = expected.encode(), target.encode()
    if before.count(old) != 1:
        raise ValueError('Endpoint não é único no arquivo; troca bloqueada')
    after = before.replace(old, new, 1)
    candidate = json.loads(after.decode('utf-8-sig'))
    desired = copy.deepcopy(data)
    desired['tts']['voicestudio_endpoint'] = target
    if candidate != desired or _validate_config(copy.deepcopy(candidate))['tts']['enabled'] is not True:
        raise ValueError('Configuração candidata inválida')
    handle, temporary = tempfile.mkstemp(prefix='.voice-test.', suffix='.tmp', dir=config.parent)
    try:
        with os.fdopen(handle, 'wb') as output:
            output.write(after)
            output.flush()
            os.fsync(output.fileno())
        if config.read_bytes() != before:
            raise RuntimeError('Configuração foi editada por outro processo; operação cancelada')
        os.replace(temporary, config)
        if config.read_bytes() != after:
            raise RuntimeError('Não foi possível confirmar a gravação')
    finally:
        Path(temporary).unlink(missing_ok=True)
    result = {'status':'selected', 'mode':mode, 'endpoint':target, 'voice':'120f734a',
              'only_changed_field':'tts.voicestudio_endpoint',
              'ai_unchanged':candidate.get('ai') == data.get('ai'),
              'backup_sha256':hashlib.sha256(backup.read_bytes()).hexdigest()}
    (runtime/('activation-result.json' if mode == 'activate' else 'restore-result.json')).write_text(
        json.dumps(result, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('activate','restore'))
    parser.add_argument('--config', type=Path, default=Path(os.environ['APPDATA'])/'Therion/config.json')
    parser.add_argument('--runtime', type=Path, default=ROOT/'tmp/omnivoice-minimal-20261020')
    args = parser.parse_args()
    print(json.dumps(switch(args.mode, args.config, args.runtime)))
