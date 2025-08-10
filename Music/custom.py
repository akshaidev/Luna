"""
Simple YouTube-backed Music Player (single file)
GUI: Tkinter
Download + convert: yt_dlp + ffmpeg (ffmpeg auto-download on Windows once)
Playback: pygame.mixer (non-blocking)
Cache: downloads/  (won't re-download existing files)
Playlists persisted to playlists.json
History in history.csv
"""

import os
import sys
import threading#To keep main loop and inner processes seperate so that main window won't freeze
import shutil
import platform
import urllib.request
import zipfile
import json
import csv
from datetime import datetime
import tkinter as tk
from tkinter import messagebox, simpledialog, filedialog

try:
    import yt_dlp #checking for yt-dlp
except Exception:
    print("install yt-dlp: pip install yt-dlp")
    raise

try:
    import pygame#checking for pygame
except Exception:
    print("install pygame: pip install pygame")
    raise

# --- Paths / config ---
BASE = os.path.abspath(os.path.dirname(__file__))#assigning base directory
FFMPEG_DIR = os.path.join(BASE, "ffmpeg-bin")#assigning ffmpeg ie music player directory
DOWNLOADS = os.path.join(BASE, "downloads")# assigning music cache directory
PLAYLISTS_FILE = os.path.join(BASE, "playlists.json")# assigning playlist directory
HISTORY_FILE = os.path.join(BASE, "history.csv")# assigning history directory

os.makedirs(FFMPEG_DIR, exist_ok=True)
os.makedirs(DOWNLOADS, exist_ok=True)

# --- Utilities ---
def cleanname(s: str) -> str:
    keep = (" ", ".", "_", "-", "(", ")", "[", "]")
    return "".join(c for c in s if c.isalnum() or c in keep).strip()#having a clean name for better file-handling

def find_system_ffmpeg():
    ff = shutil.which("ffmpeg")
    ffp = shutil.which("ffprobe")
    if ff and ffp:
        return os.path.dirname(ff)
    return None

def download_ffmpeg_windows(dest_dir):#auto-download music-player files if not exists
    zip_url = "https://github.com/GyanD/codexffmpeg/releases/download/7.1.1/ffmpeg-7.1.1-essentials_build.zip"
    zip_path = os.path.join(dest_dir, "ffmpeg-7.1.1-essentials_build.zip")
    try:
        urllib.request.urlretrieve(zip_url, zip_path)
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(dest_dir)
        os.remove(zip_path)
        for root, dirs, files in os.walk(dest_dir):
            if "ffmpeg.exe" in files and "ffprobe.exe" in files:
                return root
    except Exception as anyerror:
        print("ffmpeg download/extract failed:", anyerror)
    return None

def ensure_ffmpeg():
    # prefer system ffmpeg
    sys_dir = find_system_ffmpeg()
    if sys_dir:
        return sys_dir
    # check extracted inside FFMPEG_DIR
    for root, dirs, files in os.walk(FFMPEG_DIR):
        if platform.system() == "Windows" and "ffmpeg.exe" in files and "ffprobe.exe" in files:
            return root
        if platform.system() != "Windows" and "ffmpeg" in files and "ffprobe" in files:
            return root
    # attempt auto-download only on Windows
    if platform.system() == "Windows":
        extracted = download_ffmpeg_windows(FFMPEG_DIR)
        if extracted:
            return extracted
    # otherwise fail and ask user
    messagebox.showerror("FFmpeg missing",
                         "FFmpeg not found. Install ffmpeg (ensure ffmpeg & ffprobe are on PATH) "
                         "or let the script auto-download on Windows.")
    return None

FFMPEG_BIN_DIR = ensure_ffmpeg()
if not FFMPEG_BIN_DIR:
    sys.exit(1)

# location string passed to yt_dlp
FFMPEG_LOCATION = FFMPEG_BIN_DIR#this will allow youtube streamer to play the song using ffmpeg music player

# --- Initialize pygame mixer ---
pygame.mixer.init()#initiating pygame module

if not os.path.exists(HISTORY_FILE):#will create history file if it does'nt exist
    with open(HISTORY_FILE, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(["timestamp", "title", "video_url"])

def append_history(title, url):
    with open(HISTORY_FILE, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([datetime.now().isoformat(sep=' ', timespec='seconds'), title, url])

def load_playlists():
    if not os.path.exists(PLAYLISTS_FILE):#create playlist file if not exists
        return {}
    try:
        with open(PLAYLISTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_playlists(p):
    with open(PLAYLISTS_FILE, "w", encoding="utf-8") as f:
        json.dump(p, f, indent=2)

playlists = load_playlists()  # dict: name -> list of {title, url, id, filename}

# --- Search / download logic ---
def yt_search(query, max_results=10):
    opts = {"quiet": True, "skip_download": True, "extract_flat": "in_playlist", "default_search": f"ytsearch{max_results}"}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(query, download=False)
            entries = info.get("entries") or []
            results = []
            for e in entries:
                vid = e.get("id")
                title = e.get("title") or vid
                results.append({"id": vid, "title": title, "url": f"https://www.youtube.com/watch?v={vid}"})
            return results
    except Exception as e:
        messagebox.showerror("Search error", str(e))
        return []

def cached_mp3_path(entry):
    # use title - id.mp3 pattern sanitized
    name = f"{entry['title']} - {entry['id']}.mp3"
    name = cleanname(name)
    return os.path.join(DOWNLOADS, name)

def download_audio_to_mp3(video_url, entry):
    """
    Download + convert to mp3, return absolute mp3 path or None.
    Uses outtmpl that includes id to avoid duplicates.
    """
    outtmpl = os.path.join(DOWNLOADS, "%(title)s - %(id)s.%(ext)s")
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192"
        }],
        "ffmpeg_location": FFMPEG_LOCATION,
        "quiet": True,
        "nocheckcertificate": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            base = ydl.prepare_filename(info)  # path with original ext
            mp3_guess = os.path.splitext(base)[0] + ".mp3"
            # sanitize final name to consistent pattern
            final_name = cleanname(os.path.basename(mp3_guess))
            final_path = os.path.join(DOWNLOADS, final_name)
            # if mp3_guess exists but names mismatch, move/rename to final_path
            if os.path.exists(mp3_guess) and mp3_guess != final_path:
                try:
                    os.replace(mp3_guess, final_path)
                except Exception:
                    shutil.copy(mp3_guess, final_path)
            elif os.path.exists(final_path):
                pass
            elif os.path.exists(mp3_guess):
                final_path = mp3_guess
            else:
                # fallback: look for mp3 with id
                for f in os.listdir(DOWNLOADS):
                    if f.lower().endswith(".mp3") and entry["id"] in f:
                        final_path = os.path.join(DOWNLOADS, f)
                        break
                else:
                    return None
            return os.path.abspath(final_path)
    except Exception as e:
        print("download error:", e)
        return None

# --- Playback via pygame (non-blocking) ---
play_lock = threading.Lock()
current_file = None
playing = False
paused = False

def play_file(path, title=None, url=None):
    global current_file, playing, paused
    if not os.path.exists(path):
        messagebox.showerror("Playback", f"File not found:\n{path}")
        return
    with play_lock:
        try:
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
            current_file = path
            playing = True
            paused = False
            if title and url:
                append_history(title, url)
        except Exception as e:
            messagebox.showerror("Playback error", str(e))

def stop_playback():
    global playing, paused, current_file
    with play_lock:
        pygame.mixer.music.stop()
        playing = False
        paused = False
        current_file = None

def pause_resume():
    global paused
    with play_lock:
        if not playing:
            return
        if paused:
            pygame.mixer.music.unpause()
            paused = False
        else:
            pygame.mixer.music.pause()
            paused = True

# --- GUI callbacks & helper threads ---
search_results = []  # list of entries dicts

def do_search(query):
    global search_results
    results = yt_search(query)
    search_results = results
    def update():
        results_listbox.delete(0, tk.END)
        for r in search_results:
            results_listbox.insert(tk.END, r["title"])
    root.after(0, update)

def on_search():
    q = search_entry.get().strip()
    if not q:
        return
    results_listbox.delete(0, tk.END)
    results_listbox.insert(tk.END, "Searching...")
    threading.Thread(target=do_search, args=(q,), daemon=True).start()

def on_play():
    sel = results_listbox.curselection()
    if not sel:
        messagebox.showinfo("Select", "Select a song first.")
        return
    idx = sel[0]
    entry = search_results[idx]
    mp3_path = cached_mp3_path(entry)
    if os.path.exists(mp3_path):
        # play cached
        threading.Thread(target=play_file, args=(mp3_path, entry["title"], entry["url"]), daemon=True).start()
        return
    # else download then play
    def dl_then_play():
        play_btn.config(state=tk.DISABLED)
        stop_btn.config(state=tk.DISABLED)
        pause_btn.config(state=tk.DISABLED)
        try:
            mp3 = download_audio_to_mp3(entry["url"], entry)
            if not mp3:
                messagebox.showerror("Download failed", "Could not download/convert the song.")
            else:
                threading.Thread(target=play_file, args=(mp3, entry["title"], entry["url"]), daemon=True).start()
        finally:
            root.after(0, lambda: play_btn.config(state=tk.NORMAL))
            root.after(0, lambda: stop_btn.config(state=tk.NORMAL))
            root.after(0, lambda: pause_btn.config(state=tk.NORMAL))
    threading.Thread(target=dl_then_play, daemon=True).start()

def on_stop():
    stop_playback()

def on_pause():
    pause_resume()

# ---- Playlists (persistent) ----
def list_playlists():
    return list(playlists.keys())

def create_playlist():
    name = simpledialog.askstring("New playlist", "Playlist name:")
    if not name:
        return
    if name in playlists:
        messagebox.showinfo("Playlist", "Already exists.")
        return
    playlists[name] = []
    save_playlists(playlists)
    messagebox.showinfo("Playlist", f"Created '{name}'")

def add_selected_to_playlist():
    sel = results_listbox.curselection()
    if not sel:
        messagebox.showinfo("Select", "Select a song first.")
        return
    idx = sel[0]
    entry = search_results[idx]
    # choose playlist
    pls = list_playlists()
    if not pls:
        messagebox.showinfo("Playlist", "No playlists exist; create one first.")
        return
    pick = simpledialog.askstring("Add to playlist", f"Available: {', '.join(pls)}\nEnter playlist name:")
    if not pick or pick not in playlists:
        messagebox.showerror("Playlist", "Invalid playlist.")
        return
    # store minimal info
    item = {"title": entry["title"], "url": entry["url"], "id": entry["id"]}
    playlists[pick].append(item)
    save_playlists(playlists)
    messagebox.showinfo("Playlist", f"Added to {pick}")

def open_playlist_window():
    pls = list_playlists()
    if not pls:
        messagebox.showinfo("Playlist", "No playlists saved.")
        return
    chosen = simpledialog.askstring("Open playlist", f"Saved: {', '.join(pls)}\nEnter playlist name:")
    if not chosen or chosen not in playlists:
        return
    items = playlists[chosen]

    win = tk.Toplevel(root)
    win.title(f"Playlist: {chosen}")
    lb = tk.Listbox(win, width=80, height=15)
    lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    for it in items:
        lb.insert(tk.END, it["title"])
    def play_from_playlist():
        sel = lb.curselection()
        if not sel:
            return
        e = items[sel[0]]
        mp3p = os.path.join(DOWNLOADS, cleanname(f"{e['title']} - {e['id']}.mp3"))
        if os.path.exists(mp3p):
            threading.Thread(target=play_file, args=(mp3p, e["title"], e["url"]), daemon=True).start()
        else:
            def dl_play():
                mp3 = download_audio_to_mp3(e["url"], e)
                if mp3:
                    threading.Thread(target=play_file, args=(mp3, e["title"], e["url"]), daemon=True).start()
                else:
                    messagebox.showerror("Download failed", "Could not download playlist item.")
            threading.Thread(target=dl_play, daemon=True).start()
    tk.Button(win, text="Play Selected", command=play_from_playlist).pack(side=tk.LEFT, padx=4, pady=4)
    def remove_item():
        sel = lb.curselection()
        if not sel:
            return
        idx = sel[0]
        items.pop(idx)
        save_playlists(playlists)
        lb.delete(idx)
    tk.Button(win, text="Remove Selected", command=remove_item).pack(side=tk.LEFT, padx=4)

# --- GUI layout ---
root = tk.Tk()
root.title("YT Music Player (simple)")

top = tk.Frame(root)
top.pack(fill=tk.X, padx=8, pady=6)

search_entry = tk.Entry(top, width=60)
search_entry.pack(side=tk.LEFT, padx=(0,6), expand=True, fill=tk.X)
search_entry.insert(0, "song or artist and press Search")

tk.Button(top, text="Search", width=10, command=on_search).pack(side=tk.LEFT)

middle = tk.Frame(root)
middle.pack(fill=tk.BOTH, expand=True, padx=8)

results_listbox = tk.Listbox(middle, width=80, height=18)
results_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

scroll = tk.Scrollbar(middle, command=results_listbox.yview)
scroll.pack(side=tk.RIGHT, fill=tk.Y)
results_listbox.config(yscrollcommand=scroll.set)

controls = tk.Frame(root)
controls.pack(padx=8, pady=6)

play_btn = tk.Button(controls, text="Play", width=12, command=on_play)
play_btn.grid(row=0, column=0, padx=4)
pause_btn = tk.Button(controls, text="Pause/Resume", width=12, command=on_pause)
pause_btn.grid(row=0, column=1, padx=4)
stop_btn = tk.Button(controls, text="Stop", width=8, command=on_stop)
stop_btn.grid(row=0, column=2, padx=4)

tk.Button(controls, text="Create Playlist", width=14, command=create_playlist).grid(row=0, column=3, padx=4)
tk.Button(controls, text="Add to Playlist", width=14, command=add_selected_to_playlist).grid(row=0, column=4, padx=4)
tk.Button(controls, text="Open Playlist", width=14, command=open_playlist_window).grid(row=0, column=5, padx=4)

tk.Button(root, text="Open Downloads Folder", command=lambda: os.startfile(DOWNLOADS) if platform.system()=="Windows" else subprocess.run(["xdg-open", DOWNLOADS])).pack(pady=(0,8))

# on close -> stop playback then quit
root.protocol("WM_DELETE_WINDOW", lambda: (stop_playback(), root.destroy()))
root.mainloop()
