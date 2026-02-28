/**
 * Gemini Chat — Voice + Vision web client
 *
 * Camera → JPEG 1FPS → WS
 * Mic → 16kHz PCM → WS (via AudioWorklet)
 * WS → narration audio (24kHz mono) + text transcripts
 */

const TAG_CAMERA = 0x01;
const TAG_MIC = 0x02;
const TAG_NARRATION = 0x01;

const NARRATION_RATE = 24000;

// DOM
const video = document.getElementById("camera-video");
const canvas = document.getElementById("capture-canvas");
const ctx = canvas.getContext("2d");
const startArea = document.getElementById("start-area");
const startBtn = document.getElementById("start-btn");
const statusPill = document.getElementById("status-pill");
const statusText = document.getElementById("status-text");
const transcriptBar = document.getElementById("transcript-bar");
const transcriptText = document.getElementById("transcript-text");

// State
let ws = null;
let audioCtx = null;
let narrationGain = null;
let narrationNextTime = 0;
let micStream = null;
let micWorklet = null;
let capturing = false;
let connected = false;

// ── Camera ──────────────────────────────────────────────

async function startCamera() {
  const stream = await navigator.mediaDevices.getUserMedia({
    video: { facingMode: "environment", width: { ideal: 768 }, height: { ideal: 768 } },
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
  canvas.width = 768;
  canvas.height = 768;
  ctx.drawImage(video, (vw - size) / 2, (vh - size) / 2, size, size, 0, 0, 768, 768);

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
      setTimeout(captureLoop, 1000);
    },
    "image/jpeg",
    0.7,
  );
}

// ── Mic ─────────────────────────────────────────────────

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

// ── Audio Playback ──────────────────────────────────────

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

// ── WebSocket ───────────────────────────────────────────

function connectWS() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${proto}//${location.host}/ws/chat`);
  ws.binaryType = "arraybuffer";

  ws.onopen = () => {
    console.log("[WS] Connected");
    connected = true;
    setStatus("connected", "Connected");

    // Tell server to start Gemini session
    ws.send(JSON.stringify({ type: "start" }));

    // Start streaming camera now that WS is open
    captureLoop();
  };

  ws.onmessage = (e) => {
    if (typeof e.data === "string") {
      const msg = JSON.parse(e.data);
      if (msg.type === "narration") {
        showTranscript(msg.text);
      }
    } else {
      const data = new Uint8Array(e.data);
      if (data.length < 2) return;
      const tag = data[0];
      if (tag === TAG_NARRATION) {
        const pcm = data.slice(1);
        const int16 = new Int16Array(pcm.buffer, pcm.byteOffset, pcm.byteLength / 2);
        playNarrationChunk(int16);
        setStatus("listening", "Speaking");
        clearTimeout(connectWS._speakTimer);
        connectWS._speakTimer = setTimeout(() => {
          setStatus("connected", "Connected");
        }, 1500);
      }
    }
  };

  ws.onclose = () => {
    console.log("[WS] Disconnected");
    connected = false;
    setStatus("offline", "Offline");
    setTimeout(() => {
      if (capturing) connectWS();
    }, 2000);
  };

  ws.onerror = (err) => console.error("[WS] Error", err);
}

// ── UI ──────────────────────────────────────────────────

function setStatus(state, text) {
  statusPill.className = "status-pill " + (state === "offline" ? "" : state);
  statusText.textContent = text;
}

function showTranscript(text) {
  transcriptBar.classList.add("visible");
  transcriptText.textContent = `"${text}"`;
  clearTimeout(showTranscript._timer);
  showTranscript._timer = setTimeout(() => {
    transcriptBar.classList.remove("visible");
  }, 8000);
}

// ── Start ───────────────────────────────────────────────

async function startChat() {
  startBtn.disabled = true;
  startBtn.textContent = "CONNECTING...";

  try {
    initAudio();
    await startCamera();
  } catch (err) {
    alert("Camera access required: " + err.message);
    startBtn.disabled = false;
    startBtn.textContent = "CONNECT";
    return;
  }

  try {
    await startMic();
  } catch (err) {
    console.warn("Mic not available:", err);
  }

  capturing = true;
  startArea.classList.add("hidden");
  connectWS();
}

startBtn.addEventListener("click", startChat);
