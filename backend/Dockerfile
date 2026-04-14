FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m spacy download en_core_web_sm

COPY app.py .
COPY cache.py .
COPY ner.py .
COPY graph_retriever.py .
COPY vector_retriever.py .
COPY context_packer.py .
COPY gemini_caller.py .

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--timeout", "120", "app:app"]

