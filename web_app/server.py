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

# ==== متغير حالة الطوارئ ====
SYSTEM_PAUSED = False

# تحميل الملفات الثابتة والقوالب
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


# ==== الصفحة الرئيسية ====
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


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
        auth_file = BASE_DIR / "auth_config.json"
        config = json.loads(auth_file.read_text(encoding="utf-8"))
        pin_hash = config.get("pin_hash", "")
        input_hash = hashlib.sha256(pin.encode("utf-8")).hexdigest()
        
        if input_hash != pin_hash:
            return JSONResponse({"success": False, "error": "غير مصرح"})
        
        facts = awn.memory.get("facts", {})
        return JSONResponse({"success": True, "facts": facts})
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"success": False, "error": str(e)})


# ==== رسالة الترحيب الذكية ====
@app.post("/api/welcome")
async def api_welcome(data: dict):
    try:
        pin = data.get("pin", "")
        auth_file = BASE_DIR / "auth_config.json"
        config = json.loads(auth_file.read_text(encoding="utf-8"))
        pin_hash = config.get("pin_hash", "")
        input_hash = hashlib.sha256(pin.encode("utf-8")).hexdigest()
        
        if input_hash != pin_hash:
            return JSONResponse({"success": False, "error": "غير مصرح"})
        
        from datetime import datetime, timedelta
        now = datetime.utcnow() + timedelta(hours=3)
        hour = now.hour
        
        import random
        if 5 <= hour < 12:
            greetings = [
                "صباح الفل يا بلال! منور الصبح. كيفك اليوم؟",
                "يا هلا بالصبح! صباحك سعيد يا رفيقي. كيفك اليوم؟",
            ]
            religious_msgs = [
                "هل قرأت أذكار الصباح اليوم؟",
                "هل قرأت وردك من القرآن اليوم؟",
                "هل صليت الفجر؟",
            ]
            welcome = f"{random.choice(greetings)} {random.choice(religious_msgs)}"
        elif 12 <= hour < 18:
            greetings = [
                "يا هلا يا بلال! منور. كيفك اليوم؟",
                "أهلاً بعودتك يا رفيقي! كيفك اليوم؟",
            ]
            welcome = random.choice(greetings)
        elif 18 <= hour < 22:
            greetings = [
                "يا هلا يا بلال! منور المسا. كيف كان يومك؟",
                "أهلاً بعودتك يا رفيقي! اشتقتلك. كيف كان يومك؟",
            ]
            religious_msgs = [
                "لا تنسى أذكار المساء.",
                "هل صليت العشاء؟",
                "صلي على النبي يا بلال.",
            ]
            welcome = f"{random.choice(greetings)} {random.choice(religious_msgs)}"
        else:
            greetings = [
                "يا هلا يا بلال! لسا صاحي؟ منور. كيفك؟",
                "أهلاً بعودتك يا رفيقي! كيفك هالوقت؟",
            ]
            welcome = random.choice(greetings)
        
        return JSONResponse({"success": True, "welcome": welcome})
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"success": False, "error": str(e)})


# ==== توليد الصوت فقط ====
@app.post("/api/tts")
async def api_tts(data: dict):
    try:
        text = data.get("text", "").strip()
        voice = data.get("voice", "ar-JO-TaimNeural")
        
        if not text:
            return JSONResponse({"success": False, "error": "نص فارغ"})
        
        try:
            is_english = sum(1 for c in text if c.isascii() and c.isalpha()) > (len(text) / 2)
            chosen_voice = "en-US-AndrewNeural" if is_english else voice
            
            async def gen_audio():
                communicate = edge_tts.Communicate(text, chosen_voice)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
                    tmp_path = tmp.name
                await communicate.save(tmp_path)
                return tmp_path
            
            audio_path = await gen_audio()
            with open(audio_path, "rb") as f:
                audio_b64 = base64.b64encode(f.read()).decode("utf-8")
            os.unlink(audio_path)
            
            return JSONResponse({"success": True, "audio_base64": audio_b64})
        except Exception as e:
            print(f"[TTS error] {e}")
            return JSONResponse({"success": False, "error": str(e)})
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"success": False, "error": str(e)})


# ==== Kill Switch (إيقاف الطوارئ) ====
@app.post("/api/kill")
async def api_kill(data: dict):
    global SYSTEM_PAUSED
    pin = data.get("pin", "")
    auth_file = BASE_DIR / "auth_config.json"
    config = json.loads(auth_file.read_text(encoding="utf-8"))
    pin_hash = config.get("pin_hash", "")
    input_hash = hashlib.sha256(pin.encode("utf-8")).hexdigest()
    
    if input_hash != pin_hash:
        return JSONResponse({"success": False, "error": "غير مصرح"})
    
    SYSTEM_PAUSED = True
    print("[KILL SWITCH] System paused!")
    return JSONResponse({"success": True, "message": "تم إيقاف عون. النظام مجمد."})


# ==== Resume (إعادة التشغيل) ====
@app.post("/api/resume")
async def api_resume(data: dict):
    global SYSTEM_PAUSED
    pin = data.get("pin", "")
    auth_file = BASE_DIR / "auth_config.json"
    config = json.loads(auth_file.read_text(encoding="utf-8"))
    pin_hash = config.get("pin_hash", "")
    input_hash = hashlib.sha256(pin.encode("utf-8")).hexdigest()
    
    if input_hash != pin_hash:
        return JSONResponse({"success": False, "error": "غير مصرح"})
    
    SYSTEM_PAUSED = False
    print("[KILL SWITCH] System resumed!")
    return JSONResponse({"success": True, "message": "تم استئناف عون."})


# ==== فحص حالة النظام ====
@app.get("/api/status")
async def api_status():
    return JSONResponse({"paused": SYSTEM_PAUSED})


# ==== المحادثة ====
@app.post("/api/chat")
async def api_chat(data: dict):
    try:
        global SYSTEM_PAUSED
        if SYSTEM_PAUSED:
            return JSONResponse({"success": False, "error": "عون متوقف مؤقتاً بواسطة المدير التنفيذي (Kill Switch)."})
        
        message = data.get("message", "").strip()
        history = data.get("history", [])
        voice = data.get("voice", "ar-JO-TaimNeural")
        muted = data.get("muted", False)
        
        if not message:
            return JSONResponse({"success": False, "error": "رسالة فارغة"})
        
        messages = [{"role": "system", "content": awn.build_system_prompt()}]
        for msg in history:
            messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": message})
        
        response = awn.call_groq(messages, temperature=0.4)
        
        threading.Thread(
            target=awn.smart_extract,
            args=(message, response),
            daemon=True
        ).start()
        
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
        global SYSTEM_PAUSED
        if SYSTEM_PAUSED:
            return JSONResponse({"success": False, "error": "عون متوقف مؤقتاً (Kill Switch)."})
        
        print(f"[STT DEBUG] Filename: {audio.filename}, Content-Type: {audio.content_type}")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as tmp:
            content = await audio.read()
            print(f"[STT DEBUG] Received bytes: {len(content)}")
            print(f"[STT DEBUG] First 16 bytes (hex): {content[:16].hex()}")
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


# ==== تشغيل الخادم ====
if __name__ == "__main__":
    print("=" * 50)
    print("🚀 عون - الواجهة الاحترافية")
    print("=" * 50)
    
    import os as _os
    is_cloud = _os.getenv("AWN_CLOUD") == "1"
    
    if is_cloud:
        port = int(_os.getenv("PORT", 10000))
        print(f"☁️ وضع السحابة - منفذ: {port}")
        uvicorn.run(app, host="0.0.0.0", port=port)
    else:
        print("🏠 وضع محلي - مع SSL")
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=8000,
            ssl_certfile=str(BASE_DIR / "localhost+1.pem"),
            ssl_keyfile=str(BASE_DIR / "localhost+1-key.pem")
        )