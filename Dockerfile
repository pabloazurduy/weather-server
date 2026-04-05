FROM python:3.11-alpine
WORKDIR /app
RUN pip install --no-cache-dir pillow requests
COPY flask-server/ /app/
EXPOSE 8080
CMD ["python", "app.py"]
