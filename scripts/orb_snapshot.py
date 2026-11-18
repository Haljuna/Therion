"""Print da Orbe HUD para comparar com o protótipo.

Uso: python scripts/orb_snapshot.py --state idle --size 720 --seconds 1 --out orbe.png [--sheet 12]
     [--timer 0.64:32:focus] [--mini]

--timer FRAÇÃO:RÓTULO:fase desenha o tempo do modo foco (fase focus|pause; âmbar quando a fração cabe nos
últimos 5 min de um foco de 50). --mini tira o print da mini orbe de verdade (110 px, transparente), colada
sobre um fundo cinza, mais uma cópia ampliada ×4 (<out>_x4.png).
"""
import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--state', default='idle')
    parser.add_argument('--intensity', type=float, default=0.)
    parser.add_argument('--then', default='', help='estado aplicado na metade do tempo')
    parser.add_argument('--size', type=int, default=720)
    parser.add_argument('--seconds', type=float, default=1.)
    parser.add_argument('--quality', default='high')
    parser.add_argument('--sheet', type=int, default=0, help='quadros espaçados numa folha')
    parser.add_argument('--out', required=True)
    parser.add_argument('--timer', default='', help='FRAÇÃO:RÓTULO:fase, ex. 0.64:32:focus')
    parser.add_argument('--mini', action='store_true')
    args = parser.parse_args()

    from therion.interface.graphics import prepare_graphics
    prepare_graphics()
    from PySide6.QtCore import QTimer, Qt, QRectF
    from PySide6.QtGui import QImage, QPainter, QColor
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    from therion.interface.orb_renderer import OrbGL

    look = None
    if args.timer:
        from therion.core.focus import TimerLook
        fraction, label, phase = args.timer.split(':')
        look = TimerLook(float(fraction), label, phase, phase == 'focus' and float(fraction)*50*60 <= 300)
    if args.mini:
        import tempfile
        from therion.interface.mini_orb import MiniOrb
        mini = MiniOrb(path=str(Path(tempfile.gettempdir())/'orb_snapshot_mini.json'), reader=dict,
                       key_state=lambda vk: False)
        mini.set_state(args.state, False); mini.show()
        view = mini._renderer
        set_timer = mini.set_timer
    else:
        view = OrbGL(); view.resize(args.size, args.size); view.set_quality(args.quality)
        if look is not None:   # como no painel: a orbe ocupa uma área dentro da janela, o arco passa da borda dela
            view.focus_rect = QRectF(.06*args.size, .06*args.size, .88*args.size, .88*args.size)
        view.show(); view.set_visual(args.state, args.intensity); view.set_active(True)
        set_timer = view.set_timer
    view.metrics.connect(print)
    if look is not None:
        set_timer(look)
        resend = QTimer(); resend.timeout.connect(lambda: set_timer(look)); resend.start(1000)   # como o tique da janela
    frames, count = [], max(1, args.sheet)
    step_ms = round(1000*args.seconds/count)

    def grab():
        frames.append(view.grabFramebuffer())
        if len(frames) < count:
            QTimer.singleShot(step_ms, grab); return
        if args.sheet:
            cols = math.ceil(math.sqrt(count)); rows = math.ceil(count/cols); cell = 300
            sheet = QImage(cols*cell, rows*cell, QImage.Format_RGB32); sheet.fill(QColor('#09090F'))
            painter = QPainter(sheet)
            for i, frame in enumerate(frames):
                painter.drawImage((i % cols)*cell, (i//cols)*cell,
                                  frame.scaled(cell, cell, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            painter.end(); sheet.save(args.out)
        elif args.mini:   # transparente: colada sobre um fundo cinza, como na área de trabalho
            shot = QImage(frames[-1].size(), QImage.Format_RGB32); shot.fill(QColor('#3A3D46'))
            painter = QPainter(shot); painter.drawImage(0, 0, frames[-1]); painter.end()
            shot.save(args.out)
            shot.scaled(shot.width()*4, shot.height()*4).save(str(Path(args.out).with_suffix(''))+'_x4.png')
        else:
            frames[-1].save(args.out)
        app.quit()

    if args.then:
        QTimer.singleShot(round(500*args.seconds), lambda: view.set_visual(args.then, args.intensity))
    QTimer.singleShot(step_ms if args.sheet else round(1000*args.seconds), grab)
    app.exec()


if __name__ == '__main__':
    main()
