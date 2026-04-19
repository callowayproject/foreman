FROM python:3.12-slim
WORKDIR /app

# Install dependencies first (layer cache)
COPY pyproject.toml .
RUN pip install --no-cache-dir ".[runtime]"

# Copy application code
COPY agent.py .
COPY prompts/ prompts/

EXPOSE 8000

CMD ["uvicorn", "agent:app", "--host", "0.0.0.0", "--port", "8000"]
