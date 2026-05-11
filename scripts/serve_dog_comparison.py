#!/usr/bin/env python3
"""
serve_dog_comparison.py

Side-by-side DOG comparison UI. Serves a two-column review interface for
one (job_title × SOC DOG) comparison JSON produced by build_dog_comparison.py.

Usage:
    python scripts/serve_dog_comparison.py --file annotations/dog_comparison_15-1212_security-analyst.json
    python scripts/serve_dog_comparison.py --file annotations/dog_comparison_15-1212_security-analyst.json --port 8775
"""

import argparse
import json
import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from datetime import datetime, timezone

REPO_ROOT = Path(__file__).resolve().parent.parent

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DOG Comparison</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #0f1117; color: #e0e0e0; height: 100vh; display: flex;
         flex-direction: column; overflow: hidden; }

  /* ── header ── */
  #header { background: #1a1d27; border-bottom: 1px solid #2a2d3a;
             padding: 10px 18px; display: flex; align-items: center; gap: 14px;
             flex-shrink: 0; flex-wrap: wrap; }
  #header h1 { font-size: 15px; font-weight: 600; color: #a78bfa; white-space: nowrap; }
  #posting-select { background: #252836; border: 1px solid #3a3d4a; color: #e0e0e0;
                    padding: 5px 10px; border-radius: 6px; font-size: 13px; flex: 1;
                    min-width: 200px; max-width: 420px; }
  #meta-line { font-size: 12px; color: #888; white-space: nowrap; }
  #progress-line { font-size: 12px; color: #a78bfa; white-space: nowrap; }

  /* ── columns ── */
  #columns { display: flex; flex: 1; overflow: hidden; }

  /* ── left ── */
  #left { width: 56%; border-right: 1px solid #2a2d3a; overflow-y: auto; padding: 12px; }
  #left-header { font-size: 12px; color: #888; text-transform: uppercase;
                 letter-spacing: .08em; margin-bottom: 10px; padding-left: 2px; }

  .snippet-card { background: #1a1d27; border: 1px solid #2a2d3a; border-radius: 8px;
                  margin-bottom: 10px; padding: 12px 14px; cursor: pointer;
                  transition: border-color .15s; }
  .snippet-card:hover { border-color: #4a4d6a; }
  .snippet-card.selected { border-color: #a78bfa; background: #1e1a2e; }
  .snippet-card.annotated-task    { border-left: 3px solid #34d399; }
  .snippet-card.annotated-req     { border-left: 3px solid #fbbf24; }
  .snippet-card.annotated-missing { border-left: 3px solid #f87171; }

  .snippet-top { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
  .cat-badge { font-size: 10px; font-weight: 600; padding: 2px 7px; border-radius: 4px;
               text-transform: uppercase; letter-spacing: .06em; }
  .cat-overview     { background: #1e3a5f; color: #60a5fa; }
  .cat-role         { background: #1e3d2f; color: #34d399; }
  .cat-requirement  { background: #3d2e1a; color: #fbbf24; }
  .cat-other        { background: #2a2d3a; color: #9ca3af; }

  .snippet-text { font-size: 13px; line-height: 1.55; color: #d0d0d0; }

  .rank-badges { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
  .rank-badge { font-size: 10px; padding: 2px 8px; border-radius: 12px; cursor: pointer;
                border: 1px solid transparent; transition: border-color .12s; }
  .rank-badge:hover { border-color: #a78bfa; }
  .rank-1 { background: #2d1f5e; color: #c4b5fd; }
  .rank-2 { background: #1e2a3a; color: #93c5fd; }
  .rank-3 { background: #1e3020; color: #6ee7b7; }

  /* ── action bar ── */
  #action-bar { border-top: 1px solid #2a2d3a; padding: 10px 14px;
                display: flex; gap: 8px; align-items: center; flex-shrink: 0;
                background: #13151f; }
  #action-bar .label { font-size: 12px; color: #888; margin-right: 4px; }
  .action-btn { padding: 6px 14px; border-radius: 6px; border: 1px solid transparent;
                font-size: 12px; font-weight: 600; cursor: pointer; transition: opacity .15s; }
  .action-btn:disabled { opacity: .35; cursor: default; }
  .btn-task    { background: #1e3d2f; color: #34d399; border-color: #2d5a3d; }
  .btn-task:hover:not(:disabled) { background: #245040; }
  .btn-req     { background: #3d2e1a; color: #fbbf24; border-color: #5a4020; }
  .btn-req:hover:not(:disabled) { background: #4a3820; }
  .btn-missing { background: #3d1f1f; color: #f87171; border-color: #5a2d2d; }
  .btn-missing:hover:not(:disabled) { background: #4a2424; }
  #selected-task-label { font-size: 11px; color: #a78bfa; flex: 1;
                         overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  /* ── right ── */
  #right { flex: 1; overflow-y: auto; padding: 12px; }
  #right-header { font-size: 12px; color: #888; text-transform: uppercase;
                  letter-spacing: .08em; margin-bottom: 10px; padding-left: 2px; }

  .task-card { background: #1a1d27; border: 1px solid #2a2d3a; border-radius: 8px;
               margin-bottom: 8px; padding: 10px 12px; cursor: pointer;
               transition: border-color .15s; }
  .task-card:hover { border-color: #4a4d6a; }
  .task-card.highlighted { border-color: #a78bfa; background: #1e1a2e; }
  .task-card.selected-match { border-left: 3px solid #34d399; }

  .task-id { font-size: 10px; color: #666; font-family: monospace; margin-bottom: 3px; }
  .task-text { font-size: 12px; line-height: 1.5; color: #d0d0d0; }

  /* ── toast ── */
  #toast { position: fixed; bottom: 24px; right: 24px; background: #252836;
           border: 1px solid #3a3d4a; border-radius: 8px; padding: 10px 16px;
           font-size: 13px; opacity: 0; transition: opacity .2s;
           pointer-events: none; z-index: 100; }
  #toast.show { opacity: 1; }
</style>
</head>
<body>

<div id="header">
  <h1>DOG Comparison</h1>
  <select id="posting-select"></select>
  <span id="meta-line"></span>
  <span id="progress-line"></span>
</div>

<div id="columns">
  <div id="left">
    <div id="left-header">Snippets</div>
    <div id="snippets-container"></div>
  </div>
  <div id="right">
    <div id="right-header">Tasks in DOG</div>
    <div id="tasks-container"></div>
  </div>
</div>

<div id="action-bar">
  <span class="label">Mark as:</span>
  <button class="action-btn btn-task"    id="btn-task"    disabled>Matched Task</button>
  <button class="action-btn btn-req"     id="btn-req"     disabled>Requirement</button>
  <button class="action-btn btn-missing" id="btn-missing" disabled>Missing from DOG</button>
  <span id="selected-task-label">← select a snippet</span>
</div>

<div id="toast" id="toast"></div>

<script>
let DATA = null;
let currentPostingKey = null;
let selectedSnippetId = null;
let selectedTaskId = null;
let annotations = {};  // snippetId -> {decision, task_id, rank}

async function init() {
  const resp = await fetch('/api/data');
  DATA = await resp.json();

  // load existing annotations
  const aResp = await fetch('/api/annotations');
  const saved = await aResp.json();
  for (const a of saved) annotations[a.snippet_id] = a;

  buildPostingSelect();
  const firstKey = Object.keys(DATA.postings)[0];
  loadPosting(firstKey);
}

function buildPostingSelect() {
  const sel = document.getElementById('posting-select');
  sel.innerHTML = '';
  for (const [key, p] of Object.entries(DATA.postings)) {
    const opt = document.createElement('option');
    opt.value = key;
    opt.textContent = `${p.title} — ${p.company} (${p.snippet_count} snippets)`;
    sel.appendChild(opt);
  }
  sel.addEventListener('change', () => loadPosting(sel.value));

  const m = DATA.meta;
  document.getElementById('meta-line').textContent =
    `SOC ${m.soc_2018_code} · ${m.task_count} tasks`;
}

function loadPosting(key) {
  currentPostingKey = key;
  document.getElementById('posting-select').value = key;
  selectedSnippetId = null;
  selectedTaskId = null;
  renderSnippets();
  renderTasks();
  updateActionBar();
  updateProgress();
}

function updateProgress() {
  const posting = DATA.postings[currentPostingKey];
  const total = posting.snippets.length;
  const done = posting.snippets.filter(s => annotations[s.id]).length;
  document.getElementById('progress-line').textContent = `${done}/${total} annotated`;
}

function catClass(cat) {
  if (!cat) return 'cat-other';
  const c = cat.toLowerCase();
  if (c === 'overview') return 'cat-overview';
  if (c === 'role') return 'cat-role';
  if (c.startsWith('req')) return 'cat-requirement';
  return 'cat-other';
}

function renderSnippets() {
  const posting = DATA.postings[currentPostingKey];
  const container = document.getElementById('snippets-container');
  container.innerHTML = '';

  for (const s of posting.snippets) {
    const ann = annotations[s.id];
    const card = document.createElement('div');
    card.className = 'snippet-card' +
      (s.id === selectedSnippetId ? ' selected' : '') +
      (ann ? ` annotated-${ann.decision === 'task' ? 'task' : ann.decision === 'requirement' ? 'req' : 'missing'}` : '');
    card.dataset.id = s.id;

    const top3 = s.task_scores.slice(0, 3);
    const badgesHtml = top3.map((ts, i) => {
      const t = DATA.tasks.find(t => t.task_id === ts.task_id);
      const label = t ? t.task.slice(0, 50) + (t.task.length > 50 ? '…' : '') : ts.task_id;
      return `<span class="rank-badge rank-${i+1}" data-task-id="${ts.task_id}"
                    title="${t ? t.task : ''}" onclick="selectTask('${ts.task_id}', event)">
                #${i+1} ${ts.score.toFixed(3)}
              </span>`;
    }).join('');

    card.innerHTML = `
      <div class="snippet-top">
        <span class="cat-badge ${catClass(s.category)}">${s.category || 'other'}</span>
        ${ann ? `<span style="font-size:10px;color:#888">${ann.decision === 'task' ? '✓ task' : ann.decision === 'requirement' ? '⚠ req' : '✗ missing'}</span>` : ''}
      </div>
      <div class="snippet-text">${escHtml(s.text)}</div>
      <div class="rank-badges">${badgesHtml}</div>
    `;

    card.addEventListener('click', (e) => {
      if (e.target.classList.contains('rank-badge')) return;
      selectSnippet(s.id);
    });

    container.appendChild(card);
  }

  document.getElementById('left-header').textContent =
    `Snippets — ${posting.title} @ ${posting.company}`;
}

function renderTasks() {
  const container = document.getElementById('tasks-container');
  container.innerHTML = '';
  for (const t of DATA.tasks) {
    const card = document.createElement('div');
    card.className = 'task-card';
    card.dataset.taskId = t.task_id;
    card.innerHTML = `<div class="task-id">${t.task_id}</div>
                      <div class="task-text">${escHtml(t.task)}</div>`;
    card.addEventListener('click', () => selectTask(t.task_id));
    container.appendChild(card);
  }
  document.getElementById('right-header').textContent =
    `Tasks in DOG ${DATA.meta.soc_2018_code} (${DATA.tasks.length})`;
}

function selectSnippet(snippetId) {
  selectedSnippetId = snippetId;

  // update card highlights
  document.querySelectorAll('.snippet-card').forEach(c => {
    c.classList.toggle('selected', c.dataset.id === snippetId);
  });

  // auto-select rank-1 task for this snippet
  const posting = DATA.postings[currentPostingKey];
  const snippet = posting.snippets.find(s => s.id === snippetId);
  if (snippet && snippet.task_scores.length > 0) {
    const rank1TaskId = snippet.task_scores[0].task_id;
    // if already annotated with a task, use that
    const ann = annotations[snippetId];
    const taskToSelect = (ann && ann.decision === 'task' && ann.task_id) ? ann.task_id : rank1TaskId;
    selectTask(taskToSelect, null, false);
  }

  updateActionBar();
}

function selectTask(taskId, event, scrollToTask = true) {
  if (event) event.stopPropagation();
  selectedTaskId = taskId;

  document.querySelectorAll('.task-card').forEach(c => {
    c.classList.toggle('highlighted', c.dataset.taskId === taskId);
    c.classList.remove('selected-match');
  });

  if (scrollToTask) {
    const taskCard = document.querySelector(`.task-card[data-task-id="${taskId}"]`);
    if (taskCard) taskCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  updateActionBar();
}

function updateActionBar() {
  const hasSnippet = !!selectedSnippetId;
  document.getElementById('btn-task').disabled = !hasSnippet;
  document.getElementById('btn-req').disabled = !hasSnippet;
  document.getElementById('btn-missing').disabled = !hasSnippet;

  if (selectedTaskId && hasSnippet) {
    const t = DATA.tasks.find(t => t.task_id === selectedTaskId);
    document.getElementById('selected-task-label').textContent =
      t ? `→ ${t.task.slice(0, 100)}` : selectedTaskId;
  } else if (hasSnippet) {
    document.getElementById('selected-task-label').textContent = '(no task selected)';
  } else {
    document.getElementById('selected-task-label').textContent = '← select a snippet';
  }
}

async function saveAnnotation(decision) {
  if (!selectedSnippetId) return;
  const posting = DATA.postings[currentPostingKey];
  const snippet = posting.snippets.find(s => s.id === selectedSnippetId);
  const rank = decision === 'task' && selectedTaskId
    ? (snippet.task_scores.findIndex(ts => ts.task_id === selectedTaskId) + 1) || null
    : null;

  const record = {
    snippet_id: selectedSnippetId,
    job_key: currentPostingKey,
    comparison_file: DATA.meta.soc_2018_code,
    decision,
    task_id: decision === 'task' ? selectedTaskId : null,
    rank_at_decision: rank,
    updated_at: new Date().toISOString(),
  };

  annotations[selectedSnippetId] = record;

  await fetch('/api/annotate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(record),
  });

  // advance to next unannotated snippet
  const snippets = posting.snippets;
  const idx = snippets.findIndex(s => s.id === selectedSnippetId);
  const next = snippets.slice(idx + 1).find(s => !annotations[s.id])
            || snippets.slice(0, idx).find(s => !annotations[s.id]);

  renderSnippets();
  updateProgress();

  // highlight matched task card
  if (decision === 'task' && selectedTaskId) {
    document.querySelectorAll('.task-card').forEach(c => {
      c.classList.toggle('selected-match', c.dataset.taskId === selectedTaskId);
    });
  }

  showToast(decision === 'task' ? '✓ Matched task saved'
          : decision === 'requirement' ? '⚠ Marked as requirement'
          : '✗ Flagged: missing from DOG');

  if (next) {
    setTimeout(() => selectSnippet(next.id), 120);
    const card = document.querySelector(`.snippet-card[data-id="${next.id}"]`);
    if (card) card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
}

function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 1800);
}

function escHtml(s) {
  return (s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

document.getElementById('btn-task').addEventListener('click', () => saveAnnotation('task'));
document.getElementById('btn-req').addEventListener('click', () => saveAnnotation('requirement'));
document.getElementById('btn-missing').addEventListener('click', () => saveAnnotation('missing'));

// keyboard shortcuts: t = task, r = requirement, m = missing
document.addEventListener('keydown', e => {
  if (e.target.tagName === 'SELECT') return;
  if (e.key === 't') saveAnnotation('task');
  if (e.key === 'r') saveAnnotation('requirement');
  if (e.key === 'm') saveAnnotation('missing');
});

init();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    comparison_file: Path = None
    annotations_file: Path = None
    _data_cache: dict = None
    _lock = threading.Lock()

    def log_message(self, fmt, *args):
        pass  # suppress request logs

    def send_json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, html: str):
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.send_html(HTML)
        elif self.path == "/api/data":
            if Handler._data_cache is None:
                with open(Handler.comparison_file) as f:
                    Handler._data_cache = json.load(f)
            self.send_json(Handler._data_cache)
        elif self.path == "/api/annotations":
            records = []
            if Handler.annotations_file.exists():
                with open(Handler.annotations_file) as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            records.append(json.loads(line))
            self.send_json(records)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/annotate":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            record = json.loads(body)
            with Handler._lock:
                self._upsert_annotation(record)
            self.send_json({"ok": True})
        else:
            self.send_response(404)
            self.end_headers()

    def _upsert_annotation(self, record):
        snippet_id = record["snippet_id"]
        lines = []
        if Handler.annotations_file.exists():
            with open(Handler.annotations_file) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    existing = json.loads(line)
                    if existing.get("snippet_id") == snippet_id:
                        continue  # will be replaced
                    lines.append(line)
        lines.append(json.dumps(record))
        with open(Handler.annotations_file, "w") as f:
            f.write("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default=None,
                        help="Path to dog_comparison_*.json (default: most recent in annotations/)")
    parser.add_argument("--port", type=int, default=8775)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    if args.file:
        comparison_file = Path(args.file)
    else:
        candidates = sorted((REPO_ROOT / "annotations").glob("dog_comparison_*.json"))
        if not candidates:
            print("No dog_comparison_*.json found in annotations/. Run build_dog_comparison.py first.")
            sys.exit(1)
        comparison_file = candidates[-1]

    if not comparison_file.exists():
        print(f"File not found: {comparison_file}")
        sys.exit(1)

    ann_dir = REPO_ROOT / "annotations"
    ann_dir.mkdir(exist_ok=True)
    stem = comparison_file.stem.replace("dog_comparison_", "")
    annotations_file = ann_dir / f"snippet_to_dog_task_{stem}.jsonl"

    Handler.comparison_file = comparison_file
    Handler.annotations_file = annotations_file

    print(f"\nDOG Comparison UI")
    print(f"  Comparison : {comparison_file.name}")
    print(f"  Annotations: {annotations_file.name}")
    print(f"  http://localhost:{args.port}")
    print(f"\nKeyboard shortcuts: t = matched task  |  r = requirement  |  m = missing from DOG\n")

    server = HTTPServer(("localhost", args.port), Handler)
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(f"http://localhost:{args.port}")).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(f"\nAnnotations saved to {annotations_file}")


if __name__ == "__main__":
    main()
