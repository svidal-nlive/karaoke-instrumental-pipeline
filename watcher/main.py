#!/usr/bin/env python
import os
import time
import shutil
import json
import hashlib
import logging
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from mutagen.easyid3 import EasyID3
import redis

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

WATCH_DIR = "/downloads"
ORIGINALS_DIR = "/originals"  # New flat folder for originals
RABBITMQ_HOST = "rabbitmq"
PROCESSING_QUEUE = "splitter_jobs"
STABILITY_TIME = 10  # seconds

# Connect to Redis
redis_client = redis.StrictRedis(host=os.getenv("REDIS_HOST", "redis"), port=6379, decode_responses=True)

def compute_file_hash(file_path, hash_algo='md5'):
    hash_func = hashlib.new(hash_algo)
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_func.update(chunk)
    return hash_func.hexdigest()

def extract_metadata(file_path):
    try:
        meta = EasyID3(file_path)
        # Convert metadata to a plain dict (join lists as comma-separated strings)
        return {k: ", ".join(v) if isinstance(v, list) else str(v) for k, v in meta.items()}
    except Exception as e:
        logger.warning("Failed to extract metadata from %s: %s", file_path, e)
        return {}

def store_metadata(metadata_key, metadata):
    try:
        # Store each field in Redis under key: metadata:<metadata_key>
        redis_key = f"metadata:{metadata_key}"
        for field, value in metadata.items():
            redis_client.hset(redis_key, field, value)
        logger.info("Stored metadata under key %s", redis_key)
    except Exception as e:
        logger.error("Error storing metadata for key %s: %s", metadata_key, e)

def send_job(queue, job_payload):
    import pika
    try:
        credentials = pika.PlainCredentials('admin', 'admin')
        parameters = pika.ConnectionParameters(host=RABBITMQ_HOST, credentials=credentials)
        connection = pika.BlockingConnection(parameters)
        channel = connection.channel()
        channel.queue_declare(queue=queue, durable=True)
        body = json.dumps(job_payload)
        channel.basic_publish(
            exchange='',
            routing_key=queue,
            body=body,
            properties=pika.BasicProperties(delivery_mode=2)
        )
        connection.close()
        logger.info("Sent job to %s: %s", queue, job_payload)
    except Exception as e:
        logger.error("Failed to send job to %s: %s", queue, e)

class DownloadHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            self.handle_directory(event.src_path)
        else:
            self.handle_file(event.src_path)

    def handle_file(self, path):
        logger.info("Detected new file: %s", path)
        if self.is_file_stable(path):
            os.makedirs(ORIGINALS_DIR, exist_ok=True)
            # Compute canonical name using metadata (if available)
            try:
                meta = EasyID3(path)
                title = meta.get("title", ["Unknown Title"])[0].strip()
                artist = meta.get("artist", ["Unknown Artist"])[0].strip()
                canonical_name = f"{title} - {artist}.mp3"
            except Exception:
                canonical_name = os.path.basename(path)
            target_path = os.path.join(ORIGINALS_DIR, canonical_name)
            try:
                shutil.move(path, target_path)
                logger.info("Moved file to originals: %s", target_path)
            except Exception as e:
                logger.error("Error moving file %s to originals: %s", path, e)
                target_path = path

            # Compute a metadata key (e.g. file hash)
            file_hash = compute_file_hash(target_path)
            # Extract metadata and store it in Redis
            metadata = extract_metadata(target_path)
            store_metadata(file_hash, metadata)

            job = {
                "type": "track",
                "path": target_path,
                "metadata_key": file_hash
            }
            send_job(PROCESSING_QUEUE, job)

    def is_file_stable(self, path):
        previous_size = -1
        while True:
            try:
                current_size = os.path.getsize(path)
            except Exception:
                return False
            if current_size == previous_size:
                return True
            previous_size = current_size
            time.sleep(STABILITY_TIME)

    def handle_directory(self, path):
        logger.info("Detected new folder: %s", path)
        if self.is_directory_stable(path):
            for root, _, files in os.walk(path):
                for file in files:
                    if file.lower().endswith(".mp3"):
                        full_path = os.path.join(root, file)
                        self.handle_file(full_path)
            try:
                shutil.rmtree(path)
                logger.info("Removed original folder: %s", path)
            except Exception as e:
                logger.error("Error removing folder %s: %s", path, e)

    def is_directory_stable(self, path, wait_time=10, check_interval=2):
        stable_duration = 0
        previous_size = -1
        while stable_duration < wait_time:
            total_size = 0
            for root, _, files in os.walk(path):
                for file in files:
                    try:
                        total_size += os.path.getsize(os.path.join(root, file))
                    except Exception:
                        pass
            if total_size == previous_size:
                stable_duration += check_interval
            else:
                stable_duration = 0
                previous_size = total_size
            time.sleep(check_interval)
        return True

if __name__ == "__main__":
    os.makedirs(ORIGINALS_DIR, exist_ok=True)
    event_handler = DownloadHandler()
    observer = Observer()
    observer.schedule(event_handler, WATCH_DIR, recursive=True)
    observer.start()
    logger.info("Watching %s for new files and folders...", WATCH_DIR)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
