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

function setStepStatus(agentId, status) {
  const li = el.stepList.querySelector(`[data-id="${agentId}"]`);
  if (!li) return;
  li.className = status;
  const icon = li.querySelector(".step-icon");
  if (status === "done") icon.textContent = "✓";
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

  const res = await fetch("/api/ayra/runs/stream", { method: "POST", body: formData });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Pipeline failed (${res.status})`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let total = state.workflow.length || 22;
  let completed = 0;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";

    for (const block of parts) {
      const event = parseSseBlock(block);
      if (!event) continue;

      if (event.event === "workflow") {
        const agents = event.data.agents || [];
        total = event.data.total || agents.length;
        initSteps(agents);
        state.workflow = agents;
        el.progressSub.textContent = `0 / ${total} agents`;
      }

      if (event.event === "progress") {
        const { agent_id, title, completed: doneIds = [], errors = {} } = event.data;
        doneIds.forEach((id) => setStepStatus(id, errors[id] ? "failed" : "done"));
        if (agent_id) setStepStatus(agent_id, errors[agent_id] ? "failed" : "active");
        completed = doneIds.length;
        el.progressSub.textContent = title || agent_id;
        el.progressBar.style.width = `${Math.min(100, Math.round((completed / total) * 100))}%`;
      }

      if (event.event === "error") {
        throw new Error(event.data.detail || "Pipeline error");
      }

      if (event.event === "done") {
        el.progressBar.style.width = "100%";
        el.progressSub.textContent = "Complete";
        showProgress(false);
        if (event.data.workflow?.length) state.workflow = event.data.workflow;
        renderResults(event.data);
      }
    }
  }
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
el.fileInput.addEventListener("change", (e) => onFilesSelected(e.target.files));
el.newChat.addEventListener("click", resetChat);

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
