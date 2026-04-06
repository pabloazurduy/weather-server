FROM python:3.11-alpine
WORKDIR /app
RUN apk add --no-cache font-dejavu font-noto-emoji \
	&& pip install --no-cache-dir pillow requests
COPY flask-server/ /app/
EXPOSE 8080
CMD ["python", "app.py"]
