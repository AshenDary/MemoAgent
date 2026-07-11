# 1. Use an official, lightweight Python runtime
FROM python:3.11-slim

# 2. Set the working directory inside the container
WORKDIR /app

# 3. Mac/ARM optimization: Prevent Python from writing pyc files and buffer stdout
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 4. Copy only the requirements file first
COPY requirements.txt .

# 5. Install system build tools (sometimes required for spaCy on ARM architectures), 
# install requirements, download the language model, and clean up to keep the image small
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && pip install --no-cache-dir -r requirements.txt \
    && python -m spacy download en_core_web_sm \
    && apt-get purge -y --auto-remove build-essential \
    && rm -rf /var/lib/apt/lists/*

# 6. Copy the rest of your application code
COPY . .

# 7. Expose the port FastAPI runs on
EXPOSE 8000

# 8. Command to run your FastAPI server
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
