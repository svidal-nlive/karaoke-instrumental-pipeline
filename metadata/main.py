#!/usr/bin/env python
import os
import json
import pika
import logging
import redis
import time
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3NoHeaderError

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

RABBITMQ_HOST = "rabbitmq"
QUEUE_NAME = "metadata_jobs"

redis_client = redis.StrictRedis(host=os.getenv("REDIS_HOST", "redis"), port=6379, decode_responses=True)

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

def get_stored_metadata(metadata_key):
    key = f"metadata:{metadata_key}"
    return redis_client.hgetall(key)

def apply_metadata_from_store(final_file, metadata_key):
    try:
        metadata = get_stored_metadata(metadata_key)
        if not metadata:
            logger.warning("No stored metadata found for key %s", metadata_key)
            return
        try:
            final_meta = EasyID3(final_file)
        except ID3NoHeaderError:
            final_meta = EasyID3()
        for field, value in metadata.items():
            final_meta[field] = value
        final_meta.save(final_file)
        logger.info("Applied stored metadata to %s", final_file)
    except Exception as e:
        logger.error("Error applying metadata to %s: %s", final_file, e)

def trigger_cleanup(original_file, final_file, cleanup_paths):
    cleanup_payload = {
        "cleanup_paths": cleanup_paths,
        "final_file": final_file,
        "original_file": original_file
    }
    try:
        credentials = pika.PlainCredentials('admin', 'admin')
        parameters = pika.ConnectionParameters(
            host=RABBITMQ_HOST,
            credentials=credentials,
            heartbeat=600,
            blocked_connection_timeout=300
        )
        connection = pika.BlockingConnection(parameters)
        channel = connection.channel()
        cleanup_queue = "cleanup_jobs"
        channel.queue_declare(queue=cleanup_queue, durable=True)
        channel.basic_publish(
            exchange='',
            routing_key=cleanup_queue,
            body=json.dumps(cleanup_payload),
            properties=pika.BasicProperties(delivery_mode=2)
        )
        connection.close()
        logger.info("Triggered cleanup for original: %s, final: %s", original_file, final_file)
    except Exception as e:
        logger.error("Failed to trigger cleanup: %s", e)

def callback(ch, method, properties, body):
    try:
        job = json.loads(body.decode())
        logger.info("Received metadata job: %s", job)
        final_file = job.get("final_file")
        original_file = job.get("original_file")
        metadata_key = job.get("metadata_key")
        cleanup_paths = job.get("cleanup_paths", [])
        # Since metadata is now extracted early, we simply apply it.
        apply_metadata_from_store(final_file, metadata_key)
        # Trigger cleanup after metadata is applied.
        trigger_cleanup(original_file, final_file, cleanup_paths)
        ch.basic_ack(delivery_tag=method.delivery_tag)
    except Exception as e:
        logger.error("Error processing metadata job: %s", e)
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

if __name__ == "__main__":
    logger.info("Metadata Service listening for jobs...")
    credentials = pika.PlainCredentials('admin', 'admin')
    connection = connect_to_rabbitmq_with_retries(RABBITMQ_HOST, credentials)
    channel = connection.channel()
    channel.queue_declare(queue=QUEUE_NAME, durable=True)
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=QUEUE_NAME, on_message_callback=callback)
    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        channel.stop_consuming()
    finally:
        connection.close()
