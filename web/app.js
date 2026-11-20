// C9 Scout UI: reads the engine's aggregated JSON and draws heatmaps + evidence.
const $ = (s) => document.querySelector(s);
const cv = $("#cv"), ctx = cv.getContext("2d");
const PH = ["Buy", "0–20s", "20–40s", "40s+"];
const COLS = "ABCDEFGHIJ";
const S = { index: null, team: null, map: null, side: "defender", mode: "utility",
  agent: null, abilities: new Set(), phases: new Set([0, 1, 2, 3]), player: null, weapon: "operator", zone: null, sil: {} };
const opData = () => S.team.op?.[S.map]?.[S.side]?.[S.weapon] || {};

const get = (u) => fetch(u).then((r) => { if (!r.ok) throw new Error(u); return r.json(); });
const pct = (k, n) => (n ? Math.round((100 * k) / n) : 0);
const zoneName = (zx, zy) => `${COLS[zx]}${S.index.zone - zy}`;
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

async function init() {
  S.index = await get("data/index.json");
  $("#team").innerHTML = S.index.teams.map((t) =>
    `<option value="${t.id}">${t.name.includes("Cloud9") ? "★ " : ""}${esc(t.name)}${t.name.includes("Cloud9") ? " (self-scout)" : ""} · ${t.series} series</option>`).join("");
  const c9 = S.index.teams.find((t) => t.name === "Cloud9") || S.index.teams[0];
  $("#team").value = c9.id;
  $("#team").onchange = () => loadTeam($("#team").value);
  $("#map").onchange = () => { S.map = $("#map").value; resetFilters(); render(); };
  seg("#side", (v) => { S.side = v; resetFilters(); render(); });
  seg("#mode", (v) => { S.mode = v; S.zone = null; S.player = null; pickWeapon(); render(); });
  cv.addEventListener("click", onClick);
  cv.addEventListener("mousemove", onMove);
  cv.addEventListener("mouseleave", () => ($("#tip").hidden = true));
  await loadTeam(c9.id);
}

function seg(sel, fn) {
  document.querySelectorAll(`${sel} button`).forEach((b) => (b.onclick = () => {
    document.querySelectorAll(`${sel} button`).forEach((x) => x.classList.toggle("on", x === b));
    fn(b.dataset.v);
  }));
}
function setSeg(sel, v) { document.querySelectorAll(`${sel} button`).forEach((x) => x.classList.toggle("on", x.dataset.v === v)); }

async function loadTeam(id) {
  S.team = await get(`data/teams/${id}.json`);
  const maps = Object.keys(S.team.rounds).sort((a, b) => total(S.team.rounds[b]) - total(S.team.rounds[a]));
  $("#map").innerHTML = maps.map((m) => `<option value="${m}">${cap(m)} · ${total(S.team.rounds[m])} rds</option>`).join("");
  S.map = maps[0];
  resetFilters();
  render();
}
const total = (o) => Object.values(o || {}).reduce((a, b) => a + b, 0);
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);

function resetFilters() {
  S.zone = null; S.player = null; S.abilities.clear();
  const ar = S.team.agentRounds?.[S.map]?.[S.side] || {};
  S.agent = Object.keys(ar).sort((a, b) => ar[b] - ar[a])[0] || null;
  const casts = S.team.casts?.[S.map]?.[S.side]?.[S.agent] || {};
  const byCount = Object.entries(casts).map(([ab, cs]) => [ab, cs.reduce((a, c) => a + c[3], 0)]).sort((a, b) => b[1] - a[1]);
  if (byCount[0]) S.abilities.add(byCount[0][0]);
  pickWeapon();
}
function pickWeapon() {  // default to the long-range weapon this team actually buys most here
  const ws = S.team.op?.[S.map]?.[S.side] || {};
  S.weapon = Object.keys(ws).sort((a, b) => (ws[b].opRounds || 0) - (ws[a].opRounds || 0))[0] || "operator";
}

async function silhouette(m) {
  if (!S.sil[m]) S.sil[m] = await get(`data/maps/${m}.json`).catch(() => null);
  return S.sil[m];
}

// ---------- filters ----------
function chips(label, items, isOn, onToggle) {
  const g = document.createElement("div");
  g.className = "group";
  g.innerHTML = `<span>${label}</span>`;
  for (const [v, text, n] of items) {
    const b = document.createElement("button");
    b.className = "chip" + (isOn(v) ? " on" : "");
    b.innerHTML = `${esc(text)}${n != null ? `<b>${n}</b>` : ""}`;
    b.onclick = () => { onToggle(v); render(); };
    g.appendChild(b);
  }
  return g;
}

function renderFilters() {
  const f = $("#filters");
  f.innerHTML = "";
  const phaseChips = chips("Round time", PH.map((p, i) => [i, p]), (v) => S.phases.has(v),
    (v) => (S.phases.has(v) && S.phases.size > 1 ? S.phases.delete(v) : S.phases.add(v)));
  if (S.mode === "utility") {
    const ar = S.team.agentRounds?.[S.map]?.[S.side] || {};
    f.appendChild(chips("Agent", Object.entries(ar).sort((a, b) => b[1] - a[1]).map(([a, n]) => [a, cap(a), `${n} rds`]),
      (v) => v === S.agent, (v) => { S.agent = v; S.abilities.clear(); S.zone = null;
        const c = S.team.casts?.[S.map]?.[S.side]?.[v] || {}; const first = Object.keys(c)[0]; if (first) S.abilities.add(first); }));
    const casts = S.team.casts?.[S.map]?.[S.side]?.[S.agent] || {};
    f.appendChild(chips("Ability", Object.entries(casts).map(([ab, cs]) => [ab, ab.replace(/-/g, " "), cs.reduce((a, c) => a + c[3], 0)])
      .sort((a, b) => b[2] - a[2]), (v) => S.abilities.has(v), (v) => (S.abilities.has(v) ? S.abilities.delete(v) : S.abilities.add(v))));
  } else {
    const ws = S.team.op?.[S.map]?.[S.side] || {};
    f.appendChild(chips("Weapon", ["operator", "outlaw", "marshal", "odin"].map((w) => [w, cap(w), `${ws[w]?.opRounds || 0} rds`]),
      (v) => v === S.weapon, (v) => { S.weapon = v; S.player = null; S.zone = null; }));
    const op = opData();
    const hs = (op.holders || []).slice().sort((a, b) => b.rounds - a.rounds);
    f.appendChild(chips("Player", [[null, "All holders"], ...hs.map((h) => [h.pid, `${h.player} (${h.agent})`, `${h.rounds} rds`])],
      (v) => v === S.player, (v) => (S.player = v)));
  }
  f.appendChild(phaseChips);
}

// ---------- data selection ----------
function heatCells() {
  const grid = S.team.grid, m = new Map();
  const add = (ix, iy, n, ax = 0, ay = 0) => {
    const k = ix * grid + iy, c = m.get(k) || { ix, iy, n: 0, ax: 0, ay: 0 };
    c.n += n; c.ax += ax; c.ay += ay; m.set(k, c);
  };
  if (S.mode === "utility") {
    const casts = S.team.casts?.[S.map]?.[S.side]?.[S.agent] || {};
    for (const ab of S.abilities) for (const [ix, iy, ph, n, ax, ay] of casts[ab] || []) if (S.phases.has(ph)) add(ix, iy, n, ax, ay);
  } else {
    for (const [pid, ix, iy, ph, n] of opData().cells || [])
      if (S.phases.has(ph) && (!S.player || S.player === pid)) add(ix, iy, n);
  }
  return [...m.values()];
}

// ---------- drawing ----------
async function draw() {
  const W = cv.width, sil = await silhouette(S.map);
  ctx.clearRect(0, 0, W, W);
  if (sil) {
    const cs = W / sil.n, max = Math.log(1 + Math.max(...sil.cells.map((c) => c[2])));
    for (const [ix, iy, n] of sil.cells) {
      ctx.fillStyle = `rgba(150,170,195,${0.1 + 0.35 * Math.log(1 + n) / max})`;
      ctx.fillRect(ix * cs, (sil.n - 1 - iy) * cs, cs + 0.5, cs + 0.5);
    }
  }
  const z = S.index.zone, zs = W / z;
  ctx.strokeStyle = "rgba(255,255,255,.06)"; ctx.lineWidth = 1;
  ctx.fillStyle = "rgba(255,255,255,.25)"; ctx.font = "11px system-ui";
  for (let i = 0; i <= z; i++) {
    ctx.beginPath(); ctx.moveTo(i * zs, 0); ctx.lineTo(i * zs, W); ctx.moveTo(0, i * zs); ctx.lineTo(W, i * zs); ctx.stroke();
    if (i < z) { ctx.fillText(COLS[i], i * zs + 4, 12); ctx.fillText(String(i + 1), 3, i * zs + 24); }
  }
  const cells = heatCells(), g = S.team.grid, cs = W / g;
  const max = Math.max(1, ...cells.map((c) => c.n));
  const off = new OffscreenCanvas(W, W), o = off.getContext("2d");
  for (const c of cells) {
    const t = c.n / max;
    o.fillStyle = ramp(t);
    o.beginPath(); o.arc((c.ix + 0.5) * cs, (g - 1 - c.iy + 0.5) * cs, cs * (0.7 + t), 0, 7); o.fill();
  }
  ctx.save(); ctx.filter = "blur(5px)"; ctx.globalAlpha = 0.95; ctx.drawImage(off, 0, 0); ctx.restore();
  // aim arrows on the busiest utility spots
  if (S.mode === "utility") {
    ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.5;
    for (const c of cells.sort((a, b) => b.n - a.n).slice(0, 10)) {
      const len = Math.hypot(c.ax, c.ay); if (!len) continue;
      const x = (c.ix + 0.5) * cs, y = (g - 1 - c.iy + 0.5) * cs, dx = (c.ax / len) * 22, dy = (-c.ay / len) * 22;
      ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + dx, y + dy); ctx.stroke();
      ctx.beginPath(); ctx.arc(x + dx, y + dy, 2.5, 0, 7); ctx.fillStyle = "#fff"; ctx.fill();
    }
  }
  if (S.zone) {
    ctx.strokeStyle = "#3ddc97"; ctx.lineWidth = 3;
    ctx.strokeRect(S.zone[0] * zs, (z - 1 - S.zone[1]) * zs, zs, zs);
  }
}
function ramp(t) {
  const stops = [[25, 167, 255, 0.25], [25, 167, 255, 0.85], [255, 210, 60, 0.95], [255, 90, 60, 1]];
  const p = Math.min(t, 0.999) * (stops.length - 1), i = Math.floor(p), f = p - i, a = stops[i], b = stops[i + 1];
  return `rgba(${a.map((v, k) => (k < 3 ? Math.round(v + (b[k] - v) * f) : (v + (b[k] - v) * f).toFixed(2))).join(",")})`;
}

// ---------- side panel ----------
function renderEvidence() {
  const rounds = S.team.rounds?.[S.map]?.[S.side] || 0;
  let h = `<div class="muted">${esc(S.team.name)} · ${cap(S.map)} · ${S.side}</div>`;
  if (S.mode === "utility") {
    const ar = S.team.agentRounds?.[S.map]?.[S.side]?.[S.agent] || 0;
    const n = heatCells().reduce((a, c) => a + c.n, 0);
    h += `<div class="big">${n} casts</div><div>${S.agent ? cap(S.agent) : "—"} played ${ar} of ${rounds} rounds · ${S.team.series} series scanned</div>`;
    if (ar && ar < 15) h += `<div class="warn">Small sample (&lt;15 rounds): treat as a hint, not a tendency.</div>`;
  } else {
    const op = opData(), k = op.opRounds || 0, W = cap(S.weapon);
    h += `<div class="big">${pct(k, rounds)}% ${W} rounds</div><div>${k} of ${rounds} rounds had an ${W} after the buy phase</div>`;
    const hs = (op.holders || []).slice().sort((a, b) => b.rounds - a.rounds);
    if (hs.length) h += `<table><tr><th>Holder</th><th>Agent</th><th class="n">Rounds</th><th class="n">Share</th></tr>${hs.map((x) =>
      `<tr><td>${esc(x.player)}</td><td>${cap(x.agent)}</td><td class="n">${x.rounds}</td><td class="n">${pct(x.rounds, k)}%</td></tr>`).join("")}</table>`;
    const cells = heatCells(), byPh = [0, 0, 0, 0];
    for (const [pid, , , ph, n] of op.cells || []) if (!S.player || S.player === pid) byPh[ph] += n;
    const tot = byPh.reduce((a, b) => a + b, 0);
    if (tot) h += `<div style="margin-top:8px" class="muted">First ${W} fight each round: timing (${tot} fights)</div>` + PH.map((p, i) =>
      `<div style="display:flex;gap:8px;align-items:center"><span style="width:56px">${p}</span><div class="bar" style="flex:1"><i style="width:${pct(byPh[i], tot)}%"></i></div><span>${pct(byPh[i], tot)}%</span></div>`).join("");
    if (!cells.length) h += `<div class="warn">No ${W} fights recorded here.</div>`;
  }
  $("#evidence").innerHTML = h;
}

function renderDetail() {
  if (!S.zone) { $("#detail").innerHTML = ""; return; }
  const [zx, zy] = S.zone;
  let h = `<b>Zone ${zoneName(zx, zy)}</b>`;
  if (S.mode === "utility") {
    const ar = S.team.agentRounds?.[S.map]?.[S.side]?.[S.agent] || 0;
    const zones = S.team.zones?.[S.map]?.[S.side]?.[S.agent] || {};
    for (const ab of S.abilities) {
      const hit = (zones[ab] || []).find((z) => z[0] === zx && z[1] === zy), k = hit ? hit[2] : 0;
      h += `<div>${esc(ab.replace(/-/g, " "))}: <b>${pct(k, ar)}%</b> of ${cap(S.agent)} rounds <span class="muted">(${k}/${ar})</span></div>`;
    }
    h += `<div class="muted" style="font-size:12px">All round times; filters above change the heatmap only.</div>`;
  } else {
    const g = S.team.grid, r = g / S.index.zone, byPh = [0, 0, 0, 0];
    for (const [pid, ix, iy, ph, n] of opData().cells || [])
      if ((!S.player || S.player === pid) && Math.floor(ix / r) === zx && Math.floor(iy / r) === zy) byPh[ph] += n;
    const t = byPh.reduce((a, b) => a + b, 0);
    h += `<div>${t} first ${cap(S.weapon)} fights here ·${PH.map((p, i) => `${p} ${pct(byPh[i], t)}%`).join(" · ")}</div>`;
  }
  $("#detail").innerHTML = h;
}

function renderInsights() {
  const ins = S.team.insights || [];
  $("#inscount").textContent = `${ins.length} · min 15 rounds each`;
  $("#insights").innerHTML = ins.length ? ins.map((x, i) =>
    `<div class="ins ${x.kind === "operator" ? "op" : ""}" data-i="${i}"><span class="pct">${x.pct}%</span>
      <div class="tag">${x.kind === "operator" ? x.weapon : "utility"} · ${cap(x.map)} · ${x.side}</div>${esc(x.text)}</div>`).join("")
    : `<div class="muted">Not enough rounds for a confident pattern yet.</div>`;
  document.querySelectorAll(".ins").forEach((el) => (el.onclick = () => openInsight(ins[+el.dataset.i])));
}

function openInsight(x) {
  S.map = x.map; $("#map").value = x.map;
  S.side = x.side; setSeg("#side", x.side);
  S.mode = x.kind === "operator" ? "operator" : "utility"; setSeg("#mode", S.mode);
  S.phases = new Set([0, 1, 2, 3]); S.player = null;
  if (x.kind === "utility") { S.agent = x.agent; S.abilities = new Set([x.ability]); S.zone = x.zone; }
  else { S.zone = null; S.weapon = x.weapon; S.player = x.pid; }
  render();
  cv.scrollIntoView({ behavior: "smooth", block: "center" });
}

// ---------- interaction ----------
function zoneAt(ev) {
  const r = cv.getBoundingClientRect(), z = S.index.zone;
  const zx = Math.floor(((ev.clientX - r.left) / r.width) * z), zy = z - 1 - Math.floor(((ev.clientY - r.top) / r.height) * z);
  return [Math.min(Math.max(zx, 0), z - 1), Math.min(Math.max(zy, 0), z - 1)];
}
function onClick(ev) { S.zone = zoneAt(ev); draw(); renderDetail(); }
function onMove(ev) {
  const [zx, zy] = zoneAt(ev), tip = $("#tip"), r = cv.getBoundingClientRect();
  tip.hidden = false; tip.textContent = `Zone ${zoneName(zx, zy)}`;
  tip.style.left = `${ev.clientX - r.left + 12}px`; tip.style.top = `${ev.clientY - r.top + 12}px`;
}

function render() { renderFilters(); renderEvidence(); renderDetail(); renderInsights(); draw(); }

init().catch((e) => { document.body.insertAdjacentHTML("afterbegin", `<p class="warn" style="padding:16px">Could not load data: ${esc(e.message)}. Run the engine first (see README).</p>`); });
