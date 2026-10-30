FROM python:3.12-slim
WORKDIR /app
COPY --chown=65534:65534 server.py ./server.py
USER 65534:65534
ENV PYTHONDONTWRITEBYTECODE=1
EXPOSE 10000
CMD ["python", "-I", "-u", "server.py"]
