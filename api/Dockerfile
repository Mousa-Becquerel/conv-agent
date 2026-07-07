FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# pydantic-ai 0.0.13's metadata asks for griffe>=1.3.2, but its code
# imports `from _griffe.*` which only exists in griffe < 0.49.
# --no-deps avoids triggering pip's resolver on the conflict.
RUN pip install --no-cache-dir --force-reinstall --no-deps griffe==0.48.0

COPY . .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
