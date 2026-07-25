import asyncio
import traceback
from openai import OpenAI
import config


client = OpenAI(
    base_url=config.NVIDIA_BASE_URL,
    api_key=config.NVIDIA_API_KEY
)


def ask_dm(message, history=None, speaker_name=None, summary=None, elaborate=False):

    messages = [
        {
            "role": "system",
            "content": config.SYSTEM_PROMPT
        }
    ]

    if summary:
        messages.append({
            "role": "system",
            "content": f"Campaign summary so far: {summary}"
        })

    if elaborate:
        messages.append({
            "role": "system",
            "content": "For this reply only, give a fuller, more elaborate and vivid "
                        "description than usual — the player explicitly asked for more detail."
        })

    if history:
        for entry in history[-20:]:
            messages.append(entry)

    content = f"{speaker_name}: {message}" if speaker_name else message
    messages.append({
        "role": "user",
        "content": content
    })

    completion = client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=messages,
        temperature=config.LLM_TEMPERATURE,
        top_p=config.LLM_TOP_P,
        max_tokens=config.LLM_MAX_TOKENS if elaborate else config.LLM_MAX_TOKENS_CONCISE
    )

    return completion.choices[0].message.content


async def get_response(message, history=None, speaker_name=None, summary=None, elaborate=False):
    try:
        reply = await asyncio.wait_for(
            asyncio.to_thread(ask_dm, message, history, speaker_name, summary, elaborate),
            timeout=config.LLM_TIMEOUT
        )
        return reply
    except asyncio.TimeoutError:
        print("AI request timed out")
        return "The spirits are taking too long to respond. Try again later."
    except Exception as e:
        print(f"AI request failed: {e}")
        traceback.print_exc()
        return "Sorry, I failed to conjure a response. Try again later."
