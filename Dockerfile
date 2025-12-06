# Use an official Python runtime as a parent image
FROM python:3.13-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
# We install psycopg2 dependencies (libpq-dev, gcc) if we were building from source,
# but psycopg2-binary should be fine on standard linux. 
# However, for slim images, sometimes we need libpq-dev.
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir -r requirements.txt

# Copy the current directory contents into the container at /app
COPY . .

# Grant execution permissions to the entrypoint script
RUN chmod +x scripts/entrypoint.sh

# Make port 8000 available (documentation only, app listens on $PORT)
EXPOSE 8000

# Define environment variable
ENV PYTHONUNBUFFERED=1

# Run the entrypoint script
CMD ["./scripts/entrypoint.sh"]

