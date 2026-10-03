FROM python:3.12-slim
WORKDIR /app
COPY requirements.lock pyproject.toml ./
COPY src ./src
RUN python -m pip install --no-cache-dir -r requirements.lock \
    && python -m pip install --no-cache-dir --no-deps .
COPY config ./config
COPY tools ./tools
USER 10001:10001
CMD ["tl-twin", "--help"]
