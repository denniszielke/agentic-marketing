FROM python:3.13-slim
WORKDIR /app
COPY ./src/persona_mcp_server/requirements.txt /tmp/requirements.txt
RUN if [ -f /tmp/requirements.txt ]; then \
        pip install --no-cache-dir -r /tmp/requirements.txt; \
    else \
        echo "No requirements.txt found"; \
    fi
COPY ./src /app/src
ENV PERSONA_MCP_HOST=0.0.0.0
ENV PERSONA_MCP_PORT=8094
EXPOSE 8094
CMD ["python", "-m", "src.persona_mcp_server.server"]
