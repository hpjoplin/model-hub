/* Model Hub: reads data/index.json and data/<id>.json and shows them.
   No build step, no libraries. Works offline from the last load. */
(function () {
  "use strict";

  var view = document.getElementById("view");
  var titleEl = document.getElementById("title");
  var backBtn = document.getElementById("back");
  var refreshBtn = document.getElementById("refresh");

  var TITLE_KEYS = ["title", "game", "matchup", "event", "race", "horse", "market", "contract", "team", "name"];
  var PICK_KEYS = ["pick", "bet", "selection", "prediction", "side", "play", "call"];
  var EDGE_KEYS = ["edge", "ev", "value", "overlay"];
  var NOTE_KEYS = ["note", "notes", "reason", "why", "comment"];
  var RESULT_KEYS = ["result", "status", "outcome", "grade"];

  var state = { index: null, models: {}, filter: "" };

  // ---------- helpers ----------
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function lc(k) { return String(k).toLowerCase(); }
  function findKey(obj, keys) {
    var ks = Object.keys(obj);
    for (var i = 0; i < keys.length; i++) {
      for (var j = 0; j < ks.length; j++) if (lc(ks[j]) === keys[i]) return ks[j];
    }
    return null;
  }
  function label(k) {
    return String(k).replace(/_/g, " ").replace(/\b\w/g, function (c) { return c.toUpperCase(); });
  }
  function fmt(k, v) {
    if (v === null || v === undefined || v === "") return "";
    if (typeof v === "number") {
      var key = lc(k);
      var isProb = /prob|win%|win_pct|chance|conf|hit/.test(key) || key === "p";
      if (isProb && v >= 0 && v <= 1) return (v * 100).toFixed(1) + "%";
      if (Math.abs(v) >= 1000) return v.toLocaleString();
      if (Number.isInteger(v)) return String(v);
      return String(Math.round(v * 1000) / 1000);
    }
    if (typeof v === "boolean") return v ? "Yes" : "No";
    if (typeof v === "object") return JSON.stringify(v);
    return String(v);
  }
  function signClass(v) {
    var n = typeof v === "number" ? v : parseFloat(String(v).replace(/[^0-9.+-]/g, ""));
    if (isNaN(n) || n === 0) return "";
    return n > 0 ? "pos" : "neg";
  }
  function resultClass(v) {
    var s = lc(v);
    if (/^(w|win|won|hit|cash|cashed|correct)$/.test(s)) return "pos";
    if (/^(l|loss|lost|miss|missed|wrong)$/.test(s)) return "neg";
    return "";
  }
  function ago(iso) {
    if (!iso) return "never";
    var t = new Date(iso).getTime();
    if (isNaN(t)) return String(iso);
    var s = Math.max(0, (Date.now() - t) / 1000);
    if (s < 60) return "just now";
    if (s < 3600) return Math.floor(s / 60) + " min ago";
    if (s < 86400) return Math.floor(s / 3600) + " hr ago";
    var d = Math.floor(s / 86400);
    return d === 1 ? "yesterday" : d + " days ago";
  }
  function freshness(iso) {
    var t = new Date(iso).getTime();
    if (isNaN(t)) return "old";
    var h = (Date.now() - t) / 3600000;
    return h < 24 ? "" : h < 24 * 7 ? "stale" : "old";
  }
  function when(iso) {
    var d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    return d.toLocaleString([], { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  }

  function getJSON(path) {
    // The time stamp skips GitHub's 10 minute page cache so new results show at once.
    return fetch(path + "?t=" + Date.now(), { cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error(path + " returned " + r.status);
      return r.json();
    });
  }

  // ---------- views ----------
  function renderHome() {
    titleEl.textContent = "Model Hub";
    document.title = "Model Hub";
    backBtn.classList.add("hide");
    var idx = state.index;
    if (!idx) { view.innerHTML = '<p class="empty">Loading…</p>'; return; }
    var models = (idx.models || []).slice().sort(function (a, b) {
      return (b.updated || "").localeCompare(a.updated || "");
    });
    if (!models.length) {
      view.innerHTML = '<p class="empty">No results yet. Send some from your Mac with hub.py.</p>';
      return;
    }
    var html = '<p class="sub">Updated ' + esc(ago(idx.updated)) + "</p><div class=\"grid\">";
    models.forEach(function (m) {
      var f = freshness(m.updated);
      html += '<a class="card" href="#/m/' + encodeURIComponent(m.id) + '">' +
        '<div class="row1"><h2>' + esc(m.name || m.id) + "</h2>" +
        (m.demo ? '<span class="badge demo">Sample</span>' : "") + "</div>" +
        (m.sport ? '<div class="sport">' + esc(m.sport) + "</div>" : "") +
        (m.headline ? '<div class="headline">' + esc(m.headline) + "</div>" : "") +
        '<div class="meta"><span class="dot ' + f + '"></span><span>' + esc(ago(m.updated)) + "</span>" +
        (m.report ? "<span>Report</span>" : m.count != null ? "<span>" + esc(m.count) + (m.count === 1 ? " row" : " rows") + "</span>" : "") +
        "</div></a>";
    });
    html += "</div>";
    html += '<p class="foot">Green: updated in the last day. Yellow: this week. Gray: older.</p>';
    view.innerHTML = html;
  }

  function renderRow(r) {
    if (r === null || typeof r !== "object") {
      return '<div class="item"><b>' + esc(fmt("", r)) + "</b></div>";
    }
    var tk = findKey(r, TITLE_KEYS);
    var pk = findKey(r, PICK_KEYS);
    var ek = findKey(r, EDGE_KEYS);
    var nk = findKey(r, NOTE_KEYS);
    var rk = findKey(r, RESULT_KEYS);
    if (!tk) {
      var keys = Object.keys(r);
      for (var i = 0; i < keys.length; i++) if (typeof r[keys[i]] === "string" && keys[i] !== pk && keys[i] !== nk) { tk = keys[i]; break; }
    }
    var used = {};
    [tk, pk, ek, nk].forEach(function (k) { if (k) used[k] = 1; });
    var h = '<div class="item"><div class="t"><b>' + esc(tk ? fmt(tk, r[tk]) : "") + "</b>";
    if (ek && r[ek] !== "" && r[ek] != null) h += '<span class="edge ' + signClass(r[ek]) + '">' + esc(label(ek)) + " " + esc(fmt(ek, r[ek])) + "</span>";
    h += "</div>";
    if (pk && r[pk] !== "" && r[pk] != null) h += '<div class="pick">' + esc(fmt(pk, r[pk])) + "</div>";
    var chips = "";
    Object.keys(r).forEach(function (k) {
      if (used[k]) return;
      var v = fmt(k, r[k]);
      if (v === "") return;
      var cls = k === rk ? " " + resultClass(r[k]) : "";
      chips += '<span class="chip' + cls + '"><i>' + esc(label(k)) + "</i>" + esc(v) + "</span>";
    });
    if (chips) h += '<div class="chips">' + chips + "</div>";
    if (nk && r[nk]) h += '<div class="note">' + esc(r[nk]) + "</div>";
    return h + "</div>";
  }

  function renderModel(id) {
    backBtn.classList.remove("hide");
    var m = state.models[id];
    var meta = ((state.index && state.index.models) || []).filter(function (x) { return x.id === id; })[0] || {};
    titleEl.textContent = (m && m.name) || meta.name || id;
    document.title = titleEl.textContent + " · Model Hub";
    if (!m) { view.innerHTML = '<p class="empty">Loading…</p>'; return; }

    var html = '<p class="sub">' + esc(m.sport ? m.sport + " · " : "") + "Updated " + esc(ago(m.updated)) +
      (when(m.updated) ? " (" + esc(when(m.updated)) + ")" : "") +
      (m.demo ? ' <span class="badge demo">Sample data</span>' : "") + "</p>";
    if (m.headline) html += '<p style="margin:6px 0 0;color:var(--text-2)">' + esc(m.headline) + "</p>";
    if (m.stats && m.stats.length) {
      html += '<div class="stats">';
      m.stats.forEach(function (s) {
        html += '<div class="stat"><div class="l">' + esc(s.label) + '</div><div class="v ' + (s.tone === "pos" ? "pos" : s.tone === "neg" ? "neg" : "") + '">' + esc(fmt(s.label, s.value)) + "</div></div>";
      });
      html += "</div>";
    }
    var reps = Array.isArray(m.reports) ? m.reports : [];
    if (reps.length) {
      var pick = Math.min(state.reportIdx || 0, reps.length - 1);
      var cur = reps[pick];
      html += '<div class="repbar">';
      if (reps.length > 1) {
        html += '<select id="repsel" class="repsel" aria-label="Pick a report">';
        reps.forEach(function (r, i) {
          html += '<option value="' + i + '"' + (i === pick ? " selected" : "") + ">" +
            esc((i === 0 ? "Latest · " : "") + (when(r.updated) || r.file)) + "</option>";
        });
        html += "</select>";
      }
      html += '<a class="iconbtn" href="' + esc(cur.file) + '" target="_blank" rel="noopener">Full screen</a></div>';
      html += '<iframe class="report" title="' + esc(cur.title || "Report") + '" src="' + esc(cur.file) +
        '" sandbox="allow-scripts allow-popups allow-forms allow-popups-to-escape-sandbox"></iframe>';
    }
    var rows = Array.isArray(m.rows) ? m.rows : [];
    if (rows.length > 6) html += '<input class="search" id="q" type="search" placeholder="Filter ' + rows.length + ' rows" value="' + esc(state.filter) + '">';
    if (rows.length || !reps.length) html += '<div class="list" id="rows"></div>';
    view.innerHTML = html;
    drawRows(rows);
    var sel = document.getElementById("repsel");
    if (sel) sel.addEventListener("change", function () { state.reportIdx = +sel.value; renderModel(id); });
    var q = document.getElementById("q");
    if (q) q.addEventListener("input", function () { state.filter = q.value; drawRows(rows); });
  }

  function drawRows(rows) {
    var box = document.getElementById("rows");
    if (!box) return;
    var f = lc(state.filter.trim());
    var shown = f ? rows.filter(function (r) { return lc(JSON.stringify(r)).indexOf(f) !== -1; }) : rows;
    box.innerHTML = shown.length ? shown.map(renderRow).join("") : '<p class="empty">Nothing to show.</p>';
  }

  function showError(e, offline) {
    var div = document.createElement("div");
    div.className = "err";
    div.textContent = offline ? "Couldn't reach the site, so this is what was saved last time." : "Couldn't load results: " + (e && e.message ? e.message : e);
    view.insertBefore(div, view.firstChild);
  }

  // ---------- routing ----------
  function route() {
    var h = location.hash || "";
    var m = h.match(/^#\/m\/(.+)$/);
    if (m) {
      var id = decodeURIComponent(m[1]);
      renderModel(id);
      loadModel(id);
    } else {
      state.filter = "";
      state.reportIdx = 0;
      renderHome();
    }
    window.scrollTo(0, 0);
  }

  function loadIndex() {
    return getJSON("data/index.json").then(function (idx) {
      state.index = idx;
      try { localStorage.setItem("mh:index", JSON.stringify(idx)); } catch (e) {}
    });
  }
  function loadModel(id) {
    var meta = ((state.index && state.index.models) || []).filter(function (x) { return x.id === id; })[0];
    var file = (meta && meta.file) || (id + ".json");
    return getJSON("data/" + file).then(function (m) {
      state.models[id] = m;
      try { localStorage.setItem("mh:m:" + id, JSON.stringify(m)); } catch (e) {}
      if ((location.hash || "") === "#/m/" + encodeURIComponent(id)) renderModel(id);
    }).catch(function (e) {
      var saved = null;
      try { saved = JSON.parse(localStorage.getItem("mh:m:" + id) || "null"); } catch (x) {}
      if (saved) { state.models[id] = saved; renderModel(id); showError(e, true); }
      else { view.innerHTML = ""; showError(e, false); }
    });
  }

  function refresh() {
    refreshBtn.classList.add("spin");
    var p = loadIndex().then(function () {
      var h = (location.hash || "").match(/^#\/m\/(.+)$/);
      if (h) return loadModel(decodeURIComponent(h[1]));
      renderHome();
    }).catch(function (e) {
      try {
        var saved = JSON.parse(localStorage.getItem("mh:index") || "null");
        if (saved && !state.index) state.index = saved;
      } catch (x) {}
      route();
      showError(e, !!state.index);
    });
    p.then(function () { refreshBtn.classList.remove("spin"); });
    return p;
  }

  backBtn.addEventListener("click", function () {
    if (history.length > 1) history.back(); else location.hash = "";
  });
  refreshBtn.addEventListener("click", refresh);
  window.addEventListener("hashchange", route);
  // Refresh when you come back to the app after it sat in the background.
  document.addEventListener("visibilitychange", function () { if (!document.hidden) refresh(); });

  try {
    var cached = JSON.parse(localStorage.getItem("mh:index") || "null");
    if (cached) state.index = cached;
  } catch (e) {}
  route();
  refresh();

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("sw.js").catch(function () {});
  }
})();
