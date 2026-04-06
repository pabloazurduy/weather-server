FROM python:3.11-alpine
WORKDIR /app
RUN apk add --no-cache curl font-liberation font-noto-emoji \
	&& mkdir -p /usr/share/fonts/weathericons \
	&& curl -fsSL https://raw.githubusercontent.com/Weatherfonts/weather-font/master/font/weathericons-regular-webfont.ttf \
		-o /usr/share/fonts/weathericons/weathericons-regular-webfont.ttf \
	&& pip install --no-cache-dir pillow requests
COPY flask-server/ /app/
EXPOSE 8080
CMD ["python", "app.py"]
