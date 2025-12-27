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
COPY --chown=appuser:appuser requirements.txt /app/

# Remove MetaTrader5 from requirements.txt as it is Windows-only
# We need to do this as root or ensure appuser has permissions. 
# Since we copy as appuser, appuser can write to it.
RUN sed -i '/MetaTrader5/d' requirements.txt

# Switch to non-root user
USER appuser

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir --user -r requirements.txt

# Copy the current directory contents into the container at /app with ownership
COPY --chown=appuser:appuser . /app/

# Make port 8001 available to the world outside this container
EXPOSE 8001

# Run main.py when the container launches
CMD ["python", "main.py"]
