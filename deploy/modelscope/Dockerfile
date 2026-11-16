FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    HOME=/home/studio \
    STUDIO_HOSTED=1 \
    STUDIO_MANAGED_CONFIG=1 \
    STUDIO_DATA_DIR=/mnt/workspace/huawei-pc-content-studio

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates fonts-noto-cjk tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 studio \
    && useradd --uid 10001 --gid 10001 --create-home studio \
    && mkdir -p /mnt/workspace/huawei-pc-content-studio \
    && chown -R studio:studio /app /mnt/workspace/huawei-pc-content-studio

COPY requirements.lock ./requirements.lock
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
COPY --chown=studio:studio huawei_agent ./huawei_agent
COPY --chown=studio:studio static ./static
COPY --chown=studio:studio deploy/modelscope ./deploy/modelscope

# Bootstrap initializes only the dedicated mounted directory, then drops to UID/GID
# 10001 before importing or running the application. No root web process is started.
USER root
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
    CMD ["python", "/app/deploy/modelscope/healthcheck.py"]

ENTRYPOINT ["python", "/app/deploy/modelscope/entrypoint.py"]
