FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY sandbox ./sandbox
RUN pip install --no-cache-dir .
COPY web ./web
COPY examples ./examples
RUN useradd --uid 10001 --create-home appuser
USER appuser
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "sandbox.api:app", "--host", "0.0.0.0", "--port", "8000"]
