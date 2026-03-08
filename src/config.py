"""Configuration for Silas — gesture-based personal assistant."""

import os

# Server
HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", 8080))

# Gemini
GEMINI_MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"
GEMINI_VOICE = os.environ.get("GEMINI_VOICE", "Aoede")
BRAIN_MODEL = "gemini-2.5-flash"

# Audio rates
MIC_SAMPLE_RATE = 16000
NARRATION_SAMPLE_RATE = 24000

# VAD
VAD_AGGRESSIVENESS = 3
SPEECH_ONSET_SEC = 0.3
SILENCE_TIMEOUT_SEC = 1.5
VAD_CHUNK_SIZE = 480  # 30ms at 16kHz

# Gesture detection
GESTURE_COOLDOWN_SEC = 3.0  # minimum gap between gesture triggers

# Watcher intervals (how often Gemini checks the scene for gestures)
WATCHER_INTERVAL = 5  # seconds between gesture checks
WATCHER_RESUME_DELAY = 3  # seconds after user stops talking before watcher resumes

# WebSocket binary tags (phone -> server)
TAG_CAMERA = 0x01
TAG_MIC_AUDIO = 0x02

# WebSocket binary tags (server -> phone)
TAG_NARRATION_AUDIO = 0x01
