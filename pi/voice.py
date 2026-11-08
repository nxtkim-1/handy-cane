"""Speaks alert phrases on the belt speaker (the Pi's Bluetooth audio output).
Uses a recorded file voice/<key>.mp3 or .wav if it exists (e.g. Alex saying it in his own words),
otherwise text-to-speech: espeak-ng on the Pi, the Windows voice on a laptop."""
import os, platform, shutil, subprocess, threading
from config import VOICE_DIR, PHRASES

_lock = threading.Lock()
ON_WINDOWS = platform.system() == "Windows"

def _play_file(path):
    if ON_WINDOWS:
        from playsound3 import playsound
        playsound(path)
    elif path.endswith(".mp3"):
        subprocess.run(["mpg123", "-q", path], check=True)
    else:
        subprocess.run(["aplay", "-q", path], check=True)

def _speak_tts(text):
    if ON_WINDOWS:
        import pyttsx3
        engine = pyttsx3.init(); engine.setProperty("rate", 165); engine.say(text); engine.runAndWait()
    elif shutil.which("espeak-ng"):
        subprocess.run(["espeak-ng", "-s", "150", "-v", "en-us", text], check=True)
    else:
        print("[voice]", text)

def _play(key, text):
    with _lock:                       # never talk over itself
        for ext in (".mp3", ".wav"):
            path = os.path.join(VOICE_DIR, key + ext)
            if os.path.exists(path):
                try:
                    _play_file(path)
                    return
                except Exception as e:
                    print("audio file failed, falling back to TTS:", e)
        try:
            _speak_tts(text)
        except Exception as e:
            print("TTS failed:", e)

def say(key=None, text=None):
    """say('help') plays the stored phrase; say(text='...') speaks any text."""
    text = text or PHRASES.get(key, key)
    threading.Thread(target=_play, args=(key or "_none", text), daemon=True).start()
