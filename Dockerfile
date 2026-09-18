FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY apps ./apps
COPY wardrobe ./wardrobe
COPY worker ./worker

RUN pip install --no-cache-dir .

EXPOSE 8080
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
