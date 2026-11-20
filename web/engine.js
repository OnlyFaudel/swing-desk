// Patient Levels engine (browser). Mirrors patient.py simulate(): same pivots, entries, exits, costs.
// bars: {t:[epochSec], o:[], h:[], l:[], c:[]} hourly. Returns trades [{en,ex,ret}] (ret as fraction).
function plEngine(b, P) {
  const k = P.k ?? 5, look = P.look ?? 70, n = b.c.length;
  const front = P.front, pad = P.pad, rr = P.rr, maxh = P.maxh, valid = P.valid, thr = (P.through ?? 0) / 100, cost = P.cost / 100;
  const plo = new Uint8Array(n), phi = new Uint8Array(n);
  for (let i = k; i < n - k; i++) {
    let mn = Infinity, mx = -Infinity;
    for (let j = i - k; j <= i + k; j++) { if (b.l[j] < mn) mn = b.l[j]; if (b.h[j] > mx) mx = b.h[j]; }
    plo[i] = b.l[i] === mn ? 1 : 0; phi[i] = b.h[i] === mx ? 1 : 0;
  }
  const out = []; let i = look * 2 + k;
  while (i < n - 1) {
    const prev = b.c[i - 1]; let Z = -Infinity, R = Infinity;
    for (let j = i - look; j < i - k; j++) if (plo[j] && b.l[j] < prev * 0.995 && b.l[j] > Z) Z = b.l[j];
    for (let j = i - look * 2; j < i - k; j++) if (phi[j] && b.h[j] > prev * 1.01 && b.h[j] < R) R = b.h[j];
    if (Z === -Infinity || R === Infinity) { i++; continue; }
    const e = Z * (1 + front / 100), s = Z * (1 - pad / 100);
    if (!(s < e) || R - e < rr * (e - s) || e >= prev) { i++; continue; }
    let f = -1;
    for (let j = i; j < Math.min(i + valid, n); j++) if (b.l[j] <= e * (1 - thr)) { f = j; break; }
    if (f < 0) { i++; continue; }
    const ep = Math.min(e, b.o[f]); let res = null;
    for (let j = f; j < Math.min(f + maxh, n); j++) {
      if (b.l[j] <= s) { res = [Math.min(s, j > f ? b.o[j] : ep), j]; break; }  // gap through stop: out at fill, never above it
      if (b.h[j] >= R && j > f) { res = [Math.max(R, b.o[j]), j]; break; }
    }
    if (!res) { const j = Math.min(f + maxh, n - 1); res = [b.c[j], j]; }
    out.push({ en: b.t[f], ex: b.t[res[1]], ret: res[0] / ep - 1 - cost, entry: ep, exit: res[0], zone: Z, stop: s, target: R });
    i = res[1] + 1;
  }
  return out;
}
if (typeof module !== "undefined") module.exports = { plEngine };
