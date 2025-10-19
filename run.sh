#!/bin/bash
# Build and run the hello-whale container

set -e

echo "🐋 Building hello-whale Docker image..."
docker build -t hello-whale .

echo "🐋 Starting container..."
docker run -d -p 8080:8080 --name hello-whale-container hello-whale 2>/dev/null || docker run -p 8080:8080 hello-whale

echo "🐋 Hello Whale is running!"
echo "🐋 Visit: http://localhost:8080"
