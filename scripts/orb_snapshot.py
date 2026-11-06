"""Print da orbe holográfica para comparar com a referência.

Uso: python scripts/orb_snapshot.py --state idle --size 720 --seconds 1 --out orbe.png [--sheet 12]
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
    args = parser.parse_args()

    from therion.interface.graphics import prepare_graphics
    prepare_graphics()
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtGui import QImage, QPainter, QColor
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    from therion.interface.orb_renderer import OrbGL

    view = OrbGL(); view.resize(args.size, args.size); view.set_quality(args.quality)
    view.metrics.connect(print)
    view.show(); view.set_visual(args.state, args.intensity); view.set_active(True)
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
        else:
            frames[-1].save(args.out)
        app.quit()

    if args.then:
        QTimer.singleShot(round(500*args.seconds), lambda: view.set_visual(args.then, args.intensity))
    QTimer.singleShot(step_ms if args.sheet else round(1000*args.seconds), grab)
    app.exec()


if __name__ == '__main__':
    main()
