import asyncio
import os
import traceback
from dotenv import load_dotenv
import discord
from discord.ext import commands
from discord import opus

import config
import dm
import voice as voice_mod
from memory import CampaignMemory
from database import CampaignDatabase

load_dotenv()

opus_path = os.path.join(os.path.dirname(discord.__file__), "bin", "libopus-0.x64.dll")
if not opus.is_loaded():
    opus.load_opus(opus_path)

intents = discord.Intents.all()

bot = commands.Bot(
    command_prefix=config.COMMAND_PREFIX,
    intents=intents
)

db = CampaignDatabase()
voice_managers = {}
listening_tasks = {}
processing_tasks = {}


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

        print(f"{message.author}: {content}")

        memory = CampaignMemory(message.channel.id)
        memory.add_message("user", f"{message.author.display_name}: {content}")

        async with message.channel.typing():
            reply = await dm.get_response(content, memory.get_history())

        memory.add_message("assistant", reply)
        await message.channel.send(reply)

    await bot.process_commands(message)


@bot.command()
async def roll(ctx):
    import random
    result = random.randint(1, 20)
    await ctx.send(f"You rolled a {result}")


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
        memory.add_message("user", f"{name}: {text}")

        if vc.is_connected():
            await ctx.send(f"**{name}**: {text}")

        reply = await dm.get_response(text, memory.get_history())
        memory.add_message("assistant", reply)

        if vc.is_connected():
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
