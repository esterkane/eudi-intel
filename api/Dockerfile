FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# curl: compose/health smoke checks. git: the git collector (repo mirrors).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl git \
    && rm -rf /var/lib/apt/lists/*

# CPU-only torch wheel first: keeps the image lean and makes GPU use
# structurally impossible (the GPU is reserved for the LLM via host Ollama).
RUN pip install --upgrade pip \
    && pip install torch --index-url https://download.pytorch.org/whl/cpu

# Install the package (and its deps) from source.
COPY . .
RUN pip install -e ".[dev,embed]"

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
