FROM python:3.14.4-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["fastapi", "run", "main.py", "--port", "8000"]