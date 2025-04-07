FROM python:3.10-slim

ARG PUID=1000
ARG PGID=1000
ENV USERNAME=spleeter
# Tell Spleeter to store models in /app/pretrained_models (which we control)
ENV SPLEETER_MODEL_PATH=/app/pretrained_models

# Install system dependencies including build tools and ffmpeg
RUN apt-get update && \
    apt-get install -y ffmpeg git sudo build-essential gfortran && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd -g ${PGID} ${USERNAME} && \
    useradd -u ${PUID} -g ${PGID} -m ${USERNAME}

WORKDIR /app

# Copy the requirements first to leverage layer caching
COPY requirements.txt .
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Change ownership of /app so the non-root user can modify its contents
RUN chown -R ${USERNAME}:${USERNAME} /app

USER ${USERNAME}
CMD ["python", "-u", "main.py"]
