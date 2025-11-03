import os, sys, threading, shutil, urllib.request, zipfile, json, csv, time
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, simpledialog, filedialog
from PIL import Image, ImageTk
import pygame, yt_dlp

if getattr(sys, 'frozen', False):
    BASE = sys._MEIPASS
else:
    BASE = os.path.abspath(os.path.dirname(__file__))
USER_BASE = Path.home() / "LunaMusic"
USER_BASE.mkdir(exist_ok=True)
Self_FFMPEG_Path = os.path.join(BASE, "ffmpeg-bin")
LUNA_LOGO_PATH = os.path.join(BASE, "Luna.png")

DOWNLOADS = USER_BASE / "downloads"
PLAYLISTS_FILE = USER_BASE / "playlists.json"
HISTORY_FILE = USER_BASE / "history.csv"
THUMBNAIL_CACHE = USER_BASE / "thumbnails"

for path in [DOWNLOADS, THUMBNAIL_CACHE]:
    os.makedirs(path, exist_ok=True)

if not HISTORY_FILE.exists():
    with open(HISTORY_FILE, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(["timestamp", "title", "video_url"])

# --- Utilities ---
def cleanname(s: str) -> str:
    keep = (" ", ".", "_", "-", "(", ")", "[", "]")
    return "".join(c for c in s if c.isalnum() or c in keep).strip()

def download_ffmpeg_windows(dest_dir):
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
    for root, dirs, files in os.walk(Self_FFMPEG_Path):
        if "ffmpeg.exe" in files and "ffprobe.exe" in files:
            return root
    extracted = download_ffmpeg_windows(Self_FFMPEG_Path)
    if extracted:
        return extracted
    messagebox.showerror("FFmpeg missing", "Unable to find or download FFmpeg.")
    return None


FFMPEG_BIN_DIR = ensure_ffmpeg()
FFMPEG_LOCATION = FFMPEG_BIN_DIR

# --- Initialize pygame mixer ---
pygame.mixer.init()

def append_history(title, url):
    with open(HISTORY_FILE, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([datetime.now().isoformat(sep=' ', timespec='seconds'), title, url])

def load_playlists():
    if not os.path.exists(PLAYLISTS_FILE):
        return {}
    try:
        with open(PLAYLISTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_playlists(p):
    with open(PLAYLISTS_FILE, "w", encoding="utf-8") as f:
        json.dump(p, f, indent=2)

playlists = load_playlists()

# --- Global Playback State ---
current_playlist_name = None
current_playlist_items = [] # This will hold the actual list of song dicts for the current playlist
current_song_index = -1 # Index within current_playlist_items
current_playing_entry = None # The full entry dict of the currently playing song

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
                # Try to get thumbnail URL
                thumbnail_url = None
                if 'thumbnails' in e and e['thumbnails']:
                    # Get the largest thumbnail available
                    thumbnail_url = max(e['thumbnails'], key=lambda x: x.get('width', 0) * x.get('height', 0)).get('url')
                results.append({"id": vid, "title": title, "url": f"https://www.youtube.com/watch?v={vid}", "thumbnail": thumbnail_url})
            return results
    except Exception as e:
        messagebox.showerror("Search error", str(e))
        return []

def cached_mp3_path(entry):
    name = f"{entry['title']} - {entry['id']}.mp3"
    name = cleanname(name)
    return os.path.join(DOWNLOADS, name)

def cached_thumbnail_path(entry):
    if 'thumbnail' not in entry or not entry['thumbnail']:
        return None
    # Use video ID for thumbnail filename to ensure uniqueness and easy lookup
    name = f"{entry['id']}.jpg" # Assuming most thumbnails are JPG
    return os.path.join(THUMBNAIL_CACHE, name)

def download_thumbnail(entry):
    thumb_path = cached_thumbnail_path(entry)
    if not thumb_path:
        return None
    if os.path.exists(thumb_path):
        return thumb_path # Already cached

    thumbnail_url = entry.get('thumbnail')
    if not thumbnail_url:
        return None

    try:
        urllib.request.urlretrieve(thumbnail_url, thumb_path)
        return thumb_path
    except Exception:
        root.playback_window.thumbnail_label.config(image='')
        root.playback_window.thumbnail_label.image = None


def download_audio_to_mp3(video_url, entry):
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

    def enforce_download_limit():
        playlist_files = {cleanname(f"{item['title']} - {item['id']}.mp3") for pl in playlists.values() for item in pl}
        downloaded_files = [os.path.join(DOWNLOADS, f) for f in os.listdir(DOWNLOADS) if f.endswith(".mp3")]
        non_playlist_files = [f for f in downloaded_files if os.path.basename(f) not in playlist_files]
        non_playlist_files.sort(key=os.path.getmtime)
        while len(non_playlist_files) > 5:
            while len(non_playlist_files) > 5:
                os.remove(non_playlist_files.pop(0))

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            base = ydl.prepare_filename(info)
            mp3_guess = os.path.splitext(base)[0] + ".mp3"
            final_name = cleanname(os.path.basename(mp3_guess))
            final_path = os.path.join(DOWNLOADS, final_name)
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
                for f in os.listdir(DOWNLOADS):
                    if f.lower().endswith(".mp3") and entry["id"] in f:
                        final_path = os.path.join(DOWNLOADS, f)
                        break
                else:
                    return None
            enforce_download_limit()
            return os.path.abspath(final_path)
    except Exception as e:
        print("download error:", e)

play_lock = threading.Lock()
current_file = None
playing = False
paused = False

def update_playback_display(entry=None):
    """Updates the song title and thumbnail in the playback window."""
    if hasattr(root, 'playback_window') and root.playback_window.winfo_exists():
        if entry:
            root.playback_window.current_song_label.config(text=f"Now Playing: {entry['title']}")
            thumb_path = cached_thumbnail_path(entry)
            if thumb_path and os.path.exists(thumb_path):
                try:
                    img = Image.open(thumb_path)
                    img = img.resize((100, 75), Image.LANCZOS) # Resize for display
                    photo = ImageTk.PhotoImage(img)
                    root.playback_window.thumbnail_label.config(image=photo)
                    root.playback_window.thumbnail_label.image = photo # Keep a reference
                except Exception as e:
                    print(f"Error loading thumbnail image: {e}")
                    root.playback_window.thumbnail_label.config(image='') # Clear image
                    root.playback_window.thumbnail_label.image = None
            else:
                root.playback_window.thumbnail_label.config(image='') # Clear image
                root.playback_window.thumbnail_label.image = None
        else:
            root.playback_window.current_song_label.config(text="Now Playing: None")
            root.playback_window.thumbnail_label.config(image='') # Clear image
            root.playback_window.thumbnail_label.image = None

def play_file(path, entry):
    global current_file, playing, paused, current_playing_entry
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
            current_playing_entry = entry # Store the full entry
            append_history(entry["title"], entry["url"])
            update_playback_display(entry) # Update display with new song
        except Exception as e:
            messagebox.showerror("Playback error", str(e))
            update_playback_display(None) # Clear display on error

def stop_playback():
    global playing, paused, current_file, current_playing_entry, current_song_index
    with play_lock:
        pygame.mixer.music.stop()
        playing = False
        paused = False
        current_file = None
        current_playing_entry = None
        current_song_index = -1 # Reset index when stopped
        update_playback_display(None) # Clear display

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

def set_volume(val):
    """Sets the Pygame mixer volume based on slider value (0-100)."""
    volume = float(val) / 100.0
    pygame.mixer.music.set_volume(volume)

# --- Playback Control Functions (Next/Previous) ---
def play_next_song():
    global current_song_index, current_playlist_items
    if not current_playlist_items:
        messagebox.showinfo("Playback", "No playlist loaded or empty playlist.")
        return

    next_index = (current_song_index + 1) % len(current_playlist_items)
    # Ensure the next song is played in a new thread to avoid freezing GUI
    threading.Thread(target=play_song_from_playlist, args=(next_index,), daemon=True).start()


def play_previous_song():
    global current_song_index, current_playlist_items
    if not current_playlist_items:
        messagebox.showinfo("Playback", "No playlist loaded or empty playlist.")
        return

    prev_index = (current_song_index - 1 + len(current_playlist_items)) % len(current_playlist_items)
    # Ensure the previous song is played in a new thread to avoid freezing GUI
    threading.Thread(target=play_song_from_playlist, args=(prev_index,), daemon=True).start()


def play_song_from_playlist(index):
    global current_song_index, current_playlist_items
    if not current_playlist_items or not (0 <= index < len(current_playlist_items)):
        messagebox.showerror("Playback", "Invalid song index in playlist.")
        return

    entry = current_playlist_items[index]
    current_song_index = index # Update the global index

    mp3p = os.path.join(DOWNLOADS, cleanname(f"{entry['title']} - {entry['id']}.mp3"))
    if os.path.exists(mp3p):
        play_file(mp3p, entry) # Call play_file directly, it handles threading for actual playback
    else:
        def dl_play_and_then_play_file():
            # Update display to show downloading status
            if hasattr(root, 'playback_window') and root.playback_window.winfo_exists():
                root.playback_window.current_song_label.config(text=f"Downloading: {entry['title']}...")
                root.playback_window.thumbnail_label.config(image='') # Clear thumbnail during download
                root.playback_window.thumbnail_label.image = None

            # Disable playback controls during download
            if hasattr(root, 'playback_window') and root.playback_window.winfo_exists():
                root.playback_window.play_btn.config(state=tk.DISABLED)
                root.playback_window.pause_btn.config(state=tk.DISABLED)
                root.playback_window.stop_btn.config(state=tk.DISABLED)
                root.playback_window.next_btn.config(state=tk.DISABLED)
                root.playback_window.prev_btn.config(state=tk.DISABLED)

            mp3 = download_audio_to_mp3(entry["url"], entry)
            download_thumbnail(entry) # Download thumbnail in parallel

            # Re-enable playback controls
            if hasattr(root, 'playback_window') and root.playback_window.winfo_exists():
                root.after(0, lambda: root.playback_window.play_btn.config(state=tk.NORMAL))
                root.after(0, lambda: root.playback_window.pause_btn.config(state=tk.NORMAL))
                root.after(0, lambda: root.playback_window.stop_btn.config(state=tk.NORMAL))
                root.after(0, lambda: root.playback_window.next_btn.config(state=tk.NORMAL))
                root.after(0, lambda: root.playback_window.prev_btn.config(state=tk.NORMAL))

            if mp3:
                play_file(mp3, entry)
            else:
                messagebox.showerror("Download failed", "Could not download playlist item.")
                update_playback_display(None) # Clear display on failure
        threading.Thread(target=dl_play_and_then_play_file, daemon=True).start()


# --- GUI callbacks & helper threads ---
search_results = []

def do_search(query):
    global search_results
    results = yt_search(query)
    search_results = results
    def update():
        results_listbox.delete(0, tk.END)
        for r in search_results:
            results_listbox.insert(tk.END, r["title"])
    root.after(0, update)

def on_search(event=None):
    q = search_entry.get().strip()
    if not q:
        return
    results_listbox.delete(0, tk.END)
    results_listbox.insert(tk.END, "Searching...")
    threading.Thread(target=do_search, args=(q,), daemon=True).start()

def on_play_search_result():
    sel = results_listbox.curselection()
    if not sel:
        messagebox.showinfo("Select", "Select a song first.")
        return
    idx = sel[0]
    entry = search_results[idx]

    # When playing from search results, clear playlist context
    global current_playlist_name, current_playlist_items, current_song_index
    current_playlist_name = None
    current_playlist_items = []
    current_song_index = -1

    mp3_path = cached_mp3_path(entry)
    if os.path.exists(mp3_path):
        threading.Thread(target=play_file, args=(mp3_path, entry), daemon=True).start()
        download_thumbnail(entry) # Ensure thumbnail is downloaded even if MP3 is cached
        return
    def dl_then_play():
        if hasattr(root, 'playback_window') and root.playback_window.winfo_exists():
            root.playback_window.play_btn.config(state=tk.DISABLED)
            root.playback_window.stop_btn.config(state=tk.DISABLED)
            root.playback_window.pause_btn.config(state=tk.DISABLED)
            root.playback_window.next_btn.config(state=tk.DISABLED) # Disable next/prev
            root.playback_window.prev_btn.config(state=tk.DISABLED) # Disable next/prev
            root.playback_window.current_song_label.config(text=f"Downloading: {entry['title']}...")
            root.playback_window.thumbnail_label.config(image='') # Clear thumbnail during download
            root.playback_window.thumbnail_label.image = None
        try:
            mp3 = download_audio_to_mp3(entry["url"], entry)
            download_thumbnail(entry) # Download thumbnail in parallel
            if not mp3:
                messagebox.showerror("Download failed", "Could not download/convert the song.")
                update_playback_display(None)
            else:
                threading.Thread(target=play_file, args=(mp3, entry), daemon=True).start()
        finally:
            if hasattr(root, 'playback_window') and root.playback_window.winfo_exists():
                root.after(0, lambda: root.playback_window.play_btn.config(state=tk.NORMAL))
                root.after(0, lambda: root.playback_window.stop_btn.config(state=tk.NORMAL))
                root.after(0, lambda: root.playback_window.pause_btn.config(state=tk.NORMAL))
                root.after(0, lambda: root.playback_window.next_btn.config(state=tk.NORMAL)) # Re-enable next/prev
                root.after(0, lambda: root.playback_window.prev_btn.config(state=tk.NORMAL)) # Re-enable next/prev
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

    pls = list_playlists()
    if not pls:
        messagebox.showinfo("Playlist", "No playlists exist; create one first.")
        return

    win = tk.Toplevel(root)
    win.title("Select Playlist")
    win.geometry("400x300")

    tk.Label(win, text="Choose a playlist:").pack(pady=8)

    selected_playlist = tk.StringVar(win)
    selected_playlist.set(pls[0])
    dropdown = tk.OptionMenu(win, selected_playlist, *pls)
    dropdown.pack(pady=8)

    def confirm_selection():
        pick = selected_playlist.get()
        if not pick or pick not in playlists:
            messagebox.showerror("Playlist", "Invalid playlist.")
            return
        # Ensure the entry has a thumbnail URL before adding to playlist
        if 'thumbnail' not in entry or not entry['thumbnail']:
            # Re-search to get thumbnail if not already present (e.g., if search was from old data)
            # This is a simplified approach; a more robust solution might re-extract info
            # or prompt the user. For now, we'll just add it without thumbnail if missing.
            pass
        item = {"title": entry["title"], "url": entry["url"], "id": entry["id"], "thumbnail": entry.get("thumbnail")}
        playlists[pick].append(item)
        save_playlists(playlists)
        messagebox.showinfo("Playlist", f"Added to {pick}")
        win.destroy()

    tk.Button(win, text="Add", command=confirm_selection).pack(pady=8)

def open_playlist_window():
    pls = list_playlists()
    if not pls:
        messagebox.showinfo("Playlist", "No playlists saved.")
        return

    win = tk.Toplevel(root)
    win.title("Select Playlist")
    win.geometry("400x350")

    tk.Label(win, text="Choose a playlist:").pack(pady=8)

    lb = tk.Listbox(win, width=40, height=15)
    lb.pack(pady=8, padx=8, fill=tk.BOTH, expand=True)

    for pl in pls:
        lb.insert(tk.END, pl)

    def open_selected_playlist_action():
        global current_playlist_name, current_playlist_items, current_song_index, current_playing_entry
        sel = lb.curselection()
        if not sel:
            messagebox.showinfo("Select", "Select a playlist first.")
            return
        chosen_playlist_name = lb.get(sel[0])
        win.destroy()

        # Set global playlist context
        current_playlist_name = chosen_playlist_name
        current_playlist_items = playlists[chosen_playlist_name]
        current_song_index = -1 # Reset index when a new playlist is opened

        playlist_win = tk.Toplevel(root)
        playlist_win.title(f"Playlist: {chosen_playlist_name}")
        playlist_lb = tk.Listbox(playlist_win, width=80, height=15)
        playlist_lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        for it in current_playlist_items: # Use global items for display
            playlist_lb.insert(tk.END, it["title"])

        def play_from_playlist_selected():
            sel = playlist_lb.curselection()
            if not sel:
                return
            index_to_play = sel[0]
            threading.Thread(target=play_song_from_playlist, args=(index_to_play,), daemon=True).start()

        def remove_selected_from_playlist():
            global current_playlist_items, current_song_index, current_playing_entry
            sel_indices = playlist_lb.curselection()
            if not sel_indices:
                messagebox.showinfo("Remove", "Select one or more songs to remove.")
                return

            # Convert tuple of indices to a list and sort in descending order
            # This is important to avoid index shifting issues when deleting multiple items
            indices_to_remove = sorted(list(sel_indices), reverse=True)

            for idx in indices_to_remove:
                if 0 <= idx < len(current_playlist_items):
                    removed_entry = current_playlist_items.pop(idx)
                    # If the removed song was the currently playing one, stop playback
                    if current_playing_entry and removed_entry['id'] == current_playing_entry['id']:
                        stop_playback()
                    # Adjust current_song_index if a song before it was removed
                    if current_song_index != -1 and idx < current_song_index:
                        current_song_index -= 1

            # Update the listbox display
            playlist_lb.delete(0, tk.END)
            for it in current_playlist_items:
                playlist_lb.insert(tk.END, it["title"])

            # Save the updated playlist
            playlists[current_playlist_name] = current_playlist_items
            save_playlists(playlists)
            messagebox.showinfo("Remove", "Selected song(s) removed from playlist.")


        def play_sequentially_from_start():
            # This will start playing from the first song or selected song
            sel = playlist_lb.curselection()
            start_index = sel[0] if sel else 0
            threading.Thread(target=play_song_from_playlist_sequence, args=(start_index,), daemon=True).start()

        def play_song_from_playlist_sequence(index):
            global current_song_index, current_playlist_items
            if index >= len(current_playlist_items):
                stop_playback() # End of playlist
                return

            entry = current_playlist_items[index]
            current_song_index = index # Update global index

            mp3p = os.path.join(DOWNLOADS, cleanname(f"{entry['title']} - {entry['id']}.mp3"))
            if os.path.exists(mp3p):
                play_file(mp3p, entry)
            else:
                # Disable playback controls during download
                if hasattr(root, 'playback_window') and root.playback_window.winfo_exists():
                    root.playback_window.play_btn.config(state=tk.DISABLED)
                    root.playback_window.pause_btn.config(state=tk.DISABLED)
                    root.playback_window.stop_btn.config(state=tk.DISABLED)
                    root.playback_window.next_btn.config(state=tk.DISABLED)
                    root.playback_window.prev_btn.config(state=tk.DISABLED)
                    root.playback_window.current_song_label.config(text=f"Downloading: {entry['title']}...")
                    root.playback_window.thumbnail_label.config(image='') # Clear thumbnail during download
                    root.playback_window.thumbnail_label.image = None

                mp3 = download_audio_to_mp3(entry["url"], entry)
                download_thumbnail(entry) # Download thumbnail in parallel

                # Re-enable playback controls
                if hasattr(root, 'playback_window') and root.playback_window.winfo_exists():
                    root.playback_window.play_btn.config(state=tk.NORMAL)
                    root.playback_window.pause_btn.config(state=tk.NORMAL)
                    root.playback_window.stop_btn.config(state=tk.NORMAL)
                    root.playback_window.next_btn.config(state=tk.NORMAL)
                    root.playback_window.prev_btn.config(state=tk.NORMAL)

                if mp3:
                    play_file(mp3, entry)
                else:
                    messagebox.showerror("Download failed", f"Could not download {entry['title']}.")
                    update_playback_display(None)
                    return

            # Wait for current song to finish before playing next
            while pygame.mixer.music.get_busy():
                root.update()
            play_song_from_playlist_sequence(index + 1)


        def shuffle_playlist_action():
            global current_playlist_items, current_song_index, current_playing_entry
            if not current_playlist_items: return

            # Store the ID of the currently playing song, if any
            playing_id = current_playing_entry['id'] if current_playing_entry else None

            import random
            random.shuffle(current_playlist_items) # Shuffle the global list

            # Update the listbox display
            playlist_lb.delete(0, tk.END)
            for it in current_playlist_items:
                playlist_lb.insert(tk.END, it["title"])

            # Update current_song_index if the playing song is still in the list
            if playing_id:
                try:
                    current_song_index = next(i for i, item in enumerate(current_playlist_items) if item['id'] == playing_id)
                except StopIteration:
                    current_song_index = -1 # Song no longer in playlist or not found
            else:
                current_song_index = -1 # No song was playing

            # Save the shuffled order to the actual playlists dictionary
            playlists[current_playlist_name] = current_playlist_items
            save_playlists(playlists)

        def sort_playlist_action():
            global current_playlist_items, current_song_index, current_playing_entry
            if not current_playlist_items: return

            playing_id = current_playing_entry['id'] if current_playing_entry else None

            current_playlist_items.sort(key=lambda x: x["title"].lower()) # Sort the global list

            playlist_lb.delete(0, tk.END)
            for it in current_playlist_items:
                playlist_lb.insert(tk.END, it["title"])

            if playing_id:
                try:
                    current_song_index = next(i for i, item in enumerate(current_playlist_items) if item['id'] == playing_id)
                except StopIteration:
                    current_song_index = -1
            else:
                current_song_index = -1

            # Save the sorted order to the actual playlists dictionary
            playlists[current_playlist_name] = current_playlist_items
            save_playlists(playlists)

        # Frame for playlist control buttons
        playlist_buttons_frame = tk.Frame(playlist_win)
        playlist_buttons_frame.pack(pady=8)

        tk.Button(playlist_buttons_frame, text="Play Selected", command=play_from_playlist_selected).pack(side=tk.LEFT, padx=4)
        tk.Button(playlist_buttons_frame, text="Play All", command=play_sequentially_from_start).pack(side=tk.LEFT, padx=4)
        tk.Button(playlist_buttons_frame, text="Shuffle", command=shuffle_playlist_action).pack(side=tk.LEFT, padx=4)
        tk.Button(playlist_buttons_frame, text="Sort Alphabetically", command=sort_playlist_action).pack(side=tk.LEFT, padx=4)
        tk.Button(playlist_buttons_frame, text="Remove Selected", command=remove_selected_from_playlist).pack(side=tk.LEFT, padx=4) # New button

    tk.Button(win, text="Open", command=open_selected_playlist_action).pack(pady=8, side=tk.BOTTOM)

# --- Playback Control Window ---
def open_playback_window():
    if hasattr(root, 'playback_window') and root.playback_window.winfo_exists():
        root.playback_window.lift()
        return

    playback_win = tk.Toplevel(root)
    playback_win.title("Playback Controls")
    playback_win.geometry("300x300") # Increased height for thumbnail and next/prev buttons
    playback_win.resizable(False, False)

    root.playback_window = playback_win

    # Thumbnail Label
    playback_win.thumbnail_label = tk.Label(playback_win)
    playback_win.thumbnail_label.pack(pady=(10, 5))

    # Label to display current song title
    playback_win.current_song_label = tk.Label(playback_win, text="Now Playing: None", wraplength=280, justify=tk.CENTER)
    playback_win.current_song_label.pack(pady=(5, 10))

    playback_controls_frame = tk.Frame(playback_win)
    playback_controls_frame.pack(pady=5) # Use pack for the frame

    # Use pack for the control buttons within the frame
    playback_win.prev_btn = tk.Button(playback_controls_frame, text="<< Prev", command=play_previous_song)
    playback_win.prev_btn.pack(side=tk.LEFT, padx=2)
    playback_win.play_btn = tk.Button(playback_controls_frame, text="Play", command=on_play_search_result)
    playback_win.play_btn.pack(side=tk.LEFT, padx=2)
    playback_win.pause_btn = tk.Button(playback_controls_frame, text="Pause/Resume", command=on_pause)
    playback_win.pause_btn.pack(side=tk.LEFT, padx=2)
    playback_win.stop_btn = tk.Button(playback_controls_frame, text="Stop", command=on_stop)
    playback_win.stop_btn.pack(side=tk.LEFT, padx=2)
    playback_win.next_btn = tk.Button(playback_controls_frame, text="Next >>", command=play_next_song)
    playback_win.next_btn.pack(side=tk.LEFT, padx=2)

    # Volume Slider
    volume_frame = tk.Frame(playback_win)
    volume_frame.pack(pady=10)
    tk.Label(volume_frame, text="Volume:").pack(side=tk.LEFT)
    playback_win.volume_slider = tk.Scale(volume_frame, from_=0, to=100, orient=tk.HORIZONTAL, command=set_volume)
    playback_win.volume_slider.set(int(pygame.mixer.music.get_volume() * 100)) # Set initial slider position
    playback_win.volume_slider.pack(side=tk.LEFT, fill=tk.X, expand=True)


    # Initial display update
    update_playback_display(current_playing_entry)

# --- Splash Screen Function ---
def show_splash_screen():
    splash_root = tk.Tk()
    splash_root.withdraw() # Hide the main window initially

    splash_screen = tk.Toplevel(splash_root)
    splash_screen.overrideredirect(True) # Remove window decorations (title bar, borders)
    splash_screen.attributes("-topmost", True) # Keep splash screen on top

    # Load the image
    try:
        img = Image.open(LUNA_LOGO_PATH)
        img = img.resize((800, 640), Image.LANCZOS)
        photo = ImageTk.PhotoImage(img)
    except FileNotFoundError:
        messagebox.showerror("Error", f"Luna.png not found at {LUNA_LOGO_PATH}")
        splash_root.destroy()
        return
    except Exception as e:
        messagebox.showerror("Error", f"Could not load Luna.png: {e}")
        splash_root.destroy()
        return

    splash_label = tk.Label(splash_screen, image=photo, bg="white")
    splash_label.pack()

    # Center the splash screen
    splash_screen.update_idletasks()
    x = (splash_screen.winfo_screenwidth() // 2) - (splash_screen.winfo_width() // 2)
    y = (splash_screen.winfo_screenheight() // 2) - (splash_screen.winfo_height() // 2)
    splash_screen.geometry(f"+{x}+{y}")

    splash_screen.update()
    time.sleep(3) # Display for 3 seconds
    splash_screen.destroy()
    splash_root.destroy() # Destroy the hidden root for the splash screen

# --- Main GUI ---
if __name__ == "__main__":
    show_splash_screen() # Call the splash screen function before main GUI

    root = tk.Tk()
    root.title("Luna Music Player")

    top = tk.Frame(root)
    top.pack(fill=tk.X, padx=8, pady=6)

    search_entry = tk.Entry(top, width=60)
    search_entry.pack(side=tk.LEFT, padx=(0,6), expand=True, fill=tk.X)
    # Insert placeholder text
    search_entry.insert(0, "song or artist and press Search")


    # Function to clear placeholder when user clicks for the first time
    def clear_placeholder(event):
        if search_entry.get() == "song or artist and press Search":
            search_entry.delete(0, tk.END)
            search_entry.config(fg="black")  # Optional: reset text color if you use grey for placeholder


    search_entry.bind("<FocusIn>", clear_placeholder)  # Any focus (mouse or keyboard)
    search_entry.bind("<Return>", on_search)

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

    tk.Button(controls, text="Create Playlist", width=14, command=create_playlist).grid(row=0, column=0, padx=4)
    tk.Button(controls, text="Add to Playlist", width=14, command=add_selected_to_playlist).grid(row=0, column=1, padx=4)
    tk.Button(controls, text="Open Playlist", width=14, command=open_playlist_window).grid(row=0, column=2, padx=4)
    tk.Button(controls, text="Open Playback Controls", width=20, command=open_playback_window).grid(row=0, column=3, padx=4)

    tk.Button(root, text="Open Downloads Folder", command=lambda: os.startfile(str(DOWNLOADS))).pack(pady=6)
    root.protocol("WM_DELETE_WINDOW", lambda: (stop_playback(), root.destroy()))
    root.mainloop()
