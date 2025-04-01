import os
import time
import pika
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

PIPELINE_DIR = "/pipeline"
RABBITMQ_HOST = "rabbitmq"
QUEUE_NAME = "splitter_jobs"

def send_to_queue(payload: str):
    try:
        credentials = pika.PlainCredentials('admin', 'admin')
        parameters = pika.ConnectionParameters(host=RABBITMQ_HOST, credentials=credentials)
        connection = pika.BlockingConnection(parameters)
        channel = connection.channel()
        channel.queue_declare(queue=QUEUE_NAME, durable=True)
        channel.basic_publish(
            exchange='',
            routing_key=QUEUE_NAME,
            body=payload,
            properties=pika.BasicProperties(
                delivery_mode=2,  # Make message persistent
            )
        )
        connection.close()
        print(f"📨 Sent job to queue: {payload}")
    except Exception as e:
        print(f"❌ Failed to send job to queue: {e}")

class PipelineHandler(FileSystemEventHandler):
    def on_created(self, event):
        item = event.src_path
        job_type = "album" if os.path.isdir(item) else "track"
        job = {
            "type": job_type,
            "path": item,
        }
        send_to_queue(str(job))

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
