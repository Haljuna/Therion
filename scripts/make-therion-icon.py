"""Gera o Ã­cone do Therion a partir das mesmas partÃ­culas da orbe do app."""
import math
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[1]))
from therion.interface.constellation import particle_data  # noqa: E402

S = 1024
OUT = str(__import__('pathlib').Path(__file__).resolve().parents[1] / 'therion' / 'assets')


def render_orb(size: int, phase: float = 0.9) -> np.ndarray:
    pts = particle_data(48000)
    x, y, z, seed = pts[:, 0], pts[:, 1], pts[:, 2], pts[:, 3]
    radial = .16 + (1.18 - .16) * seed ** .65
    p = np.stack([x * radial, y * radial, z * radial], 1)
    c, s = math.cos(phase), math.sin(phase)
    p[:, 0], p[:, 2] = c * p[:, 0] - s * p[:, 2], s * p[:, 0] + c * p[:, 2]
    tilt = .32  # leve inclinaÃ§Ã£o para as fitas aparecerem em 3D
    ct, st = math.cos(tilt), math.sin(tilt)
    p[:, 1], p[:, 2] = ct * p[:, 1] - st * p[:, 2], st * p[:, 1] + ct * p[:, 2]
    depth = 1. / (3.1 - p[:, 2] * .48)
    scale = size * .40 / (1.18 / (3.1 - .48))
    px = size / 2 + p[:, 0] * depth * scale
    py = size / 2 - p[:, 1] * depth * scale
    sparkle = np.clip((seed - .96) / .04, 0, 1)
    core = 1 - np.clip((radial - .16) / .84, 0, 1)
    emission = (.17 + seed * .30 + sparkle * .26 + core * .22)
    base = np.array([.40, .24, .78])[None] * (1 - seed[:, None]) + np.array([.79, .68, 1.])[None] * seed[:, None]
    color = base * (1 - sparkle[:, None] * .7) + np.array([.95, .93, 1.])[None] * sparkle[:, None] * .7
    img = np.zeros((size, size, 3))
    ix, iy = px.astype(int), py.astype(int)
    ok = (ix >= 1) & (iy >= 1) & (ix < size - 1) & (iy < size - 1)
    w = (color * emission[:, None])[ok]
    for dx, dy, k in ((0, 0, 1.), (1, 0, .45), (-1, 0, .45), (0, 1, .45), (0, -1, .45)):
        np.add.at(img, (iy[ok] + dy, ix[ok] + dx), w * k)
    return img


def tone(img: np.ndarray) -> np.ndarray:
    return 1 - np.exp(-img * 1.4)


def tile(size: int) -> tuple[Image.Image, Image.Image]:
    """Fundo preto em quadrado arredondado + mÃ¡scara."""
    mask = Image.new('L', (size, size), 0)
    m = int(size * .04)
    ImageDraw.Draw(mask).rounded_rectangle((m, m, size - m, size - m), radius=int(size * .22), fill=255)
    return mask, Image.new('RGBA', (size, size), (0, 0, 0, 0))


def big_icon() -> Image.Image:
    orb = render_orb(S) * 1.0
    yy, xx = np.mgrid[0:S, 0:S]
    r = np.hypot(xx - S / 2, yy - S / 2) / (S / 2)
    glow = np.asarray(Image.fromarray((np.clip(orb / orb.max() * 6, 0, 1) * 255).astype('uint8')).filter(
        ImageFilter.GaussianBlur(S * .012))) / 255.
    halo = np.exp(-r * r * 2.6)[..., None] * np.array([.36, .20, .78])[None, None] * .42
    core = np.exp(-(r / .10) ** 2)[..., None] * np.array([.95, .93, 1.])[None, None] * .95
    core_glow = np.exp(-(r / .30) ** 2)[..., None] * np.array([.62, .45, 1.])[None, None] * .45
    bg = np.array([9, 9, 15]) / 255.
    rgb = bg + halo + tone(orb * 1.25) * .95 + glow * np.array([.58, .42, 1.]) * .30 + core_glow + core
    rgb = np.clip(rgb, 0, 1)
    mask, _ = tile(S)
    icon = Image.fromarray((rgb * 255).astype('uint8')).convert('RGBA')
    icon.putalpha(mask)
    m = int(S * .04)
    border = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(border).rounded_rectangle((m, m, S - m, S - m), radius=int(S * .22),
                                             outline=(167, 139, 250, 80), width=max(2, S // 170))
    return Image.alpha_composite(icon, border)


def brand_icon(size: int) -> Image.Image:
    """Marca vetorial do cabeÃ§alho (OrbBrand): espiral Ã¡urea roxa com nÃºcleo claro. NÃ­tida em 16â€“48 px."""
    k = 8
    s = size * k
    mask, _ = tile(s)
    img = Image.new('RGBA', (s, s), (9, 9, 15, 255))
    halo = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(halo).ellipse((s * .18, s * .18, s * .82, s * .82), fill=(124, 78, 230, 120))
    img = Image.alpha_composite(img, halo.filter(ImageFilter.GaussianBlur(s * .08)))
    d = ImageDraw.Draw(img)
    unit = s / 48 * 1.18
    for i in range(21):
        a = i * 2.39996
        rad = (3. + math.sqrt(i) * 3.5) * unit
        x, y = s / 2 + math.cos(a) * rad, s / 2 + math.sin(a) * rad
        dot = 1.9 * unit
        d.ellipse((x - dot, y - dot, x + dot, y + dot), fill=(167, 139, 250, min(255, 120 + i * 7)))
    c = 3.4 * unit
    d.ellipse((s / 2 - c, s / 2 - c, s / 2 + c, s / 2 + c), fill=(241, 240, 247, 255))
    img.putalpha(mask)
    return img.resize((size, size), Image.LANCZOS)


big = big_icon()
big.save(OUT + r'\therion-icon.png')
frames = [big.resize((n, n), Image.LANCZOS) for n in (16, 24, 32, 48, 64, 128, 256)]
frames[-1].save(OUT + r'\therion-orb.ico', format='ICO', sizes=[f.size for f in frames], append_images=frames[:-1])
print('ok')

