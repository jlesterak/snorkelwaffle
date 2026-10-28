# snorkelwaffle: CPU-only image. No PyTorch, no GPU, no models baked in.
# Debian, not Alpine: faster-whisper's engine (ctranslate2) only ships glibc wheels.
FROM python:3.12-slim

# ffmpeg cuts audio and fingerprints it (Debian's build has the chromaprint
# muxer). gosu drops to PUID/PGID.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg gosu \
 && rm -rf /var/lib/apt/lists/* \
 && ffmpeg -hide_banner -muxers | grep -q chromaprint

WORKDIR /app
COPY requirements.txt .
# faster-whisper is only used when "Transcribe clips" is on; its model downloads
# into /config/models on first use.
RUN pip install --no-cache-dir -r requirements.txt faster-whisper==1.2.1
COPY snorkelwaffle ./snorkelwaffle
COPY docker/entrypoint.sh /entrypoint.sh

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/config \
    LIBRARY_DIRS=/storage/media/podcasts \
    PORT=8484 \
    HF_HUB_DISABLE_TELEMETRY=1

EXPOSE 8484
VOLUME /config
HEALTHCHECK --interval=60s --timeout=5s --start-period=20s \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT','8484'), timeout=4)"
ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-m", "snorkelwaffle"]
