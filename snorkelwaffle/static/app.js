"use strict";

// ---------------------------------------------------------------- helpers
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const view = $("#view");
const player = $("#player");

function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: {} };
  if (opts.body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.body);
  }
  const res = await fetch(path, init);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function fmtTime(sec) {
  sec = Math.max(0, Math.round(sec || 0));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
}
function fmtDuration(sec) {
  sec = Math.round(sec || 0);
  if (sec < 60) return `${sec}s`;
  const h = Math.floor(sec / 3600), m = Math.round((sec % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m`;
}
function fmtClipLen(sec) {
  return sec < 600 ? `${(sec || 0).toFixed(1)}s` : fmtDuration(sec);
}
function fmtBytes(b) {
  if (!b) return "0 B";
  const u = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(u.length - 1, Math.floor(Math.log(b) / Math.log(1024)));
  return `${(b / 1024 ** i).toFixed(i > 1 ? 1 : 0)} ${u[i]}`;
}
function ago(ts) {
  if (!ts) return "never";
  const s = Math.round(Date.now() / 1000 - ts);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

let toastTimer;
function toast(msg, isError = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.toggle("error", isError);
  t.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), isError ? 6000 : 2500);
}

const ICON_PLAY = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 2.5v11l9-5.5z" fill="currentColor"/></svg>';
const ICON_STOP = '<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="3.5" y="3.5" width="9" height="9" rx="1" fill="currentColor"/></svg>';

// One shared <audio>; buttons carry data-src.
let playingBtn = null;
function setPlayIcon(btn, playing) {
  if (!btn) return;
  btn.innerHTML = playing ? ICON_STOP : ICON_PLAY;
  btn.setAttribute("aria-label", playing ? "Stop" : "Play");
}
function togglePlay(btn) {
  if (playingBtn === btn && !player.paused) {
    player.pause();
    return;
  }
  setPlayIcon(playingBtn, false);
  playingBtn = btn;
  player.src = btn.dataset.src;
  player.play().catch((e) => toast(`Can't play: ${e.message}`, true));
  setPlayIcon(btn, true);
}
player.addEventListener("pause", () => setPlayIcon(playingBtn, false));
player.addEventListener("ended", () => setPlayIcon(playingBtn, false));
function playButton(src, label = "Play") {
  return `<button class="btn icon" data-play data-src="${esc(src)}" aria-label="${esc(label)}">${ICON_PLAY}</button>`;
}
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-play]");
  if (b) { e.preventDefault(); e.stopPropagation(); togglePlay(b); }
});

// ---------------------------------------------------------------- status bar
let lastStatus = null;
async function refreshStatus() {
  try {
    const s = await api("/api/status");
    lastStatus = s;
    const job = s.worker.job || "idle";
    const busy = job !== "idle";
    $("#worker-line").innerHTML =
      `<span class="dot ${busy ? "busy" : ""}"></span><span class="job">${esc(job)}</span>` +
      (s.queue ? `<span class="muted">· ${s.queue} queued</span>` : "");
    const pending = s.stats.clips.pending || 0;
    const pill = $("#nav-pending");
    pill.textContent = pending;
    pill.classList.toggle("hidden", !pending);
    return s;
  } catch (e) {
    $("#worker-line").innerHTML = `<span class="dot"></span><span class="job">offline</span>`;
  }
}
setInterval(() => { if (!document.hidden) refreshStatus(); }, 5000);

// ---------------------------------------------------------------- router
const routes = [
  [/^#?\/?$/, renderOverview, "overview"],
  [/^#\/review$/, renderReview, "review"],
  [/^#\/clips\/(\d+)$/, renderClip, "review"],
  [/^#\/episodes$/, renderEpisodes, "episodes"],
  [/^#\/episodes\/(\d+)$/, renderEpisode, "episodes"],
  [/^#\/settings$/, renderSettings, "settings"],
  [/^#\/log$/, renderLog, "log"],
];
let viewCleanup = null;
async function route() {
  if (viewCleanup) { viewCleanup(); viewCleanup = null; }
  const hash = location.hash.split("?")[0];
  for (const [re, fn, nav] of routes) {
    const m = hash.match(re);
    if (m) {
      $$(".top nav a").forEach((a) => a.classList.toggle("active", a.dataset.nav === nav));
      try {
        await fn(...m.slice(1));
      } catch (e) {
        view.innerHTML = `<div class="empty">Something went wrong: ${esc(e.message)}</div>`;
      }
      return;
    }
  }
  location.hash = "#/";
}
window.addEventListener("hashchange", route);

// ---------------------------------------------------------------- overview
async function renderOverview() {
  const s = await refreshStatus();
  if (!s) throw new Error("server unreachable");
  const st = s.stats, set = s.settings;
  const analysed = st.episodes.analyzed || 0;
  const problems = (st.episodes.error || 0) + (st.episodes.missing || 0) + st.cut_failed;
  const capBytes = set.originals_max_gb * 1024 ** 3;
  const pct = capBytes ? Math.min(100, (100 * st.originals.bytes) / capBytes) : 0;
  const pending = st.clips.pending || 0;
  view.innerHTML = `
    <h1>Overview</h1>
    <p class="sub">Finds audio that repeats across your podcast episodes, lets you decide once per clip, and cuts the ads in place.</p>
    ${!set.cutting_enabled ? `<div class="callout"><strong>Cutting is paused.</strong> Episodes are analysed and clips found, but no files are changed. <a href="#/settings">Settings</a></div>` : ""}
    ${pending ? `<div class="callout"><strong>${pending} clip${pending === 1 ? "" : "s"} waiting for review.</strong> Nothing is cut until you mark a clip as an ad${set.auto_approve !== "off" ? " (or auto-approve picks it up)" : ""}. <a href="#/review">Review now</a></div>` : ""}
    <div class="tiles">
      <a class="tile" href="#/episodes"><div class="label">Episodes analysed</div><div class="value">${analysed.toLocaleString()}</div>
        <div class="hint">${st.episodes_total.toLocaleString()} in ${st.shows} show${st.shows === 1 ? "" : "s"}${s.queue ? ` · ${s.queue} queued` : ""}</div></a>
      <a class="tile" href="#/review"><div class="label">Clips to review</div><div class="value">${pending}</div>
        <div class="hint">${st.clips.ad || 0} ads · ${st.clips.keep || 0} kept</div></a>
      <a class="tile" href="#/episodes?filter=cut"><div class="label">Ad time removed</div><div class="value">${fmtDuration(st.removed_seconds)}</div>
        <div class="hint">from ${st.episodes_cut} episode${st.episodes_cut === 1 ? "" : "s"}</div></a>
      <div class="tile"><div class="label">Originals kept</div><div class="value">${fmtBytes(st.originals.bytes)}</div>
        <div class="hint">${st.originals.count} files · cap ${set.originals_max_gb} GB${set.originals_max_days ? `, ${set.originals_max_days} days` : ""}</div>
        <div class="meter" role="img" aria-label="${pct.toFixed(0)}% of cap used"><div style="width:${pct}%"></div></div></div>
      ${problems ? `<a class="tile" href="#/episodes?filter=problems"><div class="label">Problems</div><div class="value" style="color:var(--danger)">${problems}</div><div class="hint">errors, missing files, failed cuts</div></a>` : ""}
    </div>

    <h2>Worker</h2>
    <div class="panel">
      <div class="row"><span class="dot ${s.worker.job !== "idle" ? "busy" : ""}"></span><strong>${esc(s.worker.job)}</strong>
        <span class="muted">since ${ago(s.worker.since)}</span><span class="spacer"></span>
        <button class="btn" id="scan-now">Scan library now</button></div>
      <p class="muted" style="margin:10px 0 0">Last scan ${ago(s.worker.last_scan)} · every ${set.scan_interval_minutes} min ·
        Audiobookshelf: ${s.abs_configured ? `connected by API <button class="btn small" id="abs-test">Test</button>` : "not configured (set ABS_URL and ABS_TOKEN)"}</p>
    </div>

    <h2>How it works</h2>
    <div class="panel muted">
      <ol style="margin:0;padding-left:20px">
        <li>Each episode is fingerprinted (chromaprint via ffmpeg) and compared with nearby episodes of the same show.</li>
        <li>Audio heard in more than one episode becomes a <strong>clip</strong>. Clips are then looked for across the whole library.</li>
        <li>You mark each clip once: <span class="tag ad">Ad</span> is cut from every episode, <span class="tag keep">Keep</span> is left alone (intros, outros, jingles).</li>
        <li>Cuts are lossless and in place; the original is kept (within the cap) so any episode can be restored.</li>
      </ol>
    </div>`;
  $("#scan-now").onclick = async () => { await api("/api/scan", { method: "POST" }); toast("Scan started"); refreshStatus(); };
  const t = $("#abs-test");
  if (t) t.onclick = async () => {
    const r = await api("/api/abs/ping");
    toast(r.ok ? `Audiobookshelf OK: ${r.message}` : `Audiobookshelf: ${r.message}`, !r.ok);
  };
}

// ---------------------------------------------------------------- review
const reviewState = { status: "pending", sort: "confidence", show: "", offset: 0, selected: 0, checked: new Set() };

function suggestionTag(s) {
  if (!s) return "";
  const cls = s.kind === "ad" ? "ad" : s.kind === "theme" ? "theme" : "plain";
  const label = { ad: "Likely ad", theme: "Likely intro/outro", excerpt: "Maybe a preview" }[s.kind] || s.kind;
  return `<span class="tag ${cls}" title="${esc(s.reason)}">${label}</span>`;
}
function confidenceTag(c) {
  if (c.suggestion && c.suggestion.kind === "theme") return "";  // intros/outros: an ad score would mislead
  const n = c.confidence ?? 0;
  const cls = n >= 85 ? "ad" : n >= 60 ? "pending" : "plain";
  return `<span class="tag ${cls}" title="How likely this is an ad (0-100). Used by 'confident' auto-approve.">Ad score ${n}</span>`;
}
function timeRange(o) {
  const t = `${fmtTime(o.start)}–${fmtTime(o.end)}`;
  return o.refined ? `<span title="Exact: aligned on the audio (±0.05 s)">${t}</span>`
                   : `<span title="Approximate: from fingerprints (±1 s)">≈ ${t}</span>`;
}
function statusTag(c) {
  const t = { pending: "To review", ad: "Ad", keep: "Keep" }[c.status];
  return `<span class="tag ${c.status}">${t}${c.decided_by === "auto" ? " (auto)" : ""}</span>`;
}

function clipCard(c, i) {
  const shows = c.shows.map(esc).join(", ") + (c.show_count > c.shows.length ? ` +${c.show_count - c.shows.length}` : "");
  return `
  <article class="clip ${i === reviewState.selected ? "selected" : ""}" data-id="${c.id}" data-i="${i}">
    <input type="checkbox" aria-label="Select clip ${c.id}" data-check ${reviewState.checked.has(c.id) ? "checked" : ""}>
    ${c.has_preview ? playButton(`/api/clips/${c.id}/preview`, `Play clip ${c.id}`) : `<span></span>`}
    <div class="meta">
      <div class="title"><a href="#/clips/${c.id}">${fmtClipLen(c.duration)} clip</a> ${statusTag(c)} ${suggestionTag(c.suggestion)} ${confidenceTag(c)}</div>
      <div class="facts">In ${c.episode_count} episode${c.episode_count === 1 ? "" : "s"} · ${shows}${c.suggestion ? ` · ${esc(c.suggestion.reason)}` : ""}${c.note ? ` · “${esc(c.note)}”` : ""}</div>
    </div>
    <div class="actions">
      <button class="btn ad ${c.status === "ad" ? "on" : ""}" data-set="ad" title="Cut this everywhere (A)">Ad: cut it</button>
      <button class="btn keep ${c.status === "keep" ? "on" : ""}" data-set="keep" title="Leave it in (K)">Keep</button>
      <button class="btn small" data-where aria-expanded="false">Where?</button>
    </div>
  </article>`;
}

async function renderReview() {
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  if (params.get("status")) reviewState.status = params.get("status");
  const [data, shows] = await Promise.all([
    api(`/api/clips?status=${reviewState.status}&sort=${reviewState.sort}&show=${encodeURIComponent(reviewState.show)}&limit=50&offset=${reviewState.offset}`),
    api("/api/shows"),
  ]);
  const counts = data.counts;
  const all = Object.values(counts).reduce((a, b) => a + b, 0);
  reviewState.selected = Math.min(reviewState.selected, Math.max(0, data.items.length - 1));
  const tab = (key, label, n) => `<button role="tab" aria-selected="${reviewState.status === key}" class="${reviewState.status === key ? "active" : ""}" data-tab="${key}">${label}<span class="count">${n ?? 0}</span></button>`;
  view.innerHTML = `
    <h1>Review clips</h1>
    <p class="sub">Decide once per clip. Shortcuts: <span class="kbd">↑</span>/<span class="kbd">↓</span> move, <span class="kbd">Space</span> play, <span class="kbd">A</span> ad, <span class="kbd">K</span> keep, <span class="kbd">U</span> undecide.</p>
    <div class="tabs" role="tablist">${tab("pending", "To review", counts.pending)}${tab("ad", "Ads", counts.ad)}${tab("keep", "Kept", counts.keep)}${tab("all", "All", all)}</div>
    <div class="filters">
      <select id="f-sort" aria-label="Sort">
        <option value="confidence">Highest ad score</option><option value="episodes">Most episodes</option><option value="shows">Most shows</option>
        <option value="newest">Newest</option><option value="duration">Longest</option>
      </select>
      <select id="f-show" aria-label="Show"><option value="">All shows</option>${shows.items.map((s) => `<option ${s.show === reviewState.show ? "selected" : ""}>${esc(s.show)}</option>`).join("")}</select>
      <span class="spacer"></span>
      <span id="bulk" class="row ${reviewState.checked.size ? "" : "hidden"}">
        <span class="muted"><span id="bulk-n">${reviewState.checked.size}</span> selected</span>
        <button class="btn ad" data-bulk="ad">Mark ads</button><button class="btn keep" data-bulk="keep">Keep</button>
        <button class="btn small" data-bulk="clear">Clear</button>
      </span>
    </div>
    <div class="clips">${data.items.map(clipCard).join("") || `<div class="empty">${reviewState.status === "pending" ? "Nothing to review. New clips show up here as episodes are analysed." : "No clips here yet."}</div>`}</div>
    ${pager(data.total, reviewState.offset, 50)}`;
  $("#f-sort").value = reviewState.sort;
  $("#f-sort").onchange = (e) => { reviewState.sort = e.target.value; reviewState.offset = 0; renderReview(); };
  $("#f-show").onchange = (e) => { reviewState.show = e.target.value; reviewState.offset = 0; renderReview(); };
  $$("[data-tab]").forEach((b) => b.onclick = () => { reviewState.status = b.dataset.tab; reviewState.offset = 0; reviewState.selected = 0; history.replaceState(null, "", "#/review"); renderReview(); });
  bindPager((o) => { reviewState.offset = o; renderReview(); });

  const items = data.items;
  const cards = () => $$(".clip");
  const select = (i) => {
    reviewState.selected = Math.max(0, Math.min(items.length - 1, i));
    cards().forEach((el) => el.classList.toggle("selected", +el.dataset.i === reviewState.selected));
    const el = cards()[reviewState.selected];
    if (el) el.scrollIntoView({ block: "nearest" });
  };
  const decide = async (i, status) => {
    const c = items[i];
    if (!c) return;
    await api(`/api/clips/${c.id}`, { method: "POST", body: { status } });
    toast(status === "ad" ? "Marked as ad: it will be cut" : status === "keep" ? "Kept" : "Back to review");
    if (reviewState.status === "pending" && status !== "pending") {
      if (playingBtn && cards()[i]?.contains(playingBtn)) player.pause();
      items.splice(i, 1);
      cards()[i].remove();
      cards().forEach((el, j) => (el.dataset.i = j));
      select(Math.min(i, items.length - 1));
      refreshStatus();
      if (!items.length) renderReview();
    } else {
      c.status = status;
      c.decided_by = "user";
      cards()[i].outerHTML = clipCard(c, i);
    }
  };

  view.querySelector(".clips").addEventListener("click", async (e) => {
    const card = e.target.closest(".clip");
    if (!card) return;
    const i = +card.dataset.i;
    if (e.target.matches("[data-check]")) {
      const id = items[i].id;
      e.target.checked ? reviewState.checked.add(id) : reviewState.checked.delete(id);
      $("#bulk").classList.toggle("hidden", !reviewState.checked.size);
      $("#bulk-n").textContent = reviewState.checked.size;
      return;
    }
    select(i);
    const set = e.target.closest("[data-set]");
    if (set) return decide(i, set.dataset.set);
    const where = e.target.closest("[data-where]");
    if (where) {
      const open = card.querySelector(".where");
      if (open) { open.remove(); where.setAttribute("aria-expanded", "false"); return; }
      where.setAttribute("aria-expanded", "true");
      const d = await api(`/api/clips/${items[i].id}`);
      card.insertAdjacentHTML("beforeend", `<div class="where">${occurrenceTable(d.occurrences.slice(0, 12))}
        ${d.occurrences.length > 12 ? `<p class="muted"><a href="#/clips/${items[i].id}">All ${d.occurrences.length} places</a></p>` : ""}</div>`);
    }
  });
  $$("[data-bulk]").forEach((b) => b.onclick = async () => {
    if (b.dataset.bulk !== "clear") {
      await api("/api/clips/bulk", { method: "POST", body: { ids: [...reviewState.checked], status: b.dataset.bulk } });
      toast(`${reviewState.checked.size} clip(s) updated`);
    }
    reviewState.checked.clear();
    renderReview();
    refreshStatus();
  });

  const onKey = (e) => {
    if (e.target.closest("input, select, textarea") || e.metaKey || e.ctrlKey || e.altKey) return;
    const k = e.key.toLowerCase();
    if (k === "arrowdown" || k === "j") { e.preventDefault(); select(reviewState.selected + 1); }
    else if (k === "arrowup") { e.preventDefault(); select(reviewState.selected - 1); }
    else if (k === " ") { e.preventDefault(); const b = cards()[reviewState.selected]?.querySelector("[data-play]"); if (b) togglePlay(b); }
    else if (k === "a") decide(reviewState.selected, "ad");
    else if (k === "k") decide(reviewState.selected, "keep");
    else if (k === "u") decide(reviewState.selected, "pending");
  };
  document.addEventListener("keydown", onKey);
  viewCleanup = () => document.removeEventListener("keydown", onKey);
}

function occurrenceTable(occ) {
  if (!occ.length) return `<p class="muted">Not found in any current episode file (already cut, or episodes changed).</p>`;
  return `<div class="table-wrap"><table>
    <thead><tr><th></th><th>Episode</th><th>Show</th><th class="num">At</th><th class="num">Length</th></tr></thead>
    <tbody>${occ.map((o) => `<tr>
      <td>${playButton(`/api/occurrences/${o.id}/audio?pad=3`, "Play with 3 seconds of context")}</td>
      <td class="ep-name"><a href="#/episodes/${o.episode_id}">${esc(o.name)}</a></td>
      <td>${esc(o.show)}</td>
      <td class="num mono">${timeRange(o)}</td>
      <td class="num">${fmtClipLen(o.end - o.start)}</td></tr>`).join("")}</tbody></table></div>
    <p class="muted" style="font-size:13px;margin:6px 0 0">Play buttons here include 3 s either side, so you can check the boundaries.</p>`;
}

async function renderClip(id) {
  const d = await api(`/api/clips/${id}`);
  const c = d.clip;
  view.innerHTML = `
    <p><a href="#/review">← Review</a></p>
    <div class="row">${c.has_preview ? playButton(`/api/clips/${c.id}/preview`) : ""}
      <h1 style="margin:0">${fmtClipLen(c.duration)} clip #${c.id}</h1> ${statusTag(c)} ${suggestionTag(c.suggestion)} ${confidenceTag(c)}</div>
    <p class="sub" style="margin-top:8px">First found in <strong>${esc(c.source_show)}</strong> · heard in ${c.episode_count} episode(s) across ${c.show_count} show(s)${d.cut_episodes ? ` · cut from ${d.cut_episodes} episode(s) so far` : ""}${c.suggestion ? ` · ${esc(c.suggestion.reason)}` : ""}</p>
    <div class="row">
      <button class="btn ad ${c.status === "ad" ? "on" : ""}" data-set="ad">Ad: cut it everywhere</button>
      <button class="btn keep ${c.status === "keep" ? "on" : ""}" data-set="keep">Keep</button>
      <button class="btn" data-set="pending">Undecide</button>
      <span class="spacer"></span>
      <input id="note" type="text" placeholder="Note (e.g. sponsor name)" value="${esc(c.note || "")}" style="padding:6px 10px;border-radius:8px;border:1px solid var(--border);background:var(--surface);min-width:0;flex:1 1 200px;max-width:320px">
      <button class="btn danger" id="del" title="Forget this clip. It may be found again later.">Delete</button>
    </div>
    <h2>Where it is</h2>
    ${occurrenceTable(d.occurrences)}`;
  $$("[data-set]").forEach((b) => b.onclick = async () => {
    await api(`/api/clips/${id}`, { method: "POST", body: { status: b.dataset.set } });
    toast("Saved");
    renderClip(id);
    refreshStatus();
  });
  $("#note").onchange = async (e) => { await api(`/api/clips/${id}`, { method: "POST", body: { note: e.target.value } }); toast("Note saved"); };
  $("#del").onclick = async () => {
    if (!confirm("Delete this clip? It stops being matched; it may be rediscovered from new episodes.")) return;
    await api(`/api/clips/${id}`, { method: "DELETE" });
    location.hash = "#/review";
  };
}

// ---------------------------------------------------------------- episodes
const epState = { filter: "all", show: "", q: "", offset: 0 };

function pager(total, offset, limit) {
  if (total <= limit) return "";
  return `<div class="pager"><span>${offset + 1}–${Math.min(total, offset + limit)} of ${total.toLocaleString()}</span>
    <button class="btn small" data-page="${Math.max(0, offset - limit)}" ${offset ? "" : "disabled"}>Previous</button>
    <button class="btn small" data-page="${offset + limit}" ${offset + limit < total ? "" : "disabled"}>Next</button></div>`;
}
function bindPager(fn) {
  $$("[data-page]").forEach((b) => b.onclick = () => { fn(+b.dataset.page); window.scrollTo(0, 0); });
}

function epStatus(e) {
  if (e.cut_failed) return `<span class="tag ad" title="${esc(e.error)}">cut failed</span>`;
  if (e.status === "error") return `<span class="tag ad" title="${esc(e.error)}">error</span>`;
  if (e.status === "missing") return `<span class="tag plain">missing</span>`;
  if (e.status === "queued") return `<span class="tag pending">queued</span>`;
  if (e.status === "incomplete") return `<span class="tag plain" title="Too small to be audio: a failed or partial download">incomplete</span>`;
  if (e.status === "skipped") return `<span class="tag plain" title="This show is set to Skip">skipped</span>`;
  if (e.excluded) return `<span class="tag plain">excluded</span>`;
  if (e.removed_seconds > 0) return `<span class="tag keep">cut</span>`;
  return `<span class="tag plain">analysed</span>`;
}

async function renderEpisodes() {
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  if (params.get("filter")) { epState.filter = params.get("filter"); epState.offset = 0; history.replaceState(null, "", "#/episodes"); }
  const qs = `filter=${epState.filter}&show=${encodeURIComponent(epState.show)}&q=${encodeURIComponent(epState.q)}&limit=50&offset=${epState.offset}`;
  const [data, shows] = await Promise.all([api(`/api/episodes?${qs}`), api("/api/shows")]);
  const chip = (k, label) => `<button class="chip ${epState.filter === k ? "active" : ""}" data-filter="${k}">${label}</button>`;
  view.innerHTML = `
    <h1>Episodes</h1>
    <p class="sub">${shows.items.length} show(s). Open an episode to see where clips were found, restore the original, or exclude it from cutting.</p>
    <div class="filters">
      ${chip("all", "All")}${chip("cut", "Cut")}${chip("pending_ads", "Has ads")}${chip("queued", "Queued")}${chip("problems", "Problems")}${chip("excluded", "Excluded")}
      <span class="spacer"></span>
      <select id="f-show" aria-label="Show"><option value="">All shows</option>${shows.items.map((s) => `<option ${s.show === epState.show ? "selected" : ""}>${esc(s.show)}</option>`).join("")}</select>
      <input type="search" id="f-q" placeholder="Search file names" value="${esc(epState.q)}" aria-label="Search">
    </div>
    ${data.items.length ? `<div class="table-wrap"><table>
      <thead><tr><th>Episode</th><th>Show</th><th class="num">Length</th><th class="num">Removed</th><th class="num">Clips</th><th>Status</th></tr></thead>
      <tbody>${data.items.map((e) => `<tr class="link" data-id="${e.id}">
        <td class="ep-name"><a href="#/episodes/${e.id}">${esc(e.name)}</a></td><td>${esc(e.show)}</td>
        <td class="num">${e.duration ? fmtTime(e.duration) : "–"}</td>
        <td class="num">${e.removed_seconds ? fmtDuration(e.removed_seconds) : "–"}</td>
        <td class="num">${e.clip_count || "–"}</td><td>${epStatus(e)}</td></tr>`).join("")}</tbody></table></div>`
      : `<div class="empty">No episodes match.</div>`}
    ${pager(data.total, epState.offset, 50)}`;
  $$("[data-filter]").forEach((b) => b.onclick = () => { epState.filter = b.dataset.filter; epState.offset = 0; renderEpisodes(); });
  $("#f-show").onchange = (e) => { epState.show = e.target.value; epState.offset = 0; renderEpisodes(); };
  let t;
  $("#f-q").oninput = (e) => { clearTimeout(t); t = setTimeout(() => { epState.q = e.target.value; epState.offset = 0; renderEpisodes().then(() => { const q = $("#f-q"); q.focus(); q.setSelectionRange(q.value.length, q.value.length); }); }, 300); };
  $$("tr.link").forEach((tr) => tr.onclick = (e) => { if (!e.target.closest("a")) location.hash = `#/episodes/${tr.dataset.id}`; });
  bindPager((o) => { epState.offset = o; renderEpisodes(); });
}

async function renderEpisode(id) {
  const d = await api(`/api/episodes/${id}`);
  const e = d.episode, dur = e.duration || 1;
  const segs = d.occurrences.map((o) => `<div class="seg ${o.status}" style="left:${(100 * o.start) / dur}%;width:${(100 * (o.end - o.start)) / dur}%"
      title="${fmtTime(o.start)}–${fmtTime(o.end)} · clip #${o.clip_id} (${o.status})" data-clip="${o.clip_id}"></div>`).join("");
  const removed = d.cuts.reduce((a, c) => a + (c.end - c.start), 0);
  view.innerHTML = `
    <p><a href="#/episodes">← Episodes</a></p>
    <h1 class="ep-name">${esc(e.name)}</h1>
    <p class="sub">${esc(e.show)} · ${fmtTime(e.duration)} · ${epStatus(e)}${e.note ? ` · ${esc(e.note)}` : ""}</p>
    ${e.error ? `<div class="callout" style="border-color:var(--danger)">${esc(e.error)}</div>` : ""}
    <div class="panel">
      <div class="timeline" role="img" aria-label="Clips found in this episode">${segs}</div>
      <div class="axis"><span>0:00</span><span>${fmtTime(dur / 2)}</span><span>${fmtTime(dur)}</span></div>
      <div class="legend"><span><i style="background:var(--ad)"></i>Ad (will be cut)</span><span><i style="background:var(--pending)"></i>To review</span><span><i style="background:var(--keep)"></i>Keep</span></div>
    </div>
    <div class="row" style="margin-top:14px">
      ${d.original ? `<button class="btn" id="restore">Restore original</button>` : ""}
      <button class="btn" id="reprocess">Re-analyse</button>
      <button class="btn" id="exclude">${e.excluded ? "Allow cutting again" : "Never cut this episode"}</button>
      <span class="muted">${d.original ? `Original kept (${fmtBytes(d.original.size)}, ${ago(d.original.created_at)})` : e.removed_seconds ? "Original no longer kept (cap reached)" : ""}</span>
    </div>
    <h2>Clips in this episode</h2>
    ${d.occurrences.length ? `<div class="table-wrap"><table>
      <thead><tr><th></th><th>Clip</th><th class="num">At</th><th class="num">Length</th><th>Status</th><th class="num">Seen in</th></tr></thead>
      <tbody>${d.occurrences.map((o) => `<tr>
        <td>${playButton(`/api/occurrences/${o.id}/audio?pad=3`, "Play with context")}</td>
        <td><a href="#/clips/${o.clip_id}">#${o.clip_id}</a></td>
        <td class="num mono">${timeRange(o)}</td><td class="num">${fmtClipLen(o.end - o.start)}</td>
        <td>${statusTag({ status: o.status })}</td><td class="num">${o.episode_count} ep · ${o.show_count} show</td></tr>`).join("")}</tbody></table></div>`
      : `<p class="muted">${e.status === "queued" ? "Not analysed yet." : "No repeated audio found in the current file."}</p>`}
    ${d.cuts.length ? `<h2>Cut so far</h2><p class="muted">${fmtDuration(removed)} removed in ${d.cuts.length} span(s): ${d.cuts.map((c) => `${fmtTime(c.start)}–${fmtTime(c.end)}`).join(", ")} (times as they were at each cut).</p>` : ""}
    <p class="muted mono" style="font-size:12px;overflow-wrap:anywhere">${esc(e.path)}</p>`;
  $$(".seg").forEach((s) => s.onclick = () => (location.hash = `#/clips/${s.dataset.clip}`));
  const r = $("#restore");
  if (r) r.onclick = async () => {
    if (!confirm("Put the original file back? The episode will be excluded from future cuts.")) return;
    r.disabled = true;
    try { await api(`/api/episodes/${id}/restore`, { method: "POST" }); toast("Original restored"); } catch (err) { toast(err.message, true); }
    renderEpisode(id);
  };
  $("#reprocess").onclick = async () => { await api(`/api/episodes/${id}/reprocess`, { method: "POST" }); toast("Queued for analysis"); renderEpisode(id); };
  $("#exclude").onclick = async () => { await api(`/api/episodes/${id}/exclude`, { method: "POST", body: { excluded: !e.excluded } }); renderEpisode(id); };
}

// ---------------------------------------------------------------- settings
async function renderSettings() {
  const [d, shows] = await Promise.all([api("/api/settings"), api("/api/shows")]);
  const values = { ...d.values };
  const groups = [...new Set(d.schema.map((s) => s.group))];
  const control = (s) => {
    const v = values[s.key];
    if (s.type === "bool") return `<label class="switch"><input type="checkbox" id="s-${s.key}" data-key="${s.key}" ${v ? "checked" : ""}><span></span></label>`;
    if (s.type === "choice") return `<select id="s-${s.key}" data-key="${s.key}">${s.choices.map((c) => `<option ${c === v ? "selected" : ""}>${c}</option>`).join("")}</select>`;
    return `<input type="number" id="s-${s.key}" data-key="${s.key}" value="${v}" ${s.min !== undefined ? `min="${s.min}"` : ""} ${s.max !== undefined ? `max="${s.max}"` : ""} step="${s.type === "int" ? 1 : "any"}">`;
  };
  view.innerHTML = `
    <h1>Settings</h1>
    <p class="sub">Saved in the database and applied immediately. Deployment settings (paths, ports, Audiobookshelf credentials) come from environment variables; see below.</p>
    <form id="settings-form">
    ${groups.map((g) => `<section class="settings-group"><h2>${esc(g)}</h2><div class="panel">
      ${d.schema.filter((s) => s.group === g).map((s) => `<div class="setting">
        <label for="s-${s.key}">${esc(s.label)}</label><div class="control">${control(s)}</div>
        <div class="help">${esc(s.help)}</div></div>`).join("")}
    </div></section>`).join("")}
    <div class="savebar"><button class="btn primary" type="submit" id="save" disabled>Save changes</button><span id="dirty" class="muted"></span></div>
    </form>
    <h2>Shows</h2>
    <p class="muted" style="margin-top:-4px"><strong>Review only</strong>: clips are found but never auto-cut (good for ad-free or Patreon feeds, where repeats are usually previews or plugs). <strong>Skip</strong>: never analysed, matched or cut.</p>
    <div class="table-wrap"><table><thead><tr><th>Show</th><th class="num">Episodes</th><th>Mode</th></tr></thead>
      <tbody>${shows.items.map((s) => `<tr><td>${esc(s.show)}</td><td class="num">${s.episodes}</td>
        <td><select data-show="${esc(s.show)}" aria-label="Mode for ${esc(s.show)}">
          ${[["normal", "Normal"], ["review_only", "Review only"], ["skip", "Skip"]].map(([v, l]) => `<option value="${v}" ${s.mode === v ? "selected" : ""}>${l}</option>`).join("")}
        </select></td></tr>`).join("") || `<tr><td colspan="3" class="muted">No shows found yet.</td></tr>`}</tbody></table></div>

    <h2>Environment (read-only)</h2>
    <p class="muted" style="margin-top:-4px">Set these in docker-compose or DockSTARTer's <span class="mono">.env</span>. Any setting above can also be seeded with <span class="mono">SW_&lt;KEY&gt;</span>, e.g. <span class="mono">SW_AUTO_APPROVE=multi_show</span>, until it is changed here.</p>
    <div class="table-wrap"><table><tbody>${Object.entries(d.env).map(([k, v]) => `<tr><td class="mono">${esc(k)}</td><td class="mono">${esc(v)}</td></tr>`).join("")}</tbody></table></div>`;
  $$("[data-show]").forEach((sel) => sel.onchange = async () => {
    try {
      await api("/api/shows", { method: "POST", body: { show: sel.dataset.show, mode: sel.value } });
      toast(`${sel.dataset.show}: ${sel.options[sel.selectedIndex].text}`);
    } catch (err) { toast(err.message, true); }
  });
  const changed = {};
  const form = $("#settings-form");
  form.addEventListener("input", (e) => {
    const el = e.target.closest("[data-key]");
    if (!el) return;
    const s = d.schema.find((x) => x.key === el.dataset.key);
    const v = s.type === "bool" ? el.checked : s.type === "choice" ? el.value : el.value === "" ? null : Number(el.value);
    if (v === values[s.key] || v === null) delete changed[s.key]; else changed[s.key] = v;
    el.classList.toggle("changed", s.key in changed);
    const n = Object.keys(changed).length;
    $("#save").disabled = !n;
    $("#dirty").textContent = n ? `${n} unsaved change${n === 1 ? "" : "s"}` : "";
  });
  form.onsubmit = async (e) => {
    e.preventDefault();
    try {
      await api("/api/settings", { method: "POST", body: changed });
      toast("Settings saved");
      renderSettings();
      refreshStatus();
    } catch (err) { toast(err.message, true); }
  };
}

// ---------------------------------------------------------------- log
async function renderLog() {
  const draw = async () => {
    const d = await api("/api/log");
    const box = $("#log");
    if (!box) return;
    const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 30;
    box.innerHTML = d.items.map((r) => `<div class="${r.level}">${new Date(r.ts * 1000).toLocaleString()}  ${esc(r.msg)}</div>`).join("") || `<div class="muted">Nothing logged yet.</div>`;
    if (atBottom) box.scrollTop = box.scrollHeight;
  };
  view.innerHTML = `<h1>Log</h1><p class="sub">Recent activity (last 300 lines; full log in the container's stdout).</p><div class="log" id="log"></div>`;
  await draw();
  $("#log").scrollTop = 1e9;
  const t = setInterval(() => { if (!document.hidden) draw(); }, 4000);
  viewCleanup = () => clearInterval(t);
}

route();
