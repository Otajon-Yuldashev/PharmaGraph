FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY etl_sider.py .
COPY etl_faers.py .
COPY etl_drugbank.py .
COPY etl_pubmed.py .
COPY orchestrate.py .

CMD ["python", "-u", "orchestrate.py"]