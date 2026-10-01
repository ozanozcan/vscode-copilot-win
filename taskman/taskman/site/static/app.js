/* taskman site — Roadmap page. Built to docs-hub mockup v2 from GET /api/roadmap (lane A's JSON contract).
   Fetched once per load, never polled (plan D8). Every API string is untrusted: the DOM is built with
   textContent / setAttribute only, never innerHTML. Loaded as a module (strict, deferred). */

const WORD = {done: "done", in_progress: "in progress", blocked: "blocked", todo: "to do", backlog: "backlog", disabled: "disabled"};
const SVG = "http://www.w3.org/2000/svg";
const $ = id => document.getElementById(id);

/* h("div", {class: "box", "data-task": 3}, child, "text", …) — attributes via setAttribute, strings as text nodes */
function h(tag, attrs, ...kids){
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) if (v != null && v !== false) el.setAttribute(k, v);
  for (const k of kids.flat()) if (k != null && k !== false) el.append(k);   // append() treats strings as text
  return el;
}

let D, map, laneOf = {}, where = {};
const featureTitle = id => D.features.find(f => f.id === id)?.title || "";
const tasksOf = f => [...f.prep, ...f.waves.flatMap(w => w.lanes)];

/* "after #N · <milestone>" for every wait the wave order doesn't already say */
function waitLines(t, fid){
  const me = laneOf[t.id];
  return (t.blocked_by || []).filter(b => !(me && laneOf[b] && laneOf[b].f === me.f && laneOf[b].w < me.w)).map(b => {
    const other = (where[b] || []).filter(x => x !== fid);
    return h("span", {class: "wait"}, `after #${b}` + (other.length ? ` · ${featureTitle(other[0])}` : ""));
  });
}

/* status only ever reaches a class name after this whitelist; anything unknown draws as "to do" */
const statusOf = s => Object.hasOwn(WORD, s) ? s : "todo";
const boxClass = t => `box ${t.status}${t.priority === "keystone" ? " key" : ""}`;
// the native title carries the full, unclamped task title (the box clamps it to three lines)
const boxAttrs = (t, fid, extra) => ({class: boxClass(t) + (extra || ""), id: `t${t.id}-f${fid}`, "data-task": t.id,
  title: `#${t.id} · ${WORD[t.status]} · ${t.title}`});
const srStatus = t => h("span", {class: "sr"}, ` (${WORD[t.status]})`);   // status is a fill for the eye, a word for AT

const box = (t, fid) => h("div", boxAttrs(t, fid), h("span", {class: "id"}, `#${t.id}`), srStatus(t),
  h("div", {class: "tt"}, t.title), waitLines(t, fid));

function lane(l, fid){
  const name = String(l.brief || "").replace(/\.md$/, "").replace(/^[0-9]+-/, "").replace(/-/g, " ");
  // title="" keeps the lane's native tooltip off the chip; the chip's own tip (wireTips) shows the decision
  const chips = l.decisions.map(d => h("button", {type: "button", "data-d": d.id, title: "",
    "aria-label": d.title ? `d#${d.id} — ${d.title}` : `d#${d.id} — not on this board`}, `d#${d.id}`));
  return h("div", boxAttrs(l, fid, " lane"),
    h("span", {class: "disc", "aria-hidden": "true"}, l.letter),
    h("div", {}, h("div", {class: "nm"}, name + " ", h("span", {class: "id"}, `#${l.id}`), srStatus(l)),
      h("div", {class: "tt"}, String(l.title || "").replace(/^[0-9]+-[a-z0-9-]+:\s*/, "")), waitLines(l, fid)),
    chips.length ? h("div", {class: "dec"}, chips) : null);
}

function row(f){
  const all = tasksOf(f);
  if (!all.length) return h("div", {class: "row ghost-row"},
    h("div", {class: "topic ghost", id: `f${f.id}`, "data-stem": f.stem || ""}, h("h3", {}, f.title),
      f.stem ? h("p", {class: "meta"}, f.stem) : null));   // the section subtitle already says "no tasks yet"
  const prep = f.prep.length ? h("div", {class: "panel prep", id: `prep-${f.id}`},
    h("h4", {}, "Before it can start ", h("small", {}, `· ${f.prep.length}`)),
    h("div", {class: "boxes"}, f.prep.map(t => box(t, f.id)))) : null;
  const waves = f.waves.map(w => {
    const note = String(w.note || "").replace(/\s*(?:and\s+)?after `[^`]+` ships/, "").replace(/^,\s*/, "");
    const after = w.after_plan ? h("span", {class: "after", "data-after": w.after_plan}, `waits for ${w.after_plan}`) : null;
    return h("div", {class: "wave", id: `w${f.id}-${w.n}`},
      h("div", {class: "wave-h"}, h("b", {}, `Wave ${w.n}`), h("span", {}, after, after && note ? " · " : "", note)),
      h("div", {class: "lanes-row"}, w.lanes.map(l => lane(l, f.id))));
  });
  const lanes = f.waves.length ? h("div", {class: "panel lanes", id: `lanes-${f.id}`},
    h("h4", {}, "Build lanes ", h("small", {}, `· ${f.waves.length} wave${f.waves.length === 1 ? "" : "s"}`)), waves) : null;
  return h("div", {class: "row"}, prep,
    h("div", {class: "topic", id: `f${f.id}`, "data-stem": f.stem || ""}, h("h3", {}, f.title),
      h("p", {class: "meta"}, `${f.done} of ${f.total} done` + (f.stem ? ` · ${f.stem}` : "")),
      h("div", {class: "strip", "aria-hidden": "true"}, all.map(t => h("i", {class: t.status})))),
    lanes);
}

const section = (name, sub) => h("div", {class: "section"}, h("h2", {}, name, sub ? h("small", {}, sub) : null));

function render(){
  document.title = `Roadmap · ${D.project?.name || "taskman"}`;
  $("proj").replaceChildren(D.project?.name || "taskman", " ", h("span", {}, "· taskman"));
  D.features.forEach(f => {
    tasksOf(f).forEach(t => (where[t.id] ||= []).push(f.id));
    f.waves.forEach(w => w.lanes.forEach(l => laneOf[l.id] = {f: f.id, w: Number(w.n)}));
  });
  $("status").remove();
  if (!D.features.length){
    map.classList.add("bare"); document.body.classList.add("is-empty");
    map.append(h("p", {class: "note empty"}, "No milestones yet. ", h("code", {}, "/mow plan"), " creates them."));
  } else {
    // Part 1: product milestones with work on the board; Part 2: product milestones with no tasks yet; Harness: platform.
    const prod = D.features.filter(f => f.track !== "platform"), plat = D.features.filter(f => f.track === "platform");
    const now = prod.filter(f => tasksOf(f).length), later = prod.filter(f => !tasksOf(f).length);
    if (now.length) map.append(section("Part 1 · On the board"), ...now.map(row));
    if (later.length) map.append(section("Part 2 · Later", "milestones with no tasks yet"), ...later.map(row));
    if (plat.length) map.append(section("Harness", "tooling work this project is testing"), ...plat.map(row));
  }
  // native disclosure: open on desktop, closed on phones where 48 boxes would bury the footer
  if (D.loose.length) $("loose").append(h("details", {class: "panel", open: matchMedia("(min-width: 901px)").matches},
    h("summary", {}, h("h4", {}, "Not on the roadmap ", h("small", {}, `· ${D.loose.length} task${D.loose.length === 1 ? "" : "s"} with no plan`))),
    h("div", {class: "boxes"}, D.loose.map(t => box(t, 0)))));
  const ids = new Set([...D.features.flatMap(tasksOf), ...D.loose].map(t => t.id));
  $("foot").textContent = `Built from the board and docs/plans/*/dispatch/INDEX.md · ${D.features.length} milestones · ` +
    `${ids.size} tasks · reload to refresh`;
  document.fonts.ready.then(draw);
  let raf = 0;
  addEventListener("resize", () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(draw); });
}

/* ---- edges: dotted "belongs to" connectors + solid "waits for" arrows (mockup v2 rules) ---- */
function draw(){
  const svg = $("edges"), M = map.getBoundingClientRect(), W = M.width;
  if (!W || getComputedStyle(svg).display === "none") return;             // phone layout: connectors hidden
  const r = el => { const b = el.getBoundingClientRect();
    return {l: b.left - M.left, r: b.right - M.left, t: b.top - M.top, cy: (b.top + b.bottom) / 2 - M.top, cx: (b.left + b.right) / 2 - M.left}; };
  const kids = [];
  const path = (cls, d, arrow) => {
    const p = document.createElementNS(SVG, "path"); p.setAttribute("class", cls); p.setAttribute("d", d);
    if (arrow) p.setAttribute("marker-end", "url(#ah)"); kids.push(p); };
  const defs = document.createElementNS(SVG, "defs"), mk = document.createElementNS(SVG, "marker"), head = document.createElementNS(SVG, "path");
  Object.entries({id: "ah", viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse"})
    .forEach(([k, v]) => mk.setAttribute(k, v));
  head.setAttribute("d", "M0 0L10 5L0 10z"); head.setAttribute("class", "head"); mk.append(head); defs.append(mk); kids.push(defs);

  D.features.forEach(f => {
    const t = $("f" + f.id); if (!t) return; const T = r(t), y = T.t + 26;
    const pr = $("prep-" + f.id), la = $("lanes-" + f.id);
    if (pr){ const P = r(pr); path("conn", `M${T.l} ${y} C${T.l - 20} ${y} ${P.r + 20} ${P.t + 26} ${P.r} ${P.t + 26}`); }
    if (la){ const L = r(la); path("conn", `M${T.r} ${y} C${T.r + 20} ${y} ${L.l - 20} ${L.t + 26} ${L.l} ${L.t + 26}`); }
  });
  // plan-level wait: a wave that runs only after another plan ships -> that plan's milestone (only when lane A emitted the edge)
  (D.edges || []).filter(e => e.kind === "after_plan").forEach(e => {
    // Routed through open space only: out of the lanes PANEL's right edge into the page gutter, down the gutter to
    // the row gap above the target milestone, left along that gap, then down onto the milestone's top edge.
    const wave = map.querySelector(`[data-task="${Number(e.from)}"]`)?.closest(".wave"), tgt = $("f" + Number(e.to));
    const panel = wave?.closest(".panel"), tRow = tgt?.closest(".row");
    if (!wave || !panel || !tgt || !tRow) return;
    const A = r(wave), P = r(panel), T = r(tgt), yRow = r(tRow).t;
    const room = document.documentElement.clientWidth - M.right - 4;          // gutter right of the map
    const gx = P.r + Math.max(10, Math.min(28, room)), y0 = A.t + 10, yg = yRow - 28, k = 10, dn = yg > y0 ? 1 : -1;
    path("dep", `M${P.r} ${y0} H${gx - k} Q${gx} ${y0} ${gx} ${y0 + k * dn} V${yg - k * dn} Q${gx} ${yg} ${gx - k} ${yg}` +
      ` H${T.cx + k} Q${T.cx} ${yg} ${T.cx} ${yg + k} V${T.t - 2}`, true);
    const label = document.createElementNS(SVG, "text");                     // sits in the row gap, above the line
    label.setAttribute("x", gx - 14); label.setAttribute("y", yg - 7); label.setAttribute("text-anchor", "end");
    label.textContent = "waits for it to ship"; kids.push(label);
  });
  // task-level blocked_by, only between neighbouring milestones and never one the wave arrows already imply
  const rows = [...map.querySelectorAll(".row")];
  D.features.forEach(f => tasksOf(f).forEach(t => (t.blocked_by || []).forEach(b => {
    const src = $(`t${t.id}-f${f.id}`);
    const dst = map.querySelector(`[data-task="${Number(b)}"]:not([id$="-f${f.id}"])`) || $(`t${b}-f${f.id}`);
    if (!src || !dst || (src.closest(".wave") && src.closest(".panel") === dst.closest(".panel"))) return;
    const waitsFor = src.closest(".wave")?.querySelector("[data-after]")?.dataset.after;
    if (waitsFor && waitsFor === dst.closest(".row")?.querySelector(".topic")?.dataset.stem) return;
    const gap = Math.abs(rows.indexOf(src.closest(".row")) - rows.indexOf(dst.closest(".row")));
    const me = laneOf[t.id];
    if (gap > 1 || (me && laneOf[b] && laneOf[b].f === me.f)) return;   // longer jumps stay as "after #N" text
    if (me && me.f === f.id && dst.closest(`#prep-${f.id}`)) return;    // "Before it can start" already says a lane waits on its prep
    const S = r(src), T2 = r(dst);
    path("dep", `M${S.r} ${S.cy} C${S.r + 60} ${S.cy + 40} ${T2.l - 60} ${T2.cy + 40} ${T2.l} ${T2.cy}`, true);
  })));
  svg.setAttribute("viewBox", `0 0 ${W} ${M.height}`); svg.setAttribute("width", W); svg.setAttribute("height", M.height);
  svg.replaceChildren(...kids);
}

/* ---- decision chips: the decision's title on hover, focus and tap; #N alone when it is not on the board (d#45).
   Touch has no hover and iOS doesn't focus a tapped button, so a click toggles the tip; a second tap on the same
   chip, a tap anywhere else, or Escape closes it. ---- */
function wireTips(){
  const tip = $("tip");
  let anchor = null, pinned = false, raf = 0;
  const place = () => {
    if (!anchor) return;
    const R = anchor.getBoundingClientRect(), w = tip.offsetWidth, ht = tip.offsetHeight;
    tip.style.left = Math.max(8, Math.min(R.left, innerWidth - w - 8)) + "px";
    tip.style.top = (R.bottom + 8 + ht > innerHeight ? R.top - ht - 8 : R.bottom + 8) + "px";
  };
  const hide = () => { tip.classList.remove("on"); anchor = null; pinned = false; };
  const show = b => {
    const d = decisionById(b.closest("[data-task]"), Number(b.dataset.d));
    tip.textContent = d && d.title ? `d#${d.id} · ${d.title}` : `#${Number(b.dataset.d)}`;
    anchor = b; tip.classList.add("on"); place();
  };
  const chipOf = e => e.target.closest?.("[data-d]");
  document.addEventListener("mouseover", e => { const b = chipOf(e); if (b && !pinned) show(b); });
  document.addEventListener("mouseout", e => { if (chipOf(e) && !pinned) hide(); });
  document.addEventListener("focusin", e => { const b = chipOf(e); if (b) show(b); });
  document.addEventListener("focusout", e => { if (chipOf(e) && !pinned) hide(); });
  document.addEventListener("click", e => {
    const b = chipOf(e);
    if (!b){ if (anchor) hide(); return; }                       // a tap outside closes it
    if (pinned && anchor === b) return hide();                    // a second tap on the same chip closes it
    show(b); pinned = true;
  });
  document.addEventListener("keydown", e => e.key === "Escape" && hide());
  addEventListener("scroll", () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(place); }, {passive: true});
  addEventListener("resize", hide);
}
function decisionById(laneEl, id){
  const tid = Number(laneEl?.dataset.task);
  for (const f of D.features) for (const w of f.waves) for (const l of w.lanes)
    if (l.id === tid) return (l.decisions || []).find(d => d.id === id);
  return null;
}

async function main(){
  map = $("map");
  try {
    const res = await fetch("/api/roadmap", {headers: {Accept: "application/json"}});
    if (!res.ok) throw new Error(`/api/roadmap answered ${res.status}`);
    D = normalise(await res.json());
    render();
    wireTips();
  } catch (err){
    console.error(err);
    map.classList.add("bare");
    const line = $("status") || map.appendChild(h("p", {class: "note", id: "status"}));   // render() may have removed it
    line.setAttribute("role", "alert");
    line.textContent = `Couldn't load the roadmap (${err.message}). Check that taskman site is still running, then reload.`;
  }
}

/* Shape drift must not hang the page on "Loading…": fill every list the renderer walks, coerce ids to numbers
   (they are interpolated into selectors) and whitelist statuses before they become class names. */
function normalise(doc){
  const d = doc && typeof doc === "object" ? doc : {};
  const task = t => Object.assign(t, {id: Number(t.id), status: statusOf(t.status), title: String(t.title ?? ""),
    blocked_by: (t.blocked_by || []).map(Number)});
  d.project ||= {}; d.edges ||= []; d.loose = (d.loose || []).map(task);
  d.features = (d.features || []).map(f => {
    f.id = Number(f.id); f.title = String(f.title ?? ""); f.done ??= 0; f.total ??= 0;
    f.prep = (f.prep || []).map(task);
    f.waves = (f.waves || []).map(w => Object.assign(w, {lanes: (w.lanes || []).map(l => Object.assign(task(l), {decisions: l.decisions || []}))}));
    return f;
  });
  return d;
}
main();
