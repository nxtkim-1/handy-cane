FROM python:3.11-slim
WORKDIR /app
COPY backend/requirements.txt backend/requirements-reports.txt /app/backend/
RUN pip install --no-cache-dir -r backend/requirements.txt -r backend/requirements-reports.txt "psycopg[binary]>=3.1"
COPY backend /app/backend
COPY cane/common /app/cane/common
RUN touch /app/cane/__init__.py
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
