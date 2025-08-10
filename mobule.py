# music_player_kivy.py
# YouTube-backed music player with Kivy + ffmpeg-kit
# History in history.csv, playlists in playlists.json, cached mp3 in downloads/

import os, sys, json, csv, threading, platform, subprocess
from datetime import datetime
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.label import Label
from kivy.uix.recycleview import RecycleView
from kivy.uix.popup import Popup
from kivy.core.window import Window
from kivy.clock import mainthread

import yt_dlp

# ---- Paths ----
BASE = os.path.abspath(os.path.dirname(__file__))
DOWNLOADS = os.path.join(BASE, "downloads")
PLAYLISTS_FILE = os.path.join(BASE, "playlists.json")
HISTORY_FILE = os.path.join(BASE, "history.csv")

os.makedirs(DOWNLOADS, exist_ok=True)
if not os.path.exists(HISTORY_FILE):
    with open(HISTORY_FILE, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(["timestamp", "title", "video_url"])

def sanitize(s: str) -> str:
    keep = (" ", ".", "_", "-", "(", ")", "[", "]")
    return "".join(c for c in s if c.isalnum() or c in keep).strip()

# ---- History & Playlists ----
def append_history(title, url):
    with open(HISTORY_FILE, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([datetime.now().isoformat(sep=' ', timespec='seconds'), title, url])

def load_playlists():
    if not os.path.exists(PLAYLISTS_FILE):
        return {}
    try:
        with open(PLAYLISTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_playlists(p):
    with open(PLAYLISTS_FILE, "w", encoding="utf-8") as f:
        json.dump(p, f, indent=2)

playlists = load_playlists()

# ---- YouTube Search & Download ----
def yt_search(query, max_results=10):
    opts = {"quiet": True, "skip_download": True, "extract_flat": "in_playlist", "default_search": f"ytsearch{max_results}"}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(query, download=False)
            entries = info.get("entries") or []
            return [{"id": e.get("id"), "title": e.get("title"), "url": f"https://www.youtube.com/watch?v={e.get('id')}"} for e in entries]
    except Exception as e:
        return []

def cached_mp3_path(entry):
    return os.path.join(DOWNLOADS, sanitize(f"{entry['title']} - {entry['id']}.mp3"))

def download_audio(entry):
    if os.path.exists(cached_mp3_path(entry)):
        return cached_mp3_path(entry)
    outtmpl = os.path.join(DOWNLOADS, "%(title)s - %(id)s.%(ext)s")
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192"
        }],
        "quiet": True,
        "nocheckcertificate": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([entry["url"]])
    return cached_mp3_path(entry)

# ---- Playback (ffmpeg-kit / ffplay) ----
current_process = None
paused = False

def play_file(path, title=None, url=None):
    global current_process, paused
    stop_playback()
    cmd = ["ffplay", "-nodisp", "-autoexit", path]
    current_process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    paused = False
    if title and url:
        append_history(title, url)

def stop_playback():
    global current_process, paused
    if current_process:
        current_process.kill()
        current_process = None
    paused = False

def pause_resume():
    global paused
    if current_process:
        if paused:
            current_process.stdin.write(b"p")
            paused = False
        else:
            current_process.stdin.write(b"p")
            paused = True

# ---- UI ----
class ResultList(RecycleView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.data = []

class MusicApp(App):
    def build(self):
        self.results = []
        self.layout = BoxLayout(orientation="vertical", spacing=5, padding=5)

        search_bar = BoxLayout(size_hint_y=None, height=40)
        self.search_input = TextInput(hint_text="Search song or artist", multiline=False)
        search_btn = Button(text="Search", size_hint_x=None, width=100, on_press=lambda _: self.search())
        search_bar.add_widget(self.search_input)
        search_bar.add_widget(search_btn)
        self.layout.add_widget(search_bar)

        self.result_list = ResultList()
        self.layout.add_widget(self.result_list)

        btn_bar = BoxLayout(size_hint_y=None, height=40)
        btn_bar.add_widget(Button(text="Play", on_press=lambda _: self.play_selected()))
        btn_bar.add_widget(Button(text="Pause/Resume", on_press=lambda _: pause_resume()))
        btn_bar.add_widget(Button(text="Stop", on_press=lambda _: stop_playback()))
        btn_bar.add_widget(Button(text="Create Playlist", on_press=lambda _: self.create_playlist()))
        btn_bar.add_widget(Button(text="Add to Playlist", on_press=lambda _: self.add_to_playlist()))
        btn_bar.add_widget(Button(text="Open Playlist", on_press=lambda _: self.open_playlist_popup()))
        self.layout.add_widget(btn_bar)

        return self.layout

    def search(self):
        query = self.search_input.text.strip()
        if not query:
            return
        self.results = yt_search(query)
        self.update_result_list()

    @mainthread
    def update_result_list(self):
        self.result_list.data = [{"text": r["title"]} for r in self.results]

    def play_selected(self):
        if not self.results:
            return
        entry = self.results[0]  # simple: play first result for demo
        threading.Thread(target=self._download_and_play, args=(entry,), daemon=True).start()

    def _download_and_play(self, entry):
        mp3_path = download_audio(entry)
        play_file(mp3_path, entry["title"], entry["url"])

    def create_playlist(self):
        name = "Playlist1"
        if name not in playlists:
            playlists[name] = []
            save_playlists(playlists)

    def add_to_playlist(self):
        if not self.results:
            return
        entry = self.results[0]
        name = "Playlist1"
        playlists.setdefault(name, []).append(entry)
        save_playlists(playlists)

    def open_playlist_popup(self):
        content = BoxLayout(orientation="vertical")
        for name, items in playlists.items():
            content.add_widget(Label(text=name))
            for it in items:
                content.add_widget(Button(text=it["title"], on_press=lambda btn, e=it: threading.Thread(target=self._download_and_play, args=(e,), daemon=True).start()))
        popup = Popup(title="Playlists", content=content, size_hint=(0.8, 0.8))
        popup.open()

if __name__ == "__main__":
    MusicApp().run()
