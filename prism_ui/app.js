const SUPPORTED = new Set(["pdf", "txt", "md", "html", "htm", "docx", "csv", "json"]);

const $ = (sel) => document.querySelector(sel);

const state = {
  files: [],
  workflow: [],
  busy: false,
  whisperAvailable: false,
  recording: false,
  mediaRecorder: null,
  recordChunks: [],
  speechRecognition: null,
  listening: false,
  forceRefresh: false,
  currentRunId: null,
  totalAgents: 22,
  completedCount: 0,
};

const el = {
  greeting: $("#greeting"),
  welcome: $("#welcome"),
  messages: $("#messages"),
  progressPanel: $("#progress-panel"),
  progressSub: $("#progress-sub"),
  progressBar: $("#progress-bar"),
  stepList: $("#step-list"),
  chips: $("#chips"),
  input: $("#input"),
  send: $("#btn-send"),
  upload: $("#btn-upload"),
  fileInput: $("#file-input"),
  voice: $("#btn-voice"),
  attachments: $("#attachments"),
  newChat: $("#btn-new"),
  forceRefresh: $("#force-refresh"),
};

function ext(name) {
  const i = name.lastIndexOf(".");
  return i >= 0 ? name.slice(i + 1).toLowerCase() : "";
}

function isSupported(name) {
  return SUPPORTED.has(ext(name));
}

function toast(msg, isError = false) {
  const node = document.createElement("div");
  node.className = `toast${isError ? " error" : ""}`;
  node.textContent = msg;
  document.body.appendChild(node);
  setTimeout(() => node.remove(), 4500);
}

function setBusy(busy) {
  state.busy = busy;
  document.body.classList.toggle("is-busy", busy);
  updateSendState();
}

function clearComposer() {
  el.input.value = "";
  el.input.style.height = "auto";
  state.files = [];
  renderAttachments();
  updateSendState();
  el.input.focus();
}

function hideWelcome() {
  el.welcome.hidden = true;
  el.messages.hidden = false;
}

function addBubble(text, role = "ayra") {
  hideWelcome();
  const div = document.createElement("div");
  div.className = `bubble ${role}`;
  div.innerHTML = formatMarkdownLite(text);
  el.messages.appendChild(div);
  el.messages.scrollTop = el.messages.scrollHeight;
  return div;
}

function formatMarkdownLite(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\n/g, "<br>");
}

function buildFormData(message, files = state.files) {
  const fd = new FormData();
  fd.append("message", message);
  fd.append("project_name", "PRISM Project");
  fd.append("force_refresh", state.forceRefresh ? "true" : "false");
  files.forEach((f) => fd.append("files", f));
  return fd;
}

function hasDisplayableOutput(id, outputs, errors) {
  if (errors[id]) return false;
  const output = outputs[id];
  if (!output || output.content == null) return false;
  const content = output.content;
  if (typeof content !== "object" || Array.isArray(content)) return false;
  const keys = Object.keys(content);
  if (keys.length === 0) return false;
  if (keys.length === 1 && (keys[0] === "raw" || keys[0] === "_truncated_summary")) return false;
  const hasValue = keys.some((key) => {
    const value = content[key];
    if (value == null) return false;
    if (Array.isArray(value)) return value.length > 0;
    if (typeof value === "object") return Object.keys(value).length > 0;
    if (typeof value === "string") return value.trim().length > 0;
    return true;
  });
  return hasValue;
}

function renderAttachments() {
  if (!state.files.length) {
    el.attachments.hidden = true;
    el.attachments.innerHTML = "";
    return;
  }
  el.attachments.hidden = false;
  el.attachments.innerHTML = "";
  state.files.forEach((file, idx) => {
    const pill = document.createElement("span");
    pill.className = "attachment-pill";
    pill.textContent = file.name;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.setAttribute("aria-label", "Remove");
    btn.textContent = "×";
    btn.onclick = () => {
      state.files.splice(idx, 1);
      renderAttachments();
      updateSendState();
    };
    pill.appendChild(btn);
    el.attachments.appendChild(pill);
  });
}

function updateSendState() {
  el.send.disabled = state.busy || state.recording || (!el.input.value.trim() && state.files.length === 0);
}

function initSteps(agents) {
  el.stepList.innerHTML = "";
  agents.forEach((a) => {
    const li = document.createElement("li");
    li.dataset.id = a.id;
    li.innerHTML = `<span class="step-icon">○</span><span>${a.title}</span>`;
    el.stepList.appendChild(li);
  });
}

function setStepStatus(agentId, status, options = {}) {
  const li = el.stepList.querySelector(`[data-id="${agentId}"]`);
  if (!li) return;
  const classes = [status];
  if (options.cached) classes.push("cached");
  li.className = classes.join(" ");
  const icon = li.querySelector(".step-icon");
  if (status === "done") icon.textContent = options.cached ? "⟳" : "✓";
  else if (status === "failed") icon.textContent = "!";
  else if (status === "active") icon.textContent = "◌";
}

function showProgress(show) {
  el.progressPanel.hidden = !show;
  if (show) {
    el.chips.hidden = true;
    hideWelcome();
  }
}

async function loadConfig() {
  try {
    const res = await fetch("/api/ayra/config");
    const data = await res.json();
    state.workflow = data.workflow || [];
    state.whisperAvailable = Boolean(data.whisper_available);
    document.title = data.name || "PRISM - AI SDLC Copilot";
    el.greeting.textContent = "Hi I'm PRISM";
    el.voice.title = state.whisperAvailable
      ? "Record voice (Whisper) — click to start/stop"
      : "Voice input (browser speech — install whisper extra for better quality)";
  } catch {
    el.greeting.textContent = "Hi I'm PRISM";
  }
}

async function handleSend() {
  const message = el.input.value.trim();
  if (state.busy || state.recording) return;
  if (!message && !state.files.length) return;

  const payloadMessage = message;
  const payloadFiles = [...state.files];
  clearComposer();

  setBusy(true);
  if (payloadMessage) addBubble(payloadMessage, "user");

  try {
    const fd = buildFormData(payloadMessage, payloadFiles);
    const msgRes = await fetch("/api/ayra/message", { method: "POST", body: fd });
    const msgData = await msgRes.json();
    if (!msgRes.ok) throw new Error(msgData.detail || "Request failed");

    if (msgData.type === "reply") {
      addBubble(msgData.text, "ayra");
      return;
    }

    if (msgData.reply) addBubble(msgData.reply, "ayra");
    await streamPipeline(buildFormData(msgData.requirements || payloadMessage, payloadFiles));
  } catch (err) {
    addBubble(`Something went wrong: ${err.message}`, "ayra");
    showProgress(false);
    el.chips.hidden = false;
  } finally {
    setBusy(false);
  }
}

async function streamPipeline(formData) {
  showProgress(true);
  el.progressSub.textContent = "Starting agents…";
  el.progressBar.style.width = "0%";
  state.completedCount = 0;

  const res = await fetch("/api/ayra/runs/stream", { method: "POST", body: formData });
  await consumeSse(res, defaultSseHandlers());
}

function defaultSseHandlers() {
  return {
    workflow: (data) => {
      const agents = data.agents || [];
      state.totalAgents = data.total || agents.length;
      initSteps(agents);
      state.workflow = agents;
      el.progressSub.textContent = `0 / ${state.totalAgents} agents`;
    },
    progress: (data) => {
      const { agent_id, title, cached = false, completed: doneIds = [], errors = {} } = data;
      doneIds.forEach((id) => setStepStatus(id, errors[id] ? "failed" : "done"));
      if (agent_id) setStepStatus(agent_id, errors[agent_id] ? "failed" : "active", { cached });
      state.completedCount = doneIds.length;
      el.progressSub.textContent = (cached ? "(cached) " : "") + (title || agent_id);
      const total = state.totalAgents || 22;
      el.progressBar.style.width = `${Math.min(100, Math.round((state.completedCount / total) * 100))}%`;
    },
    requires_input: async (data) => {
      state.currentRunId = data.run_id;
      await promptForPlan(data);
    },
    requires_team_review: async (data) => {
      state.currentRunId = data.run_id;
      await promptForTeamReview(data);
    },
    done: (data) => {
      el.progressBar.style.width = "100%";
      el.progressSub.textContent = "Complete";
      showProgress(false);
      if (data.workflow?.length) state.workflow = data.workflow;
      state.currentRunId = null;
      renderResults(data);
    },
    error: (data) => {
      throw new Error(data.detail || "Pipeline error");
    },
    agent_error: (data) => {
      const { agent_id, title, error } = data;
      setStepStatus(agent_id, "failed");
      const banner = document.createElement("div");
      banner.className = "agent-error-banner";
      banner.innerHTML = `<strong>&#9888; Agent failed: ${title || agent_id}</strong><br><code>${error}</code>`;
      el.messages.hidden = false;
      el.messages.appendChild(banner);
      el.messages.scrollTop = el.messages.scrollHeight;
      console.error("[agent_error]", agent_id, error);
    },
  };
}

async function consumeSse(res, handlers) {
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Request failed (${res.status})`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";

    for (const block of parts) {
      const event = parseSseBlock(block);
      if (!event) continue;
      const handler = handlers[event.event];
      if (handler) {
        const result = handler(event.data);
        if (result && typeof result.then === "function") {
          await result;
        }
      }
    }
  }
}

function promptForPlan(data) {
  return new Promise((resolve, reject) => {
    const old = el.progressPanel.querySelector(".hitl-form");
    if (old) old.remove();

    const form = document.createElement("div");
    form.className = "hitl-form";
    form.innerHTML = `
      <h3>Sprint &amp; project planning</h3>
      <p class="hitl-hint">${
        data.cached ? "Loaded cached requirement analysis. " : ""
      }Confirm sprint length and overall project horizon before sprint_planning runs.</p>
      <div class="field-row">
        <label class="field">
          Sprint duration (weeks)
          <input type="number" id="hitl-sprint" min="1" max="8" step="1"
            value="${data.suggested_sprint_duration_weeks || 2}" />
        </label>
        <label class="field">
          Project duration (weeks)
          <input type="number" id="hitl-project" min="1" max="104" step="1"
            value="${data.suggested_project_duration_weeks || 12}" />
        </label>
      </div>
      <div class="hitl-actions">
        <button type="button" class="hitl-btn" id="hitl-continue">Continue</button>
      </div>
    `;
    el.progressPanel.appendChild(form);
    el.progressSub.textContent = "Waiting for sprint plan input…";

    const btn = form.querySelector("#hitl-continue");
    btn.addEventListener("click", async () => {
      const sprint = parseInt(form.querySelector("#hitl-sprint").value, 10);
      const project = parseInt(form.querySelector("#hitl-project").value, 10);
      if (!sprint || !project || sprint < 1 || project < 1) {
        toast("Enter positive sprint and project durations.", true);
        return;
      }
      btn.disabled = true;
      btn.textContent = "Running…";

      const fd = new FormData();
      fd.append("sprint_duration_weeks", String(sprint));
      fd.append("project_duration_weeks", String(project));

      try {
        const res = await fetch(`/api/ayra/runs/${data.run_id}/plan`, {
          method: "POST",
          body: fd,
        });
        form.remove();
        await consumeSse(res, defaultSseHandlers());
        resolve();
      } catch (err) {
        reject(err);
      }
    });
  });
}

function promptForTeamReview(data) {
  return new Promise((resolve, reject) => {
    const old = el.progressPanel.querySelector(".hitl-form");
    if (old) old.remove();

    const roles = ["Developer", "QA", "DevOps", "PM", "Designer"];
    const initialAssignments = Array.isArray(data.assignments) ? data.assignments : [];
    const tasks = Array.isArray(data.tasks) ? data.tasks : [];
    const taskIds = Array.from(
      new Set([
        ...tasks.map((t) => String(t.id || t.task_id || "")).filter(Boolean),
        ...initialAssignments.map((a) => String(a.task_id || "")).filter(Boolean),
      ]),
    );

    const form = document.createElement("div");
    form.className = "hitl-form";
    form.innerHTML = `
      <h3>Review team allocation</h3>
      <p class="hitl-hint">PRISM proposed the assignments below. Edit any cell, add or remove rows, then finalize.</p>
      <div class="assignments-wrap">
        <table class="assignments-table">
          <thead>
            <tr>
              <th>Task ID</th>
              <th>Role</th>
              <th>Owner</th>
              <th>Est. hours</th>
              <th aria-label="Remove"></th>
            </tr>
          </thead>
          <tbody id="assignments-body"></tbody>
        </table>
      </div>
      <div class="hitl-actions" style="justify-content: space-between;">
        <button type="button" class="hitl-btn hitl-btn-secondary" id="hitl-add-row">+ Add row</button>
        <button type="button" class="hitl-btn" id="hitl-finalize">Finalize</button>
      </div>
    `;
    el.progressPanel.appendChild(form);
    el.progressSub.textContent = "Waiting for team allocation review…";

    const tbody = form.querySelector("#assignments-body");

    function buildRow(a = {}) {
      const tr = document.createElement("tr");
      const roleOptions = roles
        .map(
          (r) =>
            `<option value="${r}"${(a.role || "Developer") === r ? " selected" : ""}>${r}</option>`,
        )
        .join("");

      const currentTaskId = String(a.task_id || "");
      let taskIdCell;
      if (taskIds.length > 0) {
        const options = taskIds
          .map(
            (id) =>
              `<option value="${escapeHtml(id)}"${id === currentTaskId ? " selected" : ""}>${escapeHtml(id)}</option>`,
          )
          .join("");
        const customOption =
          currentTaskId && !taskIds.includes(currentTaskId)
            ? `<option value="${escapeHtml(currentTaskId)}" selected>${escapeHtml(currentTaskId)}</option>`
            : "";
        taskIdCell = `<td><select class="cell-task">${customOption}${options}</select></td>`;
      } else {
        taskIdCell = `<td><input type="text" class="cell-task" placeholder="T-1"
          value="${escapeHtml(currentTaskId)}" /></td>`;
      }

      tr.innerHTML = `
        ${taskIdCell}
        <td><select class="cell-role">${roleOptions}</select></td>
        <td><input type="text" class="cell-owner" value="${escapeHtml(a.owner || "TBD")}" /></td>
        <td><input type="number" class="cell-hours" min="0" step="0.5"
          value="${Number.isFinite(+a.estimated_hours) ? +a.estimated_hours : 8}" /></td>
        <td><button type="button" class="row-remove" aria-label="Remove row">×</button></td>
      `;
      tr.querySelector(".row-remove").addEventListener("click", () => tr.remove());
      return tr;
    }

    const initialRows = initialAssignments.length > 0
      ? initialAssignments
      : taskIds.length > 0
        ? taskIds.map((id) => ({ task_id: id }))
        : [{}];
    initialRows.forEach((a) => tbody.appendChild(buildRow(a)));

    form.querySelector("#hitl-add-row").addEventListener("click", () => {
      tbody.appendChild(buildRow({}));
    });

    const btn = form.querySelector("#hitl-finalize");
    btn.addEventListener("click", async () => {
      const edited = Array.from(tbody.querySelectorAll("tr")).map((tr) => ({
        task_id: (tr.querySelector(".cell-task").value || "").trim(),
        role: tr.querySelector(".cell-role").value,
        owner: (tr.querySelector(".cell-owner").value || "").trim(),
        estimated_hours: parseFloat(tr.querySelector(".cell-hours").value) || 0,
      }));

      btn.disabled = true;
      btn.textContent = "Finalizing…";

      try {
        const res = await fetch(`/api/ayra/runs/${data.run_id}/finalize`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ assignments: edited }),
        });
        form.remove();
        await consumeSse(res, defaultSseHandlers());
        resolve();
      } catch (err) {
        reject(err);
      }
    });
  });
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function parseSseBlock(block) {
  let eventName = "message";
  let dataLine = "";
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) eventName = line.slice(6).trim();
    if (line.startsWith("data:")) dataLine += line.slice(5).trim();
  }
  if (!dataLine) return null;
  try {
    return { event: eventName, data: JSON.parse(dataLine) };
  } catch {
    return null;
  }
}

function renderResults(data) {
  const outputs = data.outputs || {};
  const errors = data.errors || {};
  const order = state.workflow.length
    ? state.workflow.map((a) => a.id)
    : Object.keys(outputs);
  const visibleIds = order.filter((id) => hasDisplayableOutput(id, outputs, errors));

  const summary =
    visibleIds.length > 0
      ? `Analysis complete — **${visibleIds.length}** agents returned usable JSON. Open each block below.`
      : "Analysis finished, but no agent returned usable JSON. Try again with shorter input or check LLM limits.";

  const bubble = addBubble(summary, "ayra");

  const actions = document.createElement("div");
  actions.className = "results-actions";
  for (const [fmt, href] of Object.entries(data.export_urls || {})) {
    const a = document.createElement("a");
    a.href = href;
    a.download = `${data.run_id}.${fmt}`;
    a.textContent = `Download ${fmt.toUpperCase()}`;
    actions.appendChild(a);
  }
  bubble.appendChild(actions);

  const list = document.createElement("div");
  list.className = "artifact-list";
  visibleIds.forEach((id) => {
    const meta = state.workflow.find((a) => a.id === id);
    const title = outputs[id]?.title || meta?.title || id.replace(/_/g, " ");
    const card = document.createElement("details");
    card.className = "artifact-card";
    card.open = false;

    const summaryEl = document.createElement("summary");
    summaryEl.textContent = title;
    card.appendChild(summaryEl);

    const pre = document.createElement("pre");
    pre.textContent = JSON.stringify(
      {
        agent_id: outputs[id].agent_id || id,
        title: outputs[id].title || title,
        artifact_type: outputs[id].artifact_type,
        content: outputs[id].content ?? {},
        risks: outputs[id].risks ?? [],
        assumptions: outputs[id].assumptions ?? [],
      },
      null,
      2,
    );
    card.appendChild(pre);
    list.appendChild(card);
  });
  bubble.appendChild(list);
}

function onFilesSelected(fileList) {
  for (const file of fileList) {
    if (!isSupported(file.name)) {
      toast(`"${file.name}" is not supported. Use: ${[...SUPPORTED].join(", ")}`, true);
      continue;
    }
    if (!state.files.some((f) => f.name === file.name && f.size === file.size)) {
      state.files.push(file);
    }
  }
  renderAttachments();
  updateSendState();
}

async function transcribeWithWhisper(blob) {
  const fd = new FormData();
  fd.append("audio", blob, "speech.webm");
  const res = await fetch("/api/ayra/transcribe", { method: "POST", body: fd });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "Transcription failed");
  return data.text || "";
}

function startBrowserDictation() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    toast("Voice not supported in this browser.", true);
    return;
  }
  const rec = new SR();
  rec.continuous = false;
  rec.interimResults = true;
  rec.lang = "en-US";
  rec.onresult = (e) => {
    let text = "";
    for (let i = e.resultIndex; i < e.results.length; i++) {
      text += e.results[i][0].transcript;
    }
    el.input.value = (el.input.value + " " + text).trim();
    el.input.dispatchEvent(new Event("input"));
  };
  rec.onend = () => {
    state.listening = false;
    el.voice.classList.remove("listening");
    updateSendState();
  };
  rec.onerror = () => {
    state.listening = false;
    el.voice.classList.remove("listening");
    toast("Could not capture voice. Check microphone permissions.", true);
    updateSendState();
  };
  state.speechRecognition = rec;
  state.listening = true;
  el.voice.classList.add("listening");
  rec.start();
}

async function startWhisperRecording() {
  if (!navigator.mediaDevices?.getUserMedia) {
    toast("Microphone not available in this browser.", true);
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    state.recordChunks = [];
    const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
      ? "audio/webm;codecs=opus"
      : "audio/webm";
    const recorder = new MediaRecorder(stream, { mimeType });
    state.mediaRecorder = recorder;

    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) state.recordChunks.push(e.data);
    };

    recorder.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      state.recording = false;
      el.voice.classList.remove("recording");
      updateSendState();

      const blob = new Blob(state.recordChunks, { type: mimeType });
      if (blob.size < 800) {
        toast("Recording too short. Try again.", true);
        return;
      }

      toast("Transcribing with Whisper…");
      try {
        const text = await transcribeWithWhisper(blob);
        el.input.value = (el.input.value + " " + text).trim();
        el.input.dispatchEvent(new Event("input"));
        toast("Voice added to input.");
      } catch (err) {
        toast(err.message, true);
      }
    };

    recorder.start(250);
    state.recording = true;
    el.voice.classList.add("recording");
    el.voice.title = "Recording… click to stop";
    updateSendState();
    toast("Recording… click the mic again when done.");
  } catch {
    toast("Microphone permission denied.", true);
  }
}

function stopWhisperRecording() {
  if (state.mediaRecorder && state.recording) {
    state.mediaRecorder.stop();
    el.voice.title = state.whisperAvailable
      ? "Record voice (Whisper) — click to start/stop"
      : "Voice input";
  }
}

function initVoice() {
  el.voice.addEventListener("click", () => {
    if (state.busy) return;

    if (state.whisperAvailable) {
      if (state.recording) stopWhisperRecording();
      else startWhisperRecording();
      return;
    }

    if (state.listening && state.speechRecognition) {
      state.speechRecognition.stop();
      return;
    }
    startBrowserDictation();
  });
}

function resetChat() {
  if (state.recording) stopWhisperRecording();
  el.messages.innerHTML = "";
  el.messages.hidden = true;
  el.welcome.hidden = false;
  el.progressPanel.hidden = true;
  el.chips.hidden = false;
  state.currentRunId = null;
  state.completedCount = 0;
  const oldForm = el.progressPanel.querySelector(".hitl-form");
  if (oldForm) oldForm.remove();
  clearComposer();
}

el.input.addEventListener("input", () => {
  el.input.style.height = "auto";
  el.input.style.height = `${Math.min(el.input.scrollHeight, 160)}px`;
  updateSendState();
});

el.input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    handleSend();
  }
});

el.send.addEventListener("click", handleSend);
el.upload.addEventListener("click", () => el.fileInput.click());
el.fileInput.addEventListener("change", (e) => {
  onFilesSelected(e.target.files);
  e.target.value = "";   // reset so same file can be re-selected
});
el.newChat.addEventListener("click", resetChat);
if (el.forceRefresh) {
  el.forceRefresh.addEventListener("change", (e) => {
    state.forceRefresh = !!e.target.checked;
  });
}

document.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    el.input.value = chip.dataset.prompt || "";
    el.input.dispatchEvent(new Event("input"));
    el.input.focus();
  });
});

loadConfig();
initVoice();
updateSendState();
