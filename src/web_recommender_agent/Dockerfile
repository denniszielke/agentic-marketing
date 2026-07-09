FROM python:3.13-slim
WORKDIR /app
COPY ./src/web_recommender_agent/requirements.txt /tmp/requirements.txt
RUN if [ -f /tmp/requirements.txt ]; then \
        pip install --no-cache-dir -r /tmp/requirements.txt; \
    else \
        echo "No requirements.txt found"; \
    fi
# Agent code, its /skills folder and the web UI ship in the image.
COPY ./src /app/src
ENV HOST=0.0.0.0
ENV PORT=8092
EXPOSE 8092
CMD ["python", "-m", "src.web_recommender_agent.server"]
