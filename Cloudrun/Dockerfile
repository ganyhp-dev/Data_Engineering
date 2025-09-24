# Use the official Python image as a base
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /app

# Copy the dependency file to the container
COPY requirements.txt .

# Install the dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code to the container
COPY main.py .

# Expose the port that the service will run on
EXPOSE 8080

# Define the command to run the application
# This uses Gunicorn, a production-grade WSGI server
# The app is a Flask application named `app` in the `main.py` file
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--timeout", "120", "main:app"]
