"""Publica somente o perfil Jarvis aprovado e seu cache em estado duravel."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[2]


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def install(profile_path,source,checkpoint,state,config,original_config=None):
    profile_path,source,checkpoint,state,config=map(Path,(profile_path,source,checkpoint,state,config))
    profile=json.loads(profile_path.read_text(encoding='utf-8'))
    if profile.get('id')!='120f734a' or not profile.get('ref_text','').strip():
        raise ValueError('Perfil aprovado não confirmado')
    reference=Path(profile['reference_path'])
    if digest(reference)!=profile['reference_sha256']:raise ValueError('Referência Jarvis mudou')
    identity=hashlib.sha256(json.dumps(profile,sort_keys=True).encode()+
        (source/'omnivoice/models/omnivoice.py').read_bytes()+str(checkpoint.resolve()).encode()).hexdigest()[:32]
    cache=profile_path.parent/('reference-'+identity+'.pt')
    if not cache.is_file():raise ValueError('Cache da referência aprovada ausente')
    data=json.loads(config.read_text(encoding='utf-8-sig'))
    if (data.get('voice',{}).get('provider')!='parakeet_http' or
        data.get('tts',{}).get('voicestudio_voice')!='120f734a' or
        data.get('tts',{}).get('voicestudio_endpoint')!='http://127.0.0.1:3902/v1/audio/speech'):
        raise ValueError('Configuração aprovada não está ativa')
    voice=state/'jarvis';voice.mkdir(parents=True,exist_ok=True)
    rollback=state/'rollback';rollback.mkdir(exist_ok=True)
    # Backups nunca são substituídos numa instalação repetida.
    for original,name in ((config,'config-at-adoption.json'),(original_config,'config-before-parakeet.json')):
        if original and Path(original).is_file() and not (rollback/name).exists():shutil.copy2(original,rollback/name)
    for original,destination in ((profile_path,voice/'profile.json'),(cache,voice/cache.name)):
        if destination.exists():
            if digest(destination)!=digest(original):raise ValueError('Estado permanente diverge do aprovado')
        else:shutil.copy2(original,destination)
    manifest={'schema':1,'profile':'120f734a','source_root':str(source),'checkpoint':str(checkpoint),
        'voice_runtime':str(voice),'gateway_runtime':str(state/'gateway'),
        'profile_sha256':digest(voice/'profile.json'),'reference_cache':cache.name,
        'reference_cache_sha256':digest(voice/cache.name),'device':'cuda','steps':16,
        'stt':'parakeet','config_sha256_at_adoption':digest(rollback/'config-at-adoption.json')}
    (state/'gateway').mkdir(exist_ok=True)
    (state/'installation.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--state-root',type=Path,default=Path(os.environ['LOCALAPPDATA'])/'Therion/voice')
    args=parser.parse_args()
    install(ROOT/'tmp/omnivoice-minimal-20261020/profile.json',Path('F:/VoiceStudio/runtime/project'),
        Path('F:/VoiceStudio/models/models--k2-fsa--OmniVoice/snapshots/c5fdb5ccb189668d56333f77ba2629f4cd7535f4'),
        args.state_root,Path(os.environ['APPDATA'])/'Therion/config.json',
        ROOT/'tmp/parakeet-therion-20261020/config-before-parakeet.json')
    print(json.dumps({'status':'installed','state_root':str(args.state_root)}))
