"""Speech argv and error paths. No whisper.cpp, no KittenTTS weights, no GPU."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import math
import os
import struct
import sys
import tempfile
import unittest
import wave
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-speech"


def load_speech():
    loader = importlib.machinery.SourceFileLoader("stickllm_speech_test", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


SP = load_speech()


def _wav() -> bytes:
    return b"RIFF" + (36).to_bytes(4, "little") + b"WAVE" + b"\x00" * 32


def _pcm_wav(seconds: float = 0.5, amp: int = 0) -> bytes:
    rate = 16000
    n = int(rate * seconds)
    frames = bytearray()
    for i in range(n):
        sample = int(amp * math.sin(2 * math.pi * 220 * i / rate))
        frames += struct.pack("<h", max(-32767, min(32767, sample)))
    buf = BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(frames)
    return buf.getvalue()


class SpeechArgsTest(unittest.TestCase):
    def test_timeout_constant(self):
        self.assertEqual(SP.SPEECH_TIMEOUT_SECS, 90)
        self.assertGreaterEqual(SP.SPEECH_TIMEOUT_SECS, 1)
        self.assertEqual(SP.speech_subprocess_kwargs()["timeout"], SP.SPEECH_TIMEOUT_SECS)

    def test_whisper_argv_is_english_cpu_stdin(self):
        argv = SP.whisper_argv("/usr/local/bin/whisper-cli", "/opt/stickllm/speech/ggml-tiny.en.bin")
        self.assertEqual(argv[0], "/usr/local/bin/whisper-cli")
        self.assertEqual(argv[argv.index("-m") + 1], "/opt/stickllm/speech/ggml-tiny.en.bin")
        self.assertEqual(argv[argv.index("-f") + 1], "-")
        self.assertEqual(argv[argv.index("-of") + 1], "-")
        self.assertIn("-otxt", argv)
        self.assertEqual(argv[argv.index("-l") + 1], "en")
        self.assertIn("-ng", argv)
        self.assertIn("-nt", argv)
        self.assertNotIn("-.txt", argv)
        joined = " ".join(argv)
        self.assertNotIn("/tmp", joined)
        self.assertNotIn(".wav", joined)
        self.assertNotIn("http", " ".join(argv))
        self.assertNotIn("api.kittenml.com", " ".join(argv))

    def test_espeak_argv_keeps_text_off_the_command_line(self):
        argv = SP.espeak_argv("/usr/bin/espeak-ng")
        self.assertEqual(argv, ["/usr/bin/espeak-ng", "-v", "en-us", "-q", "--ipa"])
        self.assertNotIn("hello there", argv)

    def test_sandbox_drops_root(self):
        cmd = SP.sandbox_command("/usr/local/bin/stickllm-speech", ["stt"], posix=True, euid=0, user="stickllm")
        self.assertEqual(cmd[:3], ["unshare", "--net", "--"])
        self.assertEqual(cmd[cmd.index("-u") + 1], "stickllm")
        self.assertNotIn("root", cmd)
        plain = SP.sandbox_command("/usr/local/bin/stickllm-speech", ["tts"], posix=True, euid=1000, user="stickllm")
        self.assertNotIn("unshare", plain)
        self.assertNotIn("runuser", plain)
        self.assertEqual(plain[-1], "tts")

    def test_child_env_stays_offline_and_drops_unrelated_values(self):
        os.environ["STICKLLM_DO_NOT_KEEP"] = "do-not-keep"
        try:
            env = SP.speech_child_env()
        finally:
            os.environ.pop("STICKLLM_DO_NOT_KEEP", None)
        self.assertNotIn("STICKLLM_DO_NOT_KEEP", env)
        self.assertNotIn("do-not-keep", env.values())
        self.assertEqual(env["HF_HUB_OFFLINE"], "1")
        self.assertEqual(env["TRANSFORMERS_OFFLINE"], "1")

    def test_voice_and_token_layout(self):
        self.assertEqual(SP.resolve_voice("Bella"), "expr-voice-2-f")
        self.assertEqual(SP.resolve_voice("expr-voice-5-m"), "expr-voice-5-m")
        self.assertEqual(SP.resolve_voice("nope"), "")
        self.assertEqual(SP.DEFAULT_VOICE, "Bella")
        symbols = SP.vocab_symbols()
        self.assertEqual(symbols[0], "$")
        self.assertEqual(symbols[10], "…")
        ids = SP.phoneme_token_ids("həlˈoʊ")
        self.assertEqual(ids[0], 0)
        self.assertEqual(ids[-2], 10)
        self.assertEqual(ids[-1], 0)
        chunks = SP.chunk_text("Hello. " + ("word " * 200))
        self.assertTrue(chunks)
        self.assertTrue(all(len(c) <= SP.CHUNK_CHARS for c in chunks))

    def test_pinned_names(self):
        self.assertEqual(SP.WHISPER_MODEL_NAME, "ggml-tiny.en.bin")
        self.assertEqual(SP.KITTEN_MODEL_NAME, "kitten_tts_mini_v0_8.onnx")
        self.assertEqual(SP.KITTEN_VOICES_NAME, "voices.npz")
        src = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("api.kittenml.com", src)
        self.assertNotIn("huggingface.co", src)


class SpeechErrorTest(unittest.TestCase):
    def test_empty_audio(self):
        self.assertEqual(SP.audio_error(b""), "No audio recorded.")
        self.assertEqual(SP.audio_error(b"RIFF"), "No audio recorded.")
        result = SP.transcribe(b"")
        self.assertFalse(result["ok"])
        self.assertIn("No audio", result["error"])

    def test_missing_whisper_binary(self):
        result = SP.transcribe(_wav(), bin_path=str(ROOT / "no-such-whisper-cli"), model_path=str(ROOT / "no-such-model.bin"))
        self.assertFalse(result["ok"])
        self.assertIn("whisper.cpp", result["error"])

    def test_missing_whisper_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "whisper-cli"
            binary.write_bytes(b"#!/bin/sh\n")
            result = SP.transcribe(_wav(), bin_path=str(binary), model_path=str(Path(tmp) / "ggml-tiny.en.bin"))
        self.assertFalse(result["ok"])
        self.assertIn("ggml-tiny.en.bin", result["error"])

    def test_not_wav(self):
        self.assertIn("WAV", SP.audio_error(b"x" * 64))

    def test_webm_bytes_are_not_handed_to_whisper_as_wav(self):
        webm = b"\x1a\x45\xdf\xa3" + b"\x01" * 80
        result = SP.transcribe(webm, bin_path=str(ROOT / "no-such-whisper-cli"), model_path=str(ROOT / "no-such-model.bin"))
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "Could not read the recording.")
        self.assertNotIn("WAV", result["error"])
        self.assertNotIn("whisper.cpp", result["error"])

    def test_ffmpeg_webm_and_ogg_expose_opus_packets(self):
        import shutil
        import subprocess
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            self.skipTest("ffmpeg")
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "tone.wav"
            webm = Path(tmp) / "tone.webm"
            ogg = Path(tmp) / "tone.ogg"
            wav.write_bytes(_pcm_wav(seconds=0.4, amp=8000))
            for dest, fmt in ((webm, "webm"), (ogg, "ogg")):
                proc = subprocess.run(
                    [ffmpeg, "-y", "-i", str(wav), "-c:a", "libopus", "-ac", "1", "-ar", "48000", "-f", fmt, str(dest)],
                    capture_output=True,
                )
                self.assertEqual(proc.returncode, 0, proc.stderr[-200:])
            head, packets = SP.webm_opus_packets(webm.read_bytes())
            self.assertTrue(head.startswith(b"OpusHead"))
            self.assertTrue(packets)
            self.assertGreater(head[9], 0)
            ohead, opackets = SP.ogg_opus_packets(ogg.read_bytes())
            self.assertTrue(ohead.startswith(b"OpusHead"))
            self.assertTrue(opackets)

    def test_quiet_wav_is_handed_to_whisper(self):
        self.assertLess(SP.wav_rms(_pcm_wav(amp=0)), SP.SILENCE_RMS)
        self.assertGreater(SP.wav_rms(_pcm_wav(amp=2000)), SP.SILENCE_RMS)
        self.assertGreater(SP.wav_rms(_pcm_wav(seconds=0.5, amp=80)), SP.SILENCE_RMS)
        with tempfile.TemporaryDirectory() as tmp:
            stub = Path(tmp) / "whisper_stub.py"
            stub.write_text("import sys\nsys.stdin.buffer.read()\nsys.stdout.write('hello from whisper\\n')\n", encoding="utf-8")
            model = Path(tmp) / "ggml-tiny.en.bin"
            model.write_bytes(b"x")
            if os.name == "nt":
                binary = Path(tmp) / "whisper-cli.cmd"
                binary.write_text(f'@"{sys.executable}" "{stub}"\n', encoding="utf-8")
            else:
                binary = Path(tmp) / "whisper-cli"
                binary.write_text(f"#!/bin/sh\nexec {sys.executable} {stub}\n", encoding="utf-8")
                binary.chmod(0o755)
            quiet = SP.transcribe(_pcm_wav(amp=0), bin_path=str(binary), model_path=str(model))
        self.assertTrue(quiet["ok"], quiet)
        self.assertEqual(quiet["text"], "hello from whisper")
        self.assertNotEqual(quiet.get("error"), "No sound from the microphone.")
        self.assertGreater(quiet.get("pcm_bytes") or 0, 0)

    def test_you_on_a_quiet_clip_is_not_a_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub = Path(tmp) / "whisper_stub.py"
            stub.write_text("import sys\nsys.stdin.buffer.read()\nsys.stdout.write('you\\n')\n", encoding="utf-8")
            model = Path(tmp) / "ggml-tiny.en.bin"
            model.write_bytes(b"x")
            if os.name == "nt":
                binary = Path(tmp) / "whisper-cli.cmd"
                binary.write_text(f'@"{sys.executable}" "{stub}"\n', encoding="utf-8")
            else:
                binary = Path(tmp) / "whisper-cli"
                binary.write_text(f"#!/bin/sh\nexec {sys.executable} {stub}\n", encoding="utf-8")
                binary.chmod(0o755)
            heard = SP.transcribe(_pcm_wav(amp=0), bin_path=str(binary), model_path=str(model))
        self.assertFalse(heard["ok"], heard)
        self.assertEqual(heard["error"], "No speech detected.")
        self.assertNotIn("text", heard)

    def test_frames_roundtrip(self):
        import socket

        left, right = socket.socketpair()
        try:
            SP.frame_write(left, {"op": "ping"})
            doc = SP.frame_read(right, limit=256)
        finally:
            left.close()
            right.close()
        self.assertEqual(doc, {"op": "ping"})

    def test_speak_uses_the_resident_socket(self):
        with tempfile.TemporaryDirectory() as tmp:
            espeak = Path(tmp) / "espeak-ng"
            model = Path(tmp) / "kitten.onnx"
            voices = Path(tmp) / "voices.npz"
            for path in (espeak, model, voices):
                path.write_bytes(b"x")
            seen = {}

            def fake_rpc(text, voice):
                seen["text"] = text
                seen["voice"] = voice
                return {"ok": True, "audio_base64": "QQ==", "mime": "audio/wav"}

            orig = SP.kitten_rpc
            SP.kitten_rpc = fake_rpc
            try:
                result = SP.speak(
                    "Hello there",
                    espeak=str(espeak),
                    model_path=str(model),
                    voices_path=str(voices),
                    runtime_ok=True,
                )
            finally:
                SP.kitten_rpc = orig
            self.assertTrue(result["ok"])
            self.assertEqual(result["audio_base64"], "QQ==")
            self.assertEqual(seen.get("text"), "Hello there")
            self.assertEqual(seen.get("voice"), "Bella")
            down = SP.speak(
                "Hello there",
                espeak=str(espeak),
                model_path=str(model),
                voices_path=str(voices),
                runtime_ok=True,
            )
        self.assertFalse(down["ok"])
        self.assertIn("not ready", down["error"])
        self.assertNotIn("Hello there", down["error"])

    def test_kitten_stays_a_local_service(self):
        self.assertEqual(SP.KITTEN_UNIT, "stickllm-kitten.service")
        self.assertEqual(SP.KITTEN_DIR, "/run/stickllm-kitten")
        self.assertNotIn("/tmp", SP.KITTEN_DIR)
        src = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('command == "kitten"', src)
        self.assertIn('command == "once"', src)
        self.assertIn("_tts_oneshot", src)
        self.assertIn("ensure_kitten", src)
        self.assertNotIn("api.kittenml.com", src)

    def test_tts_falls_back_when_resident_is_down(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "once-speech.py"
            script.write_text(
                "import json,sys\n"
                "if sys.argv[1] != 'once':\n"
                "    raise SystemExit(3)\n"
                "sys.stdout.write(json.dumps({'ok':True,'audio_base64':'QQ==','mime':'audio/wav'}))\n",
                encoding="utf-8",
            )
            payload = b'{"text":"secret phrase","voice":"Bella"}'
            result = SP.run_sandboxed(str(script), "tts", payload)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["audio_base64"], "QQ==")
        self.assertNotIn("secret phrase", str(result.get("error") or ""))
        argv = SP.sandbox_argv(str(script), "once")
        self.assertEqual(argv[-1], "once")
        self.assertNotIn("secret phrase", argv)

    def test_speak_empty_and_unknown_voice(self):
        empty = SP.speak("   ")
        self.assertFalse(empty["ok"])
        self.assertIn("Nothing to read", empty["error"])
        long = SP.speak("a" * (SP.MAX_SPEAK_CHARS + 5))
        self.assertFalse(long["ok"])
        self.assertIn("too long", long["error"])
        voice = SP.speak("Hello", voice="Somebody")
        self.assertFalse(voice["ok"])
        self.assertIn("Unknown voice", voice["error"])

    def test_missing_espeak_model_and_runtime(self):
        missing_espeak = SP.speak("Hello", espeak=str(ROOT / "no-espeak-ng"))
        self.assertFalse(missing_espeak["ok"])
        self.assertIn("espeak-ng", missing_espeak["error"])
        with tempfile.TemporaryDirectory() as tmp:
            espeak = Path(tmp) / "espeak-ng"
            espeak.write_bytes(b"x")
            missing_model = SP.speak("Hello", espeak=str(espeak), model_path=str(Path(tmp) / "missing.onnx"), voices_path=str(Path(tmp) / "voices.npz"))
            self.assertFalse(missing_model["ok"])
            self.assertIn("KittenTTS mini 0.8", missing_model["error"])
            model = Path(tmp) / "kitten_tts_mini_v0_8.onnx"
            voices = Path(tmp) / "voices.npz"
            model.write_bytes(b"x")
            voices.write_bytes(b"x")
            runtime = SP.speak(
                "Hello",
                espeak=str(espeak),
                model_path=str(model),
                voices_path=str(voices),
                runtime_ok=False,
            )
        self.assertFalse(runtime["ok"])
        self.assertIn("onnxruntime", runtime["error"])

    def test_clean_text_drops_links(self):
        cleaned = SP.clean_speak_text("See [docs](https://example.com/a) and https://example.com/b now.")
        self.assertNotIn("http", cleaned)
        self.assertIn("docs", cleaned)

    def test_overlong_error_is_not_returned_whole(self):
        blob = "x" * 400
        parsed = SP.parse_speech_output(('{"ok": false, "error": "%s"}' % blob).encode())
        self.assertFalse(parsed["ok"])
        self.assertEqual(parsed["error"], "Speech failed.")
        self.assertNotIn(blob, parsed["error"])

    def test_auth_matches_chat_gate(self):
        self.assertIsNone(SP.speech_denied(True, False, True, False))
        code, _msg = SP.speech_denied(False, False, True, True)
        self.assertEqual(code, 410)
        code, msg = SP.speech_denied(False, True, True, False)
        self.assertEqual(code, 401)
        self.assertIn("Pair", msg)
        self.assertIsNone(SP.speech_denied(False, True, True, True))
        self.assertIsNone(SP.speech_denied(False, True, False, False))


if __name__ == "__main__":
    unittest.main()
