FROM python:3.12-slim
WORKDIR /srv
COPY libs/lessonkit /libs/lessonkit
RUN pip install --no-cache-dir /libs/lessonkit fastapi "uvicorn[standard]" httpx
COPY services/voice/app /srv/app
RUN useradd -r app && mkdir -p /srv/media && chown -R app /srv
USER app
EXPOSE 8003
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003"]
