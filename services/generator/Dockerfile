FROM python:3.12-slim
WORKDIR /srv
COPY libs/lessonkit /libs/lessonkit
RUN pip install --no-cache-dir /libs/lessonkit fastapi "uvicorn[standard]" httpx anthropic
COPY services/generator/app /srv/app
COPY knowledge /knowledge
COPY sample /sample
RUN useradd -r app && chown -R app /srv
USER app
EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
