"""All constants for JOYBAIT."""

import os

# Server
HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", 8080))

# Gemini
GEMINI_MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"
GEMINI_VOICE = os.environ.get("GEMINI_VOICE", "Aoede")

# Lyria
LYRIA_MODEL = "models/lyria-realtime-exp"
LYRIA_BPM = 100
LYRIA_GUIDANCE = 4.0
LYRIA_TEMPERATURE = 1.1

# Audio rates
MIC_SAMPLE_RATE = 16000
NARRATION_SAMPLE_RATE = 24000
MUSIC_SAMPLE_RATE = 48000

# VAD
VAD_AGGRESSIVENESS = 3
SPEECH_ONSET_SEC = 0.3
SILENCE_TIMEOUT_SEC = 1.5
VAD_CHUNK_SIZE = 480  # 30ms at 16kHz

# Game Brain (long-context memory model)
BRAIN_MODEL = "gemini-2.5-flash"
BRAIN_MAX_HISTORY = 200  # max events to keep in brain memory

# Game
GAME_DURATION = 180  # 3 minutes
NUDGE_RESUME_DELAY = 5  # seconds after player stops talking before nudger resumes
IDLE_PENALTY_TIMEOUT = 10  # seconds without scoring before idle penalty
IDLE_PENALTY_POINTS = 3

# Adaptive nudge intervals (event-driven)
NUDGE_IDLE_INTERVAL = 8  # when player is idle
NUDGE_ACTIVE_INTERVAL = 20  # when player is socializing
NUDGE_POST_TASK_DELAY = 5  # after task completion
NUDGE_FINAL_MINUTE_INTERVAL = 12

# Rank thresholds
RANK_THRESHOLDS = [
    ("Goated", 700),
    ("Fire", 400),
    ("Valid", 200),
    ("Basic", 0),
]

# WebSocket binary tags (phone → server)
TAG_CAMERA = 0x01
TAG_MIC_AUDIO = 0x02

# WebSocket binary tags (server → phone)
TAG_NARRATION_AUDIO = 0x01
TAG_MUSIC_AUDIO = 0x02
