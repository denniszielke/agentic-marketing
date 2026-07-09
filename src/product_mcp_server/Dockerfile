FROM python:3.13-slim
WORKDIR /app
COPY ./src/product_mcp_server/requirements.txt /tmp/requirements.txt
RUN if [ -f /tmp/requirements.txt ]; then \
        pip install --no-cache-dir -r /tmp/requirements.txt; \
    else \
        echo "No requirements.txt found"; \
    fi
COPY ./src /app/src
ENV PRODUCT_MCP_HOST=0.0.0.0
ENV PRODUCT_MCP_PORT=8093
EXPOSE 8093
CMD ["python", "-m", "src.product_mcp_server.server"]
