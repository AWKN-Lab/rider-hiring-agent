FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY eval ./eval
COPY scripts ./scripts
COPY tests ./tests
EXPOSE 8077 8099
CMD ["uvicorn", "app.fastapi_app:app", "--host", "0.0.0.0", "--port", "8077"]
