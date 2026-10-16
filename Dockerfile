FROM python:3.13-slim

WORKDIR /app

COPY pyproject.toml .
COPY README.md .
COPY src ./src

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir uv && \
    uv sync

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "escala_analyzer.main:app", "--host", "0.0.0.0", "--port", "8000"]
