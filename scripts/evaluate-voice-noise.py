"""Avalia VAD local com WAV sintético explícito; nunca abre o microfone."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import wave
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from therion.voice.activity import StreamingSpeechActivity
from therion.voice.endpointing import SpeechEndpoint


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--speech-wav',required=True,help='Amostra sintética, explicitamente autorizada.')
    args=parser.parse_args()
    with wave.open(args.speech_wav,'rb') as wav:
        if wav.getsampwidth()!=2:raise ValueError('Use WAV PCM de 16 bits.')
        rate=wav.getframerate()
        speech=np.frombuffer(wav.readframes(wav.getnframes()),dtype='<i2').astype('float32')/32768
        if wav.getnchannels()>1:speech=speech.reshape(-1,wav.getnchannels()).mean(axis=1)
    if rate!=16000:
        speech=np.interp(np.arange(round(len(speech)*16000/rate))*rate/16000,
                         np.arange(len(speech)),speech).astype('float32')
    rng=np.random.default_rng(71013)
    def noise(seconds):return rng.normal(0,.04,round(seconds*16000)).astype('float32')
    cases=[('loud_noise_only',noise(5)),('speech_then_loud_noise',
        np.concatenate([noise(1),speech+noise(len(speech)/16000)*.25,noise(2)]))]
    report=[]
    for name,audio in cases:
        detector=SpeechEndpoint(activity=StreamingSpeechActivity())
        for start in range(0,len(audio),1600):
            detector.feed(audio[start:start+1600])
            if detector.complete:break
        report.append(dict(case=name,complete=detector.complete,reason=detector.reason,
            speech_seconds=round(detector.speech_seconds,3),elapsed=round(detector.elapsed,3),
            speech_length=round(len(speech)/16000,3)))
    target=Path(tempfile.mkdtemp(prefix='therion-voice-noise-eval-'))/'report.json'
    target.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'report':str(target),'cases':report}))
    assert report[0]['speech_seconds']==0
    assert report[1]['complete'] and report[1]['reason']=='silence'
    assert report[1]['elapsed']<=1+len(speech)/16000+1.2


if __name__=='__main__':main()
