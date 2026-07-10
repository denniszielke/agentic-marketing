FROM python:3.13-slim
WORKDIR /app
COPY ./src/public_product_mcp_server/requirements.txt /tmp/requirements.txt
RUN if [ -f /tmp/requirements.txt ]; then \
        pip install --no-cache-dir -r /tmp/requirements.txt; \
    else \
        echo "No requirements.txt found"; \
    fi
COPY ./src /app/src
ENV PUBLIC_PRODUCT_MCP_HOST=0.0.0.0
ENV PUBLIC_PRODUCT_MCP_PORT=8097
EXPOSE 8097
CMD ["python", "-m", "src.public_product_mcp_server.server"]
