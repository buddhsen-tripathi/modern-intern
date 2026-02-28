"""All constants for Social Alchemist."""

import os

# Server
HOST = "0.0.0.0"
PORT = 8080

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
SPEECH_ONSET_SEC = 0.5
SILENCE_TIMEOUT_SEC = 2.0
VAD_CHUNK_SIZE = 480  # 30ms at 16kHz

# Game
GAME_DURATION = 180  # 3 minutes
NUDGE_INTERVAL = 15

# Rank thresholds
RANK_THRESHOLDS = [
    ("Platinum", 700),
    ("Gold", 400),
    ("Silver", 200),
    ("Bronze", 0),
]

# WebSocket binary tags (phone → server)
TAG_CAMERA = 0x01
TAG_MIC_AUDIO = 0x02

# WebSocket binary tags (server → phone)
TAG_NARRATION_AUDIO = 0x01
TAG_MUSIC_AUDIO = 0x02
