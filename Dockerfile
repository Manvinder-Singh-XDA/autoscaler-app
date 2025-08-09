# Use official Python 3.12 alpine image
FROM python:3.12-alpine

# Set working directory
WORKDIR /app

# Copy your application code to container
COPY . /app/

# Install dependencies
# If you have requirements.txt, copy and install it
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Expose the probe port (make sure it matches your config.yaml probe_port)
EXPOSE 8081

# Command to run your app
CMD ["python3", "app/auto_scaler.py", "--config", "config.yaml"]