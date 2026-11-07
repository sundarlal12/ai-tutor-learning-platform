FROM python:3.12-slim
WORKDIR /srv
COPY libs/lessonkit /libs/lessonkit
RUN pip install --no-cache-dir /libs/lessonkit fastapi "uvicorn[standard]" httpx anthropic websockets
COPY services/doubt/app /srv/app
RUN useradd -r app && chown -R app /srv
USER app
EXPOSE 8004
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8004"]
