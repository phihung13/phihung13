# -*- coding: utf-8 -*-
"""Sài Gòn isometric — a city you can wreck from a README button.

Two things worth knowing:

1. Every moving vehicle is CUT INTO SEGMENTS BY DEPTH, and each segment is emitted into the same
   depth bucket as the houses around it. A house nearer the camera therefore paints over the
   segment behind it — traffic never flies above the rooftops.

2. The damage is a pure function of state.json. Every disaster is just an (kind, seed) pair;
   what it destroys is derived deterministically from that seed. So the map can always be rebuilt
   from scratch, and "reset" simply means throwing the event list away.
"""
import base64
import io
import json
import math
import os
from collections import defaultdict

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(HERE, "state.json")
OUT_PATH = os.path.join(HERE, "saigon.svg")

# ═══ WHY THIS IS A HYBRID ════════════════════════════════════════════
# A pure-vector city was 27,000 shapes. Any SMIL animation forces the browser to re-rasterise
# the WHOLE image every frame, so a dozen moving motorbikes dragged 27,000 shapes with them and
# the page crawled.
#
# So: the static city (houses, roads, trees) is painted straight to BITMAP with Pillow, sliced
# into depth BANDS. Only the things that actually move stay vector. The browser then composites
# a handful of pre-rendered strips plus a few hundred tiny shapes per frame.
# Vehicles are emitted between the bands, so houses in front still cover them.
SS = 2                      # supersample, then downscale — gives clean anti-aliased edges
BAND_DEPTHS = 4             # how many grid depths get flattened into one bitmap strip

TW, TH, ZH = 104, 66, 25          # bigger blocks: fewer of them, and detail survives downscaling
# the iso diamond must be big enough to cover the RECTANGLE's corners, not just its middle:
# |x|/(GRID*TW/2) + |y|/(GRID*TH/2) <= 1 at the corners → GRID >= 27 for this canvas
GRID = 28
CW, CH = 1440, 810                # 16:9 banner for the README
OX = CW / 2
OY = CH / 2 - GRID * TH / 2       # centre the diamond on the canvas
MARGIN = 260                      # anything further outside the frame is skipped
CYCLE = 24.0
RED0, RED1 = 0.40, 0.60          # the light is red for this slice of every cycle

ASPHALT, ASPHALT2 = "#68635c", "#605b54"
WALK, CURB = "#b8b1a0", "#968f80"
DIRT = "#9c9481"
SLAB_T, SLAB_L, SLAB_R = "#a8a08e", "#847d6d", "#726c5d"
GRASS, GRASS_D, POND = "#6f8f52", "#5a7742", "#5f86a0"

FACADES = [
    ("#d9c089", "#b6a06e", "#e6d3a6"), ("#bcc9b0", "#9caa91", "#d3ded0"),
    ("#d8c1b2", "#b59c8d", "#e7d5cb"), ("#c6c1b3", "#a49f90", "#dad6cb"),
    ("#e0d2ad", "#bcae8b", "#eee3c9"), ("#b9af99", "#978d78", "#cfc7b5"),
    ("#cfbcc2", "#ab99a0", "#e1d2d7"), ("#a9b3ad", "#8b968f", "#c3ccc6"),
]
MOSS, STAIN = "#5d7a4a", "#6b6455"
TILE_R, TILE_L, TILE_HL = "#9e5039", "#7d3d2c", "#b56a4f"
TIN_R, TIN_L, RUST = "#8d9298", "#6f747a", "#8a5a3c"
DRUM = ["#4a6b88", "#7a5a3a", "#5f6b52"]
TANK_T, TANK_L, TANK_R = "#9aa8ae", "#5c686e", "#7a878d"
TREE, TREE_D, TRUNK = "#57813f", "#3b5c31", "#5f4a33"
SIGNS = ["#b03e2c", "#3a6491", "#c78d24", "#3f7d52", "#8f4d80", "#2a7076"]
GLASS, FRAME, RAIL = "#5a6c7d", "#e9e3d3", "#8f8878"
GOV = ("#e0c877", "#bda75d", "#efdfa4")

# ── the colours of a bad day ─────────────────────────────────────────
RUBBLE_A, RUBBLE_B, RUBBLE_C = "#a89f8f", "#8c8474", "#6f6a5f"
CHAR_A, CHAR_B, CHAR_C = "#5c534b", "#443d37", "#6e6459"
EMBER = "#d8632c"
CRATER_A, CRATER_B = "#4a453e", "#332f2a"
WATER, WATER_HI = "#4b7f9e", "#7fb0c8"
SMOKE = "#b9b3a8"

road = [[False] * GRID for _ in range(GRID)]
taken = [[False] * GRID for _ in range(GRID)]

NBANDS = (2 * GRID) // BAND_DEPTHS + 2
_bitmaps, _draws = [], []
for _ in range(NBANDS):
    im = Image.new("RGBA", (CW * SS, CH * SS), (0, 0, 0, 0))
    _bitmaps.append(im)
    _draws.append(ImageDraw.Draw(im, "RGBA"))   # "RGBA" mode = alpha BLENDING, not overwrite


def rgba(hexcol, op=1.0):
    h = hexcol.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(max(0.0, min(1.0, op)) * 255))


class Layer:
    """One depth band: a bitmap for everything that stands still, SVG for everything that moves."""

    def __init__(self, band):
        self.band = min(max(band, 0), NBANDS - 1)
        self.svg = io.StringIO()

    def write(self, s):                 # animated / text bits stay as SVG
        self.svg.write(s)

    @property
    def draw(self):
        return _draws[self.band]


head = Layer(0)
_layers = {}


def layer(depth):
    key = min(max(depth, 0), 2 * GRID - 1)
    if key not in _layers:
        _layers[key] = Layer(key // BAND_DEPTHS)
    return _layers[key]


def rnd(s, n):
    return (s * 1103515245 + 12345) // 65536 % n


def C(gx, gy):
    return (OX + (gx - gy) * (TW / 2), OY + (gx + gy) * (TH / 2))


def mid(gx, gy, w=1, d=1):
    a, b = C(gx, gy), C(gx + w, gy + d)
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)


def P(buf, pts, fill, op=None):
    buf.draw.polygon([(x * SS, y * SS) for x, y in pts], fill=rgba(fill, 1.0 if op is None else op))


def L(buf, p, q, c, w=1, op=1.0):
    buf.draw.line([(p[0] * SS, p[1] * SS), (q[0] * SS, q[1] * SS)],
                  fill=rgba(c, op), width=max(1, int(w * SS)))


def RECT(buf, x, y, w, h, fill, op=1.0):
    buf.draw.rectangle([x * SS, y * SS, (x + w) * SS, (y + h) * SS], fill=rgba(fill, op))


def ELL(buf, cx, cy, rx, ry, fill, op=1.0):
    buf.draw.ellipse([(cx - rx) * SS, (cy - ry) * SS, (cx + rx) * SS, (cy + ry) * SS],
                     fill=rgba(fill, op))


def fp(A, B, u, v):
    return (A[0] + (B[0] - A[0]) * u, A[1] + (B[1] - A[1]) * u - v)


def panel(buf, A, B, u0, u1, v0, v1, fill, op=None):
    P(buf, [fp(A, B, u0, v0), fp(A, B, u1, v0), fp(A, B, u1, v1), fp(A, B, u0, v1)], fill, op)


# ═══ streets ═════════════════════════════════════════════════════════
def run(pts):
    x, y = pts[0]
    road[y][x] = True
    for tx, ty in pts[1:]:
        while x != tx:
            x += 1 if tx > x else -1
            road[y][x] = True
        while y != ty:
            y += 1 if ty > y else -1
            road[y][x] = True


run([(0, 6), (6, 6), (6, 9), (14, 9), (14, 12), (27, 12)])     # đại lộ chính, bẻ khúc hai lần
run([(0, 20), (9, 20), (9, 23), (19, 23), (19, 27)])           # đại lộ phía nam
run([(5, 0), (5, 14), (8, 14), (8, 27)])                       # trục dọc, lệch giữa chừng
run([(16, 0), (16, 27)])                                       # trục dọc thứ hai
run([(23, 0), (23, 27)])                                       # trục dọc thứ ba
run([(11, 4), (11, 20)])                                       # hẻm dọc dài
run([(20, 9), (20, 23)])                                       # hẻm dọc → ngã ba
run([(0, 15), (5, 15)])                                        # hẻm nối
run([(20, 17), (27, 17)])                                      # hẻm ngang

wide = [[False] * GRID for _ in range(GRID)]
for gy in range(GRID):
    for gx in range(GRID):
        if road[gy][gx]:
            wide[gy][gx] = True
            if gx + 1 < GRID:
                wide[gy][gx + 1] = True
            if gy + 1 < GRID:
                wide[gy + 1][gx] = True
road = wide


def is_road(x, y):
    return 0 <= x < GRID and 0 <= y < GRID and road[y][x]


# ═══ DISASTERS ═══════════════════════════════════════════════════════
# state.json = {"events": [{"kind": "...", "seed": 123}, ...]}. Nothing else is stored:
# what each event destroys is derived from its seed, so the map is always reproducible.
if os.path.exists(STATE_PATH):
    # utf-8-sig: tolerate a BOM, which some editors add and json.load chokes on.
    # A malformed state file is a bug worth shouting about, not silently ignoring.
    with open(STATE_PATH, encoding="utf-8-sig") as f:
        STATE = json.load(f)
else:
    STATE = {"events": []}
EVENTS = STATE.get("events", [])

collapsed = set()      # nhà sập thành đống gạch vụn  (earthquake, war)
charred = set()        # nhà cháy đen, còn bốc khói    (lightning)
craters = set()        # hố bom, mất luôn cả mặt đường (war)
cracked = set()        # đường nứt toác                (earthquake)
flooded = set()        # ngập nước                     (flood)


def pick_cells(seed, n, want_road=False):
    """deterministic scatter of cells, walking a coprime stride across the grid"""
    out_cells, k = [], (seed * 7919) % (GRID * GRID)
    stride = 3517                                     # coprime with GRID*GRID for a full tour
    for _ in range(GRID * GRID):
        gx, gy = k % GRID, k // GRID
        k = (k + stride) % (GRID * GRID)
        if not on_screen_cell(gx, gy):
            continue
        if road[gy][gx] == want_road:
            out_cells.append((gx, gy))
            if len(out_cells) >= n:
                break
    return out_cells


def on_screen_cell(gx, gy):
    x = OX + (gx - gy) * (TW / 2) + TW / 2
    y = OY + (gx + gy) * (TH / 2) + TH / 2
    return -60 < x < CW + 60 and -60 < y < CH + 60


for ev in EVENTS:
    kind, seed = ev.get("kind", ""), int(ev.get("seed", 1))

    if kind == "earthquake":                    # ĐỘNG ĐẤT: sập rải rác + nứt đường
        for c in pick_cells(seed, 9):
            collapsed.add(c)
        for c in pick_cells(seed + 31, 7, want_road=True):
            cracked.add(c)

    elif kind == "lightning":                   # SẤM SÉT: vài nhà trúng sét, cháy đen
        for c in pick_cells(seed + 7, 4):
            charred.add(c)

    elif kind == "war":                         # TÊN LỬA: hố bom + san phẳng quanh điểm rơi
        for (ex, ey) in pick_cells(seed + 13, 2):
            craters.add((ex, ey))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    cx_, cy_ = ex + dx, ey + dy
                    if not (0 <= cx_ < GRID and 0 <= cy_ < GRID):
                        continue
                    if road[cy_][cx_]:
                        if abs(dx) + abs(dy) <= 1:
                            craters.add((cx_, cy_))
                    elif abs(dx) + abs(dy) <= 1:
                        collapsed.add((cx_, cy_))
                    elif (dx + dy + seed) % 2 == 0:
                        charred.add((cx_, cy_))

    elif kind == "flood":
        # THỦY TRIỀU: nước dâng từ mép dưới khung hình lên. Tính theo toạ độ MÀN HÌNH, không
        # phải chỉ số lưới — các ô "phía trước" của lưới phần lớn nằm ngoài khung.
        tides = sum(1 for e in EVENTS if e.get("kind") == "flood")
        waterline = CH - 150 * tides            # mỗi con nước lại dâng cao thêm
        for gy in range(GRID):
            for gx in range(GRID):
                y = OY + (gx + gy) * (TH / 2) + TH / 2
                if y >= waterline and on_screen_cell(gx, gy):
                    flooded.add((gx, gy))

collapsed -= craters
charred -= collapsed | craters


def free(gx, gy, w, d):
    for y in range(gy, gy + d):
        for x in range(gx, gx + w):
            if not (0 <= x < GRID and 0 <= y < GRID) or road[y][x] or taken[y][x]:
                return False
    return True


def occupy(gx, gy, w, d):
    for y in range(gy, gy + d):
        for x in range(gx, gx + w):
            taken[y][x] = True


# The sky and its clouds are gone: the city now fills the frame edge to edge, so they were
# painted underneath the ground — invisible, but still animating and still costing frames.

def on_screen(gx, gy):
    """is this cell anywhere near the frame? everything else is skipped"""
    x, y = mid(gx, gy)
    return -MARGIN < x < CW + MARGIN and -MARGIN < y < CH + MARGIN


RECT(head, 0, 0, CW, CH, DIRT)                                        # the city bleeds off every edge

for gy in range(GRID):
    for gx in range(GRID):
        if not on_screen(gx, gy):
            continue
        N, E, S, W = C(gx, gy), C(gx + 1, gy), C(gx + 1, gy + 1), C(gx, gy + 1)
        P(head, [N, E, S, W], (ASPHALT if (gx + gy) % 2 else ASPHALT2) if road[gy][gx] else DIRT)

for gy in range(GRID):
    for gx in range(GRID):
        if road[gy][gx] or not on_screen(gx, gy):
            continue
        N, E, S, W = C(gx, gy), C(gx + 1, gy), C(gx + 1, gy + 1), C(gx, gy + 1)
        P(head, [N, E, S, W], WALK)
        if is_road(gx + 1, gy):
            L(head, E, S, CURB, 3, 0.9)
        if is_road(gx, gy + 1):
            L(head, S, W, CURB, 3, 0.9)
        if is_road(gx - 1, gy):
            L(head, N, W, CURB, 3, 0.5)
        if is_road(gx, gy - 1):
            L(head, N, E, CURB, 3, 0.5)

for gy in range(GRID):
    for gx in range(GRID):
        if not road[gy][gx] or not on_screen(gx, gy):
            continue
        ew = is_road(gx - 1, gy) and is_road(gx + 1, gy)
        ns = is_road(gx, gy - 1) and is_road(gx, gy + 1)
        if ew == ns:
            continue
        c = mid(gx, gy)
        if ew:
            L(head, (c[0] - 16, c[1] - 10), (c[0] + 16, c[1] + 10), "#ded5c1", 2, 0.45)
        else:
            L(head, (c[0] - 16, c[1] + 10), (c[0] + 16, c[1] - 10), "#ded5c1", 2, 0.45)

for gx, gy, k in ((7, 6, 0), (5, 10, 1), (12, 9, 0), (8, 21, 1), (16, 4, 0), (17, 12, 1),
                  (20, 14, 0), (4, 15, 1), (23, 8, 0), (11, 18, 1), (23, 20, 0), (16, 23, 1)):
    if not is_road(gx, gy) or not on_screen(gx, gy):
        continue
    c = mid(gx, gy)
    if k == 0:
        ELL(head, c[0], c[1], 9, 6, "#54504a")
        ELL(head, c[0], c[1], 6, 4, "#605b54")
    else:
        P(head, [(c[0] - 10, c[1]), (c[0], c[1] - 6), (c[0] + 10, c[1]), (c[0], c[1] + 6)], "#4f4b45")
        for t in range(-2, 3):
            L(head, (c[0] - 6 + t * 3, c[1] + 3), (c[0] + 1 + t * 3, c[1] - 1), "#6b665f", 1, 0.9)
head.write("\n")


# ═══ ruins ═══════════════════════════════════════════════════════════
def rubble(buf, gx, gy, seed):
    """what a house becomes: stumps of wall, a heap of debris, dust still hanging"""
    N, E, S, W = C(gx, gy), C(gx + 1, gy), C(gx + 1, gy + 1), C(gx, gy + 1)
    P(buf, [N, E, S, W], "#8f8878")                                  # bare foundation
    for i, (u, hh) in enumerate(((0.10, 26), (0.42, 14), (0.78, 22))):
        A, B = (S, E) if i % 2 else (W, S)
        panel(buf, A, B, u, u + 0.16, 0, hh, RUBBLE_A if i % 2 else RUBBLE_B)
        panel(buf, A, B, u, u + 0.16, hh - 3, hh, RUBBLE_C)
    c = mid(gx, gy)
    for k in range(9):
        ox = -34 + ((seed * (k + 3) * 17) % 68)
        oy = -6 + ((seed * (k + 5) * 11) % 22)
        s = 5 + ((seed * (k + 7)) % 9)
        col = (RUBBLE_A, RUBBLE_B, RUBBLE_C)[(seed + k) % 3]
        P(buf, [(c[0] + ox, c[1] + oy), (c[0] + ox + s, c[1] + oy - s * 0.6),
                (c[0] + ox + 2 * s, c[1] + oy), (c[0] + ox + s, c[1] + oy + s * 0.6)], col)
    for k in range(3):
        buf.write(f'<circle cx="{c[0]-18+k*16:.0f}" cy="{c[1]-30-k*10:.0f}" r="{9+k*3}" '
                  f'fill="{SMOKE}" opacity="0.18">'
                  f'<animate attributeName="opacity" values="0.05;0.22;0.05" dur="{5+k}s" '
                  f'begin="{k}s" repeatCount="indefinite"/></circle>')


def crater(buf, gx, gy, seed):
    """where the missile landed: the street is simply gone"""
    c = mid(gx, gy)
    P(buf, [(c[0] - 46, c[1]), (c[0], c[1] - 28), (c[0] + 46, c[1]), (c[0], c[1] + 28)], CRATER_A)
    P(buf, [(c[0] - 30, c[1]), (c[0], c[1] - 18), (c[0] + 30, c[1]), (c[0], c[1] + 18)], CRATER_B)
    for k in range(7):
        ox = -50 + ((seed * (k + 2) * 13) % 100)
        oy = -20 + ((seed * (k + 4) * 7) % 40)
        s = 4 + ((seed + k) % 6)
        P(buf, [(c[0] + ox, c[1] + oy), (c[0] + ox + s, c[1] + oy - s * 0.6),
                (c[0] + ox + 2 * s, c[1] + oy), (c[0] + ox + s, c[1] + oy + s * 0.6)], RUBBLE_C)
    buf.write(f'<ellipse cx="{c[0]:.0f}" cy="{c[1]-6:.0f}" rx="26" ry="14" fill="{EMBER}" '
              f'opacity="0.25"><animate attributeName="opacity" values="0.10;0.30;0.10" dur="2.2s" '
              f'repeatCount="indefinite"/></ellipse>')
    for k in range(3):
        buf.write(f'<circle cx="{c[0]-10+k*12:.0f}" cy="{c[1]-40-k*22:.0f}" r="{12+k*5}" '
                  f'fill="{SMOKE}" opacity="0.22">'
                  f'<animate attributeName="opacity" values="0.06;0.28;0.06" dur="{4+k}s" '
                  f'begin="{k*0.8}s" repeatCount="indefinite"/></circle>')


def crack(buf, gx, gy, seed):
    """a fault line torn across the asphalt"""
    c = mid(gx, gy)
    pts = []
    for k in range(6):
        t = k / 5
        jitter = -8 + ((seed * (k + 3) * 19) % 16)
        pts.append((c[0] - 48 + 96 * t, c[1] - 28 + 56 * t + jitter))
    dpath = "M" + " L".join(f"{x:.0f},{y:.0f}" for x, y in pts)
    buf.write(f'<path d="{dpath}" fill="none" stroke="{CRATER_B}" stroke-width="7" '
              f'stroke-linejoin="round"/>'
              f'<path d="{dpath}" fill="none" stroke="#231f1c" stroke-width="3"/>')


def water(buf, gx, gy, seed):
    """the tide, sitting above the street and lapping at the walls"""
    LEV = 12
    N, E = (C(gx, gy)[0], C(gx, gy)[1] - LEV), (C(gx + 1, gy)[0], C(gx + 1, gy)[1] - LEV)
    S, W = (C(gx + 1, gy + 1)[0], C(gx + 1, gy + 1)[1] - LEV), (C(gx, gy + 1)[0], C(gx, gy + 1)[1] - LEV)
    P(buf, [N, E, S, W], WATER, 0.72)
    c = mid(gx, gy)
    for k in range(2):
        buf.write(f'<ellipse cx="{c[0]-20+k*34:.0f}" cy="{c[1]-LEV+2+k*8:.0f}" rx="14" ry="4" '
                  f'fill="{WATER_HI}" opacity="0.25">'
                  f'<animate attributeName="opacity" values="0.08;0.35;0.08" dur="{3+k}s" '
                  f'begin="{(seed+k)%3}s" repeatCount="indefinite"/></ellipse>')


# ═══ a house ═════════════════════════════════════════════════════════
def house(buf, gx, gy, w, d, seed, kind="house", burnt=False):
    N, E, S, W = C(gx, gy), C(gx + w, gy), C(gx + w, gy + d), C(gx, gy + d)
    floors = 1 + rnd(seed + 3, 5) if kind == "house" else 3
    fh = ZH - 2 + rnd(seed + 31, 5)
    h = floors * fh + 8 + rnd(seed + 7, 10)
    r, l, t = (GOV if kind == "gov" else FACADES[rnd(seed + 5, len(FACADES))])
    if burnt:                                   # struck by lightning: scorched to the bone
        r, l, t = CHAR_C, CHAR_B, CHAR_A

    P(buf, [(N[0] + 10, N[1] + 6), (E[0] + 10, E[1] + 6),
            (S[0] + 10, S[1] + 6), (W[0] + 10, W[1] + 6)], "#5a5346", 0.16)
    up = lambda p: (p[0], p[1] - h)
    P(buf, [W, S, up(S), up(W)], l)
    P(buf, [S, E, up(E), up(S)], r)
    P(buf, [up(N), up(E), up(S), up(W)], t)

    street_r = any(is_road(gx + w, gy + i) for i in range(d))
    street_l = any(is_road(gx + i, gy + d) for i in range(w))

    for A, B, sunny in ((S, E, True), (W, S, False)):
        for m in range(3):
            u = 0.08 + rnd(seed + m * 5, 70) / 100
            panel(buf, A, B, u, min(u + 0.10, 0.98), 0, 3 + rnd(seed + m, 8), MOSS, 0.22)
        for m in range(2):
            u = 0.15 + rnd(seed + m * 9 + 3, 60) / 100
            panel(buf, A, B, u, u + 0.04, 6, h - 14, STAIN, 0.07)

    for f in range(floors):
        v = 10 + f * fh
        if v + fh > h - 4:
            break
        ground = (f == 0)
        for A, B, sunny, faces in ((S, E, True, street_r), (W, S, False, street_l)):
            sh = None if sunny else 0.9
            if ground and faces:
                if kind == "gov":
                    panel(buf, A, B, 0.30, 0.70, 0, 20, "#6d5f4a", sh)
                    panel(buf, A, B, 0.26, 0.74, 20, 23, "#8a7a5f", sh)
                    for k in range(4):
                        u = 0.20 + k * 0.20
                        panel(buf, A, B, u, u + 0.035, 0, h - 20, "#eee3c9", sh)
                    continue
                panel(buf, A, B, 0.14, 0.60, 0, 16, "#3f3c37", sh)
                for k in range(6):
                    L(buf, fp(A, B, 0.14, 3 + k * 2.4), fp(A, B, 0.60, 3 + k * 2.4), "#54504a", 1, 0.7)
                panel(buf, A, B, 0.66, 0.90, 0, 14, "#38352f", sh)
                panel(buf, A, B, 0.08, 0.96, 16, 19, SIGNS[rnd(seed + 2, len(SIGNS))], sh)
                panel(buf, A, B, 0.12, 0.92, 21, 28, SIGNS[rnd(seed + 4, len(SIGNS))], sh)
                # rao vặt: khoan cắt bê tông, cho thuê phòng…
                if sunny and rnd(seed + 8, 2):
                    for k in range(2 + rnd(seed + k if False else seed + 9, 2)):
                        pu = 0.62 + k * 0.10
                        panel(buf, A, B, pu, pu + 0.07, 30 + k * 9, 37 + k * 9,
                              ["#e8e2d0", "#f0d9a8", "#dfe6ea"][rnd(seed + k * 3, 3)], sh)
                        L(buf, fp(A, B, pu + 0.01, 33 + k * 9), fp(A, B, pu + 0.06, 33 + k * 9),
                          "#8a8375", 1, 0.7)
                continue
            if ground:
                panel(buf, A, B, 0.22, 0.52, 0, 13, "#46433d", sh)
                continue
            nwin = 2 if (w == 1 and d == 1) else 3
            for i in range(nwin):
                u0 = 0.12 + i * (0.76 / nwin)
                u1 = u0 + 0.76 / nwin - 0.10
                panel(buf, A, B, u0, u1, v, v + 13, FRAME, sh)
                panel(buf, A, B, u0 + 0.02, u1 - 0.02, v + 2, v + 11, GLASS, sh)
                L(buf, fp(A, B, (u0 + u1) / 2, v + 2), fp(A, B, (u0 + u1) / 2, v + 11), FRAME, 1, 0.9)
            if sunny and rnd(seed + f * 7, 3):
                panel(buf, A, B, 0.10, 0.92, v - 3, v - 1, "#c2bba9")
                for k in range(11):
                    u = 0.10 + k * 0.082
                    L(buf, fp(A, B, u, v - 3), fp(A, B, u, v + 5), RAIL, 1, 0.8)
                L(buf, fp(A, B, 0.10, v + 5), fp(A, B, 0.92, v + 5), RAIL, 1, 0.8)
                if rnd(seed + f, 2):
                    panel(buf, A, B, 0.78, 0.88, v - 1, v + 4, "#a26f4c")
                    panel(buf, A, B, 0.76, 0.90, v + 4, v + 10, TREE)
            if not sunny and rnd(seed + f * 3, 3) == 0:
                panel(buf, A, B, 0.60, 0.78, v + 2, v + 9, "#cfc9bb", 0.95)

    roof = 9 if kind == "gov" else rnd(seed + 23, 10)
    rc = mid(gx, gy, w, d)
    rcy = rc[1] - h
    if roof < 4:                                            # mái tôn
        pitch = 20 + rnd(seed, 10)
        apex = ((N[0] + S[0]) / 2, (N[1] + S[1]) / 2 - h - pitch)
        P(buf, [up(W), up(S), apex], TIN_L)
        P(buf, [up(S), up(E), apex], TIN_R)
        for k in range(1, 9):
            a = (up(S)[0] + (up(E)[0] - up(S)[0]) * k / 9, up(S)[1] + (up(E)[1] - up(S)[1]) * k / 9)
            L(buf, a, apex, "#a7acb2", 1, 0.5)
            b = (up(S)[0] + (up(W)[0] - up(S)[0]) * k / 9, up(S)[1] + (up(W)[1] - up(S)[1]) * k / 9)
            L(buf, b, apex, "#5f646a", 1, 0.4)
        if rnd(seed + 2, 2):
            P(buf, [up(S), (up(S)[0] + 18, up(S)[1] - 10), (apex[0], apex[1] + 14),
                    (up(S)[0] + 4, up(S)[1] - 2)], RUST, 0.35)
    elif roof < 6:                                          # mái ngói
        apex = ((N[0] + S[0]) / 2, (N[1] + S[1]) / 2 - h - 26)
        P(buf, [up(W), up(S), apex], TILE_L)
        P(buf, [up(S), up(E), apex], TILE_R)
        for k in range(1, 7):
            a = (up(S)[0] + (up(E)[0] - up(S)[0]) * k / 7, up(S)[1] + (up(E)[1] - up(S)[1]) * k / 7)
            L(buf, a, apex, TILE_HL, 1, 0.3)
        P(buf, [up(S), (up(S)[0] + 14, up(S)[1] - 8), (apex[0] - 6, apex[1] + 12),
                (up(S)[0] + 2, up(S)[1] - 1)], MOSS, 0.2)
    else:                                                   # sân thượng
        for A, B in ((S, E), (W, S)):
            panel(buf, A, B, 0.0, 1.0, h - 7, h, "#d6cfbe", 0.92)
            for k in range(12):
                u = 0.04 + k * 0.08
                panel(buf, A, B, u, u + 0.03, h - 7, h - 1, "#b6ae9c", 0.9)
        tx, ty = rc[0] - 14, rcy - 18
        P(buf, [(tx, ty + 10), (tx + 12, ty + 3), (tx + 24, ty + 10), (tx + 12, ty + 17)], TANK_T)
        P(buf, [(tx, ty + 10), (tx + 12, ty + 17), (tx + 12, ty + 29), (tx, ty + 22)], TANK_L)
        P(buf, [(tx + 12, ty + 17), (tx + 24, ty + 10), (tx + 24, ty + 22), (tx + 12, ty + 29)], TANK_R)
        for k in range(1 + rnd(seed + 5, 2)):               # thùng phi
            dx, dy = rc[0] + 16 + k * 13, rcy - 4 + k * 5
            c = DRUM[rnd(seed + k * 3, len(DRUM))]
            P(buf, [(dx, dy), (dx + 6, dy - 3), (dx + 12, dy), (dx + 6, dy + 3)], "#c9c2b0")
            RECT(buf, dx, dy, 12, 14, c)
            L(buf, (dx, dy + 5), (dx + 12, dy + 5), "#2f2b27", 1, 0.35)
        if rnd(seed + 9, 2):                                # vườn sân thượng
            for k in range(3):
                px, py = rc[0] - 30 + k * 11, rcy + 6 - k * 4
                RECT(buf, px, py, 8, 6, "#a26f4c")
                RECT(buf, px - 1, py - 7, 10, 8, TREE)
        if rnd(seed + 11, 2):                               # dây phơi
            L(buf, (rc[0] - 28, rcy + 2), (rc[0] + 2, rcy - 14), RAIL, 1, 0.9)
            for k, c in enumerate(("#c05a4a", "#e8e4d6", "#5f86a8", "#d8c48f")):
                RECT(buf, rc[0] - 26 + k * 7, rcy + 1 - k * 3.7, 5, 9 + k % 2, c)
        if rnd(seed + 17, 3) == 0:
            L(buf, (rc[0] - 22, rcy - 6), (rc[0] - 22, rcy - 32), RAIL, 1)
            L(buf, (rc[0] - 27, rcy - 27), (rc[0] - 17, rcy - 27), RAIL, 1)

    if burnt:                                   # smoke still pouring off the roof, embers inside
        for k in range(4):
            buf.write(f'<circle cx="{rc[0]-14+k*11:.0f}" cy="{rcy-18-k*20:.0f}" r="{10+k*5}" '
                      f'fill="{SMOKE}" opacity="0.22">'
                      f'<animate attributeName="opacity" values="0.05;0.30;0.05" dur="{4+k}s" '
                      f'begin="{k*0.7}s" repeatCount="indefinite"/></circle>')
        for A, B in ((S, E), (W, S)):
            panel(buf, A, B, 0.30, 0.55, 18, 34, EMBER, 0.55)
        buf.write(f'<ellipse cx="{rc[0]:.0f}" cy="{rcy+4:.0f}" rx="22" ry="10" fill="{EMBER}" '
                  f'opacity="0.30"><animate attributeName="opacity" values="0.12;0.42;0.12" '
                  f'dur="1.8s" repeatCount="indefinite"/></ellipse>')

    if kind == "gov":
        fx0, fy0 = rc[0], rcy - 8
        L(buf, (fx0, fy0), (fx0, fy0 - 40), RAIL, 2)
        RECT(buf, fx0, fy0 - 40, 26, 17, "#c8322c")                     # cờ đỏ
        P(buf, [(fx0 + 13, fy0 - 37), (fx0 + 17, fy0 - 26), (fx0 + 8, fy0 - 32),   # sao vàng
                (fx0 + 18, fy0 - 32), (fx0 + 9, fy0 - 26)], "#f2d64b")
        buf.write(f'<text x="{rc[0]:.0f}" y="{rcy+34:.0f}" font-family="monospace" font-size="9" '
                  f'fill="#5d5647" text-anchor="middle">UBND PHUONG</text>')


def ben_thanh(buf, gx, gy):
    w = d = 2
    N, E, S, W = C(gx, gy), C(gx + w, gy), C(gx + w, gy + d), C(gx, gy + d)
    h = 54
    up = lambda p: (p[0], p[1] - h)
    P(buf, [(N[0] + 10, N[1] + 6), (E[0] + 10, E[1] + 6), (S[0] + 10, S[1] + 6),
            (W[0] + 10, W[1] + 6)], "#5a5346", 0.16)
    P(buf, [W, S, up(S), up(W)], "#d3bd8e")
    P(buf, [S, E, up(E), up(S)], "#e6d0a0")
    for A, B, sh in ((S, E, None), (W, S, 0.9)):
        for k in range(4):
            u = 0.10 + k * 0.21
            panel(buf, A, B, u, u + 0.13, 0, 24, "#4a453d", sh)
    apex = ((N[0] + S[0]) / 2, (N[1] + S[1]) / 2 - h - 34)
    P(buf, [up(W), up(S), apex], "#7d3d2c")
    P(buf, [up(S), up(E), apex], "#9e5039")
    for k in range(1, 9):
        a = (up(S)[0] + (up(E)[0] - up(S)[0]) * k / 9, up(S)[1] + (up(E)[1] - up(S)[1]) * k / 9)
        L(buf, a, apex, "#b56a4f", 1, 0.3)
    tcx, tcy = apex[0], apex[1] + 8
    RECT(buf, tcx - 16, tcy - 56, 32, 56, "#e6d0a0")                    # tháp đồng hồ
    RECT(buf, tcx + 4, tcy - 56, 12, 56, "#c9b183")
    P(buf, [(tcx - 20, tcy - 56), (tcx + 20, tcy - 56), (tcx, tcy - 82)], "#7d3d2c")
    ELL(buf, tcx - 2, tcy - 36, 11, 11, "#4a453d")                     # mặt đồng hồ
    ELL(buf, tcx - 2, tcy - 36, 9, 9, "#f6f1e2")
    buf.write(f'<line x1="{tcx-2:.0f}" y1="{tcy-36:.0f}" x2="{tcx-2:.0f}" y2="{tcy-44:.0f}" '
              f'stroke="#4a453d" stroke-width="2">'                  # kim đồng hồ: thứ duy nhất động
              f'<animateTransform attributeName="transform" type="rotate" '
              f'from="0 {tcx-2:.0f} {tcy-36:.0f}" to="360 {tcx-2:.0f} {tcy-36:.0f}" dur="24s" '
              f'repeatCount="indefinite"/></line>'
              f'<text x="{tcx:.0f}" y="{tcy+26:.0f}" font-family="monospace" font-size="10" '
              f'fill="#5d5647" text-anchor="middle">CHO BEN THANH</text>')


def tower(buf, gx, gy):
    N, E, S, W = C(gx, gy), C(gx + 1, gy), C(gx + 1, gy + 1), C(gx, gy + 1)
    h = 190
    up = lambda p: (p[0], p[1] - h)
    P(buf, [(N[0] + 10, N[1] + 6), (E[0] + 10, E[1] + 6), (S[0] + 10, S[1] + 6),
            (W[0] + 10, W[1] + 6)], "#5a5346", 0.16)
    P(buf, [W, S, up(S), up(W)], "#7e93a4")
    P(buf, [S, E, up(E), up(S)], "#9db2c2")
    P(buf, [up(N), up(E), up(S), up(W)], "#c2d2dd")
    for f in range(11):
        v = 12 + f * 16
        for A, B, sh in ((S, E, None), (W, S, 0.9)):
            panel(buf, A, B, 0.12, 0.88, v, v + 10, "#5f7f99", sh)
    c = mid(gx, gy)
    RECT(buf, c[0] - 3, c[1] - h - 34, 5, 34, "#8fa6ba")


def park(buf, gx, gy, w=2, d=2):
    """công viên: cỏ, lối đi, hồ nhỏ, ghế đá, cây to"""
    N, E, S, W = C(gx, gy), C(gx + w, gy), C(gx + w, gy + d), C(gx, gy + d)
    P(buf, [N, E, S, W], GRASS)
    c = mid(gx, gy, w, d)
    P(buf, [(c[0] - 46, c[1]), (c[0], c[1] - 28), (c[0] + 46, c[1]), (c[0], c[1] + 28)],
      GRASS_D, 0.5)                                                   # lối đi
    P(buf, [(c[0] - 24, c[1] + 12), (c[0] - 2, c[1] + 1), (c[0] + 20, c[1] + 12),
            (c[0] - 2, c[1] + 23)], POND)                             # hồ
    P(buf, [(c[0] - 20, c[1] + 12), (c[0] - 2, c[1] + 3), (c[0] + 16, c[1] + 12),
            (c[0] - 2, c[1] + 21)], "#79a0b8", 0.6)
    for bx, by in ((c[0] - 40, c[1] - 6), (c[0] + 26, c[1] - 2)):     # ghế đá
        RECT(buf, bx, by, 20, 4, "#b6ae9c")
        RECT(buf, bx, by + 4, 3, 5, "#8f8878")
        RECT(buf, bx + 17, by + 4, 3, 5, "#8f8878")
    for ox, oy, s in ((-34, -26, 1.3), (28, -30, 1.1), (0, -40, 1.0), (36, 14, 0.9)):
        bx, by = c[0] + ox, c[1] + oy
        RECT(buf, bx, by - 24 * s, 5, 24 * s, TRUNK)
        RECT(buf, bx - 16 * s, by - 48 * s, 36 * s, 26 * s, TREE)
        RECT(buf, bx - 11 * s, by - 55 * s, 26 * s, 8 * s, TREE)
        RECT(buf, bx - 16 * s, by - 25 * s, 36 * s, 3, TREE_D)
    buf.write(f'<text x="{c[0]:.0f}" y="{c[1]+34:.0f}" font-family="monospace" font-size="9" '
              f'fill="#41502f" text-anchor="middle">CONG VIEN</text>')


# ═══ reserve the special plots ═══════════════════════════════════════
MARKET, TOWER, GOV_AT, PARK = (12, 7), (21, 6), (6, 17), (17, 17)
occupy(*MARKET, 2, 2)
for px in range(11, 16):                      # quảng trường trước chợ
    for py in range(6, 10):
        if 0 <= px < GRID and 0 <= py < GRID and not road[py][px]:
            taken[py][px] = True
occupy(*TOWER, 1, 1)
occupy(*PARK, 2, 2)

# ═══ buildings, bucketed by depth ════════════════════════════════════
for depth in range(2 * GRID):
    buf = layer(depth)
    if depth == MARKET[0] + MARKET[1]:
        ben_thanh(buf, *MARKET)
    if depth == TOWER[0] + TOWER[1]:
        tower(buf, *TOWER)
    if depth == PARK[0] + PARK[1]:
        park(buf, *PARK)
    for gx in range(GRID):
        gy = depth - gx
        if not (0 <= gy < GRID) or road[gy][gx] or taken[gy][gx] or not on_screen(gx, gy):
            continue
        seed = gx * 37 + gy * 19 + 5

        if (gx, gy) in craters:                       # nothing left to draw here
            occupy(gx, gy, 1, 1)
            continue
        if (gx, gy) in collapsed:
            occupy(gx, gy, 1, 1)
            rubble(buf, gx, gy, seed)
            continue

        if (gx, gy) == GOV_AT and free(gx, gy, 2, 2):
            occupy(gx, gy, 2, 2)
            house(buf, gx, gy, 2, 2, seed, kind="gov", burnt=(gx, gy) in charred)
            continue
        if rnd(seed, 12) == 0:                       # sân vườn
            b = mid(gx, gy)
            occupy(gx, gy, 1, 1)
            for ox, oy, s in ((-16, 6, 1.1), (10, -4, 0.8)):
                RECT(buf, b[0] + ox, b[1] + oy - 20 * s, 4, 20 * s, TRUNK)
                RECT(buf, b[0] + ox - 13 * s, b[1] + oy - 40 * s, 30 * s, 22 * s, TREE)
            continue
        shape = rnd(seed + 41, 10)
        w, d = (2, 1) if shape < 2 else ((1, 2) if shape < 4 else (1, 1))
        if not free(gx, gy, w, d):
            w = d = 1
        occupy(gx, gy, w, d)
        house(buf, gx, gy, w, d, seed, burnt=(gx, gy) in charred)

    # craters, cracks and floodwater sit at ground level of this same depth row,
    # so the houses in the row in front will still paint over them
    for gx in range(GRID):
        gy = depth - gx
        if not (0 <= gy < GRID) or not on_screen(gx, gy):
            continue
        s = gx * 7 + gy * 13 + 3
        if (gx, gy) in craters:
            crater(buf, gx, gy, s)
        elif (gx, gy) in cracked:
            crack(buf, gx, gy, s)
        if (gx, gy) in flooded:
            water(buf, gx, gy, s)

# ═══ sidewalk life — also bucketed, so houses can hide it ════════════
for gy in range(GRID):
    for gx in range(GRID):
        if road[gy][gx] or not on_screen(gx, gy) \
                or not (is_road(gx + 1, gy) or is_road(gx, gy + 1)):
            continue
        buf = layer(gx + gy)
        seed = gx * 13 + gy * 7
        c = mid(gx, gy)
        if rnd(seed + 1, 3) == 0:                                     # cây vỉa hè
            bx, by = c[0] + 20, c[1] + 14
            RECT(buf, bx, by - 22, 4, 22, TRUNK)
            RECT(buf, bx - 13, by - 44, 30, 24, TREE)
            RECT(buf, bx - 9, by - 50, 22, 7, TREE)
            RECT(buf, bx - 13, by - 23, 30, 3, TREE_D)
        if rnd(seed + 2, 5) == 0:                                     # thùng rác
            bx, by = c[0] - 22, c[1] + 12
            RECT(buf, bx, by - 14, 13, 14, "#4a7a52")
            P(buf, [(bx, by - 14), (bx + 6, by - 18), (bx + 13, by - 14), (bx + 7, by - 10)], "#5d8f63")
        if rnd(seed + 3, 6) == 0:                                     # xe ba gác đậu
            bx, by = c[0] + 4, c[1] + 22
            RECT(buf, bx - 16, by - 14, 26, 10, "#8a6a3a")
            RECT(buf, bx - 16, by - 20, 26, 6, "#a8814a")
            RECT(buf, bx + 8, by - 10, 12, 4, "#4a4640")
            RECT(buf, bx - 14, by - 4, 6, 5, "#2f2b27")
            RECT(buf, bx + 2, by - 4, 6, 5, "#2f2b27")
        if rnd(seed + 5, 7) == 0:                                     # gánh hàng rong
            bx, by = c[0] - 6, c[1] + 26
            RECT(buf, bx, by - 18, 6, 12, "#c9b48f")
            RECT(buf, bx - 1, by - 24, 8, 6, "#e0c877")                  # nón lá
            RECT(buf, bx - 14, by - 14, 34, 2, "#8a7a5f")                # đòn gánh
            RECT(buf, bx - 16, by - 12, 12, 6, "#b08a52")
            RECT(buf, bx + 12, by - 12, 12, 6, "#b08a52")
        if rnd(seed + 6, 8) == 0:                                     # xe bánh mì
            bx, by = c[0] + 14, c[1] + 26
            RECT(buf, bx - 14, by - 16, 26, 11, "#c78d24")
            RECT(buf, bx - 16, by - 22, 30, 6, "#b03e2c")
            RECT(buf, bx - 12, by - 5, 5, 5, "#2f2b27")
            RECT(buf, bx + 4, by - 5, 5, 5, "#2f2b27")

# ═══ đèn giao thông + đèn đường (bucketed) ═══════════════════════════
def traffic_light(gx, gy):
    buf = layer(gx + gy)
    b = C(gx, gy)
    L(buf, b, (b[0], b[1] - 62), "#4f4b45", 3)                     # cột: tĩnh → bitmap
    RECT(buf, b[0] - 7, b[1] - 92, 15, 34, "#3a3733")
    kt = f'0;{RED0};{RED0+0.001};{RED1};{RED1+0.001};1'
    buf.write(f'<circle cx="{b[0]:.0f}" cy="{b[1]-83:.0f}" r="4.5" fill="#c8322c">'
              f'<animate attributeName="opacity" values="0.15;0.15;1;1;0.15;0.15" keyTimes="{kt}" '
              f'dur="{CYCLE}s" repeatCount="indefinite"/></circle>'
              f'<circle cx="{b[0]:.0f}" cy="{b[1]-72:.0f}" r="4.5" fill="#d8a93a" opacity="0.2"/>'
              f'<circle cx="{b[0]:.0f}" cy="{b[1]-62:.0f}" r="4.5" fill="#3fa85c">'
              f'<animate attributeName="opacity" values="1;1;0.15;0.15;1;1" keyTimes="{kt}" '
              f'dur="{CYCLE}s" repeatCount="indefinite"/></circle>')


traffic_light(5, 6)        # ngã tư đại lộ × trục dọc thứ nhất
traffic_light(16, 12)      # ngã tư đại lộ × trục dọc thứ hai
traffic_light(8, 20)       # ngã tư đại lộ nam

for gx, gy in ((2, 4), (9, 8), (13, 10), (19, 13), (25, 15), (3, 17),
               (14, 22), (21, 25), (22, 7), (7, 13), (11, 17), (18, 20)):
    if not on_screen(gx, gy):
        continue
    buf = layer(gx + gy)
    b = C(gx + 1, gy + 1)
    L(buf, b, (b[0], b[1] - 58), RAIL, 2)
    L(buf, (b[0], b[1] - 58), (b[0] + 14, b[1] - 62), RAIL, 2)
    RECT(buf, b[0] + 11, b[1] - 65, 8, 4, "#efe8d4")
    RECT(buf, b[0] - 5, b[1] - 34, 9, 6, "#e8e2d0")          # rao vặt dán đầy cột đèn
    RECT(buf, b[0] - 4, b[1] - 24, 8, 5, "#f0d9a8")


# ═══ VEHICLES — sliced by depth so buildings can occlude them ════════
def lane_points(cells):
    return [mid(gx, gy) for gx, gy in cells]


def draw_bike(color):
    return (f'<rect x="-8" y="-6" width="16" height="5" fill="{color}"/>'
            f'<rect x="-3" y="-17" width="7" height="11" fill="#2f2b27"/>'
            f'<rect x="-4" y="-22" width="9" height="5" fill="#d8c48f"/>'
            f'<rect x="-8" y="-1" width="16" height="3" fill="#2f2b27"/>')


def draw_car(color):
    return (f'<rect x="-19" y="-13" width="38" height="13" rx="3" fill="{color}"/>'
            f'<rect x="-12" y="-23" width="24" height="11" rx="3" fill="{color}"/>'
            f'<rect x="-10" y="-21" width="9" height="7" fill="#9fb6c4"/>'
            f'<rect x="1" y="-21" width="9" height="7" fill="#9fb6c4"/>'
            f'<rect x="-19" y="-1" width="38" height="3" fill="#2f2b27"/>'
            f'<rect x="-14" y="0" width="7" height="4" rx="2" fill="#26231f"/>'
            f'<rect x="7" y="0" width="7" height="4" rx="2" fill="#26231f"/>')


def draw_bus(color):
    s = (f'<rect x="-30" y="-32" width="60" height="32" rx="3" fill="{color}"/>'
         f'<rect x="-30" y="-32" width="60" height="5" fill="#e8e4d6" opacity="0.5"/>')
    for k in range(5):
        s += f'<rect x="{-25+k*11}" y="-27" width="8" height="9" fill="#9fb6c4"/>'
    s += (f'<rect x="-30" y="-8" width="60" height="4" fill="#2f2b27" opacity="0.6"/>'
          f'<rect x="-22" y="-2" width="9" height="5" rx="2" fill="#26231f"/>'
          f'<rect x="13" y="-2" width="9" height="5" rx="2" fill="#26231f"/>')
    return s


def lane_blocked(cells):
    """A crater swallows the road, so nothing gets through. Floodwater doesn't stop anyone —
    this is Saigon; people just ride through it."""
    for gx, gy in cells:
        if (int(math.floor(gx)), int(math.floor(gy))) in craters:
            return True
    return False


def emit_traffic(cells, shape_svg, dur, phase, stops_at=None):
    """Cut the ride into depth slices; each slice is drawn with the houses at that depth."""
    if lane_blocked(cells):
        return
    pts = lane_points(cells)
    segs = []
    for i in range(len(pts) - 1):
        segs.append((pts[i], pts[i + 1], math.dist(pts[i], pts[i + 1])))
    total = sum(s[2] for s in segs)
    if total == 0:
        return

    # distance -> time, with a red-light pause partway if this lane meets a light
    def t_of(dist):
        f = dist / total
        if stops_at is None:
            return f
        if f <= stops_at:
            return RED0 * (f / stops_at) if stops_at else 0.0
        return RED1 + (1 - RED1) * (f - stops_at) / (1 - stops_at)

    # Walk the lane, cutting it whenever it crosses into a new BITMAP BAND (not every depth —
    # that produced 1,278 animated groups and killed the frame rate).
    chunks, cur, cur_band, acc = [], [pts[0]], None, 0.0
    start_dist = 0.0
    STEP = 6.0
    for (a, b, ln) in segs:
        n = max(1, int(ln / STEP))
        for k in range(1, n + 1):
            u = k / n
            p = (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u)
            acc += ln / n
            # invert the iso transform to find which cell we're standing in
            gx = ((p[0] - OX) / (TW / 2) + (p[1] - OY) / (TH / 2)) / 2
            gy = ((p[1] - OY) / (TH / 2) - (p[0] - OX) / (TW / 2)) / 2
            dep = max(0, min(2 * GRID - 1, int(math.floor(gx + gy))))
            band = dep // BAND_DEPTHS
            if cur_band is None:
                cur_band = band
            if band != cur_band:
                cur.append(p)
                chunks.append((cur_band, cur, start_dist, acc))
                cur, cur_band, start_dist = [p], band, acc
            else:
                cur.append(p)
    chunks.append((cur_band, cur, start_dist, acc))

    for band, poly_pts, d0, d1 in chunks:
        if len(poly_pts) < 2 or d1 - d0 < 1:
            continue
        t0, t1 = t_of(d0), t_of(d1)
        buf = layer(band * BAND_DEPTHS)
        path = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in poly_pts)
        pid = f"v{abs(hash((band, int(d0), int(d1), dur, phase, shape_svg[:24]))) % 10**9}"
        buf.write(f'<path id="{pid}" d="{path}" fill="none" stroke="none"/>')

        # SMIL requires keyTimes to span the whole 0..1 — so the vehicle waits at the chunk's
        # start, rides it during [t0,t1], then parks at the end (invisible either side).
        t0 = min(max(t0, 0.0), 1.0)
        t1 = min(max(t1, t0 + 0.001), 1.0)
        if stops_at is not None and d0 / total <= stops_at <= d1 / total:
            s = (stops_at * total - d0) / (d1 - d0)
            r0 = min(max(RED0, t0 + 0.0005), t1 - 0.0015)
            r1 = min(max(RED1, r0 + 0.0005), t1 - 0.001)
            kp = f'0;0;{s:.3f};{s:.3f};1;1'
            kt = f'0;{t0:.4f};{r0:.4f};{r1:.4f};{t1:.4f};1'
        else:
            kp = '0;0;1;1'
            kt = f'0;{t0:.4f};{t1:.4f};1'

        buf.write(
            f'<g opacity="0">'
            f'<animate attributeName="opacity" values="0;1;0;0" '
            f'keyTimes="0;{t0:.4f};{t1:.4f};1" dur="{dur}s" begin="{phase:.2f}s" '
            f'calcMode="discrete" repeatCount="indefinite"/>'
            f'<animateMotion dur="{dur}s" begin="{phase:.2f}s" repeatCount="indefinite" '
            f'calcMode="linear" keyPoints="{kp}" keyTimes="{kt}">'
            f'<mpath href="#{pid}"/></animateMotion>'
            f'{shape_svg}</g>\n'
        )


avenue = [(x, 6.5) for x in range(-1, 7)] + [(6.5, 7.5), (6.5, 8.5), (6.5, 9.5)] + \
         [(x, 9.5) for x in range(7, 15)] + [(14.5, 10.5), (14.5, 11.5), (14.5, 12.5)] + \
         [(x, 12.5) for x in range(15, 29)]
avenue_back = list(reversed(
    [(x, 7.2) for x in range(-1, 7)] + [(7.2, 8.0), (7.2, 9.0), (7.2, 10.2)] +
    [(x, 10.2) for x in range(7, 15)] + [(15.2, 11.0), (15.2, 12.0), (15.2, 13.2)] +
    [(x, 13.2) for x in range(15, 29)]))
south = [(x, 20.5) for x in range(-1, 10)] + [(9.5, 21.5), (9.5, 22.5), (9.5, 23.5)] + \
        [(x, 23.5) for x in range(10, 20)] + [(19.5, 24.5), (19.5, 28)]
colA = [(5.5, y) for y in range(-1, 15)] + [(6.5, 14.5), (7.5, 14.5)] + \
       [(8.5, y) for y in range(15, 29)]
colB = [(16.5, y) for y in range(-1, 29)]
colC = [(23.5, y) for y in range(29, -2, -1)]
alley = [(11.5, y) for y in range(4, 21)]
alley2 = [(20.5, y) for y in range(23, 8, -1)]

BIKES = ("#b03e2c", "#e8e4d6", "#3a6491", "#c78d24", "#6f8f52", "#46433d", "#9e5039", "#5f86a8")
CARS = ("#c9c4b6", "#3f5f8a", "#8a3b32", "#4a4640", "#d8d2c4")

# lanes that meet a light: they queue at it and wait out the red
for k in range(6):
    emit_traffic(avenue, draw_bike(BIKES[k % len(BIKES)]), CYCLE, -k * CYCLE / 6, stops_at=0.16)
emit_traffic(avenue, draw_car(CARS[1]), CYCLE, -0.45 * CYCLE, stops_at=0.13)
emit_traffic(avenue, draw_bus("#c78d24"), CYCLE, -0.80 * CYCLE, stops_at=0.10)

for k in range(5):
    emit_traffic(colA, draw_bike(BIKES[(k + 3) % len(BIKES)]), CYCLE, -k * CYCLE / 5, stops_at=0.21)
emit_traffic(colA, draw_car(CARS[2]), CYCLE, -0.6 * CYCLE, stops_at=0.18)

for k in range(5):
    emit_traffic(colB, draw_bike(BIKES[(k + 1) % len(BIKES)]), CYCLE, -k * CYCLE / 5, stops_at=0.44)
emit_traffic(colB, draw_bus("#3f7d52"), CYCLE, -0.35 * CYCLE, stops_at=0.41)

for k in range(4):
    emit_traffic(south, draw_bike(BIKES[(k + 5) % len(BIKES)]), CYCLE, -k * CYCLE / 4, stops_at=0.36)
emit_traffic(south, draw_car(CARS[0]), CYCLE, -0.7 * CYCLE, stops_at=0.33)

# lanes with no light: they just flow
for k in range(4):
    emit_traffic(colC, draw_bike(BIKES[(k + 2) % len(BIKES)]), CYCLE * 1.3, -k * 7.8)
emit_traffic(colC, draw_car(CARS[3]), CYCLE * 1.5, -12.0)
for k in range(5):
    emit_traffic(avenue_back, draw_bike(BIKES[(k + 4) % len(BIKES)]), CYCLE * 1.25, -k * 6.0)
emit_traffic(avenue_back, draw_car(CARS[4]), CYCLE * 1.45, -9.0)
for k in range(3):
    emit_traffic(alley, draw_bike(BIKES[(k + 6) % len(BIKES)]), CYCLE * 0.9, -k * 7.2)
for k in range(3):
    emit_traffic(alley2, draw_bike(BIKES[(k + 7) % len(BIKES)]), CYCLE * 0.95, -k * 7.6)

# ═══ assemble: bitmap band, then the vectors that move in front of it ════
def band_png(band):
    """crop the strip to what it actually covers, downscale, and hand back a data: URI"""
    im = _bitmaps[band]
    box = im.getbbox()
    if box is None:
        return None
    x0, y0, x1, y1 = box
    crop = im.crop(box).resize((max(1, (x1 - x0) // SS), max(1, (y1 - y0) // SS)), Image.LANCZOS)
    # flat pixel art: a 128-colour palette is indistinguishable and roughly a third of the bytes
    crop = crop.quantize(colors=128, method=Image.Quantize.FASTOCTREE)
    raw = io.BytesIO()
    crop.save(raw, format="PNG", optimize=True)
    b64 = base64.b64encode(raw.getvalue()).decode("ascii")
    return (x0 / SS, y0 / SS, crop.width, crop.height, b64)


out = io.StringIO()
out.write(
    f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
    f'viewBox="0 0 {CW} {CH}" width="{CW}" height="{CH}" '
    f'role="img" aria-label="Isometric pixel art of a Saigon neighbourhood">\n'
    f'<title>SAIGON — 8,000,000 concurrent workers, mostly on two wheels</title>\n'
)

png_bytes = 0
for band in range(NBANDS):
    strip = band_png(band)
    if strip:
        x, y, w, h, b64 = strip
        png_bytes += len(b64)
        out.write(f'<image x="{x:.0f}" y="{y:.0f}" width="{w}" height="{h}" '
                  f'image-rendering="auto" xlink:href="data:image/png;base64,{b64}"/>\n')
    # the vectors that live in this band ride on top of its bitmap
    for depth in range(band * BAND_DEPTHS, (band + 1) * BAND_DEPTHS):
        if depth in _layers:
            out.write(_layers[depth].svg.getvalue())

wrecked = len(collapsed) + len(charred) + len(craters)
if not EVENTS:
    status = "SAIGON · nguyen ven"
else:
    bits = []
    if wrecked:
        bits.append(f"{wrecked} cong trinh do nat")
    if cracked or craters:
        bits.append(f"{len(cracked) + len(craters)} doan duong hu")
    if flooded:
        bits.append(f"{len(flooded)} o ngap")
    status = f"SAIGON · {' · '.join(bits) or 'con nguyen'} · {len(EVENTS)} tham hoa"
out.write(
    f'<rect x="0" y="{CH-34}" width="{CW}" height="34" fill="#2b2823" opacity="0.55"/>'
    f'<text x="26" y="{CH-12}" font-family="monospace" font-size="14" fill="#e0d8c8">'
    f'{status} · maintainer: phihung13</text>\n</svg>\n'
)

svg = out.getvalue()
with open(OUT_PATH, "w", encoding="utf-8") as f:
    f.write(svg)

shapes = svg.count("<rect") + svg.count("<polygon") + svg.count("<line") + svg.count("<circle")
print(f"written: {len(svg)} bytes ({png_bytes//1024} KB of it PNG) | "
      f"vector shapes left: {shapes} | animations: {svg.count('<animate')} | "
      f"events={len(EVENTS)} collapsed={len(collapsed)} charred={len(charred)} "
      f"craters={len(craters)} cracked={len(cracked)} flooded={len(flooded)}")
