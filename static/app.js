/**
 * Social Alchemist — Game Client
 *
 * Two-phase start:
 *   1. ENTER REALM → init camera/audio/WS, request intro narration
 *   2. BEGIN QUEST → start game timer + scoring (enabled after intro finishes)
 *
 * Camera → JPEG 1FPS → WS
 * Mic → 16kHz PCM → WS (via AudioWorklet)
 * WS → narration audio (24kHz mono) + music audio (48kHz stereo) + JSON state
 * Web Audio API mixes narration (gain=1.0) + music (gain=0.25)
 */

// ── Constants ───────────────────────────────────────────
const TAG_CAMERA = 0x01;
const TAG_MIC = 0x02;
const TAG_NARRATION = 0x01;
const TAG_MUSIC = 0x02;

const NARRATION_RATE = 24000;
const MUSIC_RATE = 48000;

// ── DOM refs ────────────────────────────────────────────
const video = document.getElementById("camera-video");
const canvas = document.getElementById("capture-canvas");
const ctx = canvas.getContext("2d");
const startScreen = document.getElementById("start-screen");
const startBtn = document.getElementById("start-btn");
const startHint = document.getElementById("start-hint");
const introArea = document.getElementById("intro-area");
const introText = document.getElementById("intro-text");
const hud = document.getElementById("hud");
const gameoverScreen = document.getElementById("gameover-screen");

const timerEl = document.getElementById("timer");
const streakEl = document.getElementById("streak-count");
const streakContainer = document.getElementById("streak-container");
const multEl = document.getElementById("multiplier");
const rankEl = document.getElementById("rank-badge");
const essenceBar = document.getElementById("essence-fill");
const essenceGlow = document.getElementById("essence-glow");
const essenceVal = document.getElementById("essence-value");
const narrationText = document.getElementById("narration-text");
const micDot = document.getElementById("mic-dot");
const toastContainer = document.getElementById("toast-container");

const goTitle = document.getElementById("go-title");
const goRank = document.getElementById("go-rank");
const goScore = document.getElementById("go-score");
const goStreak = document.getElementById("go-best-streak");
const goMultiplier = document.getElementById("go-multiplier");
const replayBtn = document.getElementById("replay-btn");

// ── State ───────────────────────────────────────────────
let ws = null;
let audioCtx = null;
let narrationGain = null;
let musicGain = null;
let narrationNextTime = 0;
let musicNextTime = 0;
let micStream = null;
let micWorklet = null;
let capturing = false;
let bestStreak = 0;
let bestMultiplier = 1;
let lastState = null;

// Intro tracking
let phase = "idle"; // idle → intro → playing
let introAudioReceived = false;
let introEndTimer = null;

// ── Helpers ─────────────────────────────────────────────

function formatTime(seconds) {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

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

function stopMic() {
  if (micWorklet) {
    micWorklet.disconnect();
    micWorklet = null;
  }
  if (micStream) {
    micStream.getTracks().forEach((t) => t.stop());
    micStream = null;
  }
}

// ── Audio Playback ──────────────────────────────────────

function initAudio() {
  audioCtx = new AudioContext();

  narrationGain = audioCtx.createGain();
  narrationGain.gain.value = 1.0;
  narrationGain.connect(audioCtx.destination);

  musicGain = audioCtx.createGain();
  musicGain.gain.value = 0.25;
  musicGain.connect(audioCtx.destination);

  narrationNextTime = 0;
  musicNextTime = 0;
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

function playMusicChunk(int16Array) {
  if (!audioCtx || audioCtx.state === "closed") return;
  const samples = int16Array.length / 2;
  if (samples <= 0) return;

  const buffer = audioCtx.createBuffer(2, samples, MUSIC_RATE);
  const left = buffer.getChannelData(0);
  const right = buffer.getChannelData(1);
  for (let i = 0; i < samples; i++) {
    left[i] = int16Array[i * 2] / 32768;
    right[i] = int16Array[i * 2 + 1] / 32768;
  }

  const source = audioCtx.createBufferSource();
  source.buffer = buffer;
  source.connect(musicGain);

  const now = audioCtx.currentTime;
  const start = Math.max(now, musicNextTime);
  source.start(start);
  musicNextTime = start + buffer.duration;
}

// ── WebSocket ───────────────────────────────────────────

function connectWS() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${proto}//${location.host}/ws/game`);
  ws.binaryType = "arraybuffer";

  ws.onopen = () => {
    console.log("[WS] Connected");
    if (phase === "intro") {
      // Send intro request once connected
      ws.send(JSON.stringify({ type: "intro" }));
      startHint.textContent = "SILAS IS AWAKENING...";
      // Start streaming camera now that WS is open
      captureLoop();
    }
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
    setTimeout(() => {
      if (phase !== "idle") connectWS();
    }, 2000);
  };

  ws.onerror = (err) => {
    console.error("[WS] Error", err);
  };
}

function handleJSON(msg) {
  switch (msg.type) {
    case "state":
      updateHUD(msg.data);
      break;
    case "event":
      showToast(msg.data);
      break;
    case "narration":
      if (phase === "intro") {
        showIntroNarration(msg.text);
      } else {
        showNarration(msg.text);
      }
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

    if (phase === "intro") {
      introAudioReceived = true;
      // Reset the "intro done" timer every time we get audio
      clearTimeout(introEndTimer);
      introEndTimer = setTimeout(onIntroDone, 2000);
    } else {
      micDot.classList.remove("listening");
    }
  } else if (tag === TAG_MUSIC) {
    playMusicChunk(int16);
  }
}

// ── Intro Flow ──────────────────────────────────────────

function showIntroNarration(text) {
  introArea.classList.add("visible");
  introText.textContent = `"${text}"`;

  // If no audio comes (e.g. text-only), enable button after delay
  if (!introAudioReceived) {
    clearTimeout(introEndTimer);
    introEndTimer = setTimeout(onIntroDone, 5000);
  }
}

function onIntroDone() {
  console.log("[Intro] Complete — enabling BEGIN QUEST");
  startBtn.textContent = "BEGIN QUEST";
  startBtn.disabled = false;
  startHint.textContent = "TAP TO START THE GAME";

  // Switch handler to begin quest
  startBtn.removeEventListener("click", enterRealm);
  startBtn.addEventListener("click", beginQuest);
}

// ── HUD Updates ─────────────────────────────────────────

function updateHUD(state) {
  lastState = state;

  timerEl.textContent = formatTime(state.timer);

  // Timer warning colors
  if (state.timer <= 30) {
    timerEl.classList.add("critical");
    timerEl.classList.remove("warning");
  } else if (state.timer <= 60) {
    timerEl.classList.add("warning");
    timerEl.classList.remove("critical");
  } else {
    timerEl.classList.remove("warning", "critical");
  }

  streakEl.textContent = state.streak;
  multEl.textContent = `${state.multiplier}x`;

  // Streak glow effects
  if (state.streak >= 5) {
    streakContainer.classList.add("fire");
    streakContainer.classList.remove("hot");
  } else if (state.streak >= 3) {
    streakContainer.classList.add("hot");
    streakContainer.classList.remove("fire");
  } else {
    streakContainer.classList.remove("hot", "fire");
  }

  essenceVal.textContent = state.essence;

  // Essence bar
  const pct = Math.min(100, (state.essence / 1000) * 100);
  essenceBar.style.width = `${pct}%`;

  // Position glow at end of fill
  if (pct > 0) {
    essenceGlow.style.left = `calc(${pct}% - 10px)`;
    essenceGlow.style.opacity = "1";
  } else {
    essenceGlow.style.opacity = "0";
  }

  // Rank badge
  const rankText = rankEl.querySelector(".rank-text");
  if (rankText) rankText.textContent = state.rank;
  rankEl.className = `rank-badge rank-${state.rank}`;

  // Track bests
  if (state.streak > bestStreak) bestStreak = state.streak;
  if (state.multiplier > bestMultiplier) bestMultiplier = state.multiplier;

  // Game over
  if (state.gameOver) {
    showGameOver(state);
  }
}

function showToast(event) {
  const el = document.createElement("div");
  if (event.type === "score") {
    el.className = "toast score";
    el.textContent = `+${event.points} ESSENCE`;
    if (event.multiplier > 1) {
      el.textContent += ` (${event.multiplier}x)`;
    }
  } else {
    el.className = "toast penalize";
    el.textContent = `-${event.points} ESSENCE`;
  }
  toastContainer.appendChild(el);
  el.addEventListener("animationend", () => el.remove());
}

function showNarration(text) {
  narrationText.textContent = `"${text}"`;
  clearTimeout(showNarration._timer);
  showNarration._timer = setTimeout(() => {
    narrationText.textContent = "Awaiting transmission...";
  }, 8000);
}

function showGameOver(state) {
  capturing = false;
  phase = "idle";
  hud.classList.remove("active");
  gameoverScreen.classList.add("active");

  const won = state.essence >= 400;
  goTitle.textContent = won ? "TRANSMUTATION COMPLETE" : "TIME EXPIRED";
  goTitle.style.color = won ? "var(--green-400)" : "var(--red-400)";

  goRank.textContent = state.rank;
  goRank.className = `gameover-rank rank-${state.rank}`;

  goScore.textContent = state.essence;
  goStreak.textContent = bestStreak;
  goMultiplier.textContent = `${bestMultiplier}x`;
}

// ── Start / Enter / Begin / Replay ──────────────────────

async function enterRealm() {
  startBtn.disabled = true;
  startBtn.textContent = "CONNECTING...";
  startHint.textContent = "Initializing systems...";

  try {
    initAudio();
    await startCamera();
  } catch (err) {
    alert("Camera access required: " + err.message);
    startBtn.disabled = false;
    startBtn.textContent = "ENTER REALM";
    startHint.textContent = "Camera + microphone required";
    return;
  }

  try {
    await startMic();
  } catch (err) {
    console.warn("Mic not available:", err);
  }

  phase = "intro";
  introAudioReceived = false;

  // Start streaming camera immediately so Gemini sees from the start
  capturing = true;
  connectWS();
}

async function beginQuest() {
  startBtn.disabled = true;

  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "start" }));
    phase = "playing";
    bestStreak = 0;
    bestMultiplier = 1;

    startScreen.style.display = "none";
    hud.classList.add("active");
    // captureLoop already running from enterRealm — no need to restart
  }
}

function replayGame() {
  gameoverScreen.classList.remove("active");
  phase = "playing";
  capturing = true;
  bestStreak = 0;
  bestMultiplier = 1;
  narrationText.textContent = "Awaiting transmission...";
  narrationNextTime = 0;
  musicNextTime = 0;

  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "start" }));
    hud.classList.add("active");
    captureLoop();
  }
}

// ── Event Listeners ─────────────────────────────────────
startBtn.addEventListener("click", enterRealm);
replayBtn.addEventListener("click", replayGame);
