"""Preparar seleção de voz; --apply publica após prévia, sem sintetizar áudio.

O caminho de configuração é explícito. Nenhuma integração é habilitada junto.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from therion.voice.providers import EDGE_VOICES, VOICESTUDIO_ENDPOINT


def proposal(config,provider,python_path=None,voice=EDGE_VOICES[0],allow_online=False,disable=False,streaming_prepare=None,*,voicestudio_endpoint=VOICESTUDIO_ENDPOINT,voicestudio_voice=''):
    from therion.config.local import _validate_config
    updated=deepcopy(config)
    tts=deepcopy(updated.get('tts',{}))
    if not isinstance(tts,dict):raise ValueError('Configuração de voz inválida; revise o arquivo.')
    if disable:
        tts.update(enabled=False,online_allowed=False,streaming_prepare=False)
    else:
        tts.update(provider=provider,enabled=True)
        if provider=='edge':
            if streaming_prepare is True:raise ValueError('Pré-síntese incremental disponível somente no Kokoro local.')
            if allow_online is not True:raise ValueError('Edge TTS envia texto online. Use --allow-online somente se concordar.')
            if not python_path or not Path(python_path).is_file():raise ValueError('Selecione o Python do ambiente Edge TTS instalado.')
            tts.update(online_allowed=True,edge_python_path=str(Path(python_path).resolve()),edge_voice=voice)
            tts['streaming_prepare']=False
        elif provider=='voicestudio':
            if streaming_prepare is not None and type(streaming_prepare) is not bool:raise ValueError('Pré-síntese exige opção booleana explícita.')
            if not python_path or not Path(python_path).is_file():raise ValueError('Selecione o Python do cliente VoiceStudio.')
            tts.update(online_allowed=False,streaming_prepare=streaming_prepare is True,
                voicestudio_python_path=str(Path(python_path).resolve()),
                voicestudio_endpoint=voicestudio_endpoint,voicestudio_voice=voicestudio_voice)
        elif provider=='kokoro':
            tts['online_allowed']=False
            if streaming_prepare is not None:
                if type(streaming_prepare) is not bool:raise ValueError('Pré-síntese exige opção booleana explícita.')
                tts['streaming_prepare']=streaming_prepare
            if python_path:tts['python_path']=str(Path(python_path).resolve())
            root=Path(tts.get('model_root',''))
            if not Path(tts.get('python_path','')).is_file() or not all((root/name).is_file() for name in ('kokoro-v1.0.onnx','voices-v1.0.bin')):
                raise ValueError('O ambiente e os arquivos Kokoro precisam estar configurados.')
        else:raise ValueError('Provider não suportado.')
        validated=_validate_config({'tts':tts})['tts']
        if validated['enabled'] is not True:raise ValueError('Perfil de voz inválido; nenhuma configuração foi publicada.')
        tts=validated
    updated['tts']=tts
    return updated


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True,type=Path)
    parser.add_argument('--provider',choices=('kokoro','edge','voicestudio'))
    parser.add_argument('--voicestudio-endpoint',default=VOICESTUDIO_ENDPOINT)
    parser.add_argument('--voicestudio-voice-id',default='')
    parser.add_argument('--python-path')
    parser.add_argument('--voice',choices=EDGE_VOICES,default=EDGE_VOICES[0])
    parser.add_argument('--allow-online',action='store_true')
    parser.add_argument('--disable',action='store_true')
    parser.add_argument('--streaming-prepare',action=argparse.BooleanOptionalAction,default=None,
        help='Experimento local: preparar início da fala, retido até a resposta ser validada.')
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    if not args.disable and not args.provider:parser.error('Escolha --provider ou --disable.')
    path=args.config.resolve()
    original=path.read_bytes() if path.exists() else None
    if original is not None and len(original)>1_000_000:raise ValueError('Configuração acima do limite.')
    config=json.loads(original) if original is not None else {}
    if not isinstance(config,dict):raise ValueError('Configuração precisa ser um objeto JSON.')
    updated=proposal(config,args.provider,args.python_path,args.voice,args.allow_online,args.disable,args.streaming_prepare,
        voicestudio_endpoint=args.voicestudio_endpoint,voicestudio_voice=args.voicestudio_voice_id)
    preview={'config':str(path),'tts':updated['tts'],'apply':args.apply,
        'notice':('Edge TTS envia o texto falado à Microsoft. ' if args.provider=='edge' else '')+'Nenhum áudio é gerado por este comando. Feche o Therion por Sair e reabra para aplicar.'}
    print(json.dumps(preview,ensure_ascii=False,indent=2))
    if not args.apply:return 0
    path.parent.mkdir(parents=True,exist_ok=True)
    if (path.read_bytes() if path.exists() else None)!=original:raise ValueError('Configuração mudou; refaça a prévia.')
    if original is not None:
        backup=path.with_name(path.stem+'.before-voice-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+path.suffix)
        with backup.open('xb') as stream:stream.write(original)
        if backup.read_bytes()!=original:raise ValueError('Não confirmei o backup; não substituí a configuração.')
    fd,temporary=tempfile.mkstemp(dir=path.parent,prefix='.voice-config-',suffix='.tmp')
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump(updated,stream,ensure_ascii=False,indent=2);stream.flush();os.fsync(stream.fileno())
        if (path.read_bytes() if path.exists() else None)!=original:raise ValueError('Configuração mudou; não substituí.')
        os.replace(temporary,path)
        if json.loads(path.read_text(encoding='utf-8'))!=updated:raise ValueError('Não confirmei a configuração publicada; não repeti.')
    finally:
        if Path(temporary).exists():Path(temporary).unlink()
    return 0


if __name__=='__main__':sys.exit(main())
