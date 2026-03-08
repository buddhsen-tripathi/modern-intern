/**
 * Silas — Gesture-Based Personal Assistant Client
 *
 * Single tap to start. No intro phase.
 * Camera -> JPEG 1FPS -> WS
 * Mic -> 16kHz PCM -> WS (via AudioWorklet)
 * WS -> narration audio (24kHz mono) + JSON events
 */

// -- Constants --
const TAG_CAMERA = 0x01;
const TAG_MIC = 0x02;
const TAG_NARRATION = 0x01;
const NARRATION_RATE = 24000;

const GESTURE_LABELS = {
  thumbs_up: { icon: "\u{1F44D}", label: "Confirmed" },
  open_palm: { icon: "\u{270B}", label: "Taking note" },
  peace_sign: { icon: "\u{270C}", label: "Email" },
  point_up: { icon: "\u{261D}", label: "Calendar" },
  wave: { icon: "\u{1F44B}", label: "Meeting" },
  ok_sign: { icon: "\u{1F44C}", label: "Send" },
};

const ACTION_LABELS = {
  note: "Note saved",
  meeting_minutes: "Meeting minutes",
  draft_email: "Email drafted",
  send_email: "Email sent",
  read_email: "Reading email",
  calendar_event: "Event created",
};

// -- DOM refs --
const video = document.getElementById("camera-video");
const canvas = document.getElementById("capture-canvas");
const ctx = canvas.getContext("2d");
const startScreen = document.getElementById("start-screen");
const startBtn = document.getElementById("start-btn");
const startHint = document.getElementById("start-hint");
const hud = document.getElementById("hud");

const statusPill = document.getElementById("status-pill");
const gestureBadge = document.getElementById("gesture-badge");
const gestureBadgeIcon = document.getElementById("gesture-badge-icon");
const gestureBadgeText = document.getElementById("gesture-badge-text");
const narrationText = document.getElementById("narration-text");
const micDot = document.getElementById("mic-dot");
const voiceStatus = document.getElementById("voice-status");
const toastContainer = document.getElementById("toast-container");
const activityFeed = document.getElementById("activity-feed");

// -- State --
let ws = null;
let audioCtx = null;
let narrationGain = null;
let narrationNextTime = 0;
let micStream = null;
let micWorklet = null;
let capturing = false;
let gestureBadgeTimer = null;

// -- Camera --
async function startCamera() {
  const stream = await navigator.mediaDevices.getUserMedia({
    video: { facingMode: "environment", width: { ideal: 640 }, height: { ideal: 640 } },
    audio: false,
  });
  video.srcObject = stream;
  await video.play();
}

function captureLoop() {
  if (!capturing || !ws || ws.readyState !== WebSocket.OPEN) return;

  const vw = video.videoWidth;
  const vh = video.videoHeight;
  const size = Math.min(vw, vh);
  canvas.width = 400;
  canvas.height = 400;
  ctx.drawImage(video, (vw - size) / 2, (vh - size) / 2, size, size, 0, 0, 400, 400);

  canvas.toBlob(
    (blob) => {
      if (blob && ws && ws.readyState === WebSocket.OPEN) {
        blob.arrayBuffer().then((buf) => {
          const tagged = new Uint8Array(1 + buf.byteLength);
          tagged[0] = TAG_CAMERA;
          tagged.set(new Uint8Array(buf), 1);
          ws.send(tagged.buffer);
        });
      }
      setTimeout(captureLoop, 333); // ~3fps for gesture detection
    },
    "image/jpeg",
    0.7,
  );
}

// -- Mic --
async function startMic() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  micStream = stream;
  await audioCtx.audioWorklet.addModule("/static/mic-processor.js");
  const source = audioCtx.createMediaStreamSource(stream);
  micWorklet = new AudioWorkletNode(audioCtx, "mic-processor");

  micWorklet.port.onmessage = (e) => {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const pcm = new Uint8Array(e.data);
    const tagged = new Uint8Array(1 + pcm.byteLength);
    tagged[0] = TAG_MIC;
    tagged.set(pcm, 1);
    ws.send(tagged.buffer);
  };

  source.connect(micWorklet);
}

// -- Audio Playback --
function initAudio() {
  audioCtx = new AudioContext();
  narrationGain = audioCtx.createGain();
  narrationGain.gain.value = 1.0;
  narrationGain.connect(audioCtx.destination);
  narrationNextTime = 0;
}

function playNarrationChunk(int16Array) {
  if (!audioCtx || audioCtx.state === "closed") return;
  const len = int16Array.length;
  if (len === 0) return;

  const buffer = audioCtx.createBuffer(1, len, NARRATION_RATE);
  const channel = buffer.getChannelData(0);
  for (let i = 0; i < len; i++) {
    channel[i] = int16Array[i] / 32768;
  }

  const source = audioCtx.createBufferSource();
  source.buffer = buffer;
  source.connect(narrationGain);

  const now = audioCtx.currentTime;
  const start = Math.max(now, narrationNextTime);
  source.start(start);
  narrationNextTime = start + buffer.duration;
}

// -- WebSocket --
function connectWS() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${proto}//${location.host}/ws`);
  ws.binaryType = "arraybuffer";

  ws.onopen = () => {
    console.log("[WS] Connected");
    // Immediately start session and camera streaming
    ws.send(JSON.stringify({ type: "start" }));
    capturing = true;
    captureLoop();

    // Show HUD
    startScreen.style.display = "none";
    hud.classList.add("active");
  };

  ws.onmessage = (e) => {
    if (typeof e.data === "string") {
      handleJSON(JSON.parse(e.data));
    } else {
      handleBinary(new Uint8Array(e.data));
    }
  };

  ws.onclose = () => {
    console.log("[WS] Disconnected");
    // Reconnect if session was active
    if (capturing) {
      setTimeout(connectWS, 2000);
    }
  };

  ws.onerror = (err) => console.error("[WS] Error", err);
}

function handleJSON(msg) {
  switch (msg.type) {
    case "event":
      handleEvent(msg.data);
      break;
    case "narration":
      showNarration(msg.text);
      break;
    case "vad_state":
      updateVAD(msg.state);
      break;
  }
}

function handleBinary(data) {
  if (data.length < 2) return;
  const tag = data[0];
  const pcm = data.slice(1);
  const int16 = new Int16Array(pcm.buffer, pcm.byteOffset, pcm.byteLength / 2);

  if (tag === TAG_NARRATION) {
    playNarrationChunk(int16);
  }
}

// -- Event Handling --
function handleEvent(event) {
  if (event.type === "gesture") {
    showGesture(event.gesture);
  } else if (event.type === "action_armed") {
    showActionArmed(event);
  } else if (event.type === "action_result") {
    showActionResult(event);
  } else if (event.type === "action_timeout") {
    showToast(event.message || "Action timed out", "error");
  }
}

function showGesture(gesture) {
  const info = GESTURE_LABELS[gesture] || { icon: "?", label: gesture };

  gestureBadge.classList.add("visible");
  gestureBadgeIcon.textContent = info.icon;
  gestureBadgeText.textContent = info.label;

  clearTimeout(gestureBadgeTimer);
  gestureBadgeTimer = setTimeout(() => {
    gestureBadge.classList.remove("visible");
  }, 3000);

  showToast(info.icon + " " + info.label, "gesture");
}

function showActionArmed(event) {
  const label = ACTION_LABELS[event.action] || event.action;
  showToast(event.prompt || `${label} — speak now...`, "armed");
}

function showActionResult(event) {
  const label = ACTION_LABELS[event.action] || event.action;
  const isError = event.status === "error";
  showToast(event.message || label, isError ? "error" : "success");

  if (!isError) {
    addToFeed(event.action, event.message || label);
  }
}

function showToast(text, type) {
  const el = document.createElement("div");
  el.className = `toast toast-${type}`;
  el.textContent = text;
  toastContainer.appendChild(el);
  el.addEventListener("animationend", () => el.remove());
}

function addToFeed(action, message) {
  const entry = document.createElement("div");
  entry.className = "feed-entry";

  const icon = document.createElement("span");
  icon.className = "feed-icon";
  const icons = {
    note: "\u{1F4DD}",
    meeting_minutes: "\u{1F4CB}",
    draft_email: "\u{2709}",
    send_email: "\u{1F4E8}",
    read_email: "\u{1F4E9}",
    calendar_event: "\u{1F4C5}",
  };
  icon.textContent = icons[action] || "\u{2022}";

  const text = document.createElement("span");
  text.className = "feed-text";
  text.textContent = message;

  const time = document.createElement("span");
  time.className = "feed-time";
  const now = new Date();
  time.textContent = now.getHours().toString().padStart(2, "0") + ":" +
                     now.getMinutes().toString().padStart(2, "0");

  entry.appendChild(icon);
  entry.appendChild(text);
  entry.appendChild(time);
  activityFeed.appendChild(entry);

  while (activityFeed.children.length > 6) {
    activityFeed.removeChild(activityFeed.firstChild);
  }

  setTimeout(() => {
    entry.classList.add("feed-fade");
    entry.addEventListener("animationend", () => entry.remove());
  }, 30000);
}

// -- Narration --
function showNarration(text) {
  narrationText.textContent = text;
  clearTimeout(showNarration._timer);
  showNarration._timer = setTimeout(() => {
    narrationText.textContent = "Listening...";
  }, 10000);
}

function updateVAD(state) {
  if (state === "LISTENING") {
    micDot.classList.add("listening");
    voiceStatus.textContent = "LISTENING";
    voiceStatus.className = "voice-status listening";
  } else {
    micDot.classList.remove("listening");
    if (micStream) {
      voiceStatus.textContent = "VOICE";
      voiceStatus.className = "voice-status active";
    }
  }
}

// -- Start --
async function startSilas() {
  startBtn.disabled = true;
  startBtn.textContent = "STARTING...";
  startHint.textContent = "grant camera + mic permissions...";

  try {
    initAudio();
    await startCamera();
  } catch (err) {
    alert("Camera access required: " + err.message);
    startBtn.disabled = false;
    startBtn.textContent = "START";
    startHint.textContent = "camera + mic required";
    return;
  }

  try {
    await startMic();
    voiceStatus.textContent = "VOICE";
    voiceStatus.className = "voice-status active";
  } catch (err) {
    console.warn("Mic not available:", err);
    voiceStatus.textContent = "NO MIC";
    voiceStatus.className = "voice-status no-mic";
  }

  connectWS();
}

// -- Event Listeners --
startBtn.addEventListener("click", startSilas);
