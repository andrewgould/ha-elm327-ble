"""Draws the integration's icon: an OBD-II connector face with a Bluetooth badge.

    python3 assets/make_icons.py   # writes icon.svg, dark_icon.svg and the brand PNGs

Needs rsvg-convert (brew install librsvg).
"""
import pathlib
import subprocess

HERE = pathlib.Path(__file__).parent
BRAND = HERE.parent / 'custom_components' / 'elm327_ble' / 'brand'


def trapezoid(x0, x1, y0, y1, inset):
    """Wider at the top, like the J1962 socket."""
    return f'M{x0},{y0} L{x1},{y0} L{x1 - inset},{y1} L{x0 + inset},{y1} Z'


def pins(y, x0, x1, n=8, r=15):
    step = (x1 - x0) / (n - 1)
    return ''.join(f'<circle cx="{x0 + i * step:.1f}" cy="{y}" r="{r}"/>' for i in range(n))


def svg(shell, face, pin):
    cx, cy, rb, gap = 388, 388, 104, 18
    h, w = 120, 60
    corners = [(-w / 2, -h / 4), (w / 2, h / 4), (0, h / 2),
               (0, -h / 2), (w / 2, -h / 4), (-w / 2, h / 4)]
    rune = ' '.join(f'{cx + dx:.1f},{cy + dy:.1f}' for dx, dy in corners)
    # The badge cuts a transparent ring out of the connector, so it reads on any background.
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <mask id="cut">
    <rect width="512" height="512" fill="#fff"/>
    <circle cx="{cx}" cy="{cy}" r="{rb + gap}" fill="#000"/>
  </mask>
  <g mask="url(#cut)">
    <path d="{trapezoid(28, 484, 40, 330, 52)}" fill="{shell}"
          stroke="{shell}" stroke-width="40" stroke-linejoin="round"/>
    <path d="{trapezoid(72, 440, 92, 286, 38)}" fill="{face}"
          stroke="{face}" stroke-width="24" stroke-linejoin="round"/>
    <rect x="216" y="20" width="80" height="44" rx="12" fill="{face}"/>
    <g fill="{pin}">{pins(148, 110, 402)}{pins(228, 128, 384)}</g>
  </g>
  <circle cx="{cx}" cy="{cy}" r="{rb}" fill="#1E88E5"/>
  <polyline points="{rune}" fill="none" stroke="#FFFFFF" stroke-width="18"
            stroke-linecap="round" stroke-linejoin="round"/>
</svg>
'''


VARIANTS = {
    '': svg(shell='#37474F', face='#263238', pin='#FFC107'),
    'dark_': svg(shell='#B0BEC5', face='#78909C', pin='#FFD54F'),
}
BRAND.mkdir(exist_ok=True)
for prefix, text in VARIANTS.items():
    source = HERE / f'{prefix}icon.svg'
    source.write_text(text)
    for suffix, size in (('', 256), ('@2x', 512)):
        subprocess.run(['rsvg-convert', '-w', str(size), '-h', str(size), '-o',
                        BRAND / f'{prefix}icon{suffix}.png', source], check=True)
print('wrote', sorted(p.name for p in BRAND.iterdir()))
