# Опциональный учебный/синтетический worker 6.4.2.
# ОС/образ должны быть проверены и закреплены по digest перед production.
# Сборка устанавливает Poppler и img2pdf ТОЛЬКО внутри отдельного образа.
FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils img2pdf \
    && rm -rf /var/lib/apt/lists/*

COPY worker.py /usr/local/bin/aidoctor-cdr-worker
RUN chmod 0555 /usr/local/bin/aidoctor-cdr-worker

USER 65534:65534
ENV HOME=/tmp TMPDIR=/tmp
WORKDIR /tmp
CMD ["/usr/local/bin/aidoctor-cdr-worker"]
