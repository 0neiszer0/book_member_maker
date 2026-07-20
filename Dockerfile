FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

# gunicorn 프로덕션 서버 (Flask dev 서버는 로컬 개발 전용)
# --timeout 120: 조 편성 최적화 등 오래 걸리는 요청 대비
CMD ["gunicorn", "--workers", "2", "--threads", "4", "--timeout", "120", "--bind", "0.0.0.0:5000", "app:app"]