/* taskman site — Board page. Built to kanban mockup v2 (K5) from GET /api/board and GET /api/live (lane A's
   `## Signatures`). Polled every 3 s while the tab is visible (K10); a card opens nothing (K8, d#62).
   Every API value is untrusted and may not even be a string: it is coerced with str(), whitelisted before it
   becomes a class or a column key, and reaches the DOM only as a text node or through setAttribute — never
   innerHTML, never an href. Loaded as a module (strict, deferred). */

const COLS = [["backlog", "Backlog"], ["todo", "To do"], ["in_progress", "In progress"], ["review", "Review"],
  ["blocked", "Blocked"], ["done", "Done"]];
const WORD = {backlog: "backlog", todo: "to do", in_progress: "in progress", review: "review", blocked: "blocked", done: "done"};
const BOARD_STATUS = new Set(["backlog", "todo", "in_progress", "blocked", "done"]);
const RANK = {keystone: 3, high: 3, med: 2, low: 1};
const DONE_CAP = 20, POLL_MS = 3000;
const SVG = "http://www.w3.org/2000/svg";
const $ = id => document.getElementById(id);

/* h("div", {class: "card", "data-id": 3}, child, "text", …) — attributes via setAttribute, strings as text nodes */
function h(tag, attrs, ...kids){
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) if (v != null && v !== false) el.setAttribute(k, v);
  for (const k of kids.flat(Infinity)) if (k != null && k !== false) el.append(k);   // append() treats strings as text
  return el;
}
function svg(tag, attrs, ...kids){
  const el = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  el.append(...kids);
  return el;
}
const robot = () => svg("svg", {viewBox: "0 0 16 16", "aria-hidden": "true"},
  svg("rect", {x: 3, y: 5, width: 10, height: 8, rx: 2}), svg("path", {d: "M8 5V2.5"}), svg("circle", {cx: 8, cy: 2, r: .8}),
  svg("circle", {cx: 6, cy: 9, r: .9}), svg("circle", {cx: 10, cy: 9, r: .9}));

/* a string or number becomes text; anything else (a dict, a list, null) is absent */
const str = v => typeof v === "string" ? v : typeof v === "number" && Number.isFinite(v) ? String(v) : "";
const list = v => Array.isArray(v) ? v : [];
const obj = v => v && typeof v === "object" && !Array.isArray(v) ? v : null;

/* ---- the two documents, normalised once per fetch ---- */
function normBoard(doc){
  const d = obj(doc) || {};
  const plans = new Map();                                  // stem -> title (Map: a stem named "__proto__" is just a key)
  for (const p of list(d.plans)) if (obj(p) && str(p.stem)) plans.set(str(p.stem), str(p.title) || str(p.stem));
  const cards = list(d.cards).filter(obj).map(c => {
    const lane = obj(c.lane), origin = obj(c.origin);
    return {
      id: Number(c.id), title: str(c.title), status: BOARD_STATUS.has(c.status) ? c.status : "todo",
      priority: str(c.priority) || "med", kind: str(c.kind), labels: list(c.labels).map(str).filter(Boolean),
      plans: list(c.plans).map(str).filter(Boolean), lane: lane && str(lane.letter) ? {letter: str(lane.letter)} : null,
      agent: c.agent === true, blocked_by: list(c.blocked_by).map(Number).filter(Number.isFinite),
      done_at: str(c.done_at), finding: "origin" in c,
      origin: origin && {stem: str(origin.stem), wave: str(origin.wave), lane: str(origin.lane), file: str(origin.file)},
    };
  }).filter(c => Number.isFinite(c.id));
  const project = obj(d.project) || {};
  return {name: str(project.name) || str(project.slug) || "taskman", plans, cards, disabled: Number(d.disabled) || 0};
}
function normLive(doc){
  const d = obj(doc) || {};
  const cards = new Map();                                  // "92" -> overlay; the keys are strings (lane A)
  for (const [k, v] of Object.entries(obj(d.cards) || {})) {
    const o = obj(v); if (!o) continue;
    cards.set(k, {column: typeof o.column === "string" && Object.hasOwn(WORD, o.column) ? o.column : null, status: str(o.status), gate: str(o.gate),
      wave: str(o.wave), lane: str(o.lane), stem: str(o.stem), agent: str(o.agent), skill: str(o.skill), tool: str(o.tool),
      findings: list(o.findings).filter(obj).map(f => ({severity: str(f.severity), title: str(f.title), task: str(f.task)}))});
  }
  const runs = list(d.runs).filter(obj).map(r => ({stem: str(r.stem), title: str(r.title),
    stale: Number.isFinite(r.stale_minutes) ? r.stale_minutes : null, unmapped: list(r.unmapped).map(str).filter(Boolean)}));
  return {runs, cards};
}

let B = null, L = {runs: [], cards: new Map()}, lastText = "";
const state = {q: "", f: new Set(), g: "none", w: "all", live: true, allDone: false};

const liveOn = () => state.live && L.runs.length > 0;
const liveOf = c => liveOn() ? L.cards.get(String(c.id)) || null : null;
const colOf = c => liveOf(c)?.column || c.status;
const isAgent = c => c.agent || !!L.cards.get(String(c.id));
const planTitle = s => B.plans.get(s) || s;
const letterOf = c => c.lane?.letter || liveOf(c)?.lane || "";
const laneWord = c => [letterOf(c) && `lane ${letterOf(c)}`, `${c.priority} priority`].filter(Boolean).join(", ");
const filtering = () => state.q.trim() !== "" || state.f.size > 0;   // K13: a search or quick filter uncaps Done

function match(c){
  const q = state.q.trim().toLowerCase();
  if (q && !`#${c.id} ${c.title} ${c.plans.join(" ")} ${c.plans.map(planTitle).join(" ")} ${c.labels.join(" ")}`.toLowerCase().includes(q)) return false;
  if (state.w === "agents" && !isAgent(c)) return false;
  if (state.w === "people" && isAgent(c)) return false;
  if (state.f.has("waiting") && !(colOf(c) === "blocked" || c.blocked_by.length)) return false;
  if (state.f.has("urgent") && !(c.priority === "keystone" || c.priority === "high")) return false;
  return true;
}

/* `## Live overlay rules`: the line under a live card */
function liveLine(o){
  const who = o.agent ? h("b", {}, o.agent) : "no agent yet";
  if (o.status === "running")
    return [who, o.skill ? [" · in ", h("b", {}, o.skill)] : " · working", o.tool ? ` · running ${o.tool}` : ""];
  if (o.column === "blocked") {
    if (o.status === "error") return [who, " · failed"];
    // the wave's review errored; this lane's own todo may never have started, so it did not "fail"
    return [who, o.status === "pending" ? ` · not started · wave ${o.wave} review hit an error` : ` · wave ${o.wave} review hit an error`];
  }
  if (o.column === "review" && o.status === "issues") return [who, " · review found issues"];
  if (o.column === "review") return [who, ` · waiting for wave ${o.wave} review`];
  if (o.column === "done") return [who, " · review passed, ships at close-out"];
  if (o.status === "pending") return [who, ` · queued, wave ${o.wave}`];
  return [who];
}
function liveBox(c){
  const o = liveOf(c); if (!o) return null;
  return h("div", {class: "livebox"},
    h("span", {class: "tag"}, `live · ${o.stem} · lane ${o.lane}`), liveLine(o),
    o.findings.map(f => h("span", {class: "f"}, `${f.severity || "finding"}: ${f.title}`, f.task ? ` · #${f.task}` : "")));
}
function originLine(o){
  if (!o) return null;
  if (o.stem) return h("span", {class: "origin"}, [`from ${o.stem}`, o.wave && `wave ${o.wave}`, o.lane && `lane ${o.lane}`].filter(Boolean).join(" · "));
  return o.file ? h("span", {class: "origin"}, `from ${o.file}`) : null;
}

function card(c){
  const o = liveOf(c), col = colOf(c), agent = isAgent(c), letter = letterOf(c);
  const kind = c.kind ? c.kind[0].toUpperCase() + c.kind.slice(1) : "";
  return h("article", {class: `card ${col}${c.priority === "keystone" ? " key" : ""}${agent ? " agent" : ""}`, tabindex: "0",
      "data-id": c.id, "aria-label": `#${c.id} ${c.title}, ${WORD[col]}${agent ? ", agent task" : ""}, ${laneWord(c)}`},
    c.plans.map(p => h("span", {class: "epic"}, planTitle(p))),
    agent ? h("div", {class: "who"}, robot(), "Agent lane") : null,
    h("p", {class: "t"}, c.title),
    c.labels.length ? h("div", {class: "labels"}, c.labels.map(l => h("span", {}, l))) : null,
    h("div", {class: "foot"},
      letter ? h("span", {class: `disc ring${o?.status === "running" ? " run" : ""}`}, letter) : null,
      h("span", {class: "id"}, `#${c.id}`), kind ? h("span", {class: "kind"}, kind) : null,
      h("span", {class: `prio p${Object.hasOwn(RANK, c.priority) ? RANK[c.priority] : 2}`}, h("i"), h("i"), h("i"))),
    c.blocked_by.length ? h("span", {class: "wait"}, `after ${c.blocked_by.map(b => "#" + b).join(", ")}`) : null,
    c.finding ? originLine(c.origin) : null,
    liveBox(c));
}

const byDoneAt = (a, z) => z.done_at.localeCompare(a.done_at) || z.id - a.id;   // newest first; no done_at sorts last
function columns(cards){
  const cols = COLS.filter(([s]) => s !== "review" || liveOn());
  return h("div", {class: "grid", style: `--ncol:${cols.length}`}, cols.map(([s, name]) => {
    let cs = cards.filter(c => colOf(c) === s), more = null;
    if (s === "done") {
      cs = cs.sort(byDoneAt);
      if (!filtering() && !state.allDone && cs.length > DONE_CAP)
        more = h("button", {type: "button", class: "more"}, `Show all ${cs.length}`);
    }
    const shown = more ? cs.slice(0, DONE_CAP) : cs;
    return h("div", {class: "colwrap"},
      h("div", {class: `colh s-${s}`}, h("b", {role: "heading", "aria-level": "2"}, name), h("span", {}, String(cs.length))),
      h("div", {class: "col", "data-col": s}, shown.length ? shown.map(card) : h("p", {class: "empty"}, "Nothing here"), more));
  }));
}

function banner(){
  const el = $("live");
  el.hidden = !liveOn();
  if (el.hidden) return el.replaceChildren();
  const n = L.runs.length;
  el.replaceChildren(h("b", {}, `${n} live run${n === 1 ? "" : "s"}`), ...L.runs.map(r => {
    const running = [...L.cards.values()].find(o => o.stem === r.stem && o.status === "running");
    return h("div", {class: "run"},
      h("span", {class: `disc ring${running ? " run" : ""}`, "aria-hidden": "true"}, running?.lane || "·"),
      h("strong", {}, r.title || r.stem || "untitled run"), r.title && r.stem ? `· ${r.stem}` : "",
      r.stale != null ? h("span", {class: "behind"}, `· board ${r.stale}m behind`) : "",
      r.unmapped.length ? `· not on a card: ${r.unmapped.join(", ")}` : "");
  }), h("small", {}, "Read from docs/plans/*/dispatch/tracker.json. Cards move as the trackers change."));
}

function render(){
  document.title = `Board · ${B.name}`;
  $("proj").replaceChildren(B.name, " ", h("span", {}, "· taskman"));
  banner();
  const cards = B.cards.filter(match), agents = B.cards.filter(isAgent).length;
  $("sub").textContent = `${cards.length} of ${B.cards.length} tasks · ${agents} agent, ${B.cards.length - agents} people`;
  $("hidden").textContent = B.disabled ? `${B.disabled} disabled task${B.disabled === 1 ? "" : "s"} hidden, as taskman board does.` : "";
  const board = $("board"), focused = document.activeElement?.closest?.("#board .card")?.dataset.id;
  board.classList.toggle("grouped", state.g === "plan");
  if (state.g === "none") board.replaceChildren(columns(cards));
  else {
    // plans in board order, then any stem the plans list lacks, then "No plan" last (K5)
    const stems = [...new Set([...B.plans.keys(), ...cards.flatMap(c => c.plans)])].filter(s => cards.some(c => c.plans.includes(s)));
    const groups = stems.map(s => [planTitle(s), s, cards.filter(c => c.plans.includes(s))]);
    const loose = cards.filter(c => !c.plans.length);
    if (loose.length) groups.push(["No plan", "", loose]);
    board.replaceChildren(...groups.map(([title, stem, cs]) => {
      const g = columns(cs);
      g.prepend(h("div", {class: "lane-h"}, h("b", {}, title), h("span", {}, `${cs.length} task${cs.length === 1 ? "" : "s"}${stem ? " · " + stem : ""}`)));
      return g;
    }));
    if (!groups.length) board.replaceChildren(columns([]));
  }
  if (focused) cardEl(focused)?.focus({preventScroll: true});   // a refresh must not steal keyboard focus
  tips.refresh(); stickHeads();
}
const cardEl = id => $("board").querySelector(`.card[data-id="${CSS.escape(String(id))}"]`);

/* ---- column headers stay flush under the sticky bar. .colh is position:sticky at top:var(--bar-h); when #board
   scrolls sideways (below 1200px, see board.css) sticky is trapped inside it, so the header is carried down by a
   transform instead. ---- */
const bar = document.querySelector(".bar");
function stickHeads(){
  const top = bar.getBoundingClientRect().bottom, on = getComputedStyle($("board")).overflowX !== "visible";
  for (const hd of document.querySelectorAll("#board .colh")) {
    const w = hd.parentElement.getBoundingClientRect();
    const t = on ? Math.max(0, Math.min(top - w.top, w.height - hd.offsetHeight)) : 0;
    hd.style.transform = t ? `translateY(${t}px)` : "";
  }
}
let stickRaf = 0;
new ResizeObserver(() => { document.documentElement.style.setProperty("--bar-h", bar.getBoundingClientRect().height + "px"); stickHeads(); }).observe(bar);
addEventListener("scroll", () => { cancelAnimationFrame(stickRaf); stickRaf = requestAnimationFrame(stickHeads); }, {passive: true});

/* ---- tooltip: full title, #id, status, plans and blocked-by on hover, focus and tap (K8, d#60, d#62).
   Touch has no hover, so a click pins it; a second tap on the same card, a tap elsewhere or Escape closes it. ---- */
const tips = (() => {
  const tip = $("tip");
  let id = null, pinned = false, raf = 0;
  const anchor = () => id == null ? null : cardEl(id);
  const place = () => {
    const a = anchor(); if (!a) return;
    const R = a.getBoundingClientRect(), w = tip.offsetWidth, ht = tip.offsetHeight;
    tip.style.left = Math.max(8, Math.min(R.left, innerWidth - w - 8)) + "px";
    tip.style.top = (R.bottom + 8 + ht > innerHeight ? Math.max(8, R.top - ht - 8) : R.bottom + 8) + "px";
  };
  const hide = () => { anchor()?.removeAttribute("aria-describedby"); tip.classList.remove("on"); id = null; pinned = false; };
  const fill = c => {
    const o = liveOf(c);
    tip.replaceChildren(...[h("span", {}, `#${c.id} · ${WORD[colOf(c)]}${o ? ` (board: ${WORD[c.status]})` : ""}`),
      h("span", {class: "tt"}, c.title), h("span", {}, laneWord(c).replace(/^./, m => m.toUpperCase())),
      c.plans.length ? h("span", {}, `Plan: ${c.plans.map(planTitle).join(", ")}`) : null,
      c.blocked_by.length ? h("span", {}, `Blocked by ${c.blocked_by.map(b => "#" + b).join(", ")}`) : null]
      .filter(Boolean));   // replaceChildren() would print a null as "null"
  };
  const show = el => {
    const c = B.cards.find(x => String(x.id) === el.dataset.id); if (!c) return hide();
    anchor()?.removeAttribute("aria-describedby");
    id = el.dataset.id; el.setAttribute("aria-describedby", "tip"); fill(c); tip.classList.add("on"); place();
  };
  const cardOf = e => e.target.closest?.("#board .card");
  document.addEventListener("mouseover", e => { const c = cardOf(e); if (c && !pinned) show(c); });
  document.addEventListener("mouseout", e => { const c = cardOf(e); if (c && !pinned && !c.contains(e.relatedTarget)) hide(); });
  // focus on another card moves even a pinned tip there (a click's own focusin lands before its click pins)
  document.addEventListener("focusin", e => { const c = cardOf(e); if (c && (!pinned || id !== c.dataset.id)) { pinned = false; show(c); } });
  document.addEventListener("focusout", e => { if (cardOf(e) && !pinned) hide(); });
  document.addEventListener("click", e => {
    const c = cardOf(e);
    if (!c) { if (id != null) hide(); return; }                   // a tap outside closes it
    if (pinned && id === c.dataset.id) return hide();              // a second tap on the same card closes it
    show(c); pinned = true;
  });
  document.addEventListener("keydown", e => e.key === "Escape" && hide());
  addEventListener("scroll", () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(place); }, {passive: true, capture: true});
  addEventListener("resize", hide);
  return {refresh(){                                                // after a re-render: keep it on its card, if the card still exists
    if (id == null) return;
    const a = anchor(), c = a && B.cards.find(x => String(x.id) === id);
    if (!c) return hide();
    a.setAttribute("aria-describedby", "tip"); fill(c); place();
  }};
})();

/* ---- controls: state lives here, so a refresh re-renders with the same filter, group and search (L36) ---- */
function seg(attr, apply){
  const btns = document.querySelectorAll(`[data-${attr}]`);
  btns.forEach(b => b.addEventListener("click", () => {
    btns.forEach(x => x.setAttribute("aria-pressed", String(x === b)));
    apply(b.dataset[attr]); if (B) render();
  }));
}
seg("w", v => state.w = v); seg("g", v => state.g = v); seg("l", v => state.live = v === "on");
$("q").addEventListener("input", e => { state.q = e.target.value; if (B) render(); });
document.querySelectorAll("[data-f]").forEach(b => b.addEventListener("click", () => {
  const on = b.getAttribute("aria-pressed") !== "true"; b.setAttribute("aria-pressed", String(on));
  on ? state.f.add(b.dataset.f) : state.f.delete(b.dataset.f); if (B) render();
}));
$("board").addEventListener("click", e => {
  if (!e.target.closest?.("button.more")) return;
  state.allDone = true; render();                                  // stays expanded across refreshes (K13)
  $("board").querySelector('[data-col="done"] .card')?.focus({preventScroll: true});
});

/* ---- K10: fetch both on load, then every 3 s while visible; stop while hidden, fetch again on return ---- */
async function getJSON(url){
  // a hung request rejects after 10 s, so the alert reports it and the poll loop carries on
  const res = await fetch(url, {headers: {Accept: "application/json"}, cache: "no-store", signal: AbortSignal.timeout(10000)});
  if (!res.ok) throw new Error(`${url} answered ${res.status}`);
  return [await res.text(), res];
}
function alertLine(text){ const el = $("err"); if (el.textContent !== text) el.textContent = text; }   // unchanged: not re-announced; :empty hides it

let timer = 0, busy = false;
async function tick(){
  clearTimeout(timer);
  if (document.hidden || busy) return;
  busy = true;
  try {
    const [board, live] = await Promise.allSettled([getJSON("/api/board"), getJSON("/api/live")]);
    if (board.status === "rejected") {
      alertLine(`Couldn't load the board (${board.reason.message}). Check that taskman site is still running; this page retries every 3 s.`);
      if (!B) $("board").replaceChildren();
    } else {
      const liveText = live.status === "fulfilled" ? live.value[0] : "";
      const text = board.value[0] + "\n" + liveText;
      alertLine(live.status === "rejected" ? `Live runs couldn't be read (${live.reason.message}); showing the board without them.` : "");
      if (text !== lastText) {                                     // unchanged data: leave the DOM (and scroll, focus) alone
        const bdoc = JSON.parse(board.value[0]);
        let ldoc = null;
        try { ldoc = liveText ? JSON.parse(liveText) : null; } catch { ldoc = null; }
        B = normBoard(bdoc); L = normLive(ldoc); lastText = text;
        render();
      }
    }
  } catch (err) {
    alertLine(`Couldn't read the board (${err.message}). This page retries every 3 s.`);
    if (!B) $("board").replaceChildren();
  } finally {
    busy = false;
    if (!document.hidden) timer = setTimeout(tick, POLL_MS);
  }
}
document.addEventListener("visibilitychange", () => { if (document.hidden) clearTimeout(timer); else tick(); });
tick();
