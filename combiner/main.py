#!/usr/bin/env python
import os
import json
import pika
import subprocess
import logging
import redis
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

RABBITMQ_HOST = "rabbitmq"
COMBINER_QUEUE = "combiner_jobs"
MUSIC_DIR = "/music"  # Final instrumentals are placed here.

# Set up Redis connection.
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
redis_client = redis.StrictRedis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

def connect_to_rabbitmq_with_retries(host, credentials, max_attempts=10, delay=3):
    for attempt in range(1, max_attempts+1):
        try:
            logger.info("🐇 Attempting RabbitMQ connection (%d/%d)...", attempt, max_attempts)
            parameters = pika.ConnectionParameters(host=host, credentials=credentials)
            connection = pika.BlockingConnection(parameters)
            logger.info("✅ Successfully connected to RabbitMQ on attempt %d.", attempt)
            return connection
        except Exception as e:
            logger.warning("⚠️ RabbitMQ connection attempt %d/%d failed: %s. Retrying in %d seconds...", attempt, max_attempts, e, delay)
            time.sleep(delay)
    raise ConnectionError("❌ Could not connect to RabbitMQ after multiple attempts.")

def get_stored_metadata(metadata_key):
    key = f"metadata:{metadata_key}"
    metadata = redis_client.hgetall(key)
    return metadata

def generate_canonical_filename(metadata):
    """
    Build the canonical filename using the song's metadata.
    Returns a string in the format: "%title% - %artist% - (Instrumental).mp3"
    """
    title = metadata.get("title", "").strip() if metadata.get("title") else ""
    artist = metadata.get("artist", "").strip() if metadata.get("artist") else ""
    if title and artist:
        return f"{title} - {artist} - (Instrumental).mp3"
    return None

def combine_stems(job):
    source_folder = job.get("source_folder")
    stems = job.get("stems", [])
    original_filename = job.get("original_filename", "output.mp3")
    if job.get("type") == "album":
        cleanup_target = job.get("album_folder")
    else:
        cleanup_target = job.get("original_file")
    metadata_key = job.get("metadata_key")
    metadata = get_stored_metadata(metadata_key)
    canonical_name = generate_canonical_filename(metadata)
    if not canonical_name:
        base, _ = os.path.splitext(original_filename)
        canonical_name = f"{base}_combined.mp3"
    final_output = os.path.join(MUSIC_DIR, canonical_name)
    input_files = [os.path.join(source_folder, stem) for stem in stems]
    num_inputs = len(input_files)
    cmd = ["ffmpeg", "-y"]
    for file in input_files:
        cmd.extend(["-i", file])
    filter_complex = f"amix=inputs={num_inputs}:duration=longest"
    cmd.extend(["-filter_complex", filter_complex, final_output])
    logger.info("🔄 Combining stems with command: %s", " ".join(cmd))
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    logger.info("✅ Combined instrumental created at: %s", final_output)
    cleanup_paths = []
    duplicate_path = os.path.join("/pipeline", os.path.basename(cleanup_target))
    if os.path.exists(duplicate_path):
        cleanup_paths.append(duplicate_path)
    cleanup_paths.append(cleanup_target)
    base_folder = os.path.splitext(os.path.basename(cleanup_target))[0]
    splitter_folder = os.path.join("/splitter_output", base_folder)
    cleanup_paths.append(splitter_folder)
    converted_folder = os.path.join(splitter_folder, "converted")
    cleanup_paths.append(converted_folder)
    return final_output, canonical_name, cleanup_paths

def send_metadata_job(job_payload, credentials):
    try:
        connection = connect_to_rabbitmq_with_retries(RABBITMQ_HOST, credentials)
        channel = connection.channel()
        metadata_queue = "metadata_jobs"
        channel.queue_declare(queue=metadata_queue, durable=True)
        body = json.dumps(job_payload)
        channel.basic_publish(
            exchange='',
            routing_key=metadata_queue,
            body=body,
            properties=pika.BasicProperties(delivery_mode=2)
        )
        connection.close()
        logger.info("📤 Sent metadata job for file: %s", job_payload.get('final_file'))
    except Exception as e:
        logger.error("❌ Failed to send metadata job: %s", e)

def send_cleanup_job(original_file, final_file, converted_folder, credentials):
    try:
        connection = connect_to_rabbitmq_with_retries(RABBITMQ_HOST, credentials)
        channel = connection.channel()
        cleanup_queue = "cleanup_jobs"
        channel.queue_declare(queue=cleanup_queue, durable=True)
        payload = {
            "original_file": original_file,
            "final_file": final_file,
            "converted_folder": converted_folder
        }
        body = json.dumps(payload)
        channel.basic_publish(
            exchange='',
            routing_key=cleanup_queue,
            body=body,
            properties=pika.BasicProperties(delivery_mode=2)
        )
        connection.close()
        logger.info("📤 Sent cleanup job for original: %s, final: %s", original_file, final_file)
    except Exception as e:
        logger.error("❌ Failed to send cleanup job: %s", e)

def callback(ch, method, properties, body):
    credentials = pika.PlainCredentials('admin', 'admin')
    try:
        job = json.loads(body.decode())
        logger.info("📬 Received combiner job: %s", job)
        final_file, canonical_name, cleanup_paths = combine_stems(job)
        ch.basic_ack(delivery_tag=method.delivery_tag)
        metadata_job = {
            "original_file": job.get("album_folder") or job.get("original_file"),
            "final_file": final_file,
            "original_filename": job.get("original_filename"),
            "source_folder": job.get("source_folder"),
            "metadata_key": job.get("metadata_key"),
            "canonical_name": canonical_name,
            "cleanup_paths": cleanup_paths,
            "early": False
        }
        send_metadata_job(metadata_job, credentials)

        metadata_job = {
            "original_file": job.get("album_folder") or job.get("original_file"),
            "final_file": final_file,
            "original_filename": job.get("original_filename"),
            "source_folder": job.get("source_folder"),
            "metadata_key": job.get("metadata_key"),
            "canonical_name": canonical_name,
            "cleanup_paths": cleanup_paths,
            "early": False
        }
        send_metadata_job(metadata_job, credentials)

        primary_cleanup_path = cleanup_paths[0] if cleanup_paths else (job.get("album_folder") or job.get("original_file"))
        converted_folder = cleanup_paths[-1] if cleanup_paths else None
        send_cleanup_job(primary_cleanup_path, final_file, converted_folder, credentials)
    except Exception as e:
        logger.error("❌ Error processing combiner job: %s", e)
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

def run():
    credentials = pika.PlainCredentials('admin', 'admin')
    connection = connect_to_rabbitmq_with_retries(RABBITMQ_HOST, credentials)
    channel = connection.channel()
    channel.queue_declare(queue=COMBINER_QUEUE, durable=True)
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=COMBINER_QUEUE, on_message_callback=callback)
    logger.info("🎙️ Combiner listening for jobs...")
    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        channel.stop_consuming()
    finally:
        connection.close()

if __name__ == "__main__":
    run()
