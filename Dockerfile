FROM python:3.11-alpine

WORKDIR /app
ENV PYTHONUNBUFFERED=1
ENV CONFIG_PATH=/config/config.yml

COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py ./
COPY modules ./modules

# Never runs as root; needs only /config (rw) and, optionally, the music folder read-only.
RUN adduser -D -u 568 app
USER 568

CMD [ "python", "main.py" ]
