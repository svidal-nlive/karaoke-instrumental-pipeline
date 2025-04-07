import os
import time
import json
import pika
import subprocess
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

RABBITMQ_HOST = "rabbitmq"
CONVERTER_QUEUE = "converter_jobs"
COMBINER_QUEUE = "combiner_jobs"

def connect_to_rabbitmq_with_retries(host, credentials, max_attempts=10, delay=3):
    for attempt in range(1, max_attempts + 1):
        try:
            logger.info("Attempting RabbitMQ connection (%d/10)...", attempt)
            parameters = pika.ConnectionParameters(
                host=host,
                credentials=credentials,
                heartbeat=600,
                blocked_connection_timeout=300
            )
            return pika.BlockingConnection(parameters)
        except pika.exceptions.AMQPConnectionError:
            logger.warning("RabbitMQ not ready yet. Retrying in %ds...", delay)
            time.sleep(delay)
    raise ConnectionError("Could not connect to RabbitMQ after multiple attempts.")

def convert_wav_to_mp3(source_file, output_file):
    try:
        cmd = ["ffmpeg", "-y", "-i", source_file, output_file]
        logger.info("Converting: %s -> %s", source_file, output_file)
        result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        logger.info("Conversion complete: %s", output_file)
        return True
    except subprocess.CalledProcessError as e:
        logger.error("Error converting %s: %s", source_file, e.stderr.decode())
        return False

def send_combiner_job(job_payload):
    credentials = pika.PlainCredentials('admin', 'admin')
    parameters = pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        credentials=credentials,
        heartbeat=600,
        blocked_connection_timeout=300
    )
    connection = pika.BlockingConnection(parameters)
    channel = connection.channel()
    channel.queue_declare(queue=COMBINER_QUEUE, durable=True)
    body = json.dumps(job_payload)
    channel.basic_publish(
        exchange='',
        routing_key=COMBINER_QUEUE,
        body=body,
        properties=pika.BasicProperties(delivery_mode=2)
    )
    connection.close()
    logger.info("Sent job to combiner queue for: %s", job_payload.get('original_filename'))

def callback(ch, method, properties, body):
    acked = False
    try:
        job = json.loads(body.decode())
        logger.info("Received converter job: %s", job)

        source_folder = job.get("source_folder")
        stems = job.get("stems", [])
        original_filename = job.get("original_filename", "output.mp3")
        original_file = job.get("original_file")
        metadata_key = job.get("metadata_key")

        converted_stems = []
        for stem in stems:
            source_file = os.path.join(source_folder, stem)
            output_folder = os.path.join(source_folder, "converted")
            os.makedirs(output_folder, exist_ok=True)
            output_file = os.path.join(output_folder, os.path.splitext(stem)[0] + ".mp3")
            if convert_wav_to_mp3(source_file, output_file):
                converted_stems.append(os.path.basename(output_file))

        ch.basic_ack(delivery_tag=method.delivery_tag)
        acked = True

        if converted_stems:
            combiner_job = {
                "source_folder": os.path.join(source_folder, "converted"),
                "stems": converted_stems,
                "original_filename": original_filename,
                "original_file": original_file,
                "metadata_key": metadata_key
            }
            send_combiner_job(combiner_job)
        else:
            logger.warning("No stems were successfully converted; not sending combiner job.")
    except Exception as e:
        logger.error("Error processing converter job: %s", e)
        if not acked:
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

if __name__ == "__main__":
    logger.info("Converter listening for jobs...")
    credentials = pika.PlainCredentials('admin', 'admin')
    connection = connect_to_rabbitmq_with_retries(RABBITMQ_HOST, credentials)
    channel = connection.channel()
    channel.queue_declare(queue=CONVERTER_QUEUE, durable=True)
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=CONVERTER_QUEUE, on_message_callback=callback)
    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        channel.stop_consuming()
    finally:
        connection.close()
