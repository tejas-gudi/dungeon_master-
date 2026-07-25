import io
import re
import traceback
import zlib
from urllib.parse import quote

import aiohttp

import config


def _clean(text, max_len):
    text = re.sub(r"[*_`#>\[\]]", "", text)
    text = " ".join(text.split())
    return text[:max_len]


def _build_prompt(reply_text, party_desc=None, summary_anchor=None):
    scene = _clean(reply_text, 300)

    anchor_parts = []
    if summary_anchor:
        anchor_parts.append(f"Ongoing story so far: {_clean(summary_anchor, 200)}")
    if party_desc:
        anchor_parts.append(f"The party: {_clean(party_desc, 150)}")

    anchor = ". ".join(anchor_parts)
    prompt = f"{anchor}. {scene}" if anchor else scene
    return f"{prompt}, {config.IMAGE_STYLE_SUFFIX}"


def _stable_seed(channel_id):
    return zlib.crc32(str(channel_id).encode()) % 1_000_000


async def generate_scene_image(reply_text, party_desc=None, summary_anchor=None, channel_id=None):
    if not config.IMAGE_ENABLED or not reply_text.strip():
        return None

    prompt = _build_prompt(reply_text, party_desc, summary_anchor)
    url = f"{config.IMAGE_BASE_URL}/{quote(prompt)}"
    params = {
        "width": str(config.IMAGE_WIDTH),
        "height": str(config.IMAGE_HEIGHT),
        "nologo": "true",
    }
    if channel_id is not None:
        params["seed"] = str(_stable_seed(channel_id))

    try:
        timeout = aiohttp.ClientTimeout(total=config.IMAGE_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    print(f"[IMAGE] Generation failed with status {resp.status}")
                    return None
                data = await resp.read()
                return io.BytesIO(data)
    except Exception as e:
        print(f"[IMAGE] Generation error: {e}")
        traceback.print_exc()
        return None
