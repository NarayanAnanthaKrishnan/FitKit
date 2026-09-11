FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies in a cache-friendly layer, then the app package.
COPY pyproject.toml requirements.txt constraints.txt ./
COPY api ./api
COPY engine ./engine
RUN pip install --no-cache-dir -c constraints.txt .

COPY . .
RUN useradd --uid 10001 --create-home fitkit
USER 10001

EXPOSE 8000

# Compose runs migrations in a separate job before API and worker startup.
CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
