# Sandbox image for running a repository's tests. Built twice (see `patchpilot sandbox build`):
#   patchpilot-sandbox:pydantic-v1  -> source environment (benchmark task validation)
#   patchpilot-sandbox:pydantic-v2  -> target environment (migration validation)
# Dependencies are installed at build time, because containers run with --network none.
FROM python:3.12-slim

ARG REQUIREMENTS
RUN pip install --no-cache-dir ${REQUIREMENTS} \
 && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin sandbox

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/work
USER 10001
WORKDIR /work
