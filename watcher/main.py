import os
import time
import shutil
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

WATCH_DIR = "/downloads"
TARGET_DIR = "/pipeline"
STABILITY_TIME = 10  # seconds to wait before checking again

def is_file_stable(path):
    previous_size = -1
    try:
        while True:
            current_size = os.path.getsize(path)
            if current_size == previous_size:
                return True
            previous_size = current_size
            time.sleep(STABILITY_TIME)
    except FileNotFoundError:
        return False

def is_directory_fully_stable(path, wait_time=10, check_interval=2):
    """
    Returns True if the directory hasn't changed (size-wise) for the full wait_time.
    """
    stable_duration = 0
    previous_size = -1

    while stable_duration < wait_time:
        total_size = 0
        for root, _, files in os.walk(path):
            for f in files:
                try:
                    total_size += os.path.getsize(os.path.join(root, f))
                except FileNotFoundError:
                    pass  # skip temp/deleted files mid-download

        if total_size == previous_size:
            stable_duration += check_interval
        else:
            stable_duration = 0
            previous_size = total_size

        time.sleep(check_interval)

    return True

class DownloadHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            self.handle_directory(event.src_path)
        else:
            self.handle_file(event.src_path)

    def handle_file(self, path):
        print(f"📄 Detected new file: {path}")
        if is_file_stable(path):
            filename = os.path.basename(path)
            target_path = os.path.join(TARGET_DIR, filename)
            shutil.copy2(path, target_path)
            print(f"✅ Copied file to: {target_path}")
            try:
                os.remove(path)
                print(f"🗑️ Removed original file: {path}")
            except PermissionError:
                print(f"⚠️ Could not remove file: {path}")

    def handle_directory(self, path):
        print(f"📁 Detected new folder: {path}")
        if is_directory_fully_stable(path):
            folder_name = os.path.basename(path)
            target_path = os.path.join(TARGET_DIR, folder_name)
            shutil.copytree(path, target_path, dirs_exist_ok=True)
            print(f"📦 Copied album folder to: {target_path}")
            try:
                shutil.rmtree(path)
                print(f"🧹 Removed original album folder: {path}")
            except PermissionError:
                print(f"⚠️ Could not remove album folder: {path}")

if __name__ == "__main__":
    os.makedirs(TARGET_DIR, exist_ok=True)
    event_handler = DownloadHandler()
    observer = Observer()
    observer.schedule(event_handler, WATCH_DIR, recursive=True)
    observer.start()
    print(f"👀 Watching {WATCH_DIR} for new files and folders...")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
