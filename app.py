from flask import Flask, jsonify
import random

app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({
        "temperature": random.randint(-10, 35),
        "rain_probability": random.random()
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3030, debug=True)