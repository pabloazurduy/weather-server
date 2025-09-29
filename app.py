#!/usr/bin/env python3
"""
Weather Server - A simple Flask server for e-ink weather display
Generates random weather data and serves the web frontend
"""
from flask import Flask, jsonify, send_from_directory
import random
import os

# Initialize Flask app with static files in 'public' directory
app = Flask(__name__, static_folder='public')

@app.route('/api/weather')
def weather_api():
    """
    API endpoint that returns random weather data:
    - temperature: random value between -10°C and 35°C
    - rain_probability: random value between 0 and 1
    """
    return jsonify({
        "temperature": random.randint(-10, 35),
        "rain_probability": random.random()
    })

@app.route('/')
def home():
    """Serve the main index.html file"""
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/<path:path>')
def static_files(path):
    """Serve static files from the public directory"""
    return send_from_directory(app.static_folder, path)

if __name__ == '__main__':
    # Use environment variable for port if provided, otherwise default to 5001
    port = int(os.environ.get('FLASK_PORT', 5001))
    print(f"Weather Server starting on http://0.0.0.0:{port}")
    app.run(host='0.0.0.0', port=port, debug=True)
