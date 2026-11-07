FROM python:3.12-slim
WORKDIR /srv
COPY libs/lessonkit /libs/lessonkit
RUN pip install --no-cache-dir /libs/lessonkit fastapi "uvicorn[standard]" httpx
COPY services/gateway/app /srv/app
COPY sample /sample
RUN mkdir -p /srv/data/bundles
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
