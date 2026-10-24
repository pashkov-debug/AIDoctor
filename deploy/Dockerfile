FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/aidoctor/backend

WORKDIR /opt/aidoctor

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 aidoctor \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin aidoctor \
    && mkdir -p /opt/aidoctor/data/attachments \
    && chown -R 10001:10001 /opt/aidoctor/data

COPY backend/app ./backend/app
COPY backend/alembic ./backend/alembic
COPY alembic.ini ./

USER 10001:10001
EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
