FROM python:3.12-slim

# No dependencies. The validator is standard library only, and the page is
# served by http.server, so there is nothing to pin and nothing to install.
WORKDIR /app

COPY app.py validate.py schema.json kernel.md MIR-1-spec.md /app/
COPY records /app/records
COPY artifacts /app/artifacts

ENV PORT=7860 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN useradd --system --uid 1000 --home /app mir
USER mir

EXPOSE 7860
CMD ["python", "app.py"]
