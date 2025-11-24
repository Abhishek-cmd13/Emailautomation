#!/bin/bash

# Email Automation Agent Startup Script

echo "Starting Email Automation Agent..."

# Check if .env file exists
if [ ! -f .env ]; then
    echo "Warning: .env file not found. Please create one based on env.example"
    echo "You can copy it: cp env.example .env"
    echo "Then edit .env and add your Instantly.ai API key"
    echo ""
fi

# Install dependencies if needed
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

echo "Activating virtual environment..."
source venv/bin/activate

echo "Installing dependencies..."
pip install -r requirements.txt

echo "Starting FastAPI server..."
python main.py

