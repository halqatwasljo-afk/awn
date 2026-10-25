import sys
import importlib.util
import base64
import tempfile
import os
import threading
import asyncio
import edge_tts
import json
import hashlib
from pathlib import Path
from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn

# ==== الاتصال بعقل عون (awn_groq) ====
BASE_DIR = Path(__file__).parent.parent
spec = importlib.util.spec_from_file_location("awn_groq", BASE_DIR / "awn_groq.py")
awn = importlib.util.module_from_spec(spec)
sys.modules["awn_groq"] = awn
spec.loader.exec_module(awn)

# ==== إعداد FastAPI ====
app = FastAPI()

# تحميل الملفات الثابتة والقوالب
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


# ==== الصفحة الرئيسية ====
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ==== تسجيل الدخول (PIN) ====
@app.post("/api/login")
async def api_login(data: dict):
    pin = data.get("pin", "")
    
    auth_file = BASE_DIR / "auth_config.json"
    
    if not auth_file.exists():
        return JSONResponse({"success": False, "message": "ملف الإعدادات غير موجود"})
    
    config = json.loads(auth_file.read_text(encoding="utf-8"))
    pin_hash = config.get("pin_hash", "")
    input_hash = hashlib.sha256(pin.encode("utf-8")).hexdigest()
    
    if input_hash == pin_hash:
        return JSONResponse({"success": True})
    return JSONResponse({"success": False, "message": "الكود السري خطأ"})


# ==== جلب بيانات الذاكرة للقائمة الجانبية ====
@app.post("/api/memory")
async def api_memory(data: dict):
    try:
        pin = data.get("pin", "")
        # التحقق من الـ PIN (نفس منطق الدخول)
        auth_file = BASE_DIR / "auth_config.json"
        config = json.loads(auth_file.read_text(encoding="utf-8"))
        pin_hash = config.get("pin_hash", "")
        input_hash = hashlib.sha256(pin.encode("utf-8")).hexdigest()
        
        if input_hash != pin_hash:
            return JSONResponse({"success": False, "error": "غير مصرح"})
        
        # نقرأ الذاكرة من العقل
        facts = awn.memory.get("facts", {})
        return JSONResponse({"success": True, "facts": facts})
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"success": False, "error": str(e)})


# ==== المحادثة ====
@app.post("/api/chat")
async def api_chat(data: dict):
    try:
        message = data.get("message", "").strip()
        history = data.get("history", [])
        voice = data.get("voice", "ar-JO-TaimNeural")
        muted = data.get("muted", False)
        
        if not message:
            return JSONResponse({"success": False, "error": "رسالة فارغة"})
        
        # 1. بناء الرسائل
        messages = [{"role": "system", "content": awn.build_system_prompt()}]
        for msg in history:
            messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": message})
        
        # 2. استدعاء العقل (Gemini)
        response = awn.call_groq(messages, temperature=0.4)
        
        # 3. تشغيل الاستخراج في الخلفية
        threading.Thread(
            target=awn.smart_extract,
            args=(message, response),
            daemon=True
        ).start()
        
        # 4. توليد الصوت
        audio_b64 = None
        if not muted:
            try:
                is_english = sum(1 for c in response if c.isascii() and c.isalpha()) > (len(response) / 2)
                chosen_voice = "en-US-AndrewNeural" if is_english else voice
                
                async def gen_audio():
                    communicate = edge_tts.Communicate(response, chosen_voice)
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
                        tmp_path = tmp.name
                    await communicate.save(tmp_path)
                    return tmp_path
                
                audio_path = await gen_audio()
                with open(audio_path, "rb") as f:
                    audio_b64 = base64.b64encode(f.read()).decode("utf-8")
                os.unlink(audio_path)
            except Exception as e:
                print(f"[Audio error] {e}")
        
        return JSONResponse({
            "success": True,
            "reply": response,
            "audio_base64": audio_b64
        })
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"success": False, "error": str(e)})


# ==== تحويل الصوت إلى نص (STT) ====
@app.post("/api/transcribe")
async def api_transcribe(audio: UploadFile = File(...), pin: str = Form(...)):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            content = await audio.read()
            tmp.write(content)
            tmp_path = tmp.name
        
        text = awn.record_and_transcribe_from_file(tmp_path)
        os.unlink(tmp_path)
        
        if text:
            return JSONResponse({"success": True, "text": text})
        return JSONResponse({"success": False, "error": "لم أفهم الصوت"})
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"success": False, "error": str(e)})


# ==== تشغيل الخادم مع SSL ====
if __name__ == "__main__":
    print("=" * 50)
    print("🚀 عون - الواجهة الاحترافية")
    print("=" * 50)
    print("📱 الافتتاح على: https://localhost:8000")
    print("🌐 للموبايل: https://192.168.100.37:8000")
    print("=" * 50)
    
    # وضع السحابة (Hugging Face): بدون SSL (يوفره المنصة)
    # وضع محلي (بيت بلال): مع SSL (للموبايل)
    import os as _os
    is_cloud = _os.getenv("AWN_CLOUD") == "1"
    
    if is_cloud:
        print("☁️  وضع السحابة - بدون SSL محلي")
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=7860
        )
    else:
        print("🏠 وضع محلي - مع SSL")
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=8000,
            ssl_certfile=str(BASE_DIR / "localhost+1.pem"),
            ssl_keyfile=str(BASE_DIR / "localhost+1-key.pem")
        )