import asyncio
import os
import re
import traceback
from dotenv import load_dotenv
import discord
from discord.ext import commands
from discord import opus

import config
import dice
import dm
import image as image_mod
import summarizer
import voice as voice_mod
from memory import CampaignMemory
from database import CampaignDatabase

load_dotenv()

if not opus.is_loaded():
    if os.name == "nt":
        opus_path = os.path.join(os.path.dirname(discord.__file__), "bin", "libopus-0.x64.dll")
        if os.path.exists(opus_path):
            opus.load_opus(opus_path)
    else:
        for candidate in ("libopus.so.0", "libopus.so", "opus", "libopus.dylib"):
            try:
                opus.load_opus(candidate)
                break
            except OSError:
                continue

    if not opus.is_loaded():
        print("[WARN] Could not load libopus — voice features (TTS/STT) will not work "
              "until it's installed (e.g. `apt install libopus0` / `brew install opus`).")

intents = discord.Intents.all()

bot = commands.Bot(
    command_prefix=config.COMMAND_PREFIX,
    intents=intents
)

db = CampaignDatabase()
voice_managers = {}
listening_tasks = {}
processing_tasks = {}

SHOW_IMAGE_TRIGGER = re.compile(r"!show\b", re.IGNORECASE)
ELABORATE_TRIGGER = re.compile(r"!info\b", re.IGNORECASE)


def party_description(memory):
    names = [p["character_name"] for p in memory.state["players"].values()]
    return ", ".join(names) if names else None


def ensure_addressed(reply, speaker_name):
    if not speaker_name or not reply:
        return reply
    if speaker_name.lower() in reply.lower():
        return reply
    return f"{speaker_name}, {reply}"


async def run_background_summary(memory):
    try:
        existing = memory.get_summary()
        recent_messages = memory.get_messages_for_summary()
        new_summary = await summarizer.summarize(existing, recent_messages)
        memory.set_summary(new_summary)
        memory.reset_summary_counter()
    except Exception as e:
        print(f"[SUMMARY] Background summarization failed: {e}")


@bot.event
async def on_ready():
    print(f"{bot.user} is online")
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.listening,
            name="!join to start a voice session"
        )
    )


@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if isinstance(message.channel, discord.DMChannel) or bot.user in message.mentions:
        content = message.content
        for mention in message.mentions:
            content = content.replace(f"<@{mention.id}>", "").replace(f"<@!{mention.id}>", "").strip()

        if not content:
            await message.channel.send("You called, adventurer? Type your message and I shall respond!")
            await bot.process_commands(message)
            return

        show_image = bool(SHOW_IMAGE_TRIGGER.search(content))
        if show_image:
            content = SHOW_IMAGE_TRIGGER.sub("", content).strip()

        elaborate = bool(ELABORATE_TRIGGER.search(content))
        if elaborate:
            content = ELABORATE_TRIGGER.sub("", content).strip()

        if not content:
            content = "Continue the story."

        print(f"{message.author}: {content}")

        memory = CampaignMemory(message.channel.id)
        user_id = message.author.id
        speaker_name = memory.get_character(user_id, fallback=message.author.display_name)

        if not memory.is_players_turn(user_id):
            current_uid = memory.current_turn_user_id()
            current_name = memory.get_character(current_uid, fallback="someone") if current_uid else "someone"
            await message.channel.send(
                f"Hold up, {speaker_name} — it's **{current_name}**'s turn. Wait for them to act."
            )
            await bot.process_commands(message)
            return

        memory.append_message("user", user_id, speaker_name, content)

        async with message.channel.typing():
            reply = await dm.get_response(
                content,
                memory.get_recent_context(),
                speaker_name=speaker_name,
                summary=memory.get_summary(),
                elaborate=elaborate
            )

        reply = dice.resolve_roll_tags(reply)
        reply = ensure_addressed(reply, speaker_name)
        memory.append_message("assistant", None, "Valdris", reply)

        if memory.state["turns_enabled"]:
            memory.advance_turn()

        if memory.messages_since_summary() >= config.SUMMARY_TRIGGER_MESSAGE_COUNT:
            asyncio.create_task(run_background_summary(memory))

        if show_image:
            image_buf = await image_mod.generate_scene_image(
                reply,
                party_desc=party_description(memory),
                summary_anchor=memory.get_summary(),
                channel_id=message.channel.id
            )
        else:
            image_buf = None

        if image_buf:
            await message.channel.send(reply, file=discord.File(image_buf, filename="scene.png"))
        else:
            await message.channel.send(reply)

    await bot.process_commands(message)


@bot.command()
async def roll(ctx, *, args: str = None):
    notation = "1d20"
    mode = None
    if args:
        parts = args.strip().split()
        notation = parts[0]
        if len(parts) > 1 and parts[1].lower() in ("adv", "disadv"):
            mode = parts[1].lower()

    try:
        result = dice.roll_notation(notation, mode=mode)
        await ctx.send(dice.format_roll(result))
    except ValueError as e:
        await ctx.send(f"Couldn't parse that roll: {e}")


@bot.command()
async def character(ctx, *, name: str = None):
    if not name:
        await ctx.send("Usage: `!character <name>` — e.g. `!character Aria the Ranger`")
        return

    memory = CampaignMemory(ctx.channel.id)
    memory.set_character(ctx.author.id, ctx.author.display_name, name)
    memory.register_for_turns(ctx.author.id)
    await ctx.send(f"{ctx.author.display_name} is now playing as **{name}**.")


@bot.command()
async def turns(ctx, mode: str = None):
    memory = CampaignMemory(ctx.channel.id)
    if mode == "on":
        memory.enable_turns()
        await ctx.send("Turn order is now **on**. Players will be addressed one at a time.")
    elif mode == "off":
        memory.disable_turns()
        await ctx.send("Turn order is now **off**. Anyone can speak freely.")
    else:
        await ctx.send("Usage: `!turns on` or `!turns off`")


@bot.command(name="turnorder")
async def turn_order(ctx):
    memory = CampaignMemory(ctx.channel.id)

    def resolve_name(uid):
        return memory.get_character(uid, fallback=f"<@{uid}>")

    await ctx.send(f"Turn order:\n{memory.turn_order_display(resolve_name)}")


@bot.command()
async def skip(ctx):
    memory = CampaignMemory(ctx.channel.id)
    memory.skip_turn()
    current_uid = memory.current_turn_user_id()
    current_name = memory.get_character(current_uid, fallback="someone") if current_uid else "no one"
    await ctx.send(f"Turn skipped. It's now **{current_name}**'s turn.")


@bot.command()
async def summary(ctx):
    memory = CampaignMemory(ctx.channel.id)
    text = memory.get_summary()
    await ctx.send(text if text else "No campaign summary yet.")


@bot.command()
async def recall(ctx, *, keyword: str = None):
    if not keyword:
        await ctx.send("Usage: `!recall <keyword>`")
        return

    memory = CampaignMemory(ctx.channel.id)
    matches = memory.search_sessions(keyword)
    if not matches:
        await ctx.send(f"No mentions of '{keyword}' found.")
        return

    lines = [f"**{m.get('speaker') or m['role']}**: {m['content']}" for m in matches]
    await ctx.send("\n".join(lines))


@bot.command()
async def join(ctx):
    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.send("You need to be in a voice channel first!")
        return

    channel = ctx.author.voice.channel

    try:
        vc = await channel.connect(self_deaf=False)
    except Exception as e:
        await ctx.send(f"Failed to join: {e}")
        return

    guild_id = ctx.guild.id
    db.register_channel(channel.id, channel.name)
    voice_managers[guild_id] = voice_mod.VoiceManager(bot)

    await ctx.send(f"Joined **{channel.name}**. Use `{config.COMMAND_PREFIX}listen` to start listening.")


@bot.command()
async def leave(ctx):
    guild_id = ctx.guild.id

    if guild_id in listening_tasks:
        listening_tasks[guild_id].cancel()
        del listening_tasks[guild_id]

    if guild_id in processing_tasks:
        processing_tasks[guild_id].cancel()
        del processing_tasks[guild_id]

    if guild_id in voice_managers:
        voice_managers[guild_id].stop_listening(guild_id)
        del voice_managers[guild_id]

    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("Left the voice channel.")
    else:
        await ctx.send("I'm not in a voice channel.")


@bot.command()
async def listen(ctx):
    guild_id = ctx.guild.id

    if not ctx.voice_client:
        await ctx.send("I'm not in a voice channel. Use `!join` first.")
        return

    if guild_id in listening_tasks and not listening_tasks[guild_id].done():
        await ctx.send("Already listening.")
        return

    vm = voice_managers.get(guild_id)
    if not vm:
        vm = voice_mod.VoiceManager(bot)
        voice_managers[guild_id] = vm

    memory = CampaignMemory(ctx.channel.id)
    db.register_channel(ctx.channel.id, ctx.channel.name)

    await ctx.send("Loading speech recognition... (first time may take a moment)")

    vc = ctx.voice_client

    async def keep_passthrough():
        while vc.is_connected():
            if vc._connection and vc._connection.dave_session:
                try:
                    vc._connection.dave_session.set_passthrough_mode(True, 10)
                except Exception:
                    pass
            await asyncio.sleep(8)

    bot.loop.create_task(keep_passthrough())
    print("[VOICE] DAVE passthrough loop started")

    async def on_user_speech(user_id, text):
        try:
            user = ctx.guild.get_member(user_id)
            name = user.display_name if user else "Unknown"
        except Exception:
            name = "Unknown"

        print(f"Voice from {name}: {text}")
        memory.append_message("user", user_id, name, text)

        if vc.is_connected():
            await ctx.send(f"**{name}**: {text}")

        reply = await dm.get_response(
            text,
            memory.get_recent_context(),
            speaker_name=name,
            summary=memory.get_summary()
        )
        reply = dice.resolve_roll_tags(reply)
        if name != "Unknown":
            reply = ensure_addressed(reply, name)
        memory.append_message("assistant", None, "Valdris", reply)

        if memory.messages_since_summary() >= config.SUMMARY_TRIGGER_MESSAGE_COUNT:
            asyncio.create_task(run_background_summary(memory))

        if vc.is_connected():
            image_buf = await image_mod.generate_scene_image(
                reply,
                party_desc=party_description(memory),
                summary_anchor=memory.get_summary(),
                channel_id=ctx.channel.id
            )
            if image_buf:
                await ctx.send(f"**Valdris**: {reply}", file=discord.File(image_buf, filename="scene.png"))
            else:
                await ctx.send(f"**Valdris**: {reply}")
            await vm.play_response(vc, reply)

    async def listen_task():
        try:
            await vm.listen_loop(vc, ctx.channel, memory, on_user_speech)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"Listen task error: {e}")
            traceback.print_exc()

    task = asyncio.create_task(listen_task())
    listening_tasks[guild_id] = task

    await ctx.send(f"Now listening in **{vc.channel.name}**. Speak and I will respond!")


@bot.command(name="stop")
async def stop_listening(ctx):
    guild_id = ctx.guild.id

    if guild_id in listening_tasks:
        listening_tasks[guild_id].cancel()
        del listening_tasks[guild_id]

    if guild_id in processing_tasks:
        processing_tasks[guild_id].cancel()
        del processing_tasks[guild_id]

    if guild_id in voice_managers:
        voice_managers[guild_id].stop_listening(guild_id)

    await ctx.send("Stopped listening.")


@bot.command()
async def clear_campaign(ctx):
    memory = CampaignMemory(ctx.channel.id)
    memory.clear()
    await ctx.send("Campaign memory cleared.")


@bot.command()
async def voice_status(ctx):
    guild_id = ctx.guild.id
    in_voice = ctx.voice_client is not None
    listening = guild_id in listening_tasks and not listening_tasks[guild_id].done()

    status = []
    status.append(f"Voice: {'Connected to ' + ctx.voice_client.channel.name if in_voice else 'Not connected'}")
    status.append(f"Listening: {'Yes' if listening else 'No'}")
    status.append(f"STT Model: {config.WHISPER_MODEL}")
    status.append(f"TTS Voice: {config.TTS_VOICE}")
    status.append(f"LLM Model: {config.LLM_MODEL}")

    await ctx.send("\n".join(status))


@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return

    guild_id = member.guild.id

    if before.channel and before.channel != after.channel:
        if before.channel.guild.voice_client:
            vc = before.channel.guild.voice_client
            if isinstance(vc, discord.VoiceClient):
                users_in_channel = [m for m in before.channel.members if not m.bot]
                if not users_in_channel and guild_id in listening_tasks:
                    print(f"Channel empty, stopping listen in {before.channel.name}")
                    listening_tasks[guild_id].cancel()
                    del listening_tasks[guild_id]
                    if guild_id in voice_managers:
                        voice_managers[guild_id].stop_listening(guild_id)
                    if vc.is_connected():
                        await vc.disconnect()


bot.run(os.getenv("DISCORD_TOKEN"))
