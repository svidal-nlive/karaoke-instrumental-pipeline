#!/usr/bin/env python
import os
import time
import json
import pika
import logging
import redis
import hashlib
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

PIPELINE_DIR = "/pipeline"
RABBITMQ_HOST = "rabbitmq"
QUEUE_NAME = "splitter_jobs"

redis_host = os.getenv("REDIS_HOST", "redis")
redis_port = int(os.getenv("REDIS_PORT", "6379"))
redis_client = redis.StrictRedis(host=redis_host, port=redis_port, decode_responses=True)

DEDUP_KEY = "submitted_jobs"

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
        except pika.exceptions.AMQPConnectionError:
            logger.warning("RabbitMQ not ready (attempt %d/%d). Retrying in %d seconds...", attempt, max_attempts, delay)
            time.sleep(delay)
    raise ConnectionError("Could not connect to RabbitMQ after multiple attempts.")

def send_to_queue(job: dict):
    try:
        # Compute a unique job id (using the metadata_key if present, or a hash of the path)
        job_id = job.get("metadata_key") or compute_file_hash(job["path"])
        # Use a fixed key so that duplicate jobs can be detected.
        if redis_client.sismember(DEDUP_KEY, job_id):
            logger.info("Job already submitted (job_id=%s); skipping duplicate.", job_id)
            return

        # Add the job_id to the payload so that downstream services can also use it if needed.
        job["job_id"] = job_id

        payload = json.dumps(job, sort_keys=True)
        credentials = pika.PlainCredentials('admin', 'admin')
        connection = connect_to_rabbitmq_with_retries(RABBITMQ_HOST, credentials)
        channel = connection.channel()
        channel.queue_declare(queue=QUEUE_NAME, durable=True)
        channel.basic_publish(
            exchange='',
            routing_key=QUEUE_NAME,
            body=payload,
            properties=pika.BasicProperties(delivery_mode=2)
        )
        connection.close()
        redis_client.sadd(DEDUP_KEY, job_id)
        logger.info("Sent job to queue: %s", payload)
    except Exception as e:
        logger.error("Failed to send job to queue: %s", e)

class PipelineHandler(FileSystemEventHandler):
    def on_created(self, event):
        try:
            with open(event.src_path + ".job", "r") as f:
                job = json.load(f)
            payload = json.dumps(job)
            send_to_queue(payload)
        except Exception as e:
            job = {
                "type": "album" if os.path.isdir(event.src_path) else "track",
                "path": event.src_path,
            }
            if event.src_path.lower().endswith(".mp3"):
                try:
                    file_hash = compute_file_hash(event.src_path)
                    job["metadata_key"] = file_hash
                except Exception as hash_err:
                    logger.error("Error computing metadata_key for %s: %s", event.src_path, hash_err)
            payload = json.dumps(job)
            send_to_queue(payload)

if __name__ == "__main__":
    logger.info("Starting Queue Manager. Watching %s...", PIPELINE_DIR)
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
