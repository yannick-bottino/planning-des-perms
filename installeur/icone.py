"""Génère icone.ico (calendrier simplifié, palette de app/static/app.css).

Usage : python icone.py   (nécessite Pillow). Sortie : icone.ico à côté du script.
"""
from pathlib import Path

from PIL import Image, ImageDraw

ICI = Path(__file__).resolve().parent
ACCENT = (52, 83, 168, 255)       # approx. oklch(0.49 0.15 258)
ACCENT_FOND = (230, 237, 250, 255)
SURFACE = (255, 255, 255, 255)
BORD = (205, 212, 226, 255)
OK = (47, 128, 84, 255)           # approx. oklch(0.47 0.12 152)
TAILLES = [16, 24, 32, 48, 64, 128, 256]


def dessiner(n: int) -> Image.Image:
    """Dessin à 1024 px puis réduction (anticrénelage)."""
    g = 1024
    im = Image.new("RGBA", (g, g), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    m = 64
    d.rounded_rectangle([m, m + 40, g - m, g - m], radius=120, fill=SURFACE, outline=BORD, width=14)
    d.rounded_rectangle([m, m + 40, g - m, 340], radius=120, fill=ACCENT)
    d.rectangle([m, 240, g - m, 340], fill=ACCENT)
    for x in (300, g - 300):  # anneaux
        d.rounded_rectangle([x - 36, m - 20, x + 36, 240], radius=36, fill=ACCENT_FOND, outline=ACCENT, width=14)
    # grille 3 x 3 de jours, une case mise en avant
    x0, y0, pas, c = 232, 395, 190, 130
    for i in range(3):
        for j in range(3):
            x, y = x0 + j * pas, y0 + i * pas
            if (i, j) == (1, 1):
                d.rounded_rectangle([x, y, x + c, y + c], radius=30, fill=OK)
            else:
                d.rounded_rectangle([x, y, x + c, y + c], radius=30, fill=ACCENT_FOND)
    return im.resize((n, n), Image.LANCZOS)


def main() -> None:
    images = [dessiner(t) for t in TAILLES]
    images[-1].save(ICI / "icone.ico", format="ICO", sizes=[(t, t) for t in TAILLES],
                    append_images=images[:-1])
    print(f"{ICI / 'icone.ico'} : {len(TAILLES)} tailles")


if __name__ == "__main__":
    main()
