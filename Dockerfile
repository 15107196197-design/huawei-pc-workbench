FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends fonts-noto-cjk && rm -rf /var/lib/apt/lists/*
COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
COPY huawei_agent ./huawei_agent
COPY static ./static
COPY scripts/configure_access.py ./scripts/configure_access.py
RUN useradd --uid 10001 --create-home studio && mkdir -p /app/data && chown -R studio:studio /app
USER studio
EXPOSE 8787
CMD ["python", "-m", "uvicorn", "huawei_agent.app:app", "--host", "0.0.0.0", "--port", "8787"]
