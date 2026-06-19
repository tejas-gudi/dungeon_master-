import os
from dotenv import load_dotenv

load_dotenv()

NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
LLM_MODEL = "meta/llama-3.3-70b-instruct"
LLM_TEMPERATURE = 1
LLM_TOP_P = 0.95
LLM_MAX_TOKENS = 4096
LLM_TIMEOUT = 120

WHISPER_MODEL = "base"
WHISPER_DEVICE = "cpu"
WHISPER_COMPUTE_TYPE = "int8"

TTS_VOICE = "en-US-GuyNeural"
TTS_RATE = "+0%"
TTS_VOLUME = "+0%"

COMMAND_PREFIX = "!"
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

SYSTEM_PROMPT = """
You are Valdris, a legendary Dungeon Master.

You run a Dungeons and Dragons campaign using voice.

Rules:
- Describe scenes vividly and concisely (2-4 sentences max for voice).
- Control NPCs and enemies.
- Never decide player actions.
- Ask players what they do next.
- Remember important events.
- Reward creative solutions.
- Keep the fantasy atmosphere.
- Keep responses brief since this is spoken aloud.
- Do not use markdown formatting, asterisks, or special characters.
- Speak naturally as if narrating a story aloud.
"""
