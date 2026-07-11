FROM python:3.14-slim

# Install system dependencies required by Stratum
# - curl/git for downloading things
# - openssh-client and sshpass for Ansible to connect to dynamically provisioned hosts
# - ansible/ansible-core for the hardening engine
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    openssh-client \
    sshpass \
    ansible \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast python dependency management
RUN curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="/usr/local/bin" sh
ENV PATH="/usr/local/bin:$PATH"

WORKDIR /app

# Copy dependency definition files first for layer caching.
# profiles/templates and plugins/catalog are hatch force-includes, so the
# build backend requires them present even for this dependency-only layer;
# they're small and change rarely, so caching is preserved.
COPY pyproject.toml README.md ./
COPY profiles/templates ./profiles/templates
COPY plugins/catalog ./plugins/catalog

# We install all provider plugins (aws, gcp, azure, linode, do, proxmox) by default 
# to make the Docker container batteries-included.
# 'uv pip install --system' avoids virtualenv inside Docker
RUN uv pip install --system -e .[all-providers]

# Copy the rest of the application code
COPY . .

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Expose the default Uvicorn port
EXPOSE 8000

# Start the Stratum server natively
CMD ["uvicorn", "stratum.main:app", "--host", "0.0.0.0", "--port", "8000"]
