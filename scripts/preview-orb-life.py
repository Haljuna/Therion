"""Exporta a animação OpenGL real com tempo determinístico, sem serviços pessoais.

O vídeo amostra 25 quadros/s; não é benchmark. O renderizador do aplicativo segue
sua cadência normal. A exportação é incremental para não acumular frames na RAM.
"""
import argparse
import json
import math
from pathlib import Path
import sys


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default='tmp/orb-life-preview')
    parser.add_argument('--quality',choices=['high','medium','low'],default='high')
    parser.add_argument('--fps',type=int,default=25)
    args=parser.parse_args()
    if not 1<=args.fps<=60: parser.error('Use uma cadência entre 1 e 60 FPS.')
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    output=(root/args.output).resolve();output.mkdir(parents=True,exist_ok=True)
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication,QWidget,QVBoxLayout,QLabel
    from PIL import Image
    import av
    from therion.interface.graphics import prepare_graphics
    from therion.interface.constellation import ParticleGL
    from therion.interface.presentation import LABELS
    prepare_graphics();app=QApplication([])
    window=QWidget();window.setWindowTitle('Therion · Prévia da presença')
    window.setStyleSheet('background:#080808; color:#FFB347; font-family:Segoe UI;')
    layout=QVBoxLayout(window);layout.setContentsMargins(0,12,0,12);layout.setSpacing(0)
    title=QLabel(LABELS['idle']);title.setAlignment(Qt.AlignCenter)
    title.setStyleSheet('font-size:15px;');layout.addWidget(title)
    view=ParticleGL();view.setFixedSize(600,480);view.set_quality(args.quality)
    layout.addWidget(view)
    note=QLabel('PRÉVIA · INTENSIDADE SINTÉTICA · SEM ÁUDIO')
    note.setAlignment(Qt.AlignCenter);note.setStyleSheet('color:#8D887D; font-size:10px;')
    layout.addWidget(note);window.show();app.processEvents()
    if not view.ready: raise RuntimeError('Não foi possível inicializar o renderizador OpenGL.')
    view.timer.stop()
    # O mesmo integrador do app avança um passo exato por frame exportado.
    advance=view.animation.advance
    view.animation.advance=lambda seconds,*,reduced=False:None
    sequence=[('idle',3),('listening',3),('thinking',3),('executing',3),('speaking',4),('awaiting_confirmation',2),('idle',3)]
    count=0;elapsed=0.;states=[]
    target=output/'orb-life.mp4'
    with av.open(str(target),mode='w',options={'movflags':'faststart'}) as video:
        stream=video.add_stream('libx264',rate=args.fps)
        stream.width=window.width();stream.height=window.height();stream.pix_fmt='yuv420p'
        stream.options={'crf':'16','preset':'medium'}
        first=True
        for state,duration in sequence:
            states.append({'state':state,'seconds':elapsed});title.setText(LABELS[state])
            for index in range(duration*args.fps):
                intensity=0.
                if state in {'speaking','listening'}:
                    intensity=max(0.,min(1.,.48+.28*math.sin(elapsed*9)+.16*math.sin(elapsed*17)))
                    if elapsed%3.8>2.8:intensity=0.
                view.set_visual(state,intensity);advance(1/args.fps)
                view.update();app.processEvents()
                shot=window.grab().toImage().convertToFormat(QImage.Format_RGBA8888)
                frame=Image.frombytes('RGBA',(shot.width(),shot.height()),bytes(shot.constBits()),'raw','RGBA',shot.bytesPerLine()).convert('RGB')
                if first:
                    frame.save(output/'preview.png');first=False
                for packet in stream.encode(av.VideoFrame.from_image(frame)):video.mux(packet)
                if index==args.fps:frame.save(output/(state+'.png'))
                count+=1;elapsed+=1/args.fps
        for packet in stream.encode():video.mux(packet)
    report={'file':str(target),'frames':count,'fps':args.fps,'duration_seconds':round(elapsed,2),
            'size':[shot.width(),shot.height()],'states':states,'opengl_ready':view.ready,
            'limitations':'Exportação determinística; intensidade sintética, sem áudio real. Não é benchmark.'}
    (output/'preview.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    window.close();app.processEvents();print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
