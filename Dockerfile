FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy server
COPY garmin_mcp_server.py .
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# Garth tokens persisted here (mount as volume)
RUN mkdir -p /data/garth
ENV GARTH_TOKEN_DIR=/data/garth

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/mcp')" || exit 1

ENTRYPOINT ["./entrypoint.sh"]
