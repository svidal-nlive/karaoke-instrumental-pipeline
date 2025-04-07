#!/usr/bin/env python
import os
import time
import json
import pika
import shutil
import logging
import hashlib
from spleeter.separator import Separator

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

RABBITMQ_HOST = "rabbitmq"
SPLITTER_QUEUE = "splitter_jobs"
CONVERTER_QUEUE = "converter_jobs"
OUTPUT_DIR = "/splitter_output"

processed_tracks = set()

def compute_file_hash(file_path, hash_algo='md5'):
    hash_func = hashlib.new(hash_algo)
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_func.update(chunk)
    return hash_func.hexdigest()

def connect_to_rabbitmq_with_retries(host, credentials, max_attempts=15, delay=5):
    for attempt in range(1, max_attempts + 1):
        try:
            logger.info("Attempting RabbitMQ connection (%d/%d)...", attempt, max_attempts)
            parameters = pika.ConnectionParameters(
                host=host,
                credentials=credentials,
                heartbeat=600,
                blocked_connection_timeout=300
            )
            connection = pika.BlockingConnection(parameters)
            logger.info("Successfully connected to RabbitMQ on attempt %d.", attempt)
            return connection
        except Exception as e:
            logger.warning("RabbitMQ not ready (attempt %d/%d). Retrying in %d seconds...", attempt, max_attempts, delay)
            time.sleep(delay)
    raise ConnectionError("Could not connect to RabbitMQ after multiple attempts.")

def send_converter_job(job_payload):
    credentials = pika.PlainCredentials('admin', 'admin')
    try:
        connection = connect_to_rabbitmq_with_retries(RABBITMQ_HOST, credentials)
        channel = connection.channel()
        channel.queue_declare(queue=CONVERTER_QUEUE, durable=True)
        body = json.dumps(job_payload)
        channel.basic_publish(
            exchange='',
            routing_key=CONVERTER_QUEUE,
            body=body,
            properties=pika.BasicProperties(delivery_mode=2)
        )
        connection.close()
        logger.info("Sent job to converter queue for: %s", job_payload.get('original_filename'))
    except Exception as e:
        logger.error("Failed to send converter job: %s", e)

def process_track(path, metadata_key):
    logger.info("Processing track: %s", path)
    abs_path = os.path.abspath(path)
    if abs_path in processed_tracks:
        logger.info("Track %s already processed; skipping.", path)
        return

    originals_dir = "/originals"  # This is our flat folder for originals.
    os.makedirs(originals_dir, exist_ok=True)
    original_filename = os.path.basename(path)
    destination_path = os.path.join(originals_dir, original_filename)

    # Check if the file is already in the originals folder.
    if os.path.abspath(path) == os.path.abspath(destination_path):
        logger.info("Source and destination are identical; using existing file.")
        original_copy = path
    else:
        try:
            shutil.copy2(path, destination_path)
            logger.info("Copied original file to: %s", destination_path)
            original_copy = destination_path
        except Exception as e:
            logger.error("Error copying original file: %s", e)
            original_copy = path

    processed_tracks.add(abs_path)

    if not metadata_key:
        try:
            metadata_key = compute_file_hash(original_copy)
            logger.info("Recomputed metadata_key: %s", metadata_key)
        except Exception as e:
            logger.error("Failed to compute metadata_key for %s: %s", original_copy, e)

    try:
        separator = Separator('spleeter:5stems')
        separator.separate_to_file(path, OUTPUT_DIR)
        logger.info("Stem separation complete for: %s", path)
    except Exception as e:
        logger.error("Stem separation failed for %s: %s", path, e)
        return

    base_folder = os.path.splitext(original_filename)[0]
    source_folder = os.path.join(OUTPUT_DIR, base_folder)
    stems = []
    try:
        for file in os.listdir(source_folder):
            if file.endswith(".wav") and file != "vocals.wav":
                stems.append(file)
    except Exception as e:
        logger.error("Error reading stems from %s: %s", source_folder, e)

    if not stems:
        logger.warning("No stems found for %s", path)

    job_payload = {
        "type": "convert",
        "source_folder": source_folder,
        "stems": stems,
        "original_filename": original_filename,
        "original_file": original_copy,
        "metadata_key": metadata_key
    }
    send_converter_job(job_payload)

def callback(ch, method, properties, body):
    try:
        job = json.loads(body.decode())
        logger.info("Received job: %s - %s", job.get("type").upper(), job.get("path"))
        metadata_key = job.get("metadata_key")
        job_type = job.get("type").lower()
        path = job.get("path")
        if job_type == "track" and os.path.isfile(path):
            process_track(path, metadata_key)
        elif job_type == "album":
            if os.path.isdir(path):
                for file in os.listdir(path):
                    if file.lower().endswith(".mp3"):
                        process_track(os.path.join(path, file), metadata_key)
            elif os.path.isfile(path):
                logger.info("Album job received as file; treating as track: %s", path)
                process_track(path, metadata_key)
            else:
                logger.warning("Unknown or invalid job type or path: %s", job)
        else:
            logger.warning("Unknown or invalid job type or path: %s", job)
        ch.basic_ack(delivery_tag=method.delivery_tag)
    except Exception as e:
        logger.error("Error processing job: %s", e)
        try:
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        except Exception as nack_err:
            logger.error("Error sending nack: %s", nack_err)

def run():
    credentials = pika.PlainCredentials('admin', 'admin')
    while True:
        try:
            connection = connect_to_rabbitmq_with_retries(RABBITMQ_HOST, credentials)
            channel = connection.channel()
            channel.queue_declare(queue=SPLITTER_QUEUE, durable=True)
            channel.basic_qos(prefetch_count=1)
            channel.basic_consume(queue=SPLITTER_QUEUE, on_message_callback=callback)
            logger.info("Splitter started consuming from queue.")
            channel.start_consuming()
        except Exception as e:
            logger.error("Unexpected error: %s. Reconnecting...", e)
            try:
                connection.close()
            except Exception:
                pass
            time.sleep(5)

if __name__ == "__main__":
    run()
