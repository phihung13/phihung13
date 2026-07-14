/* Sài Gòn, playable.
 *
 * Same city as the README banner, but alive: disasters land the moment you click.
 *
 * The one structural trick worth knowing — the static city is pre-rendered ONCE into a stack of
 * offscreen canvases sliced by depth ("bands"). Every frame we blit those bands and slip the
 * vehicles in between them, so a house in front still covers the bike behind it, and we never
 * re-draw 500 houses at 60fps.
 */

const TW = 104, TH = 66, ZH = 25;
const GRID = 28;
const CW = 1440, CH = 810;
const OX = CW / 2, OY = CH / 2 - GRID * TH / 2;
const BAND_DEPTHS = 4;
const NBANDS = Math.ceil((2 * GRID) / BAND_DEPTHS) + 1;
const CYCLE = 12000;                     // ms — traffic light period
const RED0 = 0.40, RED1 = 0.62;

const ASPHALT = "#68635c", ASPHALT2 = "#605b54";
const WALK = "#b8b1a0", CURB = "#968f80", DIRT = "#9c9481";
const GRASS = "#6f8f52", GRASS_D = "#5a7742", POND = "#5f86a0";
const FACADES = [
  ["#d9c089", "#b6a06e", "#e6d3a6"], ["#bcc9b0", "#9caa91", "#d3ded0"],
  ["#d8c1b2", "#b59c8d", "#e7d5cb"], ["#c6c1b3", "#a49f90", "#dad6cb"],
  ["#e0d2ad", "#bcae8b", "#eee3c9"], ["#b9af99", "#978d78", "#cfc7b5"],
  ["#cfbcc2", "#ab99a0", "#e1d2d7"], ["#a9b3ad", "#8b968f", "#c3ccc6"],
];
const MOSS = "#5d7a4a", STAIN = "#6b6455";
const TILE_R = "#9e5039", TILE_L = "#7d3d2c", TILE_HL = "#b56a4f";
const TIN_R = "#8d9298", TIN_L = "#6f747a", RUST = "#8a5a3c";
const DRUM = ["#4a6b88", "#7a5a3a", "#5f6b52"];
const TANK_T = "#9aa8ae", TANK_L = "#5c686e", TANK_R = "#7a878d";
const TREE = "#57813f", TREE_D = "#3b5c31", TRUNK = "#5f4a33";
const SIGNS = ["#b03e2c", "#3a6491", "#c78d24", "#3f7d52", "#8f4d80", "#2a7076"];
const GLASS = "#5a6c7d", FRAME = "#e9e3d3", RAIL = "#8f8878";
const GOV = ["#e0c877", "#bda75d", "#efdfa4"];
const RUBBLE = ["#a89f8f", "#8c8474", "#6f6a5f"];
const CHAR = ["#5c534b", "#443d37", "#6e6459"];
const EMBER = "#d8632c", CRATER_A = "#4a453e", CRATER_B = "#332f2a";
const WATER = "#4b7f9e", SMOKE = "#b9b3a8";

const rnd = (s, n) => Math.floor((s * 1103515245 + 12345) / 65536) % n;
const Cc = (gx, gy) => [OX + (gx - gy) * (TW / 2), OY + (gx + gy) * (TH / 2)];
const mid = (gx, gy, w = 1, d = 1) => {
  const a = Cc(gx, gy), b = Cc(gx + w, gy + d);
  return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
};
const fp = (A, B, u, v) => [A[0] + (B[0] - A[0]) * u, A[1] + (B[1] - A[1]) * u - v];

/* ─── streets ─────────────────────────────────────────────────────── */
let road = Array.from({ length: GRID }, () => Array(GRID).fill(false));
function run(pts) {
  let [x, y] = pts[0];
  road[y][x] = true;
  for (const [tx, ty] of pts.slice(1)) {
    while (x !== tx) { x += tx > x ? 1 : -1; road[y][x] = true; }
    while (y !== ty) { y += ty > y ? 1 : -1; road[y][x] = true; }
  }
}
run([[0, 6], [6, 6], [6, 9], [14, 9], [14, 12], [27, 12]]);
run([[0, 20], [9, 20], [9, 23], [19, 23], [19, 27]]);
run([[5, 0], [5, 14], [8, 14], [8, 27]]);
run([[16, 0], [16, 27]]);
run([[23, 0], [23, 27]]);
run([[11, 4], [11, 20]]);
run([[20, 9], [20, 23]]);
run([[0, 15], [5, 15]]);
run([[20, 17], [27, 17]]);
{
  const wide = Array.from({ length: GRID }, () => Array(GRID).fill(false));
  for (let gy = 0; gy < GRID; gy++) for (let gx = 0; gx < GRID; gx++) {
    if (!road[gy][gx]) continue;
    wide[gy][gx] = true;
    if (gx + 1 < GRID) wide[gy][gx + 1] = true;
    if (gy + 1 < GRID) wide[gy + 1][gx] = true;
  }
  road = wide;
}
const isRoad = (x, y) => x >= 0 && x < GRID && y >= 0 && y < GRID && road[y][x];
const onScreen = (gx, gy) => {
  const [x, y] = mid(gx, gy);
  return x > -260 && x < CW + 260 && y > -260 && y < CH + 260;
};

/* ─── the plots: decided once, damaged later ──────────────────────── */
const MARKET = [12, 7], TOWER = [21, 6], GOV_AT = [6, 17], PARK = [17, 17];
const taken = Array.from({ length: GRID }, () => Array(GRID).fill(false));
const plots = [];                                  // {gx,gy,w,d,seed,kind,depth}

function occupy(gx, gy, w, d) {
  for (let y = gy; y < gy + d; y++) for (let x = gx; x < gx + w; x++)
    if (y >= 0 && y < GRID && x >= 0 && x < GRID) taken[y][x] = true;
}
function free(gx, gy, w, d) {
  for (let y = gy; y < gy + d; y++) for (let x = gx; x < gx + w; x++) {
    if (x < 0 || x >= GRID || y < 0 || y >= GRID) return false;
    if (road[y][x] || taken[y][x]) return false;
  }
  return true;
}

occupy(MARKET[0], MARKET[1], 2, 2);
for (let px = 11; px < 16; px++) for (let py = 6; py < 10; py++)
  if (px < GRID && py < GRID && !road[py][px]) taken[py][px] = true;
occupy(TOWER[0], TOWER[1], 1, 1);
occupy(PARK[0], PARK[1], 2, 2);

plots.push({ gx: MARKET[0], gy: MARKET[1], w: 2, d: 2, seed: 11, kind: "market" });
plots.push({ gx: TOWER[0], gy: TOWER[1], w: 1, d: 1, seed: 3, kind: "tower" });
plots.push({ gx: PARK[0], gy: PARK[1], w: 2, d: 2, seed: 5, kind: "park" });

for (let depth = 0; depth < 2 * GRID; depth++) {
  for (let gx = 0; gx < GRID; gx++) {
    const gy = depth - gx;
    if (gy < 0 || gy >= GRID || road[gy][gx] || taken[gy][gx] || !onScreen(gx, gy)) continue;
    const seed = gx * 37 + gy * 19 + 5;
    if (gx === GOV_AT[0] && gy === GOV_AT[1] && free(gx, gy, 2, 2)) {
      occupy(gx, gy, 2, 2);
      plots.push({ gx, gy, w: 2, d: 2, seed, kind: "gov" });
      continue;
    }
    if (rnd(seed, 12) === 0) {
      occupy(gx, gy, 1, 1);
      plots.push({ gx, gy, w: 1, d: 1, seed, kind: "garden" });
      continue;
    }
    const shape = rnd(seed + 41, 10);
    let w = shape < 2 ? 2 : 1, d = shape >= 2 && shape < 4 ? 2 : 1;
    if (!free(gx, gy, w, d)) { w = 1; d = 1; }
    occupy(gx, gy, w, d);
    plots.push({ gx, gy, w, d, seed, kind: "house" });
  }
}
for (const p of plots) p.depth = p.gx + p.gy;

/* ─── damage ──────────────────────────────────────────────────────── */
let events = [];
let collapsed = new Set(), charred = new Set(), craters = new Set(),
  cracked = new Set(), flooded = new Set();
const key = (x, y) => x + "," + y;

function pickCells(seed, n, wantRoad = false) {
  const out = [];
  let k = (seed * 7919) % (GRID * GRID);
  for (let i = 0; i < GRID * GRID; i++) {
    const gx = k % GRID, gy = Math.floor(k / GRID);
    k = (k + 3517) % (GRID * GRID);
    if (!onScreen(gx, gy)) continue;
    if (road[gy][gx] === wantRoad) {
      out.push([gx, gy]);
      if (out.length >= n) break;
    }
  }
  return out;
}

function recomputeDamage() {
  collapsed = new Set(); charred = new Set(); craters = new Set();
  cracked = new Set(); flooded = new Set();
  let tides = 0;
  for (const ev of events) {
    const { kind, seed } = ev;
    if (kind === "earthquake") {
      for (const [ex, ey] of pickCells(seed, 6)) {
        collapsed.add(key(ex, ey));
        for (const [dx, dy] of [[1, 0], [0, 1], [-1, 0], [0, -1]]) {
          const nx = ex + dx, ny = ey + dy;
          if (nx >= 0 && nx < GRID && ny >= 0 && ny < GRID && !road[ny][nx]
            && (dx + dy + seed) % 2 === 0) collapsed.add(key(nx, ny));
        }
      }
      for (const [cx, cy] of pickCells(seed + 31, 14, true)) cracked.add(key(cx, cy));
    } else if (kind === "lightning") {
      for (const [cx, cy] of pickCells(seed + 7, 8)) charred.add(key(cx, cy));
    } else if (kind === "war") {
      const spots = ev.at ? [ev.at] : pickCells(seed + 13, 3);
      for (const [ex, ey] of spots) {
        craters.add(key(ex, ey));
        for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) {
          const nx = ex + dx, ny = ey + dy;
          if (nx < 0 || nx >= GRID || ny < 0 || ny >= GRID) continue;
          const man = Math.abs(dx) + Math.abs(dy);
          if (road[ny][nx]) { if (man <= 1) craters.add(key(nx, ny)); }
          else if (man <= 1) collapsed.add(key(nx, ny));
          else if ((dx + dy + seed) % 2 === 0) charred.add(key(nx, ny));
        }
      }
    } else if (kind === "flood") {
      tides++;
      const waterline = CH - 150 * tides;
      for (let gy = 0; gy < GRID; gy++) for (let gx = 0; gx < GRID; gx++) {
        const y = OY + (gx + gy) * (TH / 2) + TH / 2;
        if (y >= waterline && onScreen(gx, gy)) flooded.add(key(gx, gy));
      }
    }
  }
  for (const k of craters) collapsed.delete(k);
  for (const k of collapsed) charred.delete(k);
  for (const k of craters) charred.delete(k);
}

/* ─── bands: the static city, pre-rendered ────────────────────────── */
const bands = [], bctx = [];
for (let i = 0; i < NBANDS; i++) {
  const cv = document.createElement("canvas");
  cv.width = CW; cv.height = CH;
  bands.push(cv);
  bctx.push(cv.getContext("2d"));
}
const bandOf = depth => Math.min(NBANDS - 1, Math.max(0, Math.floor(depth / BAND_DEPTHS)));

function poly(g, pts, fill, alpha = 1) {
  g.globalAlpha = alpha; g.fillStyle = fill;
  g.beginPath(); g.moveTo(pts[0][0], pts[0][1]);
  for (let i = 1; i < pts.length; i++) g.lineTo(pts[i][0], pts[i][1]);
  g.closePath(); g.fill(); g.globalAlpha = 1;
}
function line(g, p, q, c, w = 1, alpha = 1) {
  g.globalAlpha = alpha; g.strokeStyle = c; g.lineWidth = w;
  g.beginPath(); g.moveTo(p[0], p[1]); g.lineTo(q[0], q[1]); g.stroke(); g.globalAlpha = 1;
}
function rectf(g, x, y, w, h, fill, alpha = 1) {
  g.globalAlpha = alpha; g.fillStyle = fill; g.fillRect(x, y, w, h); g.globalAlpha = 1;
}
function ell(g, cx, cy, rx, ry, fill, alpha = 1) {
  g.globalAlpha = alpha; g.fillStyle = fill;
  g.beginPath(); g.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2); g.fill(); g.globalAlpha = 1;
}
function panel(g, A, B, u0, u1, v0, v1, fill, alpha = 1) {
  poly(g, [fp(A, B, u0, v0), fp(A, B, u1, v0), fp(A, B, u1, v1), fp(A, B, u0, v1)], fill, alpha);
}

function drawHouse(g, p) {
  const { gx, gy, w, d, seed } = p;
  const burnt = charred.has(key(gx, gy));
  const N = Cc(gx, gy), E = Cc(gx + w, gy), S = Cc(gx + w, gy + d), W = Cc(gx, gy + d);
  const govt = p.kind === "gov";
  let floors = govt ? 3 : 1 + rnd(seed + 3, 5);
  const fh = ZH - 2 + rnd(seed + 31, 5);
  const h = floors * fh + 8 + rnd(seed + 7, 10);
  let [r, l, t] = govt ? GOV : FACADES[rnd(seed + 5, FACADES.length)];
  if (burnt) { r = CHAR[2]; l = CHAR[1]; t = CHAR[0]; }

  poly(g, [[N[0] + 10, N[1] + 6], [E[0] + 10, E[1] + 6], [S[0] + 10, S[1] + 6],
  [W[0] + 10, W[1] + 6]], "#5a5346", 0.16);
  const up = pt => [pt[0], pt[1] - h];
  poly(g, [W, S, up(S), up(W)], l);
  poly(g, [S, E, up(E), up(S)], r);
  poly(g, [up(N), up(E), up(S), up(W)], t);

  let streetR = false, streetL = false;
  for (let i = 0; i < d; i++) if (isRoad(gx + w, gy + i)) streetR = true;
  for (let i = 0; i < w; i++) if (isRoad(gx + i, gy + d)) streetL = true;

  for (const [A, B] of [[S, E], [W, S]]) {
    for (let m = 0; m < 3; m++) {
      const u = 0.08 + rnd(seed + m * 5, 70) / 100;
      panel(g, A, B, u, Math.min(u + 0.10, 0.98), 0, 3 + rnd(seed + m, 8), MOSS, 0.22);
    }
    for (let m = 0; m < 2; m++) {
      const u = 0.15 + rnd(seed + m * 9 + 3, 60) / 100;
      panel(g, A, B, u, u + 0.04, 6, h - 14, STAIN, 0.07);
    }
  }

  for (let f = 0; f < floors; f++) {
    const v = 10 + f * fh;
    if (v + fh > h - 4) break;
    const ground = f === 0;
    for (const [A, B, sunny, faces] of [[S, E, true, streetR], [W, S, false, streetL]]) {
      const al = sunny ? 1 : 0.9;
      if (ground && faces) {
        if (govt) {
          panel(g, A, B, 0.30, 0.70, 0, 20, "#6d5f4a", al);
          panel(g, A, B, 0.26, 0.74, 20, 23, "#8a7a5f", al);
          for (let k = 0; k < 4; k++) {
            const u = 0.20 + k * 0.20;
            panel(g, A, B, u, u + 0.035, 0, h - 20, "#eee3c9", al);
          }
          continue;
        }
        panel(g, A, B, 0.14, 0.60, 0, 16, "#3f3c37", al);
        for (let k = 0; k < 6; k++)
          line(g, fp(A, B, 0.14, 3 + k * 2.4), fp(A, B, 0.60, 3 + k * 2.4), "#54504a", 1, 0.7);
        panel(g, A, B, 0.66, 0.90, 0, 14, "#38352f", al);
        panel(g, A, B, 0.08, 0.96, 16, 19, SIGNS[rnd(seed + 2, SIGNS.length)], al);
        panel(g, A, B, 0.12, 0.92, 21, 28, SIGNS[rnd(seed + 4, SIGNS.length)], al);
        continue;
      }
      if (ground) { panel(g, A, B, 0.22, 0.52, 0, 13, "#46433d", al); continue; }
      const nwin = (w === 1 && d === 1) ? 2 : 3;
      for (let i = 0; i < nwin; i++) {
        const u0 = 0.12 + i * (0.76 / nwin);
        const u1 = u0 + 0.76 / nwin - 0.10;
        panel(g, A, B, u0, u1, v, v + 13, FRAME, al);
        panel(g, A, B, u0 + 0.02, u1 - 0.02, v + 2, v + 11, GLASS, al);
      }
      if (sunny && rnd(seed + f * 7, 3)) {
        panel(g, A, B, 0.10, 0.92, v - 3, v - 1, "#c2bba9");
        for (let k = 0; k < 11; k++) {
          const u = 0.10 + k * 0.082;
          line(g, fp(A, B, u, v - 3), fp(A, B, u, v + 5), RAIL, 1, 0.8);
        }
        line(g, fp(A, B, 0.10, v + 5), fp(A, B, 0.92, v + 5), RAIL, 1, 0.8);
        if (rnd(seed + f, 2)) {
          panel(g, A, B, 0.78, 0.88, v - 1, v + 4, "#a26f4c");
          panel(g, A, B, 0.76, 0.90, v + 4, v + 10, TREE);
        }
      }
      if (!sunny && rnd(seed + f * 3, 3) === 0)
        panel(g, A, B, 0.60, 0.78, v + 2, v + 9, "#cfc9bb", 0.95);
    }
  }

  const rc = mid(gx, gy, w, d), rcy = rc[1] - h;
  const roof = govt ? 9 : rnd(seed + 23, 10);
  if (roof < 4) {                                    // mái tôn
    const pitch = 20 + rnd(seed, 10);
    const apex = [(N[0] + S[0]) / 2, (N[1] + S[1]) / 2 - h - pitch];
    poly(g, [up(W), up(S), apex], TIN_L);
    poly(g, [up(S), up(E), apex], TIN_R);
    for (let k = 1; k < 9; k++) {
      const a = [up(S)[0] + (up(E)[0] - up(S)[0]) * k / 9, up(S)[1] + (up(E)[1] - up(S)[1]) * k / 9];
      line(g, a, apex, "#a7acb2", 1, 0.5);
    }
    if (rnd(seed + 2, 2)) poly(g, [up(S), [up(S)[0] + 18, up(S)[1] - 10],
    [apex[0], apex[1] + 14], [up(S)[0] + 4, up(S)[1] - 2]], RUST, 0.35);
  } else if (roof < 6) {                             // mái ngói
    const apex = [(N[0] + S[0]) / 2, (N[1] + S[1]) / 2 - h - 26];
    poly(g, [up(W), up(S), apex], TILE_L);
    poly(g, [up(S), up(E), apex], TILE_R);
    for (let k = 1; k < 7; k++) {
      const a = [up(S)[0] + (up(E)[0] - up(S)[0]) * k / 7, up(S)[1] + (up(E)[1] - up(S)[1]) * k / 7];
      line(g, a, apex, TILE_HL, 1, 0.3);
    }
  } else {                                           // sân thượng
    for (const [A, B] of [[S, E], [W, S]]) {
      panel(g, A, B, 0, 1, h - 7, h, "#d6cfbe", 0.92);
      for (let k = 0; k < 12; k++) {
        const u = 0.04 + k * 0.08;
        panel(g, A, B, u, u + 0.03, h - 7, h - 1, "#b6ae9c", 0.9);
      }
    }
    const tx = rc[0] - 14, ty = rcy - 18;
    poly(g, [[tx, ty + 10], [tx + 12, ty + 3], [tx + 24, ty + 10], [tx + 12, ty + 17]], TANK_T);
    poly(g, [[tx, ty + 10], [tx + 12, ty + 17], [tx + 12, ty + 29], [tx, ty + 22]], TANK_L);
    poly(g, [[tx + 12, ty + 17], [tx + 24, ty + 10], [tx + 24, ty + 22], [tx + 12, ty + 29]], TANK_R);
    for (let k = 0; k < 1 + rnd(seed + 5, 2); k++) {
      const dx = rc[0] + 16 + k * 13, dy = rcy - 4 + k * 5;
      poly(g, [[dx, dy], [dx + 6, dy - 3], [dx + 12, dy], [dx + 6, dy + 3]], "#c9c2b0");
      rectf(g, dx, dy, 12, 14, DRUM[rnd(seed + k * 3, DRUM.length)]);
    }
    if (rnd(seed + 9, 2)) for (let k = 0; k < 3; k++) {
      const px = rc[0] - 30 + k * 11, py = rcy + 6 - k * 4;
      rectf(g, px, py, 8, 6, "#a26f4c");
      rectf(g, px - 1, py - 7, 10, 8, TREE);
    }
    if (rnd(seed + 11, 2)) {
      line(g, [rc[0] - 28, rcy + 2], [rc[0] + 2, rcy - 14], RAIL, 1, 0.9);
      ["#c05a4a", "#e8e4d6", "#5f86a8", "#d8c48f"].forEach((c, k) =>
        rectf(g, rc[0] - 26 + k * 7, rcy + 1 - k * 3.7, 5, 9 + k % 2, c));
    }
  }
  if (govt) {
    line(g, [rc[0], rcy - 8], [rc[0], rcy - 48], RAIL, 2);
    rectf(g, rc[0], rcy - 48, 26, 17, "#c8322c");
    g.fillStyle = "#f2d64b"; g.font = "12px monospace"; g.fillText("★", rc[0] + 7, rcy - 35);
    g.fillStyle = "#5d5647"; g.font = "9px monospace"; g.textAlign = "center";
    g.fillText("UBND PHUONG", rc[0], rcy + 34); g.textAlign = "left";
  }
  if (burnt) {
    for (const [A, B] of [[S, E], [W, S]]) panel(g, A, B, 0.30, 0.55, 18, 34, EMBER, 0.55);
    ell(g, rc[0], rcy + 4, 22, 10, EMBER, 0.3);
  }
}

function drawRubble(g, p) {
  const { gx, gy, seed } = p;
  const N = Cc(gx, gy), E = Cc(gx + 1, gy), S = Cc(gx + 1, gy + 1), W = Cc(gx, gy + 1);
  poly(g, [N, E, S, W], "#8f8878");
  [[0.10, 26], [0.42, 14], [0.78, 22]].forEach(([u, hh], i) => {
    const [A, B] = i % 2 ? [S, E] : [W, S];
    panel(g, A, B, u, u + 0.16, 0, hh, RUBBLE[i % 2]);
    panel(g, A, B, u, u + 0.16, hh - 3, hh, RUBBLE[2]);
  });
  const c = mid(gx, gy);
  for (let k = 0; k < 9; k++) {
    const ox = -34 + ((seed * (k + 3) * 17) % 68);
    const oy = -6 + ((seed * (k + 5) * 11) % 22);
    const s = 5 + ((seed * (k + 7)) % 9);
    poly(g, [[c[0] + ox, c[1] + oy], [c[0] + ox + s, c[1] + oy - s * 0.6],
    [c[0] + ox + 2 * s, c[1] + oy], [c[0] + ox + s, c[1] + oy + s * 0.6]], RUBBLE[(seed + k) % 3]);
  }
}

function drawCrater(g, gx, gy, seed) {
  const c = mid(gx, gy);
  poly(g, [[c[0] - 46, c[1]], [c[0], c[1] - 28], [c[0] + 46, c[1]], [c[0], c[1] + 28]], CRATER_A);
  poly(g, [[c[0] - 30, c[1]], [c[0], c[1] - 18], [c[0] + 30, c[1]], [c[0], c[1] + 18]], CRATER_B);
  ell(g, c[0], c[1] - 6, 26, 14, EMBER, 0.25);
}

function drawCrack(g, gx, gy, seed) {
  const c = mid(gx, gy);
  const pts = [];
  for (let k = 0; k < 6; k++) {
    const t = k / 5, jitter = -8 + ((seed * (k + 3) * 19) % 16);
    pts.push([c[0] - 48 + 96 * t, c[1] - 28 + 56 * t + jitter]);
  }
  g.strokeStyle = CRATER_B; g.lineWidth = 7; g.lineJoin = "round";
  g.beginPath(); g.moveTo(pts[0][0], pts[0][1]);
  pts.slice(1).forEach(p => g.lineTo(p[0], p[1]));
  g.stroke();
  g.strokeStyle = "#231f1c"; g.lineWidth = 3; g.stroke();
}

function drawPark(g, p) {
  const { gx, gy } = p, w = 2, d = 2;
  const N = Cc(gx, gy), E = Cc(gx + w, gy), S = Cc(gx + w, gy + d), W = Cc(gx, gy + d);
  poly(g, [N, E, S, W], GRASS);
  const c = mid(gx, gy, w, d);
  poly(g, [[c[0] - 46, c[1]], [c[0], c[1] - 28], [c[0] + 46, c[1]], [c[0], c[1] + 28]], GRASS_D, 0.5);
  poly(g, [[c[0] - 24, c[1] + 12], [c[0] - 2, c[1] + 1], [c[0] + 20, c[1] + 12],
  [c[0] - 2, c[1] + 23]], POND);
  [[-34, -26, 1.3], [28, -30, 1.1], [0, -40, 1.0], [36, 14, 0.9]].forEach(([ox, oy, s]) => {
    const bx = c[0] + ox, by = c[1] + oy;
    rectf(g, bx, by - 24 * s, 5, 24 * s, TRUNK);
    rectf(g, bx - 16 * s, by - 48 * s, 36 * s, 26 * s, TREE);
    rectf(g, bx - 16 * s, by - 25 * s, 36 * s, 3, TREE_D);
  });
}

function drawMarket(g, p) {
  const { gx, gy } = p, w = 2, d = 2, h = 54;
  const N = Cc(gx, gy), E = Cc(gx + w, gy), S = Cc(gx + w, gy + d), W = Cc(gx, gy + d);
  const up = pt => [pt[0], pt[1] - h];
  poly(g, [W, S, up(S), up(W)], "#d3bd8e");
  poly(g, [S, E, up(E), up(S)], "#e6d0a0");
  for (const [A, B] of [[S, E], [W, S]])
    for (let k = 0; k < 4; k++) panel(g, A, B, 0.10 + k * 0.21, 0.10 + k * 0.21 + 0.13, 0, 24, "#4a453d");
  const apex = [(N[0] + S[0]) / 2, (N[1] + S[1]) / 2 - h - 34];
  poly(g, [up(W), up(S), apex], "#7d3d2c");
  poly(g, [up(S), up(E), apex], "#9e5039");
  const tcx = apex[0], tcy = apex[1] + 8;
  rectf(g, tcx - 16, tcy - 56, 32, 56, "#e6d0a0");
  rectf(g, tcx + 4, tcy - 56, 12, 56, "#c9b183");
  poly(g, [[tcx - 20, tcy - 56], [tcx + 20, tcy - 56], [tcx, tcy - 82]], "#7d3d2c");
  ell(g, tcx - 2, tcy - 36, 11, 11, "#4a453d");
  ell(g, tcx - 2, tcy - 36, 9, 9, "#f6f1e2");
  g.fillStyle = "#5d5647"; g.font = "10px monospace"; g.textAlign = "center";
  g.fillText("CHO BEN THANH", tcx, tcy + 26); g.textAlign = "left";
  p.clock = [tcx - 2, tcy - 36];
}

function drawTower(g, p) {
  const { gx, gy } = p, h = 190;
  const N = Cc(gx, gy), E = Cc(gx + 1, gy), S = Cc(gx + 1, gy + 1), W = Cc(gx, gy + 1);
  const up = pt => [pt[0], pt[1] - h];
  poly(g, [W, S, up(S), up(W)], "#7e93a4");
  poly(g, [S, E, up(E), up(S)], "#9db2c2");
  poly(g, [up(N), up(E), up(S), up(W)], "#c2d2dd");
  for (let f = 0; f < 11; f++) {
    const v = 12 + f * 16;
    for (const [A, B] of [[S, E], [W, S]]) panel(g, A, B, 0.12, 0.88, v, v + 10, "#5f7f99");
  }
}

function drawGarden(g, p) {
  const b = mid(p.gx, p.gy);
  [[-16, 6, 1.1], [10, -4, 0.8]].forEach(([ox, oy, s]) => {
    rectf(g, b[0] + ox, b[1] + oy - 20 * s, 4, 20 * s, TRUNK);
    rectf(g, b[0] + ox - 13 * s, b[1] + oy - 40 * s, 30 * s, 22 * s, TREE);
  });
}

/* the ground, drawn once into band 0 */
function drawGround(g) {
  rectf(g, 0, 0, CW, CH, DIRT);
  for (let gy = 0; gy < GRID; gy++) for (let gx = 0; gx < GRID; gx++) {
    if (!onScreen(gx, gy)) continue;
    const N = Cc(gx, gy), E = Cc(gx + 1, gy), S = Cc(gx + 1, gy + 1), W = Cc(gx, gy + 1);
    poly(g, [N, E, S, W], road[gy][gx] ? ((gx + gy) % 2 ? ASPHALT : ASPHALT2) : DIRT);
  }
  for (let gy = 0; gy < GRID; gy++) for (let gx = 0; gx < GRID; gx++) {
    if (road[gy][gx] || !onScreen(gx, gy)) continue;
    const N = Cc(gx, gy), E = Cc(gx + 1, gy), S = Cc(gx + 1, gy + 1), W = Cc(gx, gy + 1);
    poly(g, [N, E, S, W], WALK);
    if (isRoad(gx + 1, gy)) line(g, E, S, CURB, 3, 0.9);
    if (isRoad(gx, gy + 1)) line(g, S, W, CURB, 3, 0.9);
  }
  for (let gy = 0; gy < GRID; gy++) for (let gx = 0; gx < GRID; gx++) {
    if (!road[gy][gx] || !onScreen(gx, gy)) continue;
    const ew = isRoad(gx - 1, gy) && isRoad(gx + 1, gy);
    const ns = isRoad(gx, gy - 1) && isRoad(gx, gy + 1);
    if (ew === ns) continue;
    const c = mid(gx, gy);
    if (ew) line(g, [c[0] - 16, c[1] - 10], [c[0] + 16, c[1] + 10], "#ded5c1", 2, 0.45);
    else line(g, [c[0] - 16, c[1] + 10], [c[0] + 16, c[1] - 10], "#ded5c1", 2, 0.45);
  }
}

/* street furniture, per plot cell that faces a road */
function drawSidewalk(g, gx, gy) {
  const seed = gx * 13 + gy * 7, c = mid(gx, gy);
  if (rnd(seed + 1, 3) === 0) {
    const bx = c[0] + 20, by = c[1] + 14;
    rectf(g, bx, by - 22, 4, 22, TRUNK);
    rectf(g, bx - 13, by - 44, 30, 24, TREE);
    rectf(g, bx - 13, by - 23, 30, 3, TREE_D);
  }
  if (rnd(seed + 2, 5) === 0) rectf(g, c[0] - 22, c[1] - 2, 13, 14, "#4a7a52");
  if (rnd(seed + 3, 6) === 0) {
    const bx = c[0] + 4, by = c[1] + 22;
    rectf(g, bx - 16, by - 20, 26, 16, "#a8814a");
    rectf(g, bx - 14, by - 4, 6, 5, "#2f2b27");
    rectf(g, bx + 2, by - 4, 6, 5, "#2f2b27");
  }
  if (rnd(seed + 6, 8) === 0) {
    const bx = c[0] + 14, by = c[1] + 26;
    rectf(g, bx - 14, by - 16, 26, 11, "#c78d24");
    rectf(g, bx - 16, by - 22, 30, 6, "#b03e2c");
  }
}

const lightsAt = [[5, 6], [16, 12], [8, 20]];

function renderCity() {
  bctx.forEach(g => g.clearRect(0, 0, CW, CH));
  drawGround(bctx[0]);

  for (const p of plots) {
    const g = bctx[bandOf(p.depth)];
    const k = key(p.gx, p.gy);
    if (craters.has(k)) continue;
    if (collapsed.has(k)) { drawRubble(g, p); continue; }
    if (p.kind === "market") drawMarket(g, p);
    else if (p.kind === "tower") drawTower(g, p);
    else if (p.kind === "park") drawPark(g, p);
    else if (p.kind === "garden") drawGarden(g, p);
    else drawHouse(g, p);
  }

  for (let gy = 0; gy < GRID; gy++) for (let gx = 0; gx < GRID; gx++) {
    if (road[gy][gx] || !onScreen(gx, gy)) continue;
    if (!(isRoad(gx + 1, gy) || isRoad(gx, gy + 1))) continue;
    if (collapsed.has(key(gx, gy)) || craters.has(key(gx, gy))) continue;
    drawSidewalk(bctx[bandOf(gx + gy)], gx, gy);
  }

  // damage that lies on the ground
  for (let gy = 0; gy < GRID; gy++) for (let gx = 0; gx < GRID; gx++) {
    if (!onScreen(gx, gy)) continue;
    const g = bctx[bandOf(gx + gy)];
    const k = key(gx, gy), s = gx * 7 + gy * 13 + 3;
    if (craters.has(k)) drawCrater(g, gx, gy, s);
    else if (cracked.has(k)) drawCrack(g, gx, gy, s);
  }

  // traffic light poles (the lamps are drawn live, they blink)
  for (const [gx, gy] of lightsAt) {
    const g = bctx[bandOf(gx + gy)];
    const b = Cc(gx, gy);
    line(g, b, [b[0], b[1] - 62], "#4f4b45", 3);
    rectf(g, b[0] - 7, b[1] - 92, 15, 34, "#3a3733");
  }
}

export {
  TW, TH, ZH, GRID, CW, CH, OX, OY, CYCLE, RED0, RED1, BAND_DEPTHS, NBANDS,
  road, isRoad, onScreen, mid, Cc, plots, bands, bandOf, lightsAt,
  events, recomputeDamage, renderCity, key,
  collapsed, charred, craters, cracked, flooded, WATER, SMOKE, EMBER,
};
