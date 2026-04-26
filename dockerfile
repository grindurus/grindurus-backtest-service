# dockerfile
FROM python:3.13.7-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY . .

RUN pip install -e .

EXPOSE 8001

CMD ["python", "main.py"]
