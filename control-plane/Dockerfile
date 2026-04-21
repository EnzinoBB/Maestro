FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir fastapi 'uvicorn[standard]' pydantic pyyaml jinja2 \
    sqlalchemy aiosqlite websockets httpx click mcp

COPY app/ ./app/
COPY web/ ./web/

EXPOSE 8000
ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
