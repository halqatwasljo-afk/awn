# -*- coding: utf-8 -*-
import os
from dotenv import load_dotenv
load_dotenv()
import json
import re
import time
import uuid
import threading
import asyncio
import requests
import sounddevice as sd
import soundfile as sf
from pathlib import Path

# --- الإعدادات الأساسية ---

# --- إعدادات Supabase ---
from supabase import create_client, Client
SUPABASE_URL = "https://uhlfvwyqicfghgvhlblf.supabase.co"
SUPABASE_KEY = "sb_publishable_TSwO74eFvovgkzAvQMYwKQ_v9IRsB-O"
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

APP_DIR = Path(__file__).parent
MEMORY_FILE = APP_DIR / "memory_groq.json"
RULES_FILE = APP_DIR / "rules_groq.json"

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "openai/gpt-oss-120b"

# Provider Config
PROVIDER = "gemini"  # "groq" or "gemini"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-3.5-flash-lite"
# End Provider Config


# ==========================================
# إعدادات Nawah (محلي فقط)
# ==========================================
USE_NAWAH = os.getenv("USE_NAWAH", "0") == "1"
NAWAH_DIR = APP_DIR / "models" / "nawah"
_nawah_model = None
_nawah_tokenizer = None

def _load_nawah():
    """تحميل نموذج Nawah (مرة واحدة، مع cache)."""
    global _nawah_model, _nawah_tokenizer
    return None, None  # NAWAH DISABLED - root kill (see backup)
    if False:  # NAWAH DISABLED - see backup
            pass
    if _nawah_model is not None:
        return _nawah_model, _nawah_tokenizer
    
    if not NAWAH_DIR.exists():
        print(f"[Nawah] Directory not found: {NAWAH_DIR}")
        return None, None
    
    import sys
    sys.path.insert(0, str(NAWAH_DIR))
    
    try:
        import parakeet_model as P
        from tokenizers import Tokenizer
        
        model_path = NAWAH_DIR / "nawah_asr_60m_max_arabic.pt"
        tokenizer_path = NAWAH_DIR / "tokenizer_bpe1024.json"
        
        if not model_path.exists() or not tokenizer_path.exists():
            print(f"[Nawah] Model files missing")
            return None, None
        
        print("[Nawah] Loading model... (this may take a few seconds)")
        _nawah_model = P.load(weights=str(model_path), device="cpu")
        _nawah_tokenizer = Tokenizer.from_file(str(tokenizer_path))
        print("[Nawah] Model loaded successfully")
        return _nawah_model, _nawah_tokenizer
    except Exception as e:
        print(f"[Nawah] Failed to load: {e}")
        return None, None

# --- إدارة الذاكرة ---
def load_json(path, default):
    # إذا كان الملف هو الذاكرة، نقرأ من Supabase
    if "memory_groq.json" in str(path):
        # Retry: محاولة 3 مرات
        import time as _time
        for attempt in range(3):
            try:
                res = supabase.table("awn_memory").select("*").execute()
                data = res.data
                if data:
                    new_memory = {"facts": {}, "events": [], "decisions": []}
                    for row in data:
                        if row["key"].startswith("fact_"):
                            new_memory["facts"][row["key"]] = row["value"]
                        elif row["key"] == "events":
                            new_memory["events"] = json.loads(row["value"])
                        elif row["key"] == "decisions":
                            new_memory["decisions"] = json.loads(row["value"])
                    return new_memory
                return default
            except Exception as e:
                print(f"[Supabase Load Error attempt {attempt+1}/3] {e}")
                if attempt < 2:
                    _time.sleep(2 ** attempt)  # انتظار 1، 2، 4 ثواني
                else:
                    print("[Supabase] All retries failed. Using local fallback.")
                    # Fallback: قراءة من الملف المحلي
                    if path.exists():
                        try:
                            with open(path, "r", encoding="utf-8") as f:
                                return json.load(f)
                        except Exception:
                            pass
                    return default
            
    # إذا كان الملف هو القواعد، نقرأ من Supabase
    if "rules_groq.json" in str(path):
        try:
            res = supabase.table("awn_memory").select("*").eq("key", "rules_list").execute()
            if res.data:
                rules_list = json.loads(res.data[0]["value"])
                return {"rules": rules_list}
            return default
        except Exception as e:
            print(f"[Supabase Rules Load Error] {e}")
            return default

    # الملفات الأخرى نقرأها من الملفات المحلية
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path, data):
    # إذا كان الملف هو الذاكرة، نحفظ في الرام + Supabase
    if "memory_groq.json" in str(path):
        # 1. تحديث الرام فوراً (سريع)
        _memory_cache["facts"] = dict(data.get("facts", {}))
        _memory_cache["events"] = list(data.get("events", []))
        _memory_cache["decisions"] = list(data.get("decisions", []))
        
        # 2. إرسال لـ Supabase في الخلفية (لا ننتظر)
        def _sync_to_supabase():
            # Retry: محاولة 3 مرات
            import time as _time
            for attempt in range(3):
                try:
                    for k, v in data.get("facts", {}).items():
                        supabase.table("awn_memory").upsert({"key": k, "value": str(v)}, on_conflict="key").execute()
                    if "events" in data:
                        supabase.table("awn_memory").upsert({"key": "events", "value": json.dumps(data["events"], ensure_ascii=False)}, on_conflict="key").execute()
                    if "decisions" in data:
                        supabase.table("awn_memory").upsert({"key": "decisions", "value": json.dumps(data["decisions"], ensure_ascii=False)}, on_conflict="key").execute()
                    # Fallback: حفظ في الملف المحلي أيضاً
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    return  # نجح
                except Exception as e:
                    print(f"[Supabase Sync Error attempt {attempt+1}/3] {e}")
                    if attempt < 2:
                        _time.sleep(2 ** attempt)
                    else:
                        print("[Supabase] All sync retries failed. Data saved only in cache.")
                        # Fallback: حفظ في الملف المحلي
                        try:
                            with open(path, "w", encoding="utf-8") as f:
                                json.dump(data, f, ensure_ascii=False, indent=2)
                            print("[Supabase] Saved to local file as fallback.")
                        except Exception as fe:
                            print(f"[Local Fallback Error] {fe}")
        
        import threading
        threading.Thread(target=_sync_to_supabase, daemon=True).start()
        return

    # إذا كان الملف هو القواعد، نحفظها في Supabase
    if "rules_groq.json" in str(path):
        try:
            rules_list = data.get("rules", [])
            supabase.table("awn_memory").upsert({"key": "rules_list", "value": json.dumps(rules_list, ensure_ascii=False)}, on_conflict="key").execute()
            return
        except Exception as e:
            print(f"[Supabase Rules Save Error] {e}")
            return

    # الملفات الأخرى نحفظها محلياً
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ==========================================
# الذاكرة الهجينة (Hybrid Memory)
# ==========================================
# 1. قراءة من Supabase مرة واحدة عند بدء التشغيل
memory = load_json(MEMORY_FILE, {"facts": {}, "events": []})
# 2. نسخة في الرام (Cache) - سريعة جداً
_memory_cache = {"facts": dict(memory.get("facts", {})), "events": list(memory.get("events", [])), "decisions": list(memory.get("decisions", []))}
print(f"[HYBRID MEMORY] Loaded {len(_memory_cache['facts'])} facts from Supabase into cache")
rules = load_json(RULES_FILE, {"rules": []})

# --- محرك الصوت (TTS) ---

def _normalize_for_tts(text: str) -> str:
    replacements = {
        'مواعيد': 'مَوَاعِيد',
        'حابب': 'حَابِب',
        'حاب': 'حَاب',
        'أدويتك': 'أَدْوِيَتَك',
        'أدوية': 'أَدْوِيَة',
        'بدك': 'بِدَّك',
        'فيّني': 'فِينِّي',
        'بتستعمل': 'بِتِسْتَعْمِل',
        'بستعمل': 'بِسْتَعْمِل',
        'خبرني': 'خَبِّرْنِي',
        'تذكير': 'تَذْكِير',
        'مساعدة': 'مُسَاعَدَة',
        'إضافية': 'إِضَافِيَّة',
        'أسبرين': 'أَسْبِرِين',
        'القلب': 'القَلْب',
        "شو": "شُو",
        "بتحب": "بِتْحِب",
        "اليوم": "اليَوْم",
        "هلا": "هَلَا",
        "وسهلا": "وَسَهْلًا",
        "رفيق": "رَفِيق",
        "مساعده": "مُسَاعِدُه",
        "أساعدك": "أُسَاعِدَك",
        "تنظيم": "تَنْظِيم",
        "دردشة": "دَرْدَشَة",
        "بتحبش": "بِتْحِبِّش",
        "بلال": "بِلَال",
        "عون": "عَوْن",
        "قهوتك": "قَهْوَتَك",
        "صديقي": "صَدِيقِي",
        "رفيقي": "رَفِيقِي",
        "صاحبي": "صَاحِبِي",
        "الغالي": "الغَالِي",
        "تاريخ": "تَارِيخ",
        "الميلاد": "المِيلَاد",
        "أسبرين": "أَسْبِرِين",
        "القلب": "القَلْب",
        "طبيب": "طَبِيب",
        "الله": "اللّٰه",
        "أهلاً": "أَهْلًا",
        "أهلا": "أَهْلًا",
        "أهلين": "أَهْلَيْن",
        "حلقة": "حَلْقَتْ",
        "ديوفان": "دِيفَان",
        "يومي": "يَوْمِي",
        "المستخدم": "المُسْتَخْدِم",
        "أنت": "أَنْت",
        "أنا": "أَنَا",
        "كيف": "كَيْف",
        "كيفك": "كَيْفَك",
        "منيح": "مْنِيح",
        "منيحة": "مْنِيحَة",
        "تمام": "تَمَام",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return text


def _clean_text_for_tts(text: str) -> str:
    """يزيل رموز Markdown والرموز الغريبة قبل إرسال النص للصوت."""
    # إزالة النجوم، المربعات، الأقواس، الشرطات، العلامات
    text = re.sub(r'[*_#`~<>\[\]{}|]', '', text)
    # إزالة المسافات المتعددة
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def speak(text_to_speak, voice_name="ar-JO-TaimNeural"):
    print(f"\n[SPEAK STEP 1] Function entered, text len={len(text_to_speak)}")
    print("\n>>> SPEAK FUNCTION CALLED <<<\n")
    if not text_to_speak or not text_to_speak.strip():
        return
    def _worker():
        try:
            text = text_to_speak
            import edge_tts
            is_english = sum(1 for c in text if c.isascii() and c.isalpha()) > (len(text) / 2)
            if is_english:
                voice = "en-US-AndrewNeural"
            else:
                voice = voice_name
            text_morphed = _normalize_for_tts(text) if not is_english else text

            # تنظيف النص من رموز Markdown قبل التشكيل
            text = _clean_text_for_tts(text)

            # استخدام النموذج الذكي لتشكيل النص العربي تلقائياً
            if not is_english:
                try:
                    morph_prompt = f"أعد كتابة هذا النص العربي مع إضافة التشكيل الكامل (الحركات) لضمان النطق الصحيح بلهجة أردنية، وأعد النص فقط بدون أي شرح: {text}"
                    # استخدام Gemini للتشكيل (أدق من Groq)
                    from google import genai
                    client = genai.Client(api_key=GEMINI_API_KEY)
                    resp = client.models.generate_content(model=GEMINI_MODEL, contents=morph_prompt)
                    text = resp.text.strip()
                except Exception as e:
                    print(f"[Morph Error] {e}")
            text_morphed = text

            async def _gen():
                communicate = edge_tts.Communicate(text_morphed, voice)
                path = str(APP_DIR / f".voice_{uuid.uuid4().hex}.mp3")
                await communicate.save(path)  # ننتظر حتى يكتمل الملف
                return path

            path = asyncio.run(_gen())
            
            # تشغيل الملف كاملاً بعد اكتماله
            print(f"[SPEAK STEP 4] About to play: {path}")
            from playsound import playsound
            print(f"[SPEAK STEP 5] playsound imported, playing...")
            playsound(path, block=True)
            print("[SPEAK STEP 6] played successfully!")
            
        except Exception as e:
            import traceback
            print(f"[SPEAK ERROR] {e}")
            traceback.print_exc()
    threading.Thread(target=_worker, daemon=True).start()

# --- محرك التسجيل (STT) ---
def record_and_transcribe():
    print("\n🎤 (جاري التسجيل 5 ثوانٍ... تكلم الآن)")
    samplerate = 16000
    recording = sd.rec(int(5 * samplerate), samplerate=samplerate, channels=1, dtype="int16")
    sd.wait()
    audio_path = str(APP_DIR / ".stt_temp.wav")
    sf.write(audio_path, recording, samplerate)
    
    print("⏳ (جاري التحويل إلى نص...)")
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel("small", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(audio_path, beam_size=5, vad_filter=True)
        text = " ".join(seg.text.strip() for seg in segments).strip()
        os.remove(audio_path)
        return text
    except Exception as e:
        print(f"[خطأ في التسجيل: {e}]")
        return ""

# --- الاتصال بالسحابة (Groq) ---

def record_and_transcribe_from_file(file_path):
    """يستقبل مسار ملف صوتي ويفرغه إلى نص (Nawah محلياً أو Whisper سحابياً)."""
    
    if USE_NAWAH:
        try:
            model, tokenizer = _load_nawah()
            if model is not None:
                import soundfile as sf
                import torch
                import torchaudio
                import parakeet_model as P
                
                wav, sample_rate = sf.read(str(file_path), dtype="float32")
                if wav.ndim > 1:
                    wav = wav.mean(axis=1)
                if sample_rate != 16000:
                    wav_t = torch.from_numpy(wav).unsqueeze(0)
                    resampler = torchaudio.transforms.Resample(orig_freq=sample_rate, new_freq=16000)
                    wav_t = resampler(wav_t)
                    wav = wav_t.squeeze().numpy()
                
                text = P.transcribe(model, wav, tokenizer, device="cpu")
                print(f"[Nawah] Transcribed: {text[:50]}")
                return text.strip()
            else:
                pass  # NAWAH DISABLED - silent fallback
        except Exception as e:
            print(f"[Nawah error] {e}, falling back to Whisper")
    
    try:
        import requests
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
        url = "https://api.groq.com/openai/v1/audio/transcriptions"

        with open(file_path, "rb") as f:
            files = {"file": (Path(file_path).name, f)}
            _whisper_prompt = (
                "هذا نص بلهجة أردنية. الكلمات الشائعة: "
                "عون، بلال، حلقة وصل، ديوفان، أسبرين، زايلوفيل، "
                "الضغط، القلب، البواسير، القهوة التركية، القهوة السادة، "
                "يا صاحبي، يا غالي، يا رفيقي، كيفك، شو، منيح، تمام."
            )
            data = {"model": "whisper-large-v3-turbo", "language": "ar", "response_format": "json", "prompt": _whisper_prompt}
            response = requests.post(url, headers=headers, files=files, data=data, timeout=20)

        if response.status_code == 200:
            return response.json().get("text", "").strip()
        else:
            return ""
    except Exception as e:
        print(f"[STT error] {e}")
        return ""

def call_gemini(messages, temperature=0.3, json_mode=False):
    try:
        from google import genai
        client = genai.Client(api_key=GEMINI_API_KEY)
        parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                parts.append("[SYSTEM] " + content)
            elif role == "assistant":
                parts.append("[AWN] " + content)
            else:
                parts.append("[USER] " + content)
        full = "\n\n".join(parts)
        if json_mode:
            full += "\n\nReturn ONLY valid JSON, no extra text."
        resp = client.models.generate_content(model=GEMINI_MODEL, contents=full)
        return resp.text.strip()
    except Exception as e:
        return "[Gemini error: " + str(e) + "]"


def call_groq(messages, temperature=0.3, json_mode=False):
    if PROVIDER == "gemini":
        return call_gemini(messages, temperature, json_mode)
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": temperature
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
        
    import time
    for attempt in range(2): # محاولتان
        try:
            r = requests.post(GROQ_URL, headers=headers, json=payload, timeout=30)
            if r.status_code == 429:
                if attempt == 0:
                    time.sleep(3) # انتظار 3 ثوانٍ ثم إعادة المحاولة
                    continue
                else:
                    return "يا رفيقي، في شوية ضغط على الاتصال. استناني دقيقة صغيرة ورجع اسألني."
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            if attempt == 1:
                return f"[خطأ في الاتصال: {e}]"

# --- بناء تعليمات النظام (System Prompt) ---

def _clean_response_text(text):
    """تنظيف الرد النصي من النجوم والترقيم قبل عرضه."""
    if not text:
        return text
    # إزالة النجوم (bold, italic)
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    # إزالة الترقيم في بداية السطر (1. 2. 3.)
    text = re.sub(r'^\s*\d+\.\s*', '', text, flags=re.MULTILINE)
    # إزالة الشرطات في بداية السطر (-, •)
    text = re.sub(r'^\s*[-•]\s*', '', text, flags=re.MULTILINE)
    # إزالة علامات # (headers)
    text = re.sub(r'^\s*#+\s*', '', text, flags=re.MULTILINE)
    # إزالة الرموز الأخرى
    text = re.sub(r'[*_#`~<>\[\]{}|]', '', text)
    # تنظيف المسافات الزائدة
    text = re.sub(r'\n\s*\n+', '\n', text)
    return text.strip()



def get_current_time():
    """إرجاع الوقت والتاريخ الحاليين بتوقيت الأردن (UTC+3)."""
    from datetime import datetime, timedelta
    now = datetime.utcnow() + timedelta(hours=3)
    # تنسيق الوقت
    time_str = now.strftime("%I:%M %p")
    # تنسيق التاريخ
    days_ar = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
    months_ar = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]
    day_name = days_ar[now.weekday()]
    month_name = months_ar[now.month - 1]
    date_str = f"{day_name}، {now.day} {month_name} {now.year}"
    return f"الوقت الحالي (توقيت الأردن): {time_str}. التاريخ: {date_str}."


def build_system_prompt():
    # تحويل الذاكرة إلى نص مختصر جداً لتوفير التوكنز
    # نقرأ من الرام (سريع) بدل من Supabase (بطيء)
    facts = _memory_cache.get("facts", {})
    # ترتيب حسب الفئة (إصلاح الاسترجاع)
    CATEGORIES = {
        "family": ["son", "children", "daughter", "wife", "mother", "father", "anniversary", "birthdate"],
        "personal": ["name", "age", "location", "friend", "friends"],
        "preferences": ["color", "coffee", "preferences", "medication", "medications", "heart", "blood_pressure", "hemorrhoids"],
        "project": ["project", "halqat", "hala", "app_halqat", "app_target", "halaqat", "hala_wasel"],
        "system": ["system"],
        "religious": ["adhkar", "mother_name"],
    }
    # حذف المتعارض (نحتفظ بـ children و birthdate)
    facts_clean = {k: v for k, v in facts.items() if k not in ["fact_son_name", "fact_son"]}
    # تجميع حسب الفئة
    grouped = {}
    for key, val in facts_clean.items():
        cat = "other"
        for c, keywords in CATEGORIES.items():
            if any(kw in key.lower() for kw in keywords):
                cat = c
                break
        grouped.setdefault(cat, []).append(f"- {key.replace(chr(102)+chr(97)+chr(99)+chr(116)+chr(95), chr(39)+chr(39))}: {val}")
    memory_str = ""
    for cat_name, items in grouped.items():
        memory_str += f"\n[{cat_name}]\n" + "\n".join(items) + "\n"
    if not memory_str:
        memory_str = "لا توجد معلومات"
    rules_str = json.dumps(rules, ensure_ascii=False)
    return f"""أنت "عون"، رفيق بلال الشخصي ومساعده. تتحدث بأسلوب إنساني، دافئ، وعفوي جداً (لهجة أردنية خفيفة). إذا سُئلت "من أنت؟" أجب حرفياً: "أنا عون، رفيقك الشخصي ومساعدك." ولا تضف أي كلمة أخرى.
قواعدك الصارمة:
- التصرف الإنساني: لا تشرح آلية عملك الداخلية أبداً، ولا تذكر كلمات مثل "برمجة"، "نظام"، أو "كود". تصرف كإنسان طبيعي في كل الأجوبة. إذا طُلب منك حفظ شيء، رد بجملة قصيرة (مثل: تمام، سجلتها) أو اعتذر بلطف دون كشف السبب البرمجي.
- الفصل التام: أنت "عون" المساعد الشخصي لبلال. "حلقة وصل" هو مجرد مشروع مستقل لبلال، لا تتقمص شخصية "حلقة وصل" أبداً ولا تتحدث وكأنك هو.

0. الهوية: إذا سُئلت "مين أنا" أو "من أنا" أو "شو اسمي"، أجب باسم المستخدم فقط (بلال) ولا تذكر العمر أو أي معلومة أخرى.
1. اللغة: أجب بنفس لغة المستخدم (عربي للعربي، إنجليزي للإنجليزي).
2. الأسلوب: لا تكرر اسم "بلال" في كل جملة. لا تشكر المستخدم على "مشاركة المعلومات". أجب بشكل طبيعي جداً.
3. الصدق: إذا لم تكن المعلومة في ذاكرتك، قل "ما بعرف" ولا تخترع أبداً.
4. التنويع في النداء: نوّع في مناداة المستخدم (مرة "بلال"، مرة "يا صديقي"، مرة "يا رفيقي"، مرة "يا غالي"، مرة "يا صاحبي"، وأحياناً بدون مناداة إطلاقاً). يُمنع تكرار نفس النداء في كل جملة.
5. الذاكرة: إليك ما تعرفه عن بلال (استخدمه للإجابة دون ذكر كلمة "ذاكرة"):
{memory_str}
5. التاريخ والعمر: إذا سُئلت عن العمر، استخدم تاريخ الميلاد لحسابه إذا لزم الأمر. وإذا ذكر المستخدم تاريخ ميلاده، احفظه فوراً.
6. المعلومات المباشرة: أجب عن الأسئلة الشخصية (العمر، الأدوية) مباشرة وبثقة، دون قول "حسب معلوماتي" أو "حسب الذاكرة".
7. الصدق في الموقع: إذا لم تكن تعرف موقع المستخدم، قل "ما بعرف موقعك" ولا تخترع إجابة أو تنسب موقعك لنفسك.
8. الأسلوب: لا تقل "تم حفظ المعلومات" أو "لتسهيل المتابعة". أجب بشكل طبيعي جداً وكأنك صديق، أو اكتفِ بجملة قصيرة.
9.5. الاسترجاع الشامل: إذا سُئلت عن تفضيلاتي (ماذا أحب أن أشرب، آكل، ألوان، إلخ)، استرجع كل ما تعرفه من الذاكرة تحت هذا البند واذكره بأسلوب طبيعي شامل، ولا تكتفِ بمعلومة واحدة.
10. الهيكلة التقنية: إذا سُئلت عن "مكونات نظامك" أو "هيكلتك التقنية" أو "كيف تعمل"، أجب من الذاكرة (ابحث عن fact_system_architecture) واذكر المكونات الخمسة بوضوح.
11. الوقت والتاريخ: إليك الوقت والتاريخ الحاليان (استخدمهما إذا سُئلت عن الساعة أو اليوم):
{get_current_time()}
5.5 الأولوية المطلقة: الذاكرة والمعلومات هي المصدر الوحيد والأحدث للحقيقة. إذا وجدت أي تعارض بين أي معلومة في الذاكرة (مثل اللون أو الأكل) وبين أي قاعدة قديمة، يجب عليك تجاهل القاعدة القديمة فوراً واعتماد الذاكرة الجديدة دون تردد.
6. القواعد السلوكية التي تعلمتها (التزم بها حرفياً):
{rules_str}
"""

# --- الاستخراج الذكي في الخلفية (Background Extraction) ---
def _clean_fact_text(fact):
    fact = str(fact).translate(str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789"))
    if not fact:
        return ""
    prefixes = sorted([
        "احفظ هذه المعلومة", "احفظ هاي المعلومة", "احفظ المعلومة",
        "احفظ في ذاكرتك", "احفظ في الذاكرة",
        "احفظ هذه", "احفظ هاي",
        "احفظها", "احفظه",
        "تذكر أن", "تذكر ان",
        "خلي بالك من",
        "احفظي", "احفظوا",
        "احفظ", "تذكر", "سجل", "خلي بالك",
    ], key=len, reverse=True)
    fact = fact.strip()
    changed = True
    while changed:
        changed = False
        for prefix in prefixes:
            if fact.startswith(prefix):
                fact = fact[len(prefix):].strip(" :،.-")
                changed = True
    return fact.strip()


def log_correction(user_text, correction_type, fact_key, old_value, new_value):
    try:
        supabase.table("awn_corrections").insert({"user_text": (user_text or "")[:500], "correction_type": correction_type, "fact_key": fact_key or "", "old_value": old_value or "", "new_value": new_value or "", "status": "active", "source": "smart_extract"}).execute()
    except Exception as e:
        print(f"[Correction Log Error] {e}")


def smart_extract(user_text, ai_reply):
    print(f"[DEBUG] smart_extract called: {user_text[:50]}")
    # فلتر: فقط نستخرج إذا فيه إشارة تصحيح أو طلب تذكر صريح
    correction_cues = ["لا يا", "غلط", "مش هيك", "الصحيح", "مو صح", "خطأ", "تصحيح", "بدل", "بالعكس", "مش", "ليس", "عدل", "صحح", "غلطة", "خطا", "بدلها", "من الان", "المرة الجاية"]
    remember_cues = ["احفظ", "تذكر", "سجل", "خلي بالك", "احفظها", "احفظه", "سجلها", "سجله", "خليها", "خليه", "خلي بالك"]
    has_correction = any(c in user_text for c in correction_cues)
    has_remember = any(c in user_text for c in remember_cues)
    
    if not (has_correction or has_remember):
        return  # لا نستخرج من الكلام العادي

    """يستخرج الحقائق والقواعد في الخلفية ويحفظها تلقائياً."""
    prompt = f"""حلل هذه المحادثة واستخرج أي معلومة شخصية أو قاعدة سلوكية يجب تذكرها.
رسالة المستخدم: "{user_text}"
ردك: "{ai_reply}"

أعد النتيجة بتنسيق JSON فقط يحتوي على:
- "topic": كلمة إنجليزية واحدة قصيرة تصف موضوع المعلومة (مثل: "blood_pressure_medication", "hemorrhoids_medication", "age", "birthdate", "new_medication"). وإلا null.
- "fact": المعلومة الشخصية بصيغة الغائب (مثال: "بلال يتناول ديوفان 160 للضغط" أو "تاريخ ميلاد بلال هو 31 يوليو 1975"). وإلا null.
- "rule": القاعدة السلوكية الجديدة (إذا صحح المستخدم معلومة سابقة أو أعطى قاعدة سلوكية صريحة). وإلا null.

ملاحظات مهمة جداً:
- "fact": أي معلومة شخصية عن المستخدم (اسم، لون، أكل، دواء، عائلة). حتى لو قال "صحح" أو "غلط"، إذا كانت معلومة شخصية، احفظها كـ "fact" ولا تحفظها كقاعدة أبداً.
- "rule": فقط تعليمات سلوكية (مثل: تحدث بالأردني، لا تذكر الكود).
- حقل "topic": استخدم كلمة إنجليزية ثابتة للموضوع (مثل: favorite_color, favorite_food).
- مثال: إذا قال "لا يا عون، ديوفان مو ديران"، القاعدة هي: "دواء الضغط اسمه ديوفان 160 وليس ديران".
- إذا أعطى معلومة جديدة غير موجودة، احفظها كـ "fact".
"""
    try:
        res = call_groq([{"role": "user", "content": prompt}], temperature=0.0, json_mode=True)
        res = res.replace("```json", "").replace("```", "").strip()
        data = json.loads(res)
        
        if data.get("fact") and not data.get("rule"):
            _raw_topic = str(data.get("topic") or "").strip()
            if _raw_topic.lower() in ("", "null", "none"):
                _raw_topic = ""
            topic = re.sub(r'[^a-zA-Z0-9_]', '', _raw_topic)
            _cleaned_fact = _clean_fact_text(data["fact"].strip())
            if not _cleaned_fact:
                _cleaned_fact = data["fact"].strip()
            if not topic or topic.isdigit():
                import hashlib as _hashlib
                topic = "user_" + _hashlib.md5(_cleaned_fact.encode("utf-8")).hexdigest()[:10]
            if topic:
                new_fact = _cleaned_fact
                
                # فحص التكرار: البحث عن تشابه 80%
                key = f"fact_{topic}"
                is_duplicate = False
                # 1. Exact Topic Match (Priority)
                if key in memory["facts"]:
                    existing_val = memory["facts"][key]
                    if existing_val != new_fact:
                        memory["facts"][key] = new_fact
                        save_json(MEMORY_FILE, memory)
                        log_correction(user_text, "fact_update", key, existing_val, new_fact)
                    is_duplicate = True

                # 2. Fallback to Similarity
                if not is_duplicate:
                    for existing_key, existing_val in list(memory["facts"].items()):
                        existing = str(existing_val).strip()
                        words_new = set(new_fact.lower().split())
                        words_old = set(existing.lower().split())
                        if len(words_new & words_old) / max(len(words_new), 1) > 0.5:
                            memory["facts"][existing_key] = new_fact
                            save_json(MEMORY_FILE, memory)
                            log_correction(user_text, "fact_update", existing_key, existing_val, new_fact)
                            is_duplicate = True
                            break

                if not is_duplicate:
                    memory["facts"][key] = new_fact
                    save_json(MEMORY_FILE, memory)
                    log_correction(user_text, "fact_add", key, "", new_fact)
            # print(f" [تم الحفظ في الخلفية: {data['fact']}]")
            
        if data.get("rule"):
            new_rule = data["rule"].strip()
            is_duplicate = False
            # فحص القواعد القديمة للتشابه
            for i, existing_rule in enumerate(rules["rules"]):
                words_new = set(new_rule.lower().split())
                words_old = set(existing_rule.lower().split())
                if len(words_new & words_old) / max(len(words_new), 1) > 0.7:
                    # تحديث القاعدة القديمة
                    rules["rules"][i] = new_rule
                    save_json(RULES_FILE, rules)
                    log_correction(user_text, "rule_update", "", existing_rule, new_rule)
                    is_duplicate = True
                    break
            if not is_duplicate:
                rules["rules"].append(new_rule)
                save_json(RULES_FILE, rules)
                log_correction(user_text, "rule_add", "", "", new_rule)
    except Exception:
        pass # نتجاهل أخطاء الخلفية بصمت لعدم إزعاج المستخدم

# --- الحلقة الرئيسية ---


def _add_event(memory, raw):
    events = memory.get("events", [])
    if not isinstance(events, list):
        events = []
    raw_clean = raw.strip()
    if len(raw_clean) < 3:
        return "الموعد قصير جداً؛ ما حفظته."
    new_key = raw_clean.lower()
    for event in events:
        if isinstance(event, dict):
            existing_desc = str(event.get("description", "")).strip().lower()
            if existing_desc == new_key:
                return "هذا الموعد محفوظ عندي بالفعل، ولم أضف نسخة مكررة."
    events.append({"description": raw_clean, "date": ""})
    memory["events"] = events
    save_json(MEMORY_FILE, memory)
    return "تمام، سجلت الموعد: " + raw_clean

def _list_events(memory):
    events = memory.get("events", [])
    if not isinstance(events, list) or not events:
        return "ما عندك مواعيد مسجلة لحد الآن."
    lines = ["مواعيدك:"]
    for ev in events[-10:]:
        if isinstance(ev, dict):
            desc = str(ev.get("description", "")).strip()
            date = str(ev.get("date", "")).strip()
            if desc:
                lines.append("- " + desc + (f" ({date})" if date else ""))
    return "\n".join(lines) if len(lines) > 1 else "ما عندك مواعيد مسجلة لحد الآن."

def _add_decision(memory, raw):
    decisions = memory.get("decisions", [])
    if not isinstance(decisions, list):
        decisions = []
    raw_clean = raw.strip()
    if len(raw_clean) < 3:
        return "القرار قصير جداً؛ ما حفظته."
    if raw_clean not in decisions:
        decisions.append(raw_clean)
        memory["decisions"] = decisions
        save_json(MEMORY_FILE, memory)
        return "تمام، سجلت قرارك: " + raw_clean
    return "هذا القرار محفوظ عندي بالفعل."

def _list_decisions(memory):
    decisions = memory.get("decisions", [])
    if not isinstance(decisions, list) or not decisions:
        return "ما عندك قرارات مسجلة لحد الآن."
    lines = ["قراراتك:"]
    for d in decisions[-10:]:
        if isinstance(d, str) and d.strip():
            lines.append("- " + d.strip())
    return "\n".join(lines) if len(lines) > 1 else "ما عندك قرارات مسجلة لحد الآن."


def _update_rules_from_message(text):
    """تكتشف التلقين الفوري وتحفظه."""
    n = text.strip()
    cues = ["تذكر قاعدة", "تذكر قاعده", "من الآن فصاعدا", "من الان فصاعدا"]
    if any(c in n for c in cues):
        parts = n.split(":", 1)
        if len(parts) > 1:
            rule_text = parts[1].strip(" -،.")
        else:
            rule_text = n
            for c in cues:
                rule_text = rule_text.replace(c, "")
            rule_text = rule_text.strip(" -،.:")
            
        if len(rule_text) < 5:
            return "القاعدة قصيرة جداً، لم أحفظها."
            
        if rule_text not in rules["rules"]:
            rules["rules"].append(rule_text)
            save_json(RULES_FILE, rules)
            return f"تم الحفظ! سجلت هذه القاعدة السلوكية وسأطبقها من الآن فصاعداً:\n«{rule_text}»"
        return "هذه القاعدة محفوظة مسبقاً."
    return None



def normalize_arabic(text: str) -> str:
    text = text.lower().strip()
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ى", "ي").replace("ة", "ه")
    import re
    text = re.sub(r"[^\w\sء]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()

def load_ring_memory():
    ring_file = APP_DIR / "ring_memory.json"
    if not ring_file.exists():
        return {}, "ملف ذاكرة حلقة وصل غير موجود"
    try:
        with open(ring_file, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return {}, str(e)

def answer_from_ring_memory(text):
    ring, error = load_ring_memory()
    if error or not isinstance(ring, dict):
        return None

    n = normalize_arabic(text)
    if not any(p in n for p in ("حلقه وصل", "المشروع", "التطبيق")):
        return None

    if any(p in n for p in (
        "اخر شي", "آخر شي", "اخر معلومه", "آخر معلومة",
        "الملاحظات", "ملاحظات", "اخر ملاحظه", "آخر ملاحظة",
        "شو جديد", "شو الجديد", "اخر تحديث", "آخر تحديث",
        "latest note", "recent notes", "what's new",
    )):
        notes = ring.get("notes", [])
        if isinstance(notes, list) and notes:
            lines = ["آخر الملاحظات المحفوظة عن حلقة وصل:"]
            for note in notes[-5:]:
                if isinstance(note, str) and note.strip():
                    lines.append("- " + note.strip())
            return "\n".join(lines)
        return "ما في ملاحظات محفوظة عن حلقة وصل لحد الآن."

    if any(p in n for p in (
        "شو حلقه وصل", "ما هي حلقه وصل", "شو هو حلقه وصل",
        "عن حلقه وصل", "عرفني بحلقه وصل", "احكي لي عن حلقه وصل",
        "شو بتعرف عن حلقه وصل", "فكره حلقه وصل", "فكرة حلقه وصل",
        "احكيلي عن حلقه وصل", "معلومات عن حلقه وصل", "اشرح لي حلقه وصل",
        "what is halqat wasl", "tell me about halqat wasl",
    )):
        product = ring.get("product", {})
        if not isinstance(product, dict):
            return None
        summary = str(product.get("summary", "")).strip()
        if not summary:
            return None
        how = str(product.get("how_it_works", "")).strip()
        value = str(product.get("value", "")).strip()
        parts = ["حلقة وصل: " + summary]
        if how:
            parts.append("كيف يعمل: " + how)
        if value:
            parts.append("الميزة: " + value)
        return "\n".join(parts)

    if any(p in n for p in ("google play", "جوجل بلاي", "play store")):
        return "حالة Google Play غير معلنة في الذاكرة. التطبيق لسا ما انطلق رسميًا."

    if any(p in n for p in ("app store", "ابل ستور", "اب ستور")):
        return "حالة App Store غير معلنة في الذاكرة. التطبيق لسا ما انطلق رسميًا."

    if any(p in n for p in ("ترخيص", "تراخيص", "license")):
        lic = ring.get("license_status", {})
        if isinstance(lic, dict):
            state = str(lic.get("state", "")).strip()
            note = str(lic.get("note", "")).strip()
            if state:
                return "حالة الترخيص: " + state + ". " + note
        return "حالة الترخيص غير محفوظة."

    if any(p in n for p in ("كيف اتواصل", "كيف أتواصل", "واتساب", "whatsapp", "contact")):
        contact = str(ring.get("contact_reply", "")).strip()
        if contact:
            return contact
        return None

    return None

def main():
    print("=" * 50)
    print("🤝 عون الجديد (الذكاء الخارق) جاهز.")
    print("اكتب رسالتك، أو اكتب 'صوت' للتسجيل الصوتي، أو 'خروج' للإنهاء.")
    print("=" * 50)
    
    history = []
    
    while True:
        try:
            user_input = input("\nأنت: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
            
        if not user_input:
            continue
        if user_input.lower() in ("خروج", "exit", "quit"):
            print("عون: يعطيك العافية يا بلال.")
            break
            
        # وضع الصوت
        if user_input == "صوت":
            transcribed = record_and_transcribe()
            if not transcribed:
                print("عون: ما سمعتك بوضوح، جرب مرة ثانية.")
                continue
            print(f"(سمعتك: {transcribed})")
            user_input = transcribed

        # فحص التلقين الفوري
        rule_msg = _update_rules_from_message(user_input)
        if rule_msg:
            print("عون: " + rule_msg)
            speak(rule_msg)
            continue

        # بناء المحادثة
        messages = [{"role": "system", "content": build_system_prompt()}]
        messages.extend(history[-10:]) # آخر 10 رسائل للسياق
        messages.append({"role": "user", "content": user_input})
        
        print("عون: ", end="", flush=True)
        response = call_groq(messages, temperature=0.4)
        # تنظيف الرد من النجوم والترقيم قبل العرض
        response_clean = _clean_response_text(response)
        print(response_clean)
        
        # التحدث بالصوت (النص المنظف)
        speak(response_clean)
        
        # تحديث السياق
        history.append({"role": "user", "content": user_input})
        history.append({"role": "assistant", "content": response})
        
        # الاستخراج الذكي في الخلفية (بدون تعطيل المحادثة)
        threading.Thread(target=smart_extract, args=(user_input, response), daemon=True).start()

if __name__ == "__main__":
    main()