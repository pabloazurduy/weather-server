# Flask Application

This is a simple Flask application.

## Setup

1. Clone the repository:
   ```
   git clone <repository-url>
   ```

2. Navigate to the project directory:
   ```
   cd flask-app
   ```

3. Install the required dependencies:
   ```
   pip install -r requirements.txt
   ```

## Usage

To run the application, execute the following command:
```
python app.py
```

The application will be accessible at `http://127.0.0.1:5000/`.

## Running the app with Docker

1. Build the Docker image:

   ```bash
   docker build -t weather-app .
   ```

2. Run the Docker container:

   ```bash
   docker run -p 5000:5000 weather-app
   ```

3. Access the app at `http://localhost:5000` in your browser.