import asyncio
import traceback
from openai import OpenAI
import config

client = OpenAI(
    base_url=config.NVIDIA_BASE_URL,
    api_key=config.NVIDIA_API_KEY
)


def _summarize(existing_summary, new_messages):
    transcript = "\n".join(f"{m['speaker']}: {m['content']}" for m in new_messages)

    prompt = (
        f"Existing campaign summary:\n{existing_summary or '(none yet)'}\n\n"
        f"New events:\n{transcript}\n\n"
        "Write an updated, concise running summary (under 300 words) of the campaign "
        "so far, preserving important plot points, character decisions, and world state. "
        "Merge the new events into the existing summary rather than just appending."
    )

    completion = client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[
            {"role": "system", "content": "You summarize tabletop RPG campaign logs concisely."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3,
        max_tokens=500
    )

    return completion.choices[0].message.content


async def summarize(existing_summary, new_messages):
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_summarize, existing_summary, new_messages),
            timeout=config.LLM_TIMEOUT
        )
    except Exception as e:
        print(f"[SUMMARY] Summarization failed: {e}")
        traceback.print_exc()
        return existing_summary
