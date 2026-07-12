FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    IRONTRAIL_MODE=cloud \
    HOME=/home/appuser

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends libcap2-bin \
    && setcap 'cap_net_bind_service=+ep' /usr/local/bin/python3.12 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 appuser

COPY --chown=appuser:appuser . .

RUN python -m pip install --no-cache-dir ".[cloud]"

USER appuser

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:80/_stcore/health', timeout=3)"

CMD ["python", "-m", "streamlit", "run", "streamlit_app.py", \
     "--server.address=0.0.0.0", "--server.port=80", \
     "--server.headless=true", "--server.runOnSave=false"]
