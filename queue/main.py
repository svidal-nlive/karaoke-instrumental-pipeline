import os
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

PIPELINE_DIR = "/pipeline"

class PipelineHandler(FileSystemEventHandler):
    def on_created(self, event):
        item = event.src_path
        if event.is_directory:
            print(f"📦 New album folder queued: {item}")
        else:
            print(f"🎵 New file queued: {item}")

        # TODO: Send job to actual processing queue
        # For now, just log it
        print(f"📝 Queued for processing: {item}")

if __name__ == "__main__":
    print(f"🧭 Starting Queue Manager. Watching {PIPELINE_DIR}...")
    event_handler = PipelineHandler()
    observer = Observer()
    observer.schedule(event_handler, PIPELINE_DIR, recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
