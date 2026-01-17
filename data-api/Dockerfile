# Use an official Python runtime as a parent image
FROM python:3.9-slim-bullseye

# Create a non-root user
RUN useradd -m appuser

# Set the working directory in the container
WORKDIR /app

# Prevent Python from writing pyc files to disc
ENV PYTHONDONTWRITEBYTECODE=1
# Prevent Python from buffering stdout and stderr
ENV PYTHONUNBUFFERED=1
# Add user local bin to PATH
ENV PATH="/home/appuser/.local/bin:$PATH"

# Copy requirements with ownership
COPY --chown=appuser:appuser data-api/requirements.txt /app/

# Switch to non-root user
USER appuser

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir --user -r requirements.txt

# Copy the current directory contents into the container at /app with ownership
COPY --chown=appuser:appuser data-api/ /app/
COPY --chown=appuser:appuser shared/logger/ /app/logger/

# Make port 8000 available to the world outside this container
EXPOSE 8000

# Run controller.py when the container launches
CMD ["uvicorn", "controller:app", "--host", "0.0.0.0", "--port", "8000"]
