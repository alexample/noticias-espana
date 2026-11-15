FROM python:3.13-slim
WORKDIR /app
COPY . .
ENV NEWS_DB=/data/noticias.db
VOLUME /data
EXPOSE 8000
CMD ["python", "run.py"]
