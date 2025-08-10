import os
import sys
import subprocess
import json
import urllib.request
import zipfile
import shutil

# === CONFIG ===
REQUIRED_MODULES = ["yt_dlp", "pydub","audioop-lts"]
DOWNLOADS_DIR = "downloads"
PLAYLIST_FILE = "playlists.json"
FFMPEG_DIR = os.path.join(os.getcwd(), "ffmpeg")
FFMPEG_BIN = os.path.join(FFMPEG_DIR, "bin", "ffmpeg.exe")


def install_module(module):
    """Install a Python module via pip."""
    try:
        __import__(module)
        print(f"[OK] Python module '{module}' is already installed.")
    except ImportError:
        print(f"[INSTALL] Installing '{module}'...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", module])


def check_ffmpeg():
    """Check if FFmpeg exists, if not, download and extract it."""
    if os.path.isfile(FFMPEG_BIN):
        print("[OK] FFmpeg is already installed.")
        return

    print("[INSTALL] Downloading FFmpeg...")
    ffmpeg_zip_url = "https://github.com/GyanD/codexffmpeg/releases/download/7.1.1/ffmpeg-7.1.1-essentials_build.zip"
    ffmpeg_zip_path = os.path.join(os.getcwd(), "ffmpeg.zip")

    urllib.request.urlretrieve(ffmpeg_zip_url, ffmpeg_zip_path)

    print("[EXTRACT] Extracting FFmpeg...")
    with zipfile.ZipFile(ffmpeg_zip_path, 'r') as zip_ref:
        zip_ref.extractall(os.getcwd())

    # Find extracted FFmpeg folder
    for folder in os.listdir():
        if folder.startswith("ffmpeg") and os.path.isdir(folder) and folder != "ffmpeg":
            shutil.move(folder, FFMPEG_DIR)
            break

    os.remove(ffmpeg_zip_path)
    print("[DONE] FFmpeg installed.")


def setup_folders_files():
    """Create essential folders and files."""
    if not os.path.exists(DOWNLOADS_DIR):
        os.makedirs(DOWNLOADS_DIR)
        print(f"[CREATE] Folder '{DOWNLOADS_DIR}' created.")
    else:
        print(f"[OK] Folder '{DOWNLOADS_DIR}' exists.")

    if not os.path.exists(PLAYLIST_FILE):
        with open(PLAYLIST_FILE, "w") as f:
            json.dump({}, f)
        print(f"[CREATE] File '{PLAYLIST_FILE}' created.")
    else:
        print(f"[OK] File '{PLAYLIST_FILE}' exists.")


if __name__ == "__main__":
    print("=== Running Prerequisite Checker ===")

    # 1. Check Python packages
    for module in REQUIRED_MODULES:
        install_module(module)

    # 2. Check tkinter (should be default in Python)
    try:
        import tkinter
        print("[OK] Tkinter is available.")
    except ImportError:
        print("[WARNING] Tkinter is not installed! Install Python with Tkinter support.")

    # 3. Check FFmpeg
    check_ffmpeg()

    # 4. Setup folders and files
    setup_folders_files()

    print("=== All prerequisites are satisfied. You can now run music_player.py ===")
