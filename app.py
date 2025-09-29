from flask import Flask, jsonify, send_from_directory
import random
import os

app = Flask(__name__, static_folder='public')

@app.route('/api/weather')
def weather_api():
    return jsonify({
        "temperature": random.randint(-10, 35),
        "rain_probability": random.random()
    })

@app.route('/')
def home():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/<path:path>')
def static_files(path):
    return send_from_directory(app.static_folder, path)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
