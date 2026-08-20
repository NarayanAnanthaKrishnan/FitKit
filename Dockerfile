FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies in a cache-friendly layer, then the app package.
COPY pyproject.toml requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -c constraints.txt .

COPY . .

EXPOSE 8000

# Apply Alembic migrations, then serve. DATABASE_URL and the bot credentials
# come from the runtime environment only.
CMD ["sh", "-c", "python -m alembic upgrade head && python -m uvicorn api.main:app --host 0.0.0.0 --port 8000"]
