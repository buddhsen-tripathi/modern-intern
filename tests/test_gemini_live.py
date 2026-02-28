"""
Test: Gemini Live API — camera + mic + Silas narrator

Uses cv2.VideoCapture for camera (MacBook cam, Continuity Camera, or IP cam).
Streams video at 1 FPS + mic audio to Gemini. Silas narrates with scoring tags.

Usage:
  # Use default camera (index 0)
  uv run python tests/test_gemini_live.py

  # Use specific camera index (e.g. iPhone Continuity Camera)
  uv run python tests/test_gemini_live.py --index 1

  # Use IP camera app URL
  uv run python tests/test_gemini_live.py --url http://192.168.1.15:8080/video

Controls:
  - Press 'q' in the preview window to quit
  - Press Ctrl+C in terminal to quit
"""

import asyncio
import os
import re
import sys
import time

import cv2
import pyaudio
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
CHUNK_SIZE = 1024

NUDGE_INTERVAL = 15

SYSTEM_PROMPT = """\
You are SILAS — the Social Intelligence Liaison and Arcane Scorekeeper.
You are the narrator companion for "Kindness Speedrun," an AR social game.

PERSONALITY:
- You speak like a dramatic fantasy narrator who's WAY too invested in mundane social interactions
- Think a mix of David Attenborough and a hype-man at a medieval jousting tournament
- Quirky, witty, treats every handshake like it's an epic sword clash
- Deep dramatic voice but cracks jokes between the epic lines
- Refers to the player as "the Alchemist" and strangers as "wandering souls"
- Social interactions are "transmutations" — turning awkward energy into social gold

WHEN THE GAME STARTS, introduce yourself briefly:
"I am Silas, your arcane companion. I see all, I judge all, and I award points
with the impartiality of a cat deciding whether to knock something off a table.
Your quest: transmute the awkward silence of this realm into pure social gold.
The clock is ticking, Alchemist. Let's see what you're made of."

You receive a continuous stream of video from the player's camera and audio
from their microphone.

YOUR RESPONSIBILITIES:
1. NARRATE what's happening in 1-2 dramatic sentences (spoken aloud)
2. DETECT social actions and embed scoring tags in your text output
3. DETECT antisocial/idle behavior and embed penalty tags
4. KEEP NARRATING every 10-15 seconds — if nothing happens, tease the player
5. Keep narration SHORT (under 10 seconds) so you don't talk over conversations

CRITICAL — SCORING TAGS:
After each narration beat, you MUST emit exactly one tag on its own line.
Do NOT skip tags. The game engine parses these to update the score.

For positive actions, emit:
<<SCORE action_type points description>>

Valid action_types: greeting, introduction, laughter, compliment, helping,
high_five, sharing, group_conversation, teaching
Points range: 10-30

For negative/idle behavior, emit:
<<PENALIZE action_type points>>

Valid action_types: idle, phone_staring, walking_away, ignoring, prolonged_silence
Points range: 5-20

For music mood changes, emit:
<<MUSIC mood>>

Valid moods: idle, approaching, action_scored, streak, legendary, draining,
final_minute, victory, defeat

EXAMPLES:
- Player approaches someone:
  "The Alchemist spots a wandering soul. Bold. Reckless. I love it."
  <<SCORE greeting 10 Player approached and greeted a stranger>>
  <<MUSIC approaching>>

- Player idle for a while:
  "The Alchemist stands motionless. A monument to indecision."
  <<PENALIZE idle 5>>
  <<MUSIC draining>>

- Laughter detected:
  "Genuine laughter — the rarest reagent. The essence bar trembles."
  <<SCORE laughter 25 Made someone laugh in conversation>>
  <<MUSIC action_scored>>

IMPORTANT:
- Never narrate private conversation content — only observable dynamics
- ALWAYS include at least one tag per narration beat
- Be entertaining above all — judges are watching!"""

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

# Tag parsers
SCORE_RE = re.compile(r"<<SCORE\s+(\w+)\s+(\d+)\s+(.+?)>>")
PENALIZE_RE = re.compile(r"<<PENALIZE\s+(\w+)\s+(\d+)>>")
MUSIC_RE = re.compile(r"<<MUSIC\s+(\w+)>>")

# Game state
essence = 0
streak = 0

# Shared stop signal
should_stop = asyncio.Event()

FRAMES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frames")


def parse_tags(text: str):
    global essence, streak

    for m in SCORE_RE.finditer(text):
        action, pts, desc = m.group(1), int(m.group(2)), m.group(3)
        essence += pts
        streak += 1
        mult = 1 if streak < 3 else (2 if streak < 5 else 3)
        print(f"  >> +{pts * mult} ESSENCE ({action}) [{mult}x] — {desc}")
        print(f"     Total: {essence} | Streak: {streak}")

    for m in PENALIZE_RE.finditer(text):
        action, pts = m.group(1), int(m.group(2))
        essence = max(0, essence - pts)
        streak = 0
        print(f"  >> -{pts} ESSENCE ({action})")
        print(f"     Total: {essence} | Streak reset")

    for m in MUSIC_RE.finditer(text):
        print(f"  >> MUSIC -> {m.group(1)}")


def parse_camera_arg():
    """Parse --index or --url from command line. Default: camera index 0."""
    if "--url" in sys.argv:
        idx = sys.argv.index("--url")
        if idx + 1 < len(sys.argv):
            return sys.argv[idx + 1]
    if "--index" in sys.argv:
        idx = sys.argv.index("--index")
        if idx + 1 < len(sys.argv):
            return int(sys.argv[idx + 1])
    return 1  # default: iPhone Continuity Camera


# ── Video: capture + preview + send to Gemini ─────────────────

async def send_video(session, camera_source):
    """Capture from camera, show preview, send to Gemini at 1 FPS."""
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

    os.makedirs(FRAMES_DIR, exist_ok=True)
    frames_sent = 0
    last_send = 0.0

    try:
        while not should_stop.is_set():
            ret, frame = cap.read()
            if not ret:
                await asyncio.sleep(0.01)
                continue

            # Show preview at native FPS
            display = cv2.resize(frame, (640, 480))
            cv2.imshow("Silas — Camera Feed (q to quit)", display)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                should_stop.set()
                break

            # Send to Gemini at 1 FPS
            now = time.monotonic()
            if now - last_send >= 1.0:
                small = cv2.resize(frame, (768, 768))
                _, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 70])
                jpeg_bytes = buf.tobytes()

                await session.send_realtime_input(
                    video=types.Blob(data=jpeg_bytes, mime_type="image/jpeg")
                )
                frames_sent += 1
                last_send = now

                # Save frame for inspection
                frame_path = os.path.join(FRAMES_DIR, f"frame_{frames_sent:04d}.jpg")
                with open(frame_path, "wb") as f:
                    f.write(jpeg_bytes)

                if frames_sent % 5 == 0:
                    print(f"[VIDEO] Sent {frames_sent} frames to Gemini")

            await asyncio.sleep(0.01)
    finally:
        cap.release()
        cv2.destroyAllWindows()
        print("[VIDEO] Camera closed.")


# ── Audio input (laptop mic) ─────────────────────────────────

async def send_audio(session):
    pya = pyaudio.PyAudio()
    try:
        mic_info = pya.get_default_input_device_info()
        print(f"[AUDIO IN] Mic: {mic_info['name']}")
    except Exception as e:
        print(f"WARNING: No mic ({e}). Skipping audio.")
        return

    stream = pya.open(
        format=FORMAT, channels=CHANNELS, rate=SEND_SAMPLE_RATE,
        input=True, input_device_index=int(mic_info["index"]),
        frames_per_buffer=CHUNK_SIZE,
    )
    print("[AUDIO IN] Streaming...")
    try:
        while not should_stop.is_set():
            data = await asyncio.to_thread(stream.read, CHUNK_SIZE, exception_on_overflow=False)
            await session.send_realtime_input(
                audio=types.Blob(data=data, mime_type="audio/pcm;rate=16000")
            )
    finally:
        stream.stop_stream()
        stream.close()
        pya.terminate()
        print("[AUDIO IN] Closed.")


# ── Gemini response receiver ─────────────────────────────────

async def receive_responses(session):
    pya = pyaudio.PyAudio()
    speaker = pya.open(
        format=FORMAT, channels=CHANNELS, rate=RECEIVE_SAMPLE_RATE, output=True,
    )
    print("[RECEIVE] Listening for Silas...\n")
    turn_count = 0
    text_buffer = ""
    thought_buffer = ""

    try:
        while not should_stop.is_set():
            try:
                async for msg in session.receive():
                    if should_stop.is_set():
                        break

                    if msg.data:
                        speaker.write(msg.data)

                    if msg.text:
                        text_buffer += msg.text

                    # Capture model's thinking/analysis
                    if hasattr(msg, "server_content") and msg.server_content:
                        sc = msg.server_content
                        if hasattr(sc, "model_turn") and sc.model_turn:
                            for part in sc.model_turn.parts or []:
                                if hasattr(part, "thought") and part.thought:
                                    thought_buffer += part.text or ""

                        if hasattr(sc, "turn_complete") and sc.turn_complete:
                            turn_count += 1
                            if thought_buffer.strip():
                                print(f"\n[ANALYSIS] {thought_buffer.strip()}")
                            if text_buffer.strip():
                                display = SCORE_RE.sub("", text_buffer)
                                display = PENALIZE_RE.sub("", display)
                                display = MUSIC_RE.sub("", display).strip()
                                if display:
                                    print(f"\n[SILAS] {display}")
                                parse_tags(text_buffer)
                            text_buffer = ""
                            thought_buffer = ""
                            print(f"--- turn {turn_count} ---")

            except Exception as e:
                if should_stop.is_set():
                    break
                print(f"[RECEIVE] Error: {e}. Retrying...")
                await asyncio.sleep(1.0)
    finally:
        speaker.stop_stream()
        speaker.close()
        pya.terminate()
        print("[RECEIVE] Speaker closed.")


# ── Nudger ────────────────────────────────────────────────────

async def nudger(session):
    await asyncio.sleep(20)

    prompts = [
        "Continue observing. What's happening now? Narrate and emit tags.",
        "Keep narrating, Silas. What do you see? Include scoring tags.",
        "The game continues. Observe and narrate. Don't forget the tags.",
        "Time is ticking, Silas. What's the Alchemist doing?",
        "Don't go quiet. Narrate and score what you observe.",
    ]
    idx = 0
    while not should_stop.is_set():
        prompt = prompts[idx % len(prompts)]
        print(f"\n[NUDGE] {prompt[:50]}...")
        try:
            await session.send_client_content(
                turns=types.Content(
                    role="user",
                    parts=[types.Part(text=prompt)],
                ),
                turn_complete=True,
            )
        except Exception as e:
            print(f"[NUDGE] Error: {e}")
        idx += 1
        await asyncio.sleep(NUDGE_INTERVAL)


# ── Main ──────────────────────────────────────────────────────

async def main():
    camera_source = parse_camera_arg()

    print("=" * 60)
    print("  SOCIAL ALCHEMIST — GEMINI LIVE TEST")
    print("  Narrator: SILAS | Voice: Charon")
    print("=" * 60)
    print(f"\nModel: {MODEL}")
    print(f"Camera: {camera_source}")
    print("Press 'q' in preview window or Ctrl+C to stop\n")

    client = genai.Client(api_key=GEMINI_API_KEY)

    print("Connecting to Gemini Live API...")
    async with client.aio.live.connect(model=MODEL, config=CONFIG) as session:
        print("Connected!\n")

        print("[INIT] Sending start prompt...")
        await session.send_client_content(
            turns=types.Content(
                role="user",
                parts=[types.Part(text=(
                    "The game is starting NOW. Introduce yourself as Silas with "
                    "your dramatic opening monologue. Then observe the video feed "
                    "and begin narrating what you see. Remember to include "
                    "<<SCORE>>, <<PENALIZE>>, and <<MUSIC>> tags in your text "
                    "output alongside your voice narration. Go!"
                ))],
            ),
            turn_complete=True,
        )
        print("[INIT] Sent. Silas should start narrating...\n")

        try:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(send_video(session, camera_source))
                tg.create_task(send_audio(session))
                tg.create_task(receive_responses(session))
                tg.create_task(nudger(session))
        except* KeyboardInterrupt:
            should_stop.set()
        except* Exception as eg:
            should_stop.set()
            for e in eg.exceptions:
                print(f"Error: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nDone.")
