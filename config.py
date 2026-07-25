import os
from dotenv import load_dotenv

load_dotenv()

NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
LLM_MODEL = "meta/llama-3.1-8b-instruct"
LLM_TEMPERATURE = 1
LLM_TOP_P = 0.95
LLM_MAX_TOKENS = 4096
LLM_MAX_TOKENS_CONCISE = 220
LLM_TIMEOUT = 120

WHISPER_MODEL = "base"
WHISPER_DEVICE = "cpu"
WHISPER_COMPUTE_TYPE = "int8"

TTS_VOICE = "en-US-GuyNeural"
TTS_RATE = "+0%"
TTS_VOLUME = "+0%"

COMMAND_PREFIX = "!"
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

IMAGE_ENABLED = os.getenv("IMAGE_ENABLED", "true").lower() == "true"
IMAGE_BASE_URL = "https://image.pollinations.ai/prompt"
IMAGE_WIDTH = 512
IMAGE_HEIGHT = 512
IMAGE_TIMEOUT = 20
IMAGE_STYLE_SUFFIX = (
    "Studio Ghibli style anime background art, Hayao Miyazaki inspired, hand-painted "
    "watercolor textures, soft painterly linework, lush detailed nature, warm nostalgic "
    "natural lighting, whimsical gentle atmosphere, vibrant soft color palette, "
    "cel animation style, consistent character designs"
)

SUMMARY_TRIGGER_MESSAGE_COUNT = 20

SYSTEM_PROMPT = """
You are Valdris, a legendary Dungeon Master.

You run a Dungeons and Dragons campaign using voice.

Rules:
- By default, keep replies concise: 2-4 sentences. Only give a longer, fully elaborate
  description when the player has explicitly asked for more detail this turn.
- Control NPCs and enemies.
- Never decide player actions.
- Ask players what they do next.
- Remember important events.
- Reward creative solutions.
- Keep the fantasy atmosphere.
- Do not use markdown formatting, asterisks, or special characters.
- Speak naturally as if narrating a story aloud.
- Each message you receive is prefixed with the character name of whoever is currently
  speaking to you (e.g. "Aria: I search the room"). Always address that specific
  character by name in your reply. Other players' past lines are context for the
  ongoing story, not who you are replying to right now.
- When an action calls for a dice roll (ability check, attack, saving throw, etc.),
  do not ask the player to roll it themselves. Instead include a tag in your reply in
  the exact format [ROLL:XdY+Z] (e.g. [ROLL:1d20+3] for a perception check with a +3
  modifier, or [ROLL:1d20 adv] for advantage). The tag will be automatically resolved
  into an actual dice result. Only include a roll tag when a roll is genuinely needed.
"""
