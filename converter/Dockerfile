FROM python:3.10-slim

ARG PUID=1000
ARG PGID=1000
ENV USERNAME=converter

# Install system dependencies including ffmpeg and build tools
RUN apt-get update && \
    apt-get install -y ffmpeg git sudo build-essential && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd -g ${PGID} ${USERNAME} && \
    useradd -u ${PUID} -g ${PGID} -m ${USERNAME}

WORKDIR /app

# Copy the requirements first for layer caching
COPY requirements.txt .
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Ensure /app is writable by our non-root user
RUN chown -R ${USERNAME}:${USERNAME} /app

USER ${USERNAME}

CMD ["python", "-u", "main.py"]
