import os
import shutil
import json
import time
import logging
import pika

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

RABBITMQ_HOST = "rabbitmq"
CLEANUP_QUEUE = "cleanup_jobs"

def connect_to_rabbitmq_with_retries(host, credentials, max_attempts=10, delay=3):
    for attempt in range(1, max_attempts + 1):
        try:
            logger.info("Attempting connection to RabbitMQ (%d/%d)...", attempt, max_attempts)
            parameters = pika.ConnectionParameters(
                host=host,
                credentials=credentials,
                heartbeat=600,
                blocked_connection_timeout=300
            )
            connection = pika.BlockingConnection(parameters)
            logger.info("Connected to RabbitMQ.")
            return connection
        except Exception as e:
            logger.warning("RabbitMQ connection failed on attempt %d: %s", attempt, e)
            time.sleep(delay)
    raise ConnectionError("Could not connect to RabbitMQ.")

def cleanup_path(path):
    if os.path.exists(path):
        try:
            if os.path.isfile(path):
                os.remove(path)
                logger.info("Removed file: %s", path)
            elif os.path.isdir(path):
                shutil.rmtree(path)
                logger.info("Removed folder: %s", path)
        except Exception as e:
            logger.error("Error removing path %s: %s", path, e)
    else:
        logger.info("Path %s not found; skipping cleanup.", path)

def callback(ch, method, properties, body):
    try:
        job = json.loads(body.decode())
        cleanup_paths = job.get("cleanup_paths", [])
        if not cleanup_paths:
            logger.info("No cleanup paths provided in job; nothing to do.")
            ch.basic_ack(delivery_tag=method.delivery_tag)
            return
        for path in cleanup_paths:
            cleanup_path(path)
        ch.basic_ack(delivery_tag=method.delivery_tag)
    except Exception as e:
        logger.error("Error processing cleanup job: %s", e)
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

def run_cleanup_service():
    credentials = pika.PlainCredentials('admin', 'admin')
    while True:
        try:
            connection = connect_to_rabbitmq_with_retries(RABBITMQ_HOST, credentials)
            channel = connection.channel()
            channel.queue_declare(queue=CLEANUP_QUEUE, durable=True)
            channel.basic_qos(prefetch_count=1)
            channel.basic_consume(queue=CLEANUP_QUEUE, on_message_callback=callback)
            logger.info("Cleanup service started. Listening for cleanup jobs...")
            channel.start_consuming()
        except Exception as e:
            logger.error("Cleanup service error: %s. Reconnecting in 5 seconds...", e)
            time.sleep(5)
        finally:
            try:
                connection.close()
            except Exception:
                pass

if __name__ == "__main__":
    run_cleanup_service()
