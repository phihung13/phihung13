# -*- coding: utf-8 -*-
"""Sài Gòn isometric v5.

The fix that matters: every moving vehicle is CUT INTO SEGMENTS BY DEPTH, and each segment is
emitted into the same depth bucket as the houses around it. A house nearer the camera therefore
paints over the segment behind it — no more traffic flying above the rooftops.
"""
import io
import math
from collections import defaultdict

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

road = [[False] * GRID for _ in range(GRID)]
taken = [[False] * GRID for _ in range(GRID)]
layers = defaultdict(io.StringIO)      # depth bucket -> svg fragments
head = io.StringIO()
tail = io.StringIO()


def rnd(s, n):
    return (s * 1103515245 + 12345) // 65536 % n


def C(gx, gy):
    return (OX + (gx - gy) * (TW / 2), OY + (gx + gy) * (TH / 2))


def mid(gx, gy, w=1, d=1):
    a, b = C(gx, gy), C(gx + w, gy + d)
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)


def P(buf, pts, fill, op=None):
    d = " ".join(f"{x:.0f},{y:.0f}" for x, y in pts)     # integers keep the file small
    o = f' opacity="{op}"' if op else ""
    buf.write(f'<polygon points="{d}" fill="{fill}"{o}/>')


def L(buf, p, q, c, w=1, op=1.0):
    sw = "" if w == 1 else f' stroke-width="{w}"'        # 1 is the default — don't write it
    o = "" if op >= 1 else f' opacity="{op}"'
    buf.write(f'<line x1="{p[0]:.0f}" y1="{p[1]:.0f}" x2="{q[0]:.0f}" y2="{q[1]:.0f}" '
              f'stroke="{c}"{sw}{o}/>')


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


# ═══ sky, slab, ground (all behind everything) ═══════════════════════
head.write(
    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {CW} {CH}" width="{CW}" height="{CH}" '
    f'role="img" aria-label="Isometric pixel art of a Saigon neighbourhood">\n'
    f'<title>SAIGON — 8,000,000 concurrent workers, mostly on two wheels</title>\n'
    f'<defs><linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">'
    f'<stop offset="0%" stop-color="#a7c4da"/><stop offset="55%" stop-color="#d2dfe6"/>'
    f'<stop offset="100%" stop-color="#ecdcc2"/></linearGradient></defs>\n'
    f'<rect width="{CW}" height="{CH}" fill="url(#sky)"/>\n'
    f'<circle cx="1160" cy="80" r="32" fill="#f7e6c6" opacity="0.85"/>\n'
    f'<g opacity="0.22">'
    f'<rect x="960" y="10" width="30" height="150" fill="#8fa6ba"/>'
    f'<rect x="971" y="-6" width="5" height="16" fill="#8fa6ba"/>'
    f'<rect x="1020" y="54" width="34" height="106" fill="#9db2c4"/>'
    f'<rect x="1010" y="68" width="54" height="6" fill="#9db2c4"/>'
    f'<rect x="180" y="60" width="38" height="100" fill="#a8b8c6"/>'
    f'<rect x="120" y="88" width="28" height="72" fill="#b0bfcb"/></g>\n'
)
for cyy, cw, dur, dl in ((34, 120, 170, 0), (96, 80, 220, -90)):
    head.write(
        f'<g opacity="0.7"><animateTransform attributeName="transform" type="translate" '
        f'values="-{cw+100} 0;{CW+cw} 0" dur="{dur}s" begin="{dl}s" repeatCount="indefinite"/>'
        f'<rect x="0" y="{cyy}" width="{cw}" height="14" fill="#f2ede1"/>'
        f'<rect x="20" y="{cyy-10}" width="{cw-50}" height="10" fill="#f2ede1"/></g>\n'
    )

def on_screen(gx, gy):
    """is this cell anywhere near the frame? everything else is skipped"""
    x, y = mid(gx, gy)
    return -MARGIN < x < CW + MARGIN and -MARGIN < y < CH + MARGIN


head.write(f'<rect width="{CW}" height="{CH}" fill="{DIRT}"/>\n')   # the city bleeds off every edge

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
        head.write(f'<ellipse cx="{c[0]:.0f}" cy="{c[1]:.0f}" rx="9" ry="6" fill="#54504a"/>'
                   f'<ellipse cx="{c[0]:.0f}" cy="{c[1]:.0f}" rx="6" ry="4" fill="#605b54"/>')
    else:
        P(head, [(c[0] - 10, c[1]), (c[0], c[1] - 6), (c[0] + 10, c[1]), (c[0], c[1] + 6)], "#4f4b45")
        for t in range(-2, 3):
            L(head, (c[0] - 6 + t * 3, c[1] + 3), (c[0] + 1 + t * 3, c[1] - 1), "#6b665f", 1, 0.9)
head.write("\n")


# ═══ a house ═════════════════════════════════════════════════════════
def house(buf, gx, gy, w, d, seed, kind="house"):
    N, E, S, W = C(gx, gy), C(gx + w, gy), C(gx + w, gy + d), C(gx, gy + d)
    floors = 1 + rnd(seed + 3, 5) if kind == "house" else 3
    fh = ZH - 2 + rnd(seed + 31, 5)
    h = floors * fh + 8 + rnd(seed + 7, 10)
    r, l, t = (GOV if kind == "gov" else FACADES[rnd(seed + 5, len(FACADES))])

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
            buf.write(f'<rect x="{dx:.0f}" y="{dy:.0f}" width="12" height="14" fill="{c}"/>')
            L(buf, (dx, dy + 5), (dx + 12, dy + 5), "#2f2b27", 1, 0.35)
        if rnd(seed + 9, 2):                                # vườn sân thượng
            for k in range(3):
                px, py = rc[0] - 30 + k * 11, rcy + 6 - k * 4
                buf.write(f'<rect x="{px:.0f}" y="{py:.0f}" width="8" height="6" fill="#a26f4c"/>'
                          f'<rect x="{px-1:.0f}" y="{py-7:.0f}" width="10" height="8" fill="{TREE}"/>')
        if rnd(seed + 11, 2):                               # dây phơi
            L(buf, (rc[0] - 28, rcy + 2), (rc[0] + 2, rcy - 14), RAIL, 1, 0.9)
            for k, c in enumerate(("#c05a4a", "#e8e4d6", "#5f86a8", "#d8c48f")):
                buf.write(f'<rect x="{rc[0]-26+k*7:.0f}" y="{rcy+1-k*3.7:.0f}" width="5" '
                          f'height="{9+k%2}" fill="{c}"/>')
        if rnd(seed + 17, 3) == 0:
            L(buf, (rc[0] - 22, rcy - 6), (rc[0] - 22, rcy - 32), RAIL, 1)
            L(buf, (rc[0] - 27, rcy - 27), (rc[0] - 17, rcy - 27), RAIL, 1)

    if kind == "gov":
        fx0, fy0 = rc[0], rcy - 8
        L(buf, (fx0, fy0), (fx0, fy0 - 40), RAIL, 2)
        buf.write(f'<rect x="{fx0:.0f}" y="{fy0-40:.0f}" width="26" height="17" fill="#c8322c"/>'
                  f'<text x="{fx0+13:.0f}" y="{fy0-27:.0f}" font-size="12" fill="#f2d64b" '
                  f'text-anchor="middle">★</text>'
                  f'<text x="{rc[0]:.0f}" y="{rcy+34:.0f}" font-family="monospace" font-size="9" '
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
    buf.write(f'<rect x="{tcx-16:.0f}" y="{tcy-56:.0f}" width="32" height="56" fill="#e6d0a0"/>'
              f'<rect x="{tcx+4:.0f}" y="{tcy-56:.0f}" width="12" height="56" fill="#c9b183"/>')
    P(buf, [(tcx - 20, tcy - 56), (tcx + 20, tcy - 56), (tcx, tcy - 82)], "#7d3d2c")
    buf.write(f'<circle cx="{tcx-2:.0f}" cy="{tcy-36:.0f}" r="10" fill="#f6f1e2" stroke="#4a453d" '
              f'stroke-width="2"/>'
              f'<line x1="{tcx-2:.0f}" y1="{tcy-36:.0f}" x2="{tcx-2:.0f}" y2="{tcy-44:.0f}" '
              f'stroke="#4a453d" stroke-width="2">'
              f'<animateTransform attributeName="transform" type="rotate" '
              f'from="0 {tcx-2:.0f} {tcy-36:.0f}" to="360 {tcx-2:.0f} {tcy-36:.0f}" dur="30s" '
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
    buf.write(f'<rect x="{c[0]-3:.0f}" y="{c[1]-h-34:.0f}" width="5" height="34" fill="#8fa6ba"/>')


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
        buf.write(f'<rect x="{bx:.0f}" y="{by:.0f}" width="20" height="4" fill="#b6ae9c"/>'
                  f'<rect x="{bx:.0f}" y="{by+4:.0f}" width="3" height="5" fill="#8f8878"/>'
                  f'<rect x="{bx+17:.0f}" y="{by+4:.0f}" width="3" height="5" fill="#8f8878"/>')
    for ox, oy, s in ((-34, -26, 1.3), (28, -30, 1.1), (0, -40, 1.0), (36, 14, 0.9)):
        bx, by = c[0] + ox, c[1] + oy
        buf.write(f'<rect x="{bx:.0f}" y="{by-24*s:.0f}" width="5" height="{24*s:.0f}" fill="{TRUNK}"/>'
                  f'<rect x="{bx-16*s:.0f}" y="{by-48*s:.0f}" width="{36*s:.0f}" '
                  f'height="{26*s:.0f}" fill="{TREE}"/>'
                  f'<rect x="{bx-11*s:.0f}" y="{by-55*s:.0f}" width="{26*s:.0f}" '
                  f'height="{8*s:.0f}" fill="{TREE}"/>'
                  f'<rect x="{bx-16*s:.0f}" y="{by-25*s:.0f}" width="{36*s:.0f}" height="3" fill="{TREE_D}"/>')
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
    buf = layers[depth]
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

        if (gx, gy) == GOV_AT and free(gx, gy, 2, 2):
            occupy(gx, gy, 2, 2)
            house(buf, gx, gy, 2, 2, seed, kind="gov")
            continue
        if rnd(seed, 12) == 0:                       # sân vườn
            b = mid(gx, gy)
            occupy(gx, gy, 1, 1)
            for ox, oy, s in ((-16, 6, 1.1), (10, -4, 0.8)):
                buf.write(f'<rect x="{b[0]+ox:.0f}" y="{b[1]+oy-20*s:.0f}" width="4" '
                          f'height="{20*s:.0f}" fill="{TRUNK}"/>'
                          f'<rect x="{b[0]+ox-13*s:.0f}" y="{b[1]+oy-40*s:.0f}" width="{30*s:.0f}" '
                          f'height="{22*s:.0f}" fill="{TREE}"/>')
            continue
        shape = rnd(seed + 41, 10)
        w, d = (2, 1) if shape < 2 else ((1, 2) if shape < 4 else (1, 1))
        if not free(gx, gy, w, d):
            w = d = 1
        occupy(gx, gy, w, d)
        house(buf, gx, gy, w, d, seed)

# ═══ sidewalk life — also bucketed, so houses can hide it ════════════
for gy in range(GRID):
    for gx in range(GRID):
        if road[gy][gx] or not on_screen(gx, gy) \
                or not (is_road(gx + 1, gy) or is_road(gx, gy + 1)):
            continue
        buf = layers[gx + gy]
        seed = gx * 13 + gy * 7
        c = mid(gx, gy)
        if rnd(seed + 1, 3) == 0:                                     # cây vỉa hè
            bx, by = c[0] + 20, c[1] + 14
            buf.write(f'<rect x="{bx:.0f}" y="{by-22:.0f}" width="4" height="22" fill="{TRUNK}"/>'
                      f'<rect x="{bx-13:.0f}" y="{by-44:.0f}" width="30" height="24" fill="{TREE}"/>'
                      f'<rect x="{bx-9:.0f}" y="{by-50:.0f}" width="22" height="7" fill="{TREE}"/>'
                      f'<rect x="{bx-13:.0f}" y="{by-23:.0f}" width="30" height="3" fill="{TREE_D}"/>')
        if rnd(seed + 2, 5) == 0:                                     # thùng rác
            bx, by = c[0] - 22, c[1] + 12
            buf.write(f'<rect x="{bx:.0f}" y="{by-14:.0f}" width="13" height="14" fill="#4a7a52"/>')
            P(buf, [(bx, by - 14), (bx + 6, by - 18), (bx + 13, by - 14), (bx + 7, by - 10)], "#5d8f63")
        if rnd(seed + 3, 6) == 0:                                     # xe ba gác đậu
            bx, by = c[0] + 4, c[1] + 22
            buf.write(f'<rect x="{bx-16:.0f}" y="{by-14:.0f}" width="26" height="10" fill="#8a6a3a"/>'
                      f'<rect x="{bx-16:.0f}" y="{by-20:.0f}" width="26" height="6" fill="#a8814a"/>'
                      f'<rect x="{bx+8:.0f}" y="{by-10:.0f}" width="12" height="4" fill="#4a4640"/>'
                      f'<rect x="{bx-14:.0f}" y="{by-4:.0f}" width="6" height="5" fill="#2f2b27"/>'
                      f'<rect x="{bx+2:.0f}" y="{by-4:.0f}" width="6" height="5" fill="#2f2b27"/>')
        if rnd(seed + 5, 7) == 0:                                     # gánh hàng rong
            bx, by = c[0] - 6, c[1] + 26
            buf.write(f'<rect x="{bx:.0f}" y="{by-18:.0f}" width="6" height="12" fill="#c9b48f"/>'
                      f'<rect x="{bx-1:.0f}" y="{by-24:.0f}" width="8" height="6" fill="#e0c877"/>'  # nón lá
                      f'<rect x="{bx-14:.0f}" y="{by-14:.0f}" width="34" height="2" fill="#8a7a5f"/>'
                      f'<rect x="{bx-16:.0f}" y="{by-12:.0f}" width="12" height="6" fill="#b08a52"/>'
                      f'<rect x="{bx+12:.0f}" y="{by-12:.0f}" width="12" height="6" fill="#b08a52"/>')
        if rnd(seed + 6, 8) == 0:                                     # xe bánh mì
            bx, by = c[0] + 14, c[1] + 26
            buf.write(f'<rect x="{bx-14:.0f}" y="{by-16:.0f}" width="26" height="11" fill="#c78d24"/>'
                      f'<rect x="{bx-16:.0f}" y="{by-22:.0f}" width="30" height="6" fill="#b03e2c"/>'
                      f'<rect x="{bx-12:.0f}" y="{by-5:.0f}" width="5" height="5" fill="#2f2b27"/>'
                      f'<rect x="{bx+4:.0f}" y="{by-5:.0f}" width="5" height="5" fill="#2f2b27"/>')

# ═══ đèn giao thông + đèn đường (bucketed) ═══════════════════════════
def traffic_light(gx, gy):
    buf = layers[gx + gy]
    b = C(gx, gy)
    L(buf, b, (b[0], b[1] - 62), "#4f4b45", 3)
    buf.write(f'<rect x="{b[0]-7:.0f}" y="{b[1]-92:.0f}" width="15" height="34" rx="3" fill="#3a3733"/>')
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
    buf = layers[gx + gy]
    b = C(gx + 1, gy + 1)
    L(buf, b, (b[0], b[1] - 58), RAIL, 2)
    L(buf, (b[0], b[1] - 58), (b[0] + 14, b[1] - 62), RAIL, 2)
    buf.write(f'<rect x="{b[0]+11:.0f}" y="{b[1]-65:.0f}" width="8" height="4" fill="#efe8d4"/>')
    # rao vặt dán đầy cột đèn
    buf.write(f'<rect x="{b[0]-5:.0f}" y="{b[1]-34:.0f}" width="9" height="6" fill="#e8e2d0"/>'
              f'<rect x="{b[0]-4:.0f}" y="{b[1]-24:.0f}" width="8" height="5" fill="#f0d9a8"/>')


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


def emit_traffic(cells, shape_svg, dur, phase, stops_at=None):
    """Cut the ride into depth slices; each slice is drawn with the houses at that depth."""
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

    # walk the lane, cutting whenever the depth bucket changes
    chunks, cur, cur_d, acc = [], [pts[0]], None, 0.0
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
            dep = int(math.floor(gx + gy))
            if cur_d is None:
                cur_d = dep
            if dep != cur_d:
                cur.append(p)
                chunks.append((cur_d, cur, start_dist, acc))
                cur, cur_d, start_dist = [p], dep, acc
            else:
                cur.append(p)
    chunks.append((cur_d, cur, start_dist, acc))

    for dep, poly_pts, d0, d1 in chunks:
        if len(poly_pts) < 2 or d1 - d0 < 1:
            continue
        t0, t1 = t_of(d0), t_of(d1)
        buf = layers[max(0, min(2 * GRID - 1, dep))]
        path = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in poly_pts)
        pid = f"v{abs(hash((dep, int(d0), int(d1), dur, phase))) % 10**9}"
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

# ═══ assemble: depth by depth ════════════════════════════════════════
out = io.StringIO()
out.write(head.getvalue())
for depth in sorted(layers):
    out.write(layers[depth].getvalue())
out.write(
    f'<text x="26" y="{CH-24}" font-family="monospace" font-size="14" fill="#6b6459">'
    f'SAIGON · 8,000,000 concurrent workers · uptime 326y · maintainer: phihung13</text>\n</svg>\n'
)

with open("saigon-iso6.svg", "w", encoding="utf-8") as f:
    f.write(out.getvalue())
print("written:", len(out.getvalue()), "bytes")
