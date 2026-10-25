FROM python:3.11-slim

# تثبيت مكتبات النظام المطلوبة للصوت
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsndfile1 \
    portaudio19-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# إنشاء مجلد العمل
WORKDIR /app

# نسخ المتطلبات وتثبيتها
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ باقي الملفات
COPY . .

# تفعيل وضع السحابة
ENV AWN_CLOUD=1
ENV PORT=7860

# فتح المنفذ
EXPOSE 7860

# تشغيل الخادم
CMD ["python", "web_app/server.py"]