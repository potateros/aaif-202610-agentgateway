FROM python:3.12-slim
# App code is not baked in: compose mounts the repo at /work.
RUN pip install --no-cache-dir "fastapi>=0.110" "uvicorn>=0.29" "httpx>=0.27" "pytest>=8"
WORKDIR /work
