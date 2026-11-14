"""Gera a animação de inicialização do tablet (bootanimation.zip) no tema da Estação Therion.

Sem texto: a animação do Android não gira, e o tablet pode ficar em pé. Só o anel, redondo e centralizado.
"""
import io
import math
import os
from pathlib import Path
import zipfile

from PIL import Image, ImageDraw

LARGURA, ALTURA, QPS = 1024, 600, 12
ESCALA = 2  # desenha em dobro e reduz, para o traço sair suave
FUNDO, LINHA, ECO, CLARO = (0x0d, 0x0a, 0x18), (0x9b, 0x87, 0xff), (0x4b, 0x3b, 0xb0), (0xe7, 0xe0, 0xff)
RAIO = 150


def _anel(desenho, raio_de, cor, largura):
    cx, cy = LARGURA * ESCALA / 2, ALTURA * ESCALA / 2
    pontos = []
    for i in range(241):
        q = i / 240 * 2 * math.pi
        r = raio_de(q) * ESCALA
        pontos.append((cx + math.cos(q) * r, cy + math.sin(q) * r))
    desenho.line(pontos, fill=cor, width=largura * ESCALA, joint='curve')


def _quadro(raio_de, raio_base, cor_linha) -> bytes:
    img = Image.new('RGB', (LARGURA * ESCALA, ALTURA * ESCALA), FUNDO)
    d = ImageDraw.Draw(img)
    cx, cy = LARGURA * ESCALA / 2, ALTURA * ESCALA / 2
    externo = raio_base * 1.4 * ESCALA
    if externo > 1:
        d.ellipse((cx - externo, cy - externo, cx + externo, cy + externo), outline=ECO, width=ESCALA)
    if raio_base > 1:
        _anel(d, lambda q: raio_de(q) * 0.7, ECO, 1)
        _anel(d, raio_de, cor_linha, 3)
    miolo = 8 * ESCALA
    d.ellipse((cx - miolo, cy - miolo, cx + miolo, cy + miolo), fill=CLARO)
    saida = io.BytesIO()
    img.resize((LARGURA, ALTURA), Image.LANCZOS).save(saida, 'PNG')
    return saida.getvalue()


def _nascimento(n: int) -> bytes:
    progresso = 1 - (1 - (n + 1) / 30) ** 3
    raio = RAIO * progresso
    return _quadro(lambda q: raio, raio, CLARO if n >= 26 else LINHA)


def _falando(n: int) -> bytes:
    t = n * 0.35
    amplitude = 22 * (0.5 + abs(math.sin(1.7 * t)))
    return _quadro(lambda q: RAIO + math.sin(8 * q + 4 * t) * amplitude * math.sin(3 * q + t), RAIO, LINHA)


def gerar(destino: Path) -> Path:
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    arquivo = destino / 'bootanimation.zip'
    with zipfile.ZipFile(arquivo, 'w', compression=zipfile.ZIP_STORED) as z:
        z.writestr('desc.txt', f'{LARGURA} {ALTURA} {QPS}\np 1 0 part0\np 0 0 part1\n')
        for n in range(30):
            z.writestr(f'part0/{n:05d}.png', _nascimento(n))
        for n in range(24):
            z.writestr(f'part1/{n:05d}.png', _falando(n))
    return arquivo


def main() -> None:
    pasta = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'Therion' / 'estacao'
    print(gerar(pasta))


if __name__ == '__main__':
    main()
