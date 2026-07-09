FROM python:3.13-slim
WORKDIR /app
COPY ./src/market_insights_server/requirements.txt /tmp/requirements.txt
RUN if [ -f /tmp/requirements.txt ]; then \
        pip install --no-cache-dir -r /tmp/requirements.txt; \
    else \
        echo "No requirements.txt found"; \
    fi
COPY ./src /app/src
# Static market sales datasets (annual + monthly) loaded in-process.
COPY ./data /app/data
ENV MARKET_MCP_HOST=0.0.0.0
ENV MARKET_MCP_PORT=8096
ENV MARKETING_DATA_DIR=/app/data
EXPOSE 8096
CMD ["python", "-m", "src.market_insights_server.server"]
