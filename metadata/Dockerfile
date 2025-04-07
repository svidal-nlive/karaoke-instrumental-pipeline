FROM python:3.10-slim

ARG PUID=1000
ARG PGID=1000
ENV USERNAME=metadata

# Install system dependencies (ffmpeg, git, sudo, build-essential) if needed
RUN apt-get update && \
    apt-get install -y ffmpeg git sudo build-essential && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd -g ${PGID} ${USERNAME} && \
    useradd -u ${PUID} -g ${PGID} -m ${USERNAME}

WORKDIR /app

# Copy the requirements first for caching
COPY requirements.txt .
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY . .

# Ensure /app is writable by our non-root user
RUN chown -R ${USERNAME}:${USERNAME} /app

USER ${USERNAME}
CMD ["python", "-u", "main.py"]
