# snorkelwaffle: small, CPU-only image. No PyTorch, no models, no GPU.
FROM python:3.12-alpine

# ffmpeg cuts audio; chromaprint's fpcalc fingerprints it (Alpine's ffmpeg has
# no chromaprint muxer, and the two give the same values). su-exec drops to
# PUID/PGID.
RUN apk add --no-cache ffmpeg chromaprint su-exec \
 && fpcalc -version

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY snorkelwaffle ./snorkelwaffle
COPY docker/entrypoint.sh /entrypoint.sh

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/config \
    LIBRARY_DIRS=/storage/media/podcasts \
    PORT=8484

EXPOSE 8484
VOLUME /config
HEALTHCHECK --interval=60s --timeout=5s --start-period=20s \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT','8484'), timeout=4)"
ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-m", "snorkelwaffle"]
