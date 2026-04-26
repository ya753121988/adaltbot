FROM python:3.9-slim

# ffmpeg এবং প্রয়োজনীয় টুল ইনস্টল করা
RUN apt-get update && apt-get install -y ffmpeg libsm6 libxext6 && apt-get clean

# ওয়ার্কিং ডিরেক্টরি
WORKDIR /app

# ফাইলগুলো কপি করা
COPY . /app

# লাইব্রেরি ইনস্টল করা
RUN pip install --no-cache-dir -r requirements.txt

# বট রান করা
CMD ["python", "main.py"]
