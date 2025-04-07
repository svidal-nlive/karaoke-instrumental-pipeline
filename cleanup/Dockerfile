FROM python:3.10-slim

ARG PUID=1000
ARG PGID=1000
ENV USERNAME=cleanup

RUN apt-get update && \
    apt-get install -y git sudo build-essential && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd -g ${PGID} ${USERNAME} && \
    useradd -u ${PUID} -g ${PGID} -m ${USERNAME}

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chown -R ${USERNAME}:${USERNAME} /app
USER ${USERNAME}

CMD ["python", "-u", "main.py"]
