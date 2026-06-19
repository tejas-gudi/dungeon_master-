import io
import os
import uuid
import struct
import select
import asyncio
import socket
import tempfile
import traceback
import threading
import time
from collections import defaultdict

import discord
import edge_tts
from faster_whisper import WhisperModel

import config


class SpeechToText:

    def __init__(self):
        self.model = None
        self._loaded = False

    def load(self):
        if self._loaded:
            return
        print(f"[STT] Loading Whisper model: {config.WHISPER_MODEL}")
        self.model = WhisperModel(
            config.WHISPER_MODEL,
            device=config.WHISPER_DEVICE,
            compute_type=config.WHISPER_COMPUTE_TYPE
        )
        self._loaded = True
        print("[STT] Whisper model loaded")

    def transcribe(self, audio_bytes):
        if not self._loaded:
            self.load()

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name

        try:
            segments, info = self.model.transcribe(
                tmp_path,
                beam_size=5,
                language="en"
            )
            text = " ".join(segment.text.strip() for segment in segments)
            return text.strip()
        finally:
            os.unlink(tmp_path)


class TextToSpeech:

    def __init__(self):
        self.voice = config.TTS_VOICE
        self.rate = config.TTS_RATE
        self.volume = config.TTS_VOLUME

    async def synthesize_to_file(self, text, output_path):
        communicate = edge_tts.Communicate(
            text,
            self.voice,
            rate=self.rate,
            volume=self.volume
        )
        await communicate.save(output_path)


class VoiceManager:

    def __init__(self, bot):
        self.bot = bot
        self.stt = SpeechToText()
        self.tts = TextToSpeech()
        self.active_channels = {}
        self._current_voice_client = None
        self._socket_thread = None
        self._socket_stop = threading.Event()

        self.user_buffers = defaultdict(bytearray)
        self.user_last_active = {}
        self._decoders = {}
        self._lock = threading.Lock()

        self.silence_threshold = 0.02
        self.buffer_duration = 1.5
        self.sample_rate = 48000
        self.channels = 2
        self.bytes_per_sample = 2
        self.frame_size = 960
        self.frame_bytes = self.frame_size * self.channels * self.bytes_per_sample

        self._packet_count = 0
        self._decrypt_fail_count = 0
        self._opus_fail_count = 0
        self._audio_count = 0
        self._last_log_time = 0

    def _pcm_to_wav(self, pcm_data):
        import wave
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(self.bytes_per_sample)
            wf.setframerate(self.sample_rate)
            wf.writeframes(bytes(pcm_data))
        return buf.getvalue()

    def _get_audio_level(self, pcm_data):
        if len(pcm_data) < 2:
            return 0
        samples = struct.unpack(f"<{len(pcm_data)//2}h", pcm_data)
        if not samples:
            return 0
        rms = (sum(s ** 2 for s in samples) / len(samples)) ** 0.5
        return rms / 32768.0

    @staticmethod
    def _strip_header_ext(data):
        # RTP one-byte extension header (profile 0xBEDE). In the _rtpsize AEAD
        # modes the extension lives inside the *encrypted* payload, so it must
        # be stripped only after decryption.
        if len(data) >= 4 and data[0] == 0xBE and data[1] == 0xDE:
            length = struct.unpack_from('>H', data, 2)[0]
            offset = 4 + length * 4
            data = data[offset:]
        return data

    def _decrypt_packet(self, data, voice_client):
        # Need at least a 12-byte RTP header + 4-byte trailing nonce.
        if len(data) < 16:
            return None, None

        # Skip RTCP control packets (payload types 200-204); they aren't audio.
        if 200 <= data[1] <= 204:
            return None, None

        ssrc = struct.unpack_from('>I', data, 8)[0]

        key = voice_client.secret_key
        mode = voice_client.mode
        if not key or not mode:
            return ssrc, None

        # For every supported mode the authenticated header is exactly the
        # 12-byte base RTP header. CSRC/extension bytes are part of the
        # ciphertext and are stripped after decryption.
        header = bytes(data[:12])

        try:
            key_bytes = bytes(key)

            if mode == 'aead_xchacha20_poly1305_rtpsize':
                import nacl.secret
                nonce = bytearray(24)
                nonce[:4] = data[-4:]
                ciphertext = bytes(data[12:-4])
                decrypted = nacl.secret.Aead(key_bytes).decrypt(
                    ciphertext, header, bytes(nonce)
                )

            elif mode == 'aead_aes256_gcm_rtpsize':
                from cryptography.hazmat.primitives.ciphers.aead import AESGCM
                nonce = bytearray(12)
                nonce[:4] = data[-4:]
                ciphertext = bytes(data[12:-4])
                decrypted = AESGCM(key_bytes).decrypt(
                    bytes(nonce), ciphertext, header
                )

            elif mode == 'xsalsa20_poly1305':
                import nacl.secret
                nonce = bytearray(24)
                nonce[:12] = header
                decrypted = nacl.secret.SecretBox(key_bytes).decrypt(
                    bytes(data[12:]), bytes(nonce)
                )

            elif mode == 'xsalsa20_poly1305_suffix':
                import nacl.secret
                nonce = bytes(data[-24:])
                decrypted = nacl.secret.SecretBox(key_bytes).decrypt(
                    bytes(data[12:-24]), nonce
                )

            elif mode == 'xsalsa20_poly1305_lite':
                import nacl.secret
                nonce = bytearray(24)
                nonce[:4] = data[-4:]
                decrypted = nacl.secret.SecretBox(key_bytes).decrypt(
                    bytes(data[12:-4]), bytes(nonce)
                )

            else:
                if self._decrypt_fail_count < 1:
                    print(f"[VOICE] Unsupported encryption mode: {mode}")
                self._decrypt_fail_count += 1
                return ssrc, None

            return ssrc, self._strip_header_ext(decrypted)

        except Exception as e:
            self._decrypt_fail_count += 1
            if self._decrypt_fail_count <= 5:
                print(f"[VOICE] Decrypt failed (ssrc={ssrc}, mode={mode}, len={len(data)}): {e}")
            return ssrc, None

    def _decode_opus_to_pcm(self, ssrc, opus_data):
        # Opus decoders are stateful per stream, so keep one decoder per SSRC.
        try:
            decoder = self._decoders.get(ssrc)
            if decoder is None:
                decoder = discord.opus.Decoder()
                self._decoders[ssrc] = decoder
            try:
                return decoder.decode(opus_data)
            except TypeError:
                # Older discord.py opus Decoder.decode requires frame_size.
                return decoder.decode(opus_data, self.frame_size)
        except Exception as e:
            self._opus_fail_count += 1
            if self._opus_fail_count <= 3:
                print(f"[VOICE] Opus decode failed: {e}")
            return None

    def _socket_reader_thread(self, voice_client):
        conn = getattr(voice_client, '_connection', None)
        raw_socket = getattr(conn, 'socket', None) if conn else None
        if raw_socket is None:
            print("[VOICE] No socket available")
            return

        print(f"[VOICE] Socket reader started, reading from UDP socket")
        raw_socket.setblocking(False)

        while not self._socket_stop.is_set():
            try:
                readable, _, _ = select.select([raw_socket], [], [], 0.5)
            except (ValueError, TypeError, OSError) as e:
                print(f"[VOICE] Select error: {e}")
                break

            if not readable:
                continue

            try:
                data, addr = raw_socket.recvfrom(4096)
            except BlockingIOError:
                continue
            except OSError:
                break

            self._packet_count += 1

            now = time.monotonic()
            if now - self._last_log_time > 10:
                print(f"[VOICE] Stats: pkts={self._packet_count}, decrypt_fails={self._decrypt_fail_count}, opus_fails={self._opus_fail_count}, audio_ok={self._audio_count}")
                self._last_log_time = now

            ssrc, opus_data = self._decrypt_packet(data, voice_client)
            if ssrc is None or opus_data is None:
                continue

            pcm = self._decode_opus_to_pcm(ssrc, opus_data)
            if pcm is None:
                continue

            level = self._get_audio_level(pcm)

            if self._packet_count <= 10:
                print(f"[VOICE] Pkt#{self._packet_count}: ssrc={ssrc}, opus={len(opus_data)}, pcm={len(pcm)}, level={level:.4f}")

            if level < self.silence_threshold:
                continue

            self._audio_count += 1

            with self._lock:
                self.user_buffers[ssrc].extend(pcm)
                self.user_last_active[ssrc] = time.monotonic()

        print("[VOICE] Socket reader stopped")

    async def listen_loop(self, voice_client, channel, memory, on_user_speech):
        guild_id = voice_client.guild.id
        self.active_channels[guild_id] = True
        self._current_voice_client = voice_client
        self._packet_count = 0
        self._decrypt_fail_count = 0
        self._opus_fail_count = 0
        self._audio_count = 0
        self._last_log_time = 0
        self._decoders.clear()

        print(f"[VOICE] mode={voice_client.mode}, secret_key={'set' if voice_client.secret_key else 'NONE'}")

        for _ in range(50):
            conn = getattr(voice_client, '_connection', None)
            if conn and isinstance(getattr(conn, 'socket', None), socket.socket):
                break
            await asyncio.sleep(0.1)
        else:
            print("[VOICE] ERROR: UDP socket not initialized")
            return

        print(f"[VOICE] UDP socket ready: {voice_client._connection.socket}")

        self._socket_stop.clear()
        self._socket_thread = threading.Thread(
            target=self._socket_reader_thread,
            args=(voice_client,),
            daemon=True,
            name="voice-socket-reader"
        )
        self._socket_thread.start()

        print(f"[VOICE] Listening in {voice_client.channel.name}")

        while self.active_channels.get(guild_id, False):
            await asyncio.sleep(0.5)

            now = time.monotonic()
            to_process = []

            with self._lock:
                for ssrc in list(self.user_buffers.keys()):
                    buf = self.user_buffers[ssrc]
                    if not buf:
                        continue

                    last_active = self.user_last_active.get(ssrc, 0)
                    time_since_active = now - last_active

                    if time_since_active >= self.buffer_duration and len(buf) > self.frame_bytes:
                        pcm_data = bytes(buf)
                        self.user_buffers[ssrc] = bytearray()
                        to_process.append((ssrc, pcm_data))

            for ssrc, pcm_data in to_process:
                try:
                    wav_data = self._pcm_to_wav(pcm_data)
                    print(f"[STT] Transcribing {len(pcm_data)} bytes of PCM...")
                    text = await asyncio.to_thread(self.stt.transcribe, wav_data)
                    if text and len(text) > 2:
                        name = f"SSRC-{ssrc}"
                        print(f"[STT] Transcribed [{name}]: {text}")
                        await on_user_speech(0, text)
                    else:
                        print(f"[STT] Transcription empty or too short: '{text}'")
                except Exception as e:
                    print(f"[STT] Transcription error: {e}")
                    traceback.print_exc()

        self._socket_stop.set()
        if self._socket_thread:
            self._socket_thread.join(timeout=3)
        print(f"[VOICE] Stopped listening in {guild_id}")

    async def play_response(self, voice_client, text):
        if not voice_client.is_connected():
            return

        mp3_path = os.path.join(
            tempfile.gettempdir(), f"dm_response_{uuid.uuid4().hex}.mp3"
        )

        try:
            await self.tts.synthesize_to_file(text, mp3_path)

            if not voice_client.is_connected():
                return

            if voice_client.is_playing():
                voice_client.stop()

            source = discord.FFmpegPCMAudio(mp3_path, options="-loglevel quiet")

            loop = asyncio.get_running_loop()
            done = asyncio.Event()

            def after_play(error):
                if error:
                    print(f"[TTS] Playback finished with error: {error}")
                loop.call_soon_threadsafe(done.set)

            voice_client.play(source, after=after_play)
            await done.wait()

        except Exception as e:
            print(f"[TTS] Playback error: {e}")
            traceback.print_exc()
        finally:
            try:
                os.unlink(mp3_path)
            except OSError:
                pass

    def stop_listening(self, guild_id):
        self.active_channels[guild_id] = False
        self._socket_stop.set()

        if self._socket_thread:
            self._socket_thread.join(timeout=3)
            self._socket_thread = None

        with self._lock:
            self.user_buffers.clear()
            self.user_last_active.clear()
            self._decoders.clear()

        self._current_voice_client = None
