"""
Test: Lyria RealTime API — music generation + dynamic mood transitions

What this tests:
  1. WebSocket connection to Lyria RealTime (v1alpha)
  2. Initial music generation from a text prompt
  3. Smooth transitions: changing density, brightness, and prompts mid-stream
  4. BPM change via reset_context() — measure the audio gap
  5. Playing the output audio (48kHz stereo PCM)

Usage:
  uv run python tests/test_lyria_music.py

Requirements:
  - GEMINI_API_KEY in .env (same key works for Lyria)
  - Speakers/headphones

Controls:
  - The script cycles through moods automatically every 8 seconds
  - Press Ctrl+C to stop
"""

import asyncio
import os
import sys
import time

import pyaudio
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    print("ERROR: Set GEMINI_API_KEY in .env")
    sys.exit(1)

MODEL = "models/lyria-realtime-exp"

# Audio output config — Lyria outputs 48kHz stereo 16-bit PCM
FORMAT = pyaudio.paInt16
CHANNELS = 2
SAMPLE_RATE = 48000

# Music mood definitions — these map to the game states
# NOTE: BPM is fixed at 100 to avoid reset_context() gaps.
# Only density, brightness, and prompts change smoothly.
MOODS = {
    "idle": {
        "density": 0.2,
        "brightness": 0.3,
        "prompts": [
            types.WeightedPrompt(text="ambient lo-fi chill melancholy sparse piano", weight=1.0),
        ],
    },
    "approaching": {
        "density": 0.4,
        "brightness": 0.5,
        "prompts": [
            types.WeightedPrompt(text="hopeful building anticipation light acoustic guitar", weight=1.0),
        ],
    },
    "action_scored": {
        "density": 0.7,
        "brightness": 0.8,
        "prompts": [
            types.WeightedPrompt(text="triumphant bright celebration orchestral uplifting", weight=1.0),
        ],
    },
    "streak": {
        "density": 0.8,
        "brightness": 0.9,
        "prompts": [
            types.WeightedPrompt(text="energetic driving momentum upbeat electronic funk", weight=1.0),
        ],
    },
    "legendary": {
        "density": 1.0,
        "brightness": 1.0,
        "prompts": [
            types.WeightedPrompt(text="epic heroic powerful full orchestra electronic hybrid", weight=1.0),
        ],
    },
    "draining": {
        "density": 0.15,
        "brightness": 0.2,
        "prompts": [
            types.WeightedPrompt(text="somber lonely sparse desolate ambient dark", weight=1.0),
        ],
    },
    "final_minute": {
        "density": 0.9,
        "brightness": 0.7,
        "prompts": [
            types.WeightedPrompt(text="urgent tense racing against time dramatic percussion", weight=1.0),
        ],
    },
    "victory": {
        "density": 0.9,
        "brightness": 1.0,
        "prompts": [
            types.WeightedPrompt(text="victorious celebration triumphant fanfare bright joyful", weight=1.0),
        ],
    },
    "defeat": {
        "density": 0.3,
        "brightness": 0.3,
        "prompts": [
            types.WeightedPrompt(text="bittersweet reflective gentle piano fading", weight=1.0),
        ],
    },
}

# Order to cycle through moods during the test
MOOD_SEQUENCE = [
    "idle", "approaching", "action_scored", "streak",
    "legendary", "draining", "final_minute", "victory", "defeat",
]


async def play_audio(session):
    """Receive audio chunks from Lyria and play them."""
    pya = pyaudio.PyAudio()
    speaker = pya.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=SAMPLE_RATE,
        output=True,
        frames_per_buffer=4096,
    )

    print("[AUDIO] Playing music...")
    chunk_count = 0
    try:
        async for msg in session.receive():
            if msg.server_content and msg.server_content.audio_chunks:
                for chunk in msg.server_content.audio_chunks:
                    speaker.write(chunk.data)
                    chunk_count += 1
                    if chunk_count % 25 == 0:
                        print(f"  [AUDIO] Played {chunk_count} chunks")

            if hasattr(msg, "filtered_prompt") and msg.filtered_prompt:
                print(f"  [FILTER] Prompt was filtered: {msg.filtered_prompt}")
    finally:
        speaker.stop_stream()
        speaker.close()
        pya.terminate()
        print("[AUDIO] Speaker closed.")


async def cycle_moods(session):
    """Cycle through mood states to test smooth transitions."""
    # Wait for initial settling
    print("\n[MOOD] Waiting 6s for initial music to settle...")
    await asyncio.sleep(6)

    for mood_name in MOOD_SEQUENCE:
        mood = MOODS[mood_name]
        print(f"\n{'='*50}")
        print(f"  TRANSITIONING TO: {mood_name.upper()}")
        print(f"  density={mood['density']}, brightness={mood['brightness']}")
        print(f"  prompt: {mood['prompts'][0].text[:60]}...")
        print(f"{'='*50}")

        await session.set_weighted_prompts(prompts=mood["prompts"])
        await session.set_music_generation_config(
            config=types.LiveMusicGenerationConfig(
                density=mood["density"],
                brightness=mood["brightness"],
            )
        )

        # Listen for 8 seconds per mood
        await asyncio.sleep(8)

    # Test BPM change with reset_context
    print(f"\n{'='*50}")
    print("  TESTING BPM CHANGE (requires reset_context)")
    print("  Changing from 100 BPM to 140 BPM")
    print("  NOTE: This will cause an audio gap!")
    print(f"{'='*50}")

    t_start = time.time()
    await session.set_music_generation_config(
        config=types.LiveMusicGenerationConfig(bpm=140)
    )
    await session.reset_context()
    elapsed = time.time() - t_start
    print(f"  reset_context() took {elapsed:.2f}s")

    print("\n[MOOD] Waiting 8s for BPM-changed music to settle...")
    await asyncio.sleep(8)

    print("\n[MOOD] All mood tests complete!")


async def main():
    print("=" * 60)
    print("  LYRIA REALTIME API TEST")
    print("  Music Generation + Dynamic Mood Transitions")
    print("=" * 60)
    print()
    print(f"Model: {MODEL}")
    print("Press Ctrl+C to stop\n")

    client = genai.Client(
        api_key=GEMINI_API_KEY,
        http_options={"api_version": "v1alpha"},
    )

    initial_mood = MOODS["idle"]

    print("Connecting to Lyria RealTime...")
    async with client.aio.live.music.connect(model=MODEL) as session:
        print("Connected!")

        # Set initial config
        await session.set_weighted_prompts(prompts=initial_mood["prompts"])
        await session.set_music_generation_config(
            config=types.LiveMusicGenerationConfig(
                bpm=100,
                density=initial_mood["density"],
                brightness=initial_mood["brightness"],
                guidance=4.0,
                temperature=1.1,
            )
        )

        # Start playback
        await session.play()
        print("[MUSIC] Playback started with 'idle' mood (BPM=100)\n")

        try:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(play_audio(session))
                tg.create_task(cycle_moods(session))
        except* KeyboardInterrupt:
            print("\nStopping...")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nDone.")
