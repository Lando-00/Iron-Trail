# Pinned by digest, not by tag: `azd deploy` triggers a remote ACR build that
# would otherwise resolve `3.12-slim` to whatever is newest at that moment.
# This is the multi-arch index digest for python:3.12-slim as of 2026-08-01
# (linux/amd64 -> sha256:cab2dbf575e971934a81e4622f5aba17aa7929719bd7e31033a3a83b97fd0464).
# To move it on: docker buildx imagetools inspect python:3.12-slim
FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de

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

# Dependencies first, from a fully hash-pinned lockfile. --require-hashes makes
# pip refuse anything whose artifact does not match, so a compromised or
# re-uploaded release on PyPI cannot enter the image. Copying only the lockfile
# here also means application edits do not invalidate this layer.
COPY --chown=appuser:appuser requirements-cloud.lock ./
RUN python -m pip install --no-cache-dir --require-hashes -r requirements-cloud.lock

COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:80/_stcore/health', timeout=3)"

CMD ["python", "-m", "streamlit", "run", "streamlit_app.py", \
     "--server.address=0.0.0.0", "--server.port=80", \
     "--server.headless=true", "--server.runOnSave=false"]
