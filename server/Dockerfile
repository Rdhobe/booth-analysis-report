# UPBI serving image: FastAPI + static frontend. The store
# (servedb.sqlite) is NOT baked in - entrypoint.sh downloads it once
# from STORE_URL into /data (Render disk) and reuses it across boots.
# Build the store locally first: it is too big for git.
#   python Scripts/build_servedb.py --db server/servedb.sqlite
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl \
  && rm -rf /var/lib/apt/lists/*
COPY server/requirements.txt ./server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt
COPY server/app.py ./server/app.py
COPY server/insights.py ./server/insights.py
COPY server/insights_extra.py ./server/insights_extra.py
# Phase 1 model output (static JSON). Refresh with:
#   python Scripts/ml/build_insights.py --export-server
#   python Scripts/ml/build_extra.py --export-server
COPY server/insights_data ./server/insights_data
COPY server/frontend/docs.html ./server/frontend/docs.html
COPY server/assets ./server/assets
COPY server/entrypoint.sh ./server/entrypoint.sh
RUN chmod +x ./server/entrypoint.sh
ENV DB_PATH=/data/servedb.sqlite COMPLIANCE_MODE=off PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/meta')"
CMD ["./server/entrypoint.sh"]
