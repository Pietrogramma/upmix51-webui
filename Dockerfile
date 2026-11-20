# Upmix51 - web interface for stereo -> AC-3 (Dolby Digital) 5.1 upmixing
# MIT licence (see LICENSE). The resulting image also contains GPL-licensed
# FFmpeg binaries: see THIRD_PARTY_NOTICES.md before redistributing a built image.
FROM mwader/static-ffmpeg:7.1.1 AS ffmpeg

FROM python:3.12-slim
LABEL org.opencontainers.image.title="Upmix51" \
      org.opencontainers.image.description="Web UI to upmix stereo audio tracks to AC-3 5.1 with FFmpeg" \
      org.opencontainers.image.licenses="MIT"
COPY --from=ffmpeg /ffmpeg /ffprobe /usr/local/bin/
WORKDIR /app
COPY app/ /app/
ENV PORT=8765 \
    DATA=/config \
    PYTHONUNBUFFERED=1
EXPOSE 8765
CMD ["python", "/app/server.py"]
