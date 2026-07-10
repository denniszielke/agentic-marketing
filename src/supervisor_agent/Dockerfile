FROM python:3.13-slim
WORKDIR /app
COPY ./src/supervisor_agent/requirements.txt /tmp/requirements.txt
RUN if [ -f /tmp/requirements.txt ]; then \
        pip install --no-cache-dir -r /tmp/requirements.txt; \
    else \
        echo "No requirements.txt found"; \
    fi
# The agent code ships inside the image.
COPY ./src /app/src
ENV PORT=8088
EXPOSE 8088
CMD ["python", "-m", "src.supervisor_agent.agent"]
