/* InstructionRoot Resolve — static dashboard (P028 T009).
 *
 * Local only: the only network call this page makes is a fetch of a
 * relative receipt file (receipt.json by default) from the same server
 * that served this page. No CDN, fonts, analytics, or other requests.
 *
 * Single source of truth: the source tree, the effective chain, and
 * the import graph are all rendered from the same receipt object —
 * receipt.sources (in discovery order) and receipt.edges. There is no
 * second hand-written copy of the source list anywhere in this file.
 * Selecting a source in any of the three views highlights the same
 * source_id in the other two and fills the Why panel.
 */
(function () {
  "use strict";

  var DEFAULT_RECEIPT = "receipt.json";

  /* Trust values that block under the default policy (block_symlink_escape,
   * block_import_escape, block_outside_repo, block_missing_reference).
   * GIT_UNTRACKED / GIT_MODIFIED do not block by default. The receipt's
   * own verdict remains authoritative; this set only decides which
   * individual sources get the BLOCK visual treatment. */
  var BLOCKING_TRUST = {
    SYMLINK_ESCAPE: true,
    IMPORT_ESCAPE: true,
    OUTSIDE_REPO: true,
    MISSING: true
  };

  var currentReceipt = null;
  var currentFileName = DEFAULT_RECEIPT;
  var selectedId = null;

  function el(id) { return document.getElementById(id); }

  function clear(node) { node.textContent = ""; }

  function make(tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text !== undefined && text !== null) { node.textContent = text; }
    return node;
  }

  function isBlockingSource(source) {
    return !!BLOCKING_TRUST[source.trust];
  }

  function sourceById(receipt, id) {
    var i;
    for (i = 0; i < receipt.sources.length; i++) {
      if (receipt.sources[i].source_id === id) { return receipt.sources[i]; }
    }
    return null;
  }

  /* Display-only redaction: show the home directory as <HOME>.
   * The receipt itself (and its hash) always uses the real path. */
  function displayPath(receipt, path) {
    if (!path) { return "(missing path)"; }
    var home = receipt.workspace && receipt.workspace.home;
    if (home && path.indexOf(home) === 0) {
      return "<HOME>" + path.slice(home.length);
    }
    return path;
  }

  function shortSha(sha) {
    if (!sha) { return "— (missing file: no hash)"; }
    return sha.slice(0, 12) + "…";
  }

  function gitSummary(source) {
    var git = source.git || {};
    if (!git.repo) { return "no repo"; }
    var parts = [];
    parts.push(git.tracked ? "tracked" : "untracked");
    if (git.modified) { parts.push("modified"); }
    if (git.head_commit) { parts.push("HEAD " + git.head_commit.slice(0, 7)); }
    return parts.join(" · ");
  }

  function groupOf(receipt, source) {
    if (source.scope === "user") { return "HOME"; }
    var repo = receipt.workspace && receipt.workspace.repo_root;
    var path = source.resolved_path || source.canonical_path || "";
    if (repo && path.indexOf(repo) === 0) { return "REPO"; }
    return "OUTSIDE";
  }

  function markSelected(id) {
    selectedId = id;
    var nodes = document.querySelectorAll("[data-source-id]");
    var i;
    for (i = 0; i < nodes.length; i++) {
      if (nodes[i].getAttribute("data-source-id") === id) {
        nodes[i].classList.add("selected");
      } else {
        nodes[i].classList.remove("selected");
      }
    }
    renderWhy(currentReceipt, sourceById(currentReceipt, id));
  }

  function selectHandler(id) {
    return function () { markSelected(id); };
  }

  /* (1) Verdict header + BLOCK banner */
  function renderVerdict(receipt) {
    var header = el("verdict-header");
    header.className = "verdict-header verdict-" + receipt.verdict;
    el("verdict-value").textContent = receipt.verdict;
    var blocked = receipt.sources.filter(isBlockingSource);
    var counts = "sources=" + receipt.sources.length +
      " blocked=" + blocked.length +
      " edges=" + receipt.edges.length;
    el("verdict-meta").textContent =
      (receipt.profile ? receipt.profile.id + " (" + receipt.profile.version + ")" : "") +
      " · " + counts;
    var banner = el("block-banner");
    if (receipt.verdict === "BLOCK" && blocked.length > 0) {
      banner.hidden = false;
      el("block-banner-text").textContent = blocked.map(function (s) {
        return s.source_id + " " + displayPath(receipt, s.canonical_path) +
          " (" + s.trust + ")";
      }).join("; ");
    } else {
      banner.hidden = true;
      el("block-banner-text").textContent = "";
    }
  }

  /* (4) Trust badges: one badge per trust value present, with counts. */
  function renderBadges(receipt) {
    var box = el("trust-badges");
    clear(box);
    var counts = {};
    receipt.sources.forEach(function (s) {
      counts[s.trust] = (counts[s.trust] || 0) + 1;
    });
    var keys = Object.keys(counts).sort();
    if (keys.length === 0) {
      box.appendChild(make("span", "badge", "no sources"));
      return;
    }
    keys.forEach(function (trust) {
      var badge = make("span", "badge" + (BLOCKING_TRUST[trust] ? " blocking" : ""),
        trust + " × " + counts[trust]);
      box.appendChild(badge);
    });
  }

  /* (2) Source tree, grouped HOME / REPO / OUTSIDE (PROJECT_BOOK §10.1).
   * Built from receipt.sources — the same array as the chain and graph. */
  function renderTree(receipt) {
    var box = el("source-tree");
    clear(box);
    var groups = { HOME: [], REPO: [], OUTSIDE: [] };
    receipt.sources.forEach(function (s) { groups[groupOf(receipt, s)].push(s); });
    var root = make("ul", null);
    ["HOME", "REPO", "OUTSIDE"].forEach(function (name) {
      if (groups[name].length === 0) { return; }
      var groupLi = make("li", null);
      groupLi.appendChild(make("span", "tree-group", name + " (" + groups[name].length + ")"));
      var list = make("ul", null);
      groups[name].forEach(function (s) {
        var item = make("li", null);
        var label = make("span", "tree-item" + (isBlockingSource(s) ? " blocked" : ""));
        label.setAttribute("data-source-id", s.source_id);
        label.appendChild(make("span", null, displayPath(receipt, s.canonical_path)));
        label.appendChild(make("span", "trust", " " + s.trust));
        if (isBlockingSource(s)) {
          label.appendChild(make("span", "block-tag", "BLOCK"));
        }
        label.addEventListener("click", selectHandler(s.source_id));
        item.appendChild(label);
        list.appendChild(item);
      });
      groupLi.appendChild(list);
      root.appendChild(groupLi);
    });
    if (receipt.sources.length === 0) {
      root.appendChild(make("li", null, "No sources discovered."));
    }
    box.appendChild(root);
  }

  /* (3) Effective chain: one card per source, in discovery order.
   * Built from receipt.sources — the same array as the tree and graph. */
  function renderChain(receipt) {
    var list = el("effective-chain");
    clear(list);
    receipt.sources.forEach(function (s, index) {
      var card = make("li", "chain-card" + (isBlockingSource(s) ? " blocked" : ""));
      card.setAttribute("data-source-id", s.source_id);
      card.addEventListener("click", selectHandler(s.source_id));
      var head = make("div", "path", (index + 1) + ". " + displayPath(receipt, s.canonical_path));
      card.appendChild(head);
      if (isBlockingSource(s)) {
        card.appendChild(make("span", "block-tag", "BLOCK · " + s.trust));
      }
      var dl = make("dl", null);
      var rows = [
        ["source_id", s.source_id],
        ["scope", s.scope],
        ["phase", s.phase],
        ["discovery rule", s.discovery_rule],
        ["precedence", s.precedence ? s.precedence.kind : "—"],
        ["trust", s.trust],
        ["git", gitSummary(s)],
        ["sha256", s.sha256 || "—"]
      ];
      if (s.is_symlink) { rows.push(["symlink target", s.symlink_target || "—"]); }
      if (s.resolved_path && s.resolved_path !== s.canonical_path) {
        rows.push(["resolved to", displayPath(receipt, s.resolved_path)]);
      }
      rows.forEach(function (row) {
        dl.appendChild(make("dt", null, row[0]));
        dl.appendChild(make("dd", null, row[1]));
      });
      card.appendChild(dl);
      list.appendChild(card);
    });
    if (receipt.sources.length === 0) {
      list.appendChild(make("li", null, "No sources discovered."));
    }
  }

  /* (5) Import graph: chain nodes in order, then import edges.
   * Nodes come from receipt.sources and edges from receipt.edges —
   * the same arrays as the tree and chain, so the graph and the list
   * cannot disagree. An edge whose target is not a source (to === null)
   * is shown by its resolved target path instead. */
  function renderGraph(receipt) {
    var box = el("import-graph");
    clear(box);
    receipt.sources.forEach(function (s, index) {
      if (index > 0) {
        box.appendChild(make("div", "graph-arrow", "│\n▼"));
      }
      var node = make("div", "graph-node" + (isBlockingSource(s) ? " blocked" : ""));
      node.setAttribute("data-source-id", s.source_id);
      node.addEventListener("click", selectHandler(s.source_id));
      node.appendChild(make("span", null,
        s.source_id + " — " + displayPath(receipt, s.canonical_path)));
      node.appendChild(make("span", "trust", " " + s.trust));
      if (isBlockingSource(s)) {
        node.appendChild(make("span", "block-tag", "BLOCK"));
      }
      box.appendChild(node);
    });
    if (receipt.sources.length === 0) {
      box.appendChild(make("p", "empty-note", "No sources, so no graph."));
    }
    if (receipt.edges.length === 0) {
      box.appendChild(make("p", "empty-note",
        "No import edges in this receipt (0 edges). The chain above is the whole graph."));
    }
    receipt.edges.forEach(function (edge) {
      var target = edge.to ? sourceById(receipt, edge.to) : null;
      var targetText = target
        ? target.source_id + " — " + displayPath(receipt, target.canonical_path)
        : (edge.resolved_target ? displayPath(receipt, edge.resolved_target) : "(unresolved target)");
      var from = sourceById(receipt, edge.from);
      var row = make("div", "graph-edge" + (edge.allowed ? "" : " blocked-edge"));
      row.appendChild(make("span", null,
        (from ? from.source_id : edge.from) + "  — " + edge.syntax + " →  " + targetText +
        "  · " + (edge.allowed ? "allowed" : "NOT ALLOWED") + " · " + edge.reason));
      if (!edge.allowed) {
        row.appendChild(make("span", "block-tag", "BLOCK"));
      }
      box.appendChild(row);
    });
  }

  /* (6) Why panel: why discovered / why this trust / why blocked,
   * derived only from the selected source's own receipt fields. */
  function renderWhy(receipt, source) {
    var panel = el("why-panel");
    clear(panel);
    if (!source) {
      panel.appendChild(make("p", null,
        "Select a source in the tree, chain, or graph to see why it was discovered, why it has its trust value, and why it blocks (if it does)."));
      return;
    }
    panel.appendChild(make("h3", null, source.source_id + " — " + displayPath(receipt, source.canonical_path)));
    if (isBlockingSource(source)) {
      panel.appendChild(make("span", "block-tag", "BLOCK · " + source.trust));
    }
    panel.appendChild(make("h4", null, "Why discovered"));
    panel.appendChild(make("p", null,
      "Harness rule " + source.discovery_rule + " found this file in scope " +
      source.scope + " during the " + source.phase + " phase."));
    if (source.precedence) {
      panel.appendChild(make("p", null,
        "Precedence: " + source.precedence.kind +
        (source.precedence.detail ? " — " + source.precedence.detail : "") +
        (source.precedence.relative_to && source.precedence.relative_to.length
          ? " (relative to " + source.precedence.relative_to.join(", ") + ")"
          : "")));
    }
    panel.appendChild(make("h4", null, "Why this trust value"));
    var trustText = "Trust " + source.trust + ". " + gitSummary(source) + ".";
    if (source.is_symlink) {
      trustText += " Reached through a symlink (" + (source.symlink_target || "?") + ");" +
        " resolved path " + displayPath(receipt, source.resolved_path) +
        (source.resolved_path !== source.canonical_path
          ? " differs from the canonical path, so it escapes the repository."
          : " equals the canonical path.");
    } else if (source.resolved_path && source.resolved_path !== source.canonical_path) {
      trustText += " Resolved path differs from the canonical path: " +
        displayPath(receipt, source.resolved_path) + ".";
    }
    if (!source.sha256) {
      trustText += " The file is missing, so there is no content hash.";
    }
    panel.appendChild(make("p", null, trustText));
    panel.appendChild(make("h4", null, "Why blocked"));
    if (isBlockingSource(source)) {
      panel.appendChild(make("p", null,
        "Blocked because trust is " + source.trust +
        " and the default policy blocks that trust value. The receipt verdict is " +
        receipt.verdict + "."));
    } else {
      panel.appendChild(make("p", null,
        "Not blocked: trust " + source.trust +
        " does not block under the default policy. The receipt verdict is " +
        receipt.verdict + "."));
    }
    var related = receipt.edges.filter(function (e) {
      return e.from === source.source_id || e.to === source.source_id;
    });
    panel.appendChild(make("h4", null, "Import edges"));
    if (related.length === 0) {
      panel.appendChild(make("p", null, "No import edges touch this source."));
    }
    related.forEach(function (e) {
      panel.appendChild(make("p", null,
        e.edge_id + ": " + e.from + " — " + e.syntax + " → " + (e.to || "(no source)") +
        " · " + (e.allowed ? "allowed" : "NOT ALLOWED") + " · " + e.reason));
    });
    panel.appendChild(make("h4", null, "Content hash"));
    panel.appendChild(make("p", null, "SHA-256: " + (source.sha256 || "— (missing file)")));
  }

  /* (7) Raw JSON */
  function renderRaw(receipt) {
    el("raw-json").textContent = JSON.stringify(receipt, null, 2);
    el("receipt-meta").textContent =
      "Receipt: " + currentFileName +
      " · receipt_version " + receipt.receipt_version +
      " · receipt_hash " + (receipt.receipt_hash || "—") +
      " · CWD " + (receipt.workspace ? receipt.workspace.cwd : "—");
  }

  function renderAll(receipt) {
    currentReceipt = receipt;
    if (selectedId && !sourceById(receipt, selectedId)) { selectedId = null; }
    renderVerdict(receipt);
    renderBadges(receipt);
    renderTree(receipt);
    renderChain(receipt);
    renderGraph(receipt);
    renderWhy(receipt, selectedId ? sourceById(receipt, selectedId) : null);
    renderRaw(receipt);
    ["load-pass", "load-block", "load-default"].forEach(function (id) {
      var button = el(id);
      if (button) {
        button.setAttribute("aria-pressed",
          button.getAttribute("data-receipt") === currentFileName ? "true" : "false");
      }
    });
  }

  function showError(message) {
    el("verdict-value").textContent = "ERROR";
    el("verdict-meta").textContent = message;
    el("block-banner").hidden = true;
    renderWhy(currentReceipt || { sources: [], edges: [], verdict: "ERROR" }, null);
    el("why-panel").textContent = message +
      " Serve this folder over a local server (for example: python -m http.server 8765 --directory web) " +
      "and open the page through that server; opening index.html directly from disk blocks the local receipt fetch in most browsers.";
  }

  function loadReceipt(fileName) {
    currentFileName = fileName;
    return fetch(fileName).then(function (response) {
      if (!response.ok) { throw new Error("receipt fetch failed: " + response.status); }
      return response.json();
    }).then(function (receipt) {
      selectedId = null;
      renderAll(receipt);
    }).catch(function (err) {
      showError(String(err && err.message ? err.message : err));
    });
  }

  /* (8) Export button: downloads the currently displayed receipt as JSON. */
  function exportReceipt() {
    if (!currentReceipt) { return; }
    var blob = new Blob(
      [JSON.stringify(currentReceipt, null, 2) + "\n"],
      { type: "application/json" });
    var url = URL.createObjectURL(blob);
    var link = document.createElement("a");
    link.href = url;
    link.download = "receipt-" + currentReceipt.verdict.toLowerCase() + ".json";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }

  function requestedReceipt() {
    var match = window.location.search.match(/[?&]receipt=([^&]+)/);
    if (!match) { return DEFAULT_RECEIPT; }
    var name = decodeURIComponent(match[1]);
    /* Only a plain file name in this folder; never a path or another host. */
    if (!/^[A-Za-z0-9._-]+\.json$/.test(name)) { return DEFAULT_RECEIPT; }
    return name;
  }

  function init() {
    ["load-pass", "load-block", "load-default"].forEach(function (id) {
      var button = el(id);
      if (button) {
        button.addEventListener("click", function () {
          loadReceipt(button.getAttribute("data-receipt"));
        });
      }
    });
    var exportButton = el("export-button");
    if (exportButton) { exportButton.addEventListener("click", exportReceipt); }
    var fileInput = el("receipt-file");
    if (fileInput) {
      fileInput.addEventListener("change", function () {
        var file = fileInput.files && fileInput.files[0];
        if (!file) { return; }
        var reader = new FileReader();
        reader.onload = function () {
          try {
            currentFileName = file.name;
            selectedId = null;
            renderAll(JSON.parse(reader.result));
          } catch (err) {
            showError("Could not parse " + file.name + " as a receipt JSON file.");
          }
        };
        reader.readAsText(file);
      });
    }
    loadReceipt(requestedReceipt());
  }

  /* Exposed for the headless verification check (see TASK_RESULT.md):
   * renderAll / isBlockingSource are pure render/classify functions. */
  window.__instructionroot = {
    renderAll: renderAll,
    isBlockingSource: isBlockingSource,
    displayPath: displayPath
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
