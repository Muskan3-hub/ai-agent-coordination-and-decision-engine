# Multi-AI-Agent Coding Assistant - production image (Milestone 4)
FROM python:3.12-slim

# Non-interactive pip + UTF-8 (Windows-authored files are UTF-16; ensure runtime works)
ENV PYTHONUNBUFFERED=1     PYTHONDONTWRITEBYTECODE=1     PIP_NO_CACHE_DIR=1     PYTHONIOENCODING=utf-8

WORKDIR /app

# Install dependencies first (cached layer)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY . .

# The app writes its SQLite DB, uploads and logs into these dirs
RUN mkdir -p user_data logs memory

# Streamlit (UI) + REST API ports
EXPOSE 8501 8787

# Healthcheck for orchestration platforms
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3     CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4)" || exit 1

# Default: the Streamlit UI (override CMD to run the API: python scripts/start_api.py)
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
