const UID = "demo";
const SESSION = "live";

const PRESETS = [
  "Priya said Burma Burma in Bandra — you can remember that. My new debit PIN is 4419, don't store that. Also my knee flared after stairs, that's private. Off the record I'll cover for Dev. Send Rohan the API spec tonight — work can see that.",
  "Where did Priya want to eat?",
  "What's going on with my knee?",
  "What do I owe?",
  "Mark the Rohan spec done",
  "Forget everything about my health",
];

let pollTimer = null;
let lastForgetPre = null;

function principal() {
  return document.getElementById("principal-select").value;
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function tierPill(tier) {
  return `<span class="pill ${tier || ""}">${tier || "unknown"}</span>`;
}

function scopeChips(scope) {
  return (scope || []).map((s) => `<span class="chip-scope">${s}</span>`).join("");
}

function renderState(data) {
  document.getElementById("lyzr-badge").textContent =
    data.lyzr_mode === "live" ? "Lyzr: live" : "Lyzr: fallback";

  const log = document.getElementById("live-log");
  log.innerHTML = (data.events || [])
    .map(
      (e) =>
        `<li><span class="log-code">${e.code}</span> ${e.detail || ""} <span class="muted">${e.ts || ""}</span></li>`
    )
    .join("") || `<li class="muted">No events yet</li>`;

  const commits = document.getElementById("commitments-list");
  commits.innerHTML = (data.commitments || [])
    .map(
      (c) => `<li>
        <strong>${c.who || ""}</strong> — ${c.what || c.text}
        <div class="chips-row">${scopeChips(c.scope)}</div>
        <div class="muted">${c.status}</div>
        <button class="btn done-btn" data-id="${c.id}">Done</button>
      </li>`
    )
    .join("") || `<li class="muted">No open commitments</li>`;

  document.querySelectorAll(".done-btn").forEach((btn) => {
    btn.onclick = async () => {
      await api("/commitments/set_status", {
        method: "POST",
        body: JSON.stringify({ id: btn.dataset.id, status: "done" }),
      });
      refresh();
    };
  });

  const receipts = document.getElementById("receipts-list");
  receipts.innerHTML = (data.receipts || [])
    .map(
      (r) =>
        `<li><span class="muted">${r.ts || ""}</span> ${r.preview || r.reason || ""} <span class="pill never">${r.reason || r.action || ""}</span></li>`
    )
    .join("") || `<li class="muted">Nothing refused yet.</li>`;

  const mems = document.getElementById("memories-list");
  mems.innerHTML = (data.memories || [])
    .map(
      (m) => `<li>
        ${m.text}
        <div class="chips-row">${tierPill(m.tier)} ${scopeChips(m.scope)}</div>
        <div class="muted">${m.ts || ""} · ${(m.people || []).join(", ")}</div>
      </li>`
    )
    .join("") || `<li class="muted">No memories visible</li>`;

  const c = data.counts || {};
  document.getElementById("counts").innerHTML = `
    <div class="count-box"><div class="num">${c.memories ?? 0}</div><div class="muted">memories</div></div>
    <div class="count-box"><div class="num">${c.commitments ?? 0}</div><div class="muted">commitments</div></div>
    <div class="count-box"><div class="num">${c.receipts ?? 0}</div><div class="muted">receipts</div></div>
  `;

  const health = c.health ?? 0;
  const proof = document.getElementById("forget-proof");
  if (lastForgetPre !== null) {
    proof.innerHTML = `<span class="big-num">${lastForgetPre}</span> → <span class="big-num">${health}</span> <span class="muted">health memories</span>`;
  } else {
    proof.innerHTML = `<span class="muted">Forget demo shows health count 1 → 0</span>`;
  }
}

async function refresh() {
  const data = await api(`/demo/state?uid=${UID}&principal=${encodeURIComponent(principal())}`);
  renderState(data);
}

async function sendUtterance(text) {
  await api("/dev/utterance", {
    method: "POST",
    body: JSON.stringify({
      uid: UID,
      session_id: SESSION,
      text,
      speaker: "USER",
      is_user: true,
      principal: principal(),
    }),
  });
  if (text.toLowerCase().includes("forget") && text.toLowerCase().includes("health")) {
    const before = await api(`/demo/state?uid=${UID}&principal=${encodeURIComponent(principal())}`);
    lastForgetPre = before.counts?.health ?? 1;
  }
  await refresh();
}

async function ask() {
  const q = document.getElementById("ask-input").value.trim();
  if (!q) return;
  const result = await api("/dev/utterance", {
    method: "POST",
    body: JSON.stringify({
      uid: UID,
      session_id: SESSION,
      text: q,
      speaker: "USER",
      is_user: true,
      principal: principal(),
    }),
  });
  const payload = result.result?.results?.length
    ? result.result.results[result.result.results.length - 1]
    : result.result;
  const ans = payload?.answer || "";
  const ids = payload?.point_ids || [];
  const box = document.getElementById("ask-answer");
  if (!ans && !ids.length) {
    box.textContent = "I have no memory I'm allowed to use for that.";
  } else {
    box.innerHTML = `${ans} ${ids.map((id) => `<span class="cite">${id}</span>`).join("")}`;
  }
  refresh();
}

async function loadEval() {
  try {
    const data = await api("/eval/gate");
    const tiers = ["never", "ephemeral", "personal", "knowledge"];
    let html = `<table class="matrix"><tr><th></th>${tiers.map((t) => `<th>${t}</th>`).join("")}</tr>`;
    for (const row of tiers) {
      html += `<tr><th>${row}</th>`;
      for (const col of tiers) {
        html += `<td>${(data.matrix?.[row]?.[col]) ?? 0}</td>`;
      }
      html += "</tr>";
    }
    html += `</table><p class="caption">Never-recall: ${(data.never_recall * 100).toFixed(1)}%</p>`;
    document.getElementById("eval-matrix").innerHTML = html;
  } catch (_) {
    document.getElementById("eval-matrix").textContent = "Eval unavailable";
  }
}

function setupPresets() {
  const wrap = document.getElementById("preset-chips");
  PRESETS.forEach((line) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "chip";
    chip.textContent = line.slice(0, 42) + (line.length > 42 ? "…" : "");
    chip.title = line;
    chip.onclick = () => {
      document.getElementById("composer").value = line;
    };
    wrap.appendChild(chip);
  });
}

function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(() => {
    if (document.visibilityState === "visible") refresh();
  }, 2000);
}

document.getElementById("send-btn").onclick = () => {
  const text = document.getElementById("composer").value.trim();
  if (text) sendUtterance(text);
};
document.getElementById("seed-btn").onclick = async () => {
  await api("/dev/seed", { method: "POST" });
  lastForgetPre = null;
  refresh();
};
document.getElementById("reset-btn").onclick = async () => {
  await api("/dev/reset", { method: "POST" });
  lastForgetPre = null;
  refresh();
};
document.getElementById("ask-btn").onclick = ask;
document.getElementById("composer").addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendUtterance(e.target.value.trim());
});
document.getElementById("principal-select").onchange = refresh;

document.getElementById("eval-details").addEventListener("toggle", (e) => {
  if (e.target.open) loadEval();
});

setupPresets();
refresh();
startPolling();
