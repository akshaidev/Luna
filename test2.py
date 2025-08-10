#!/usr/bin/env python3
"""
Minimal main music player (assumes prerequisites installed).
- GUI: Tkinter
- Search & download: yt_dlp (downloads MP3 via ffmpeg)
- Playback: pygame.mixer (non-blocking)
- Cache: downloads/ (won't re-download existing files)
- Playlists persisted to playlists.json
- History persisted to history.csv
"""

import os
import json
import csv
import threading
import platform
import tkinter as tk
from tkinter import messagebox, simpledialog
from datetime import datetime

# these must already be installed in the environment
import yt_dlp
import pygame

# ------- configuration -------
BASE = os.path.abspath(os.path.dirname(__file__))
DOWNLOADS = os.path.join(BASE, "downloads")
PLAYLISTS_FILE = os.path.join(BASE, "playlists.json")
HISTORY_FILE = os.path.join(BASE, "history.csv")

os.makedirs(DOWNLOADS, exist_ok=True)

# ensure persistence files exist (only simple creation)
if not os.path.exists(PLAYLISTS_FILE):
    with open(PLAYLISTS_FILE, "w", encoding="utf-8") as f:
        json.dump({}, f)
if not os.path.exists(HISTORY_FILE):
    with open(HISTORY_FILE, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(["timestamp", "title", "video_url"])

# ------- helpers -------
def sanitize(name: str) -> str:
    keep = (" ", ".", "_", "-", "(", ")", "[", "]")
    return "".join(c for c in name if c.isalnum() or c in keep).strip()

def load_playlists():
    with open(PLAYLISTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_playlists(pl):
    with open(PLAYLISTS_FILE, "w", encoding="utf-8") as f:
        json.dump(pl, f, indent=2)

def append_history(title, url):
    with open(HISTORY_FILE, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([datetime.now().isoformat(sep=' ', timespec='seconds'), title, url])

# ------- yt_dlp helpers (download & search) -------
def yt_search(query, max_results=10):
    opts = {"quiet": True, "skip_download": True, "extract_flat": "in_playlist", "default_search": f"ytsearch{max_results}"}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(query, download=False)
        entries = info.get("entries") or []
        results = []
        for e in entries:
            vid = e.get("id")
            title = e.get("title") or vid
            results.append({"id": vid, "title": title, "url": f"https://www.youtube.com/watch?v={vid}"})
        return results

def cached_mp3_path(entry):
    name = f"{entry['title']} - {entry['id']}.mp3"
    return os.path.join(DOWNLOADS, sanitize(name))

def download_audio_to_mp3(entry):
    """
    Download + convert to mp3 into DOWNLOADS and return path.
    Assumes ffmpeg is available (no checks here).
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
        "quiet": True,
        "nocheckcertificate": True
        # don't pass ffmpeg_location — assume system has ffmpeg if needed
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(entry["url"], download=True)
        base = ydl.prepare_filename(info)
        mp3_guess = os.path.splitext(base)[0] + ".mp3"
        final_name = sanitize(os.path.basename(mp3_guess))
        final_path = os.path.join(DOWNLOADS, final_name)

        if os.path.exists(mp3_guess) and mp3_guess != final_path:
            try:
                os.replace(mp3_guess, final_path)
            except Exception:
                import shutil
                shutil.copy(mp3_guess, final_path)
        elif os.path.exists(final_path):
            pass
        elif os.path.exists(mp3_guess):
            final_path = mp3_guess
        else:
            # fallback: search downloads for mp3 containing id
            final_path = None
            for f in os.listdir(DOWNLOADS):
                if f.lower().endswith(".mp3") and entry["id"] in f:
                    final_path = os.path.join(DOWNLOADS, f)
                    break
            if final_path is None:
                return None
        return os.path.abspath(final_path)

# ------- playback (pygame) -------
pygame.mixer.init()
play_lock = threading.Lock()
is_playing = False
is_paused = False
current_file = None

def play_file(path, title=None, url=None):
    global is_playing, is_paused, current_file
    if not os.path.exists(path):
        messagebox.showerror("Playback", f"File not found:\n{path}")
        return
    with play_lock:
        try:
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
            current_file = path
            is_playing = True
            is_paused = False
            if title and url:
                append_history(title, url)
        except Exception as e:
            messagebox.showerror("Playback error", str(e))

def stop_playback():
    global is_playing, is_paused, current_file
    with play_lock:
        pygame.mixer.music.stop()
        is_playing = False
        is_paused = False
        current_file = None

def pause_resume():
    global is_paused
    with play_lock:
        if not is_playing:
            return
        if is_paused:
            pygame.mixer.music.unpause()
            is_paused = False
        else:
            pygame.mixer.music.pause()
            is_paused = True

# ------- GUI & callbacks -------
playlists = load_playlists()
search_results = []

root = tk.Tk()
root.title("YT Music Player (minimal)")

# top: search
top = tk.Frame(root); top.pack(fill=tk.X, padx=8, pady=6)
search_entry = tk.Entry(top, width=60); search_entry.pack(side=tk.LEFT, padx=(0,6), expand=True, fill=tk.X)
search_entry.insert(0, "song or artist and press Search")
def do_search_thread(q):
    global search_results
    results = yt_search(q)
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
    threading.Thread(target=do_search_thread, args=(q,), daemon=True).start()

tk.Button(top, text="Search", width=10, command=on_search).pack(side=tk.LEFT)

# middle: results
middle = tk.Frame(root); middle.pack(fill=tk.BOTH, expand=True, padx=8)
results_listbox = tk.Listbox(middle, width=80, height=18); results_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
scroll = tk.Scrollbar(middle, command=results_listbox.yview); scroll.pack(side=tk.RIGHT, fill=tk.Y)
results_listbox.config(yscrollcommand=scroll.set)

# controls
controls = tk.Frame(root); controls.pack(padx=8, pady=6)
def on_play():
    sel = results_listbox.curselection()
    if not sel:
        messagebox.showinfo("Select", "Select a song first.")
        return
    idx = sel[0]; entry = search_results[idx]
    mp3_path = cached_mp3_path(entry)
    if os.path.exists(mp3_path):
        threading.Thread(target=play_file, args=(mp3_path, entry["title"], entry["url"]), daemon=True).start()
        return
    def dl_then_play():
        play_btn.config(state=tk.DISABLED); stop_btn.config(state=tk.DISABLED); pause_btn.config(state=tk.DISABLED)
        try:
            mp3 = download_audio_to_mp3(entry)
            if not mp3:
                root.after(0, lambda: messagebox.showerror("Download failed", "Could not download/convert the song."))
            else:
                threading.Thread(target=play_file, args=(mp3, entry["title"], entry["url"]), daemon=True).start()
        finally:
            root.after(0, lambda: play_btn.config(state=tk.NORMAL))
            root.after(0, lambda: stop_btn.config(state=tk.NORMAL))
            root.after(0, lambda: pause_btn.config(state=tk.NORMAL))
    threading.Thread(target=dl_then_play, daemon=True).start()

def on_stop(): stop_playback()
def on_pause(): pause_resume()

play_btn = tk.Button(controls, text="Play", width=12, command=on_play); play_btn.grid(row=0, column=0, padx=4)
pause_btn = tk.Button(controls, text="Pause/Resume", width=12, command=on_pause); pause_btn.grid(row=0, column=1, padx=4)
stop_btn = tk.Button(controls, text="Stop", width=8, command=on_stop); stop_btn.grid(row=0, column=2, padx=4)

# playlist buttons
def create_playlist():
    name = simpledialog.askstring("New playlist", "Playlist name:")
    if not name: return
    if name in playlists:
        messagebox.showinfo("Playlist", "Already exists."); return
    playlists[name] = []; save_playlists(playlists); messagebox.showinfo("Playlist", f"Created '{name}'")

def add_selected_to_playlist():
    sel = results_listbox.curselection()
    if not sel:
        messagebox.showinfo("Select", "Select a song first."); return
    idx = sel[0]; entry = search_results[idx]
    pls = list(playlists.keys())
    if not pls:
        messagebox.showinfo("Playlist", "No playlists exist; create one first."); return
    pick = simpledialog.askstring("Add to playlist", f"Available: {', '.join(pls)}\nEnter playlist name:")
    if not pick or pick not in playlists:
        messagebox.showerror("Playlist", "Invalid playlist."); return
    playlists[pick].append({"title": entry["title"], "url": entry["url"], "id": entry["id"]})
    save_playlists(playlists)
    messagebox.showinfo("Playlist", f"Added to {pick}")

def open_playlist_window():
    pls = list(playlists.keys())
    if not pls:
        messagebox.showinfo("Playlist", "No playlists saved."); return
    chosen = simpledialog.askstring("Open playlist", f"Saved: {', '.join(pls)}\nEnter playlist name:")
    if not chosen or chosen not in playlists: return
    items = playlists[chosen]
    win = tk.Toplevel(root); win.title(f"Playlist: {chosen}")
    lb = tk.Listbox(win, width=80, height=15); lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    for it in items: lb.insert(tk.END, it["title"])
    def play_from_playlist():
        sel = lb.curselection()
        if not sel: return
        e = items[sel[0]]
        mp3p = cached_mp3_path(e)
        if os.path.exists(mp3p):
            threading.Thread(target=play_file, args=(mp3p, e["title"], e["url"]), daemon=True).start()
        else:
            def dl_play():
                mp3 = download_audio_to_mp3(e)
                if mp3:
                    threading.Thread(target=play_file, args=(mp3, e["title"], e["url"]), daemon=True).start()
                else:
                    root.after(0, lambda: messagebox.showerror("Download failed", "Could not download playlist item."))
            threading.Thread(target=dl_play, daemon=True).start()
    tk.Button(win, text="Play Selected", command=play_from_playlist).pack(side=tk.LEFT, padx=4, pady=4)
    def remove_item():
        sel = lb.curselection()
        if not sel: return
        idx = sel[0]; items.pop(idx); save_playlists(playlists); lb.delete(idx)
    tk.Button(win, text="Remove Selected", command=remove_item).pack(side=tk.LEFT, padx=4)

tk.Button(controls, text="Create Playlist", width=14, command=create_playlist).grid(row=0, column=3, padx=4)
tk.Button(controls, text="Add to Playlist", width=14, command=add_selected_to_playlist).grid(row=0, column=4, padx=4)
tk.Button(controls, text="Open Playlist", width=14, command=open_playlist_window).grid(row=0, column=5, padx=4)

# history + open downloads
def show_history():
    if not os.path.exists(HISTORY_FILE):
        messagebox.showinfo("History", "No history found."); return
    win = tk.Toplevel(root); win.title("History")
    lb = tk.Listbox(win, width=100); lb.pack(fill=tk.BOTH, expand=True)
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        reader = csv.reader(f); next(reader, None)
        for r in reader:
            lb.insert(tk.END, f"{r[0]}  {r[1]}  {r[2]}")

tk.Button(root, text="History", command=show_history).pack(pady=(2,6))
def open_downloads():
    if platform.system() == "Windows":
        os.startfile(DOWNLOADS)
    elif platform.system() == "Darwin":
        os.system(f'open "{DOWNLOADS}"')
    else:
        os.system(f'xdg-open "{DOWNLOADS}"')

tk.Button(root, text="Open Downloads Folder", command=open_downloads).pack(pady=(0,8))

# cleanup on exit
root.protocol("WM_DELETE_WINDOW", lambda: (stop_playback(), root.destroy()))
root.mainloop()
