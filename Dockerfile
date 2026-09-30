# Recruit — per-student placement shortlist alerts
# Friends-only pilot. Deterministic matcher = source of truth; LLM summary is cosmetic.

# ---- build ----
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir -e . uvicorn[standard]
EXPOSE 8090
# Poll + serve in one supervisor-less process is not possible cleanly; see compose.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090"]