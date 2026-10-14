FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY backend/requirements.lock backend/requirements.lock
RUN pip install --no-cache-dir -r backend/requirements.lock
COPY . .
RUN pip install --no-deps -e ./backend && mkdir -p /app/data && useradd --create-home leados && chown -R leados:leados /app
USER leados
EXPOSE 8000
CMD ["sh", "-c", "uvicorn leados.api:app --host 0.0.0.0 --port ${PORT:-8000}"]

