FROM node:24.21.0-alpine AS frontend
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend ./
RUN npm run build

FROM python:3.12.15-slim
WORKDIR /app
COPY requirements.lock pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.lock
COPY src ./src
RUN pip install --no-cache-dir --no-deps .
COPY config ./config
COPY migrations ./migrations
COPY alembic.ini ./
COPY tools ./tools
COPY --from=frontend /web/dist ./frontend/dist
RUN mkdir -p /app/data && chown -R 10001:10001 /app
USER 10001:10001
CMD ["uvicorn", "grid_twin.api:app", "--host", "0.0.0.0", "--port", "8000"]
