# Depot EV — container image for IBM Cloud Code Engine
# Build:  docker build -t depot-ev .
# Run:    docker run -p 8080:8080 --env-file .env -e DB_PATH=/data/data.db -v depot-data:/data depot-ev
# Test:   curl http://localhost:8080/api/sessions

# Use a slim Python image — server.py has zero third-party dependencies
FROM python:3.12-slim

# Non-root user for Code Engine (runs as arbitrary UID by default; this is advisory)
RUN useradd -m -u 1001 depot

WORKDIR /app

# Copy only the files the server needs to serve and run
COPY server.py           ./
COPY common.css          ./
COPY common.js           ./
COPY depot-engine.js     ./
COPY data-tools.js       ./
COPY reference-data.js   ./
COPY index.html          ./
COPY dispatch.html       ./
COPY customers.html      ./
COPY history.html        ./
COPY architecture.html   ./
COPY docs/Depot-EV-Solution.pdf ./docs/

# /data is the persistent volume mount point; the DB lives there in production.
# The directory is created here so local runs without a volume still work.
RUN mkdir -p /data && chown depot:depot /data /app

USER depot

# Code Engine sets PORT; default to 8080 to match Cloud conventions.
ENV PORT=8080
EXPOSE 8080

# DB_PATH is set via Code Engine environment variable / secret to /data/data.db
# All other secrets (DEPOT_TOKEN, WATSONX_*, NREL_*, etc.) are injected at runtime.
CMD ["sh", "-c", "python server.py ${PORT}"]
