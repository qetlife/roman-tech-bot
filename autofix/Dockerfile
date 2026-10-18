# Sandbox for the auto-fix job (autofix/run.py): Claude Code, git, gh and the
# test dependencies. It gets no Docker socket and no access to the Pi; only
# the work folder is mounted.
FROM python:3.12-slim

ARG GH_VERSION=2.102.0
# The Pi user running the job, so files in the mounted work folder stay theirs
ARG UID=1000

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git jq \
    && rm -rf /var/lib/apt/lists/*

RUN arch="$(dpkg --print-architecture)" \
    && curl -fsSL "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_${arch}.tar.gz" \
       | tar -xz -C /tmp \
    && mv "/tmp/gh_${GH_VERSION}_linux_${arch}/bin/gh" /usr/local/bin/gh \
    && rm -rf /tmp/gh_*

COPY requirements.txt requirements-dev.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements-dev.txt

RUN useradd --create-home --uid "${UID}" fixer
USER fixer
WORKDIR /work

RUN curl -fsSL https://claude.ai/install.sh | bash -s stable
ENV PATH="/home/fixer/.local/bin:${PATH}"

RUN git config --global user.name "Claude (auto-fix)" \
    && git config --global user.email "noreply@anthropic.com" \
    && git config --global credential.helper '!gh auth git-credential'
