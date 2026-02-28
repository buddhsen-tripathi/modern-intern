"""
Test: Gemini Live API — phone camera + voice chat with smart VAD

Gemini sees your camera feed continuously. Audio uses a 3-state system:
  IDLE → speak for 0.5s+ → LISTENING (audio forwarded to Gemini)
  LISTENING → 2s silence → IDLE
  RESPONDING → Gemini is talking, mic muted so it won't get interrupted
  RESPONDING → Gemini finishes → IDLE

Usage:
  uv run python tests/test_gemini_chat.py
  uv run python tests/test_gemini_chat.py --index 0

Controls:
  - Speak towards the phone to talk to Gemini
  - Press 'q' in the preview window to quit
  - Press Ctrl+C in terminal to quit
"""

import asyncio
import os
import queue
import sys
import threading
import time

import cv2
import pyaudio
import webrtcvad
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    print("ERROR: Set GEMINI_API_KEY in .env")
    sys.exit(1)

MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"

# Audio config
FORMAT = pyaudio.paInt16
CHANNELS = 1
SEND_SAMPLE_RATE = 16000
RECEIVE_SAMPLE_RATE = 24000
MIC_CHUNK = 480  # 30ms at 16kHz (webrtcvad needs 10/20/30ms frames)

# VAD config
VAD_AGGRESSIVENESS = 3  # 0-3, higher filters more non-speech
SPEECH_ONSET_SEC = 0.5  # must speak this long before audio is sent to Gemini
SILENCE_TIMEOUT_SEC = 2.0  # this long of silence → back to idle

SYSTEM_PROMPT = """\
You are a helpful, conversational AI assistant with access to a live camera feed.
You can see what the user's camera is pointing at in real time.

BEHAVIOR:
- Answer questions about what you see naturally and concisely
- When the user asks "what do you see?" describe the scene briefly
- Keep responses SHORT (1-3 sentences) so the conversation feels natural
- Be casual and friendly, like a knowledgeable friend looking over their shoulder
- If you're not sure what something is, say so honestly
- You can reference things you saw earlier in the conversation
"""

CONFIG = types.LiveConnectConfig(
    response_modalities=["AUDIO"],
    system_instruction=types.Content(
        parts=[types.Part(text=SYSTEM_PROMPT)]
    ),
    speech_config=types.SpeechConfig(
        voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                voice_name="Charon"
            )
        )
    ),
    context_window_compression=types.ContextWindowCompressionConfig(
        sliding_window=types.SlidingWindow(),
    ),
)

# ── Shared state ──────────────────────────────────────────────
should_stop = asyncio.Event()
audio_queue = queue.Queue()

# Mic states: IDLE / PENDING / LISTENING
# IDLE      — not sending audio, watching for speech onset
# PENDING   — speech detected, accumulating to confirm it's sustained
# LISTENING — forwarding audio to Gemini
mic_state = "IDLE"
mic_state_lock = threading.Lock()

# Gemini speaking flag — when True, mic is muted to prevent interruptions
gemini_speaking = False
gemini_speaking_lock = threading.Lock()


def set_mic_state(new_state):
    global mic_state
    with mic_state_lock:
        old = mic_state
        mic_state = new_state
    if old != new_state:
        print(f"[STATE] {old} → {new_state}")


def get_mic_state():
    with mic_state_lock:
        return mic_state


def set_gemini_speaking(val):
    global gemini_speaking
    with gemini_speaking_lock:
        gemini_speaking = val


def is_gemini_speaking():
    with gemini_speaking_lock:
        return gemini_speaking


def parse_camera_arg():
    if "--url" in sys.argv:
        idx = sys.argv.index("--url")
        if idx + 1 < len(sys.argv):
            return sys.argv[idx + 1]
    if "--index" in sys.argv:
        idx = sys.argv.index("--index")
        if idx + 1 < len(sys.argv):
            return int(sys.argv[idx + 1])
    return 1  # default: iPhone Continuity Camera


# ── Audio playback (separate thread) ─────────────────────────

def audio_player_thread():
    pya = pyaudio.PyAudio()
    speaker = pya.open(
        format=FORMAT, channels=CHANNELS, rate=RECEIVE_SAMPLE_RATE, output=True,
    )
    try:
        while True:
            data = audio_queue.get()
            if data is None:
                break
            speaker.write(data)
    finally:
        speaker.stop_stream()
        speaker.close()
        pya.terminate()
        print("[SPEAKER] Closed.")


def clear_audio_queue():
    while not audio_queue.empty():
        try:
            audio_queue.get_nowait()
        except queue.Empty:
            break


# ── Video ─────────────────────────────────────────────────────

async def send_video(session, camera_source):
    print(f"[VIDEO] Opening camera: {camera_source}")
    cap = cv2.VideoCapture(camera_source)

    if not cap.isOpened():
        print(f"ERROR: Could not open camera: {camera_source}")
        should_stop.set()
        return

    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"[VIDEO] Camera open: {w}x{h}")
    print("[VIDEO] Press 'q' in preview window to quit\n")

    frames_sent = 0
    last_send = 0.0

    try:
        while not should_stop.is_set():
            ret, frame = cap.read()
            if not ret:
                await asyncio.sleep(0.01)
                continue

            # Show preview with state overlay
            display = cv2.resize(frame, (640, 480))
            state = get_mic_state()
            if is_gemini_speaking():
                cv2.putText(display, "Gemini speaking...", (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 200, 0), 1)
            elif state == "LISTENING":
                cv2.putText(display, "LISTENING...", (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            elif state == "PENDING":
                cv2.putText(display, "Detecting speech...", (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 1)

            cv2.imshow("Gemini Chat (q to quit)", display)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                should_stop.set()
                break

            # Send to Gemini at 1 FPS
            now = time.monotonic()
            if now - last_send >= 1.0:
                small = cv2.resize(frame, (768, 768))
                _, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 70])

                await session.send_realtime_input(
                    video=types.Blob(data=buf.tobytes(), mime_type="image/jpeg")
                )
                frames_sent += 1
                last_send = now

                if frames_sent % 10 == 0:
                    print(f"[VIDEO] Sent {frames_sent} frames")

            await asyncio.sleep(0.01)
    finally:
        cap.release()
        cv2.destroyAllWindows()
        print("[VIDEO] Camera closed.")


# ── Audio (mic → Gemini with smart VAD) ──────────────────────

async def send_audio(session):
    pya = pyaudio.PyAudio()

    # Find iPhone mic, fall back to default
    mic_index = None
    for i in range(pya.get_device_count()):
        info = pya.get_device_info_by_index(i)
        if info["maxInputChannels"] > 0 and "iPhone" in info["name"]:
            mic_index = i
            print(f"[MIC] Using iPhone: {info['name']}")
            break

    if mic_index is None:
        try:
            info = pya.get_default_input_device_info()
            mic_index = int(info["index"])
            print(f"[MIC] iPhone mic not found, using default: {info['name']}")
        except Exception as e:
            print(f"WARNING: No mic ({e}). Voice chat disabled.")
            return

    stream = pya.open(
        format=FORMAT, channels=CHANNELS, rate=SEND_SAMPLE_RATE,
        input=True, input_device_index=mic_index,
        frames_per_buffer=MIC_CHUNK,
    )

    vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)
    silence = b"\x00" * MIC_CHUNK * 2  # 2 bytes per sample (16-bit)

    speech_start = 0.0  # when continuous speech started
    last_speech = 0.0  # last time speech was detected
    pending_buffer = []  # buffered audio during PENDING state

    print(f"[MIC] VAD active (aggressiveness={VAD_AGGRESSIVENESS})")
    print(f"[MIC] Speak for {SPEECH_ONSET_SEC}s to activate, {SILENCE_TIMEOUT_SEC}s silence to deactivate\n")

    try:
        while not should_stop.is_set():
            data = await asyncio.to_thread(stream.read, MIC_CHUNK, exception_on_overflow=False)
            now = time.monotonic()
            state = get_mic_state()

            try:
                is_speech = vad.is_speech(data, SEND_SAMPLE_RATE)
            except Exception:
                is_speech = False

            # If Gemini is speaking, always send silence (don't interrupt)
            if is_gemini_speaking():
                await session.send_realtime_input(
                    audio=types.Blob(data=silence, mime_type="audio/pcm;rate=16000")
                )
                # Reset mic state so we're ready when Gemini finishes
                if state != "IDLE":
                    pending_buffer = []
                    set_mic_state("IDLE")
                continue

            if state == "IDLE":
                if is_speech:
                    # Speech detected — start confirming
                    speech_start = now
                    pending_buffer = [data]
                    set_mic_state("PENDING")
                else:
                    await session.send_realtime_input(
                        audio=types.Blob(data=silence, mime_type="audio/pcm;rate=16000")
                    )

            elif state == "PENDING":
                pending_buffer.append(data)

                if is_speech:
                    if now - speech_start >= SPEECH_ONSET_SEC:
                        # Confirmed! Send all buffered audio
                        for chunk in pending_buffer:
                            await session.send_realtime_input(
                                audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000")
                            )
                        pending_buffer = []
                        last_speech = now
                        set_mic_state("LISTENING")
                else:
                    # Speech stopped before onset threshold — false alarm
                    if now - speech_start > SPEECH_ONSET_SEC:
                        pending_buffer = []
                        set_mic_state("IDLE")

            elif state == "LISTENING":
                await session.send_realtime_input(
                    audio=types.Blob(data=data, mime_type="audio/pcm;rate=16000")
                )

                if is_speech:
                    last_speech = now

                # Silence timeout → done talking, back to idle
                if now - last_speech > SILENCE_TIMEOUT_SEC:
                    set_mic_state("IDLE")

    finally:
        stream.stop_stream()
        stream.close()
        pya.terminate()
        print("[MIC] Closed.")


# ── Receive Gemini responses ─────────────────────────────────

async def receive_responses(session):
    print("[SPEAKER] Ready.\n")
    turn_count = 0
    text_buffer = ""

    try:
        while not should_stop.is_set():
            try:
                async for msg in session.receive():
                    if should_stop.is_set():
                        break

                    if msg.data:
                        audio_queue.put(msg.data)
                        # Gemini is sending audio — mute mic
                        if not is_gemini_speaking():
                            set_gemini_speaking(True)
                            print("[GEMINI] Speaking...")

                    if msg.text:
                        text_buffer += msg.text

                    if hasattr(msg, "server_content") and msg.server_content:
                        sc = msg.server_content

                        if hasattr(sc, "interrupted") and sc.interrupted:
                            clear_audio_queue()
                            set_gemini_speaking(False)
                            print("[INTERRUPTED] You cut in — listening...")
                            text_buffer = ""

                        if hasattr(sc, "turn_complete") and sc.turn_complete:
                            turn_count += 1
                            if text_buffer.strip():
                                print(f"\n[GEMINI] {text_buffer.strip()}")
                            text_buffer = ""
                            set_gemini_speaking(False)
                            print(f"--- turn {turn_count} done ---")

            except Exception as e:
                if should_stop.is_set():
                    break
                print(f"[RECEIVE] Error: {e}. Reconnecting...")
                await asyncio.sleep(1.0)
    finally:
        audio_queue.put(None)


# ── Main ──────────────────────────────────────────────────────

async def main():
    camera_source = parse_camera_arg()

    print("=" * 60)
    print("  GEMINI LIVE — VOICE + VIDEO CHAT")
    print("  Speak to talk. Video streams continuously.")
    print("=" * 60)
    print(f"\nModel: {MODEL}")
    print(f"Camera: {camera_source}\n")

    client = genai.Client(api_key=GEMINI_API_KEY)

    player = threading.Thread(target=audio_player_thread, daemon=True)
    player.start()

    print("Connecting to Gemini Live API...")
    async with client.aio.live.connect(model=MODEL, config=CONFIG) as session:
        print("Connected!\n")

        await session.send_client_content(
            turns=types.Content(
                role="user",
                parts=[types.Part(text=(
                    "Hey! I've got my camera on. I'll talk to you when I have questions. "
                    "Keep responses short and natural. Wait for me to speak first."
                ))],
            ),
            turn_complete=True,
        )

        try:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(send_video(session, camera_source))
                tg.create_task(send_audio(session))
                tg.create_task(receive_responses(session))
        except KeyboardInterrupt:
            should_stop.set()
        except Exception as eg:
            should_stop.set()
            for e in eg.exceptions:
                print(f"Error: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nDone.")
