"""Cadência gráfica do desktop; não altera qualidade, serviços ou configurações."""
from PySide6.QtGui import QSurfaceFormat


# A animação usa um relógio próprio. Evitar desenhar além de aproximadamente
# 60 quadros/s também deixa a thread gráfica disponível para texto e áudio.
FRAME_INTERVAL_MS = 16


def prepare_graphics():
    """Configurar antes de QApplication criar a superfície nativa do desktop.

    O intervalo do QOpenGLWidget não controla a troca da janela que o compõe.
    No Windows, a espera adicional desse compositor chegou a ~80 ms por quadro.
    Aplicamos a opção ao formato padrão usado pela janela nativa e mantemos o
    ritmo pelo QTimer. Preservar todos os outros campos mantém o render intacto.
    """
    # Exigido pelo Qt WebEngine (leitor de e-mail HTML) antes de existir a QApplication.
    from PySide6.QtCore import QCoreApplication, Qt
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    # Sem isto o WebEngine usa Direct3D e fica preto na mesma janela da orbe OpenGL.
    from PySide6.QtQuick import QQuickWindow, QSGRendererInterface
    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)
    surface = QSurfaceFormat.defaultFormat()
    surface.setSwapInterval(0)
    QSurfaceFormat.setDefaultFormat(surface)
