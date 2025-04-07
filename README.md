---

# Karaoke Instrumental Pipeline

A multi-service Docker-based pipeline for **automated** splitting of song audio into instrumental stems, converting them to MP3, and optionally tagging them with metadata before placing them into a music library. This pipeline leverages several containers and a message broker to orchestrate the entire workflow—from watching a downloads folder for new MP3s to automatically delivering instrumental versions to your music folder.

---

## Overview

The **Karaoke Instrumental Pipeline** automates the process of:

1. Watching for new music files (MP3s).
2. Moving them to a dedicated folder.
3. Extracting and storing metadata (title, artist, etc.).
4. Splitting the audio into multiple stems (e.g., bass, drums, instruments, vocals) using [Spleeter](https://github.com/deezer/spleeter).
5. Converting the separated stems to MP3.
6. Combining all stems except for vocals into an **instrumental** MP3.
7. Writing back the original metadata to the final instrumental MP3.
8. Cleaning up intermediate files when finished.

In short, drop an MP3 into a folder, and get an **instrumental** version out!

---

## High-Level Workflow

1. **Watcher** monitors a `downloads` directory for new MP3s.
   - Once a file is stable, the watcher moves it to `originals/`.
   - A Redis key is created for its metadata, and a **splitter** job is published to RabbitMQ.

2. **Queue** container monitors a `pipeline/` directory for newly dropped files or `.job` descriptions.
   - It automatically sends tasks to the **splitter_jobs** queue when a file or job is created in `pipeline/`.

3. **Splitter** container receives a job from **splitter_jobs** and uses [Spleeter](https://github.com/deezer/spleeter) to split the track into stems (5 stems by default).
   - When complete, it publishes a **converter_jobs** message referencing the newly generated stems.

4. **Converter** receives the job from **converter_jobs** and converts each `.wav` stem (except vocals) to `.mp3` using `ffmpeg`.
   - It then sends a **combiner_jobs** message referencing the newly converted stems.

5. **Combiner** receives a job from **combiner_jobs** and merges all the stem `.mp3` files (except vocals) into a single **instrumental** track.
   - The final instrumental file is stored in a `music/` directory.
   - It then sends a **metadata_jobs** message so the final MP3 can be properly tagged.

6. **Metadata** receives a job from **metadata_jobs**, retrieves any stored metadata from Redis (based on the file’s hash), applies it to the final MP3, and requests a cleanup.

7. **Cleanup** receives a **cleanup_jobs** message with paths to remove (intermediate stems, pipeline directory items, etc.) and safely removes them.

8. **Navidrome** can be used to serve your final music library, and **Deemix** can be used to download music.

---

## Services Overview

Below is a quick summary of the containers, each of which is defined in the **docker-compose.yml**:

1. **RabbitMQ**  
   The message broker for orchestrating jobs across containers. Uses the `rabbitmq:3-management` image.

2. **Redis**  
   Key-value store used to save MP3 metadata. Uses the `redis:7-alpine` image.

3. **Watcher**  
   Watches the `downloads/` folder for incoming MP3s. Moves them to `originals/`, extracts metadata, and sends a job to the **splitter** queue.

4. **Queue**  
   Watches `/pipeline` for new files or `.job` descriptors, then pushes jobs to the **splitter_jobs** RabbitMQ queue. (This is an alternative entry point to feed the pipeline with file references.)

5. **Splitter**  
   Listens on **splitter_jobs**. Uses Spleeter to split the audio into 5 stems. Forwards the results to the **converter** queue.

6. **Converter**  
   Listens on **converter_jobs**. Converts `.wav` stems to `.mp3` via `ffmpeg`. Sends the list of converted stems to **combiner_jobs**.

7. **Combiner**  
   Listens on **combiner_jobs**. Combines all `.mp3` stems except for the vocals into one **instrumental** track. Sends a **metadata_jobs** message.

8. **Metadata**  
   Listens on **metadata_jobs**. Loads stored metadata from Redis, applies it to the final MP3, and triggers a **cleanup_jobs** message.

9. **Cleanup**  
   Listens on **cleanup_jobs**. Removes specified intermediate files and folders.

10. **Navidrome**  
    Optionally run a Navidrome music server that points to the `music/` folder containing your final instrumentals.

11. **Deemix**  
    Optionally run a Deemix container for retrieving MP3 files from various sources into your `downloads/` folder.

---

## Directory Structure

A simplified view of the repository:

```
.
├── cleanup/
│   ├── Dockerfile
│   ├── main.py
│   └── requirements.txt
├── watcher/
│   ├── Dockerfile
│   ├── main.py
│   └── requirements.txt
├── queue/
│   ├── Dockerfile
│   ├── main.py
│   └── requirements.txt
├── splitter/
│   ├── Dockerfile
│   ├── main.py
│   └── requirements.txt
├── converter/
│   ├── Dockerfile
│   ├── main.py
│   └── requirements.txt
├── combiner/
│   ├── Dockerfile
│   ├── main.py
│   └── requirements.txt
├── metadata/
│   ├── Dockerfile
│   ├── main.py
│   └── requirements.txt
├── shared/
│   ├── downloads/        # Where the Watcher sees new MP3s
│   ├── originals/        # Where new MP3s are moved to
│   ├── pipeline/         # Where the Queue container sees new .job or files
│   ├── splitter_output/  # Spleeter results
│   ├── converted_output/ # MP3 stems
│   ├── music/            # Final instruments
│   └── spleeter_models/  # Pre-trained Spleeter models
├── navidrome/
│   └── data/             # Navidrome data
├── deemix/
│   └── config/           # Deemix config
├── .env
├── docker-compose.yml
└── README.md (this file)
```

---

## Environment Variables

A few important environment variables are defined in **.env**:

| Variable | Description                                     | Default |
|----------|-------------------------------------------------|---------|
| `PUID`   | Host user ID used when running the containers   | `1000`  |
| `PGID`   | Host group ID used when running the containers  | `1000`  |

Additional environment variables such as `REDIS_HOST`, `ARL` (for Deemix), and more can be adjusted if necessary.

---

## Docker Deployment

1. **Clone** this repository and enter the project directory:
   ```bash
   git clone https://github.com/svidal-nlive/karaoke-instrumental-pipeline.git
   cd karaoke-instrumental-pipeline
   ```

2. **Set up your environment** by editing `.env` if your UID/GID differ from the default.

3. **Create the necessary folders**:
   ```bash
   mkdir -p shared/downloads shared/originals shared/pipeline \
            shared/splitter_output shared/converted_output shared/music \
            shared/spleeter_models navidrome/data deemix/config
   ```

4. **(Optional) Place pretrained Spleeter models** in `shared/spleeter_models` if you want to avoid re-downloading them.

5. **Build and start** the services:
   ```bash
   docker-compose up --build -d
   ```
   The `--build` flag ensures each service is rebuilt if needed.

6. Check logs for any potential issues:
   ```bash
   docker-compose logs -f
   ```

7. **Congratulations!** Your pipeline should now be running.  

---

## Detailed Service Descriptions

### Watcher <a id="detailed-watcher"></a>

- **Location**: `./watcher`
- **Listens** for filesystem events in `/downloads` (mounted from `./shared/downloads`).
- **Logic**:
  1. When a new `.mp3` appears, waits for the file to stabilize (no more writes).
  2. Reads basic ID3 metadata with `mutagen`.
  3. Moves the file to `/originals`.
  4. Computes a hash for the file, stores the metadata in Redis, and sends a job (`{"type": "track", "path": "...", "metadata_key": "..."}`) to the **splitter_jobs** queue in RabbitMQ.

### Queue <a id="detailed-queue"></a>

- **Location**: `./queue`
- **Watches** `/pipeline` for newly created files or `.job` descriptors.
- **Logic**:
  1. If a file is placed into `/pipeline`, it’s typically `{"type": "track" or "album", "path": "..."}`.
  2. The queue service reads or builds that job info and sends it to **splitter_jobs** in RabbitMQ.
  3. Avoids duplicates by checking a Redis set key.

### Splitter <a id="detailed-splitter"></a>

- **Location**: `./splitter`
- **Listens** on `splitter_jobs`.
- **Uses** [Spleeter](https://github.com/deezer/spleeter) (`spleeter:5stems`) to separate the track into 5 stems (vocals, drums, bass, piano, other).
- **Logic**:
  1. Receives a job with `{"type": "track", "path": "...", "metadata_key": "..."}`.
  2. Runs Spleeter, saving `.wav` stems into `/splitter_output/<basename-of-file>`.
  3. Filters out `vocals.wav`, gathers the rest, and sends them to `converter_jobs`.

### Converter <a id="detailed-converter"></a>

- **Location**: `./converter`
- **Listens** on `converter_jobs`.
- **Uses** `ffmpeg` to convert each `.wav` stem (except vocals) into `.mp3`.
- **Logic**:
  1. Receives a job specifying stems.
  2. For each `.wav`, calls `ffmpeg -i <stem>.wav <stem>.mp3`.
  3. Collects the list of newly converted `.mp3` stems and forwards them to `combiner_jobs`.

### Combiner <a id="detailed-combiner"></a>

- **Location**: `./combiner`
- **Listens** on `combiner_jobs`.
- **Combines** the non-vocal stems into a single **instrumental** track with `ffmpeg`’s `amix`.
- **Logic**:
  1. Receives list of `.mp3` stems to combine.
  2. Issues an `ffmpeg` command like: `ffmpeg -i stem1.mp3 -i stem2.mp3 ... -filter_complex amix=inputs=N:duration=longest output.mp3`.
  3. Places the final **instrumental** file in `/music`.
  4. Sends a `metadata_jobs` message to label the final track with any stored metadata.

### Metadata <a id="detailed-metadata"></a>

- **Location**: `./metadata`
- **Listens** on `metadata_jobs`.
- **Retrieves** metadata from Redis and applies it to the final MP3 using `mutagen`.
- **Logic**:
  1. Receives a job referencing the final file path and a `metadata_key`.
  2. Reads stored fields from `redis`, applies them to the ID3 tags.
  3. Sends `cleanup_jobs` message to remove intermediate files/folders once metadata is set.

### Cleanup <a id="detailed-cleanup"></a>

- **Location**: `./cleanup`
- **Listens** on `cleanup_jobs`.
- **Removes** any temporary or unnecessary files/folders mentioned in the job (`splitter_output`, etc.).
- **Logic**:
  1. Receives job with an array of `cleanup_paths`.
  2. Deletes each path if it exists, logging successes/failures.

---

## Additional Notes

- **Navidrome** is included to serve any finished MP3 files in the `music/` directory via a web UI and REST API.
- **Deemix** can be used to pull down tracks directly into the `downloads/` folder, automating your pipeline further.
- **File Paths**:
  - `./shared/downloads -> /downloads`
  - `./shared/originals -> /originals`
  - `./shared/pipeline -> /pipeline`
  - `./shared/splitter_output -> /splitter_output`
  - `./shared/converted_output -> /converted_output`
  - `./shared/music -> /music`
  - `./shared/spleeter_models -> /app/pretrained_models`

If you place a `.mp3` in `./shared/downloads`, the **watcher** container should move it to `originals`, ingest it, and produce an instrumental track in `./shared/music`.

---

## License

To be updated!

---
