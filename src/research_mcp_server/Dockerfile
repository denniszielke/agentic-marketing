FROM python:3.13-slim
WORKDIR /app
COPY ./src/research_mcp_server/requirements.txt /tmp/requirements.txt
RUN if [ -f /tmp/requirements.txt ]; then \
        pip install --no-cache-dir -r /tmp/requirements.txt; \
    else \
        echo "No requirements.txt found"; \
    fi
COPY ./src /app/src
ENV RESEARCH_MCP_HOST=0.0.0.0
ENV RESEARCH_MCP_PORT=8095
EXPOSE 8095
CMD ["python", "-m", "src.research_mcp_server.server"]
