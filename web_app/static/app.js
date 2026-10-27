// ============ المتغيرات ============
let chatHistory = [];
let currentPin = null;
let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;

// ============ الدخول (PIN) ============
async function login() {
    const pin = document.getElementById('pin-input').value.trim();
    const errorEl = document.getElementById('login-error');

    if (!pin) {
        errorEl.textContent = 'الرجاء إدخال الكود السري';
        return;
    }

    try {
        const res = await fetch('/api/login', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({pin: pin})
        });
        const data = await res.json();

        if (data.success) {
            currentPin = pin;
            document.getElementById('login-screen').classList.remove('active');
            document.getElementById('chat-screen').classList.add('active');
            document.getElementById('msg-input').focus();
            loadSidebarData(); // جلب بيانات القائمة الجانبية

            // ============ طلب رسالة الترحيب الذكية ============
            setTimeout(async () => {
                try {
                    const wRes = await fetch('/api/welcome', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({pin: currentPin})
                    });
                    const wData = await wRes.json();
                    if (wData.success && wData.welcome) {
                        addMessage('bot', wData.welcome);
                    }
                } catch (e) {
                    console.log('Welcome error:', e);
                }
            }, 500);
            // ============ نهاية الترحيب ============

        } else {
            errorEl.textContent = data.message || 'الكود السري خطأ';
        }
    } catch (e) {
        errorEl.textContent = 'خطأ في الاتصال';
    }
}

// السماح بالدخول بمفتاح Enter
document.getElementById('pin-input')?.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') login();
});

// ============ القائمة الجانبية ============
function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebar-overlay');
    
    sidebar.classList.toggle('open');
    if (sidebar.classList.contains('open')) {
        overlay.style.display = 'block';
    } else {
        overlay.style.display = 'none';
    }
}

async function loadSidebarData() {
    try {
        const res = await fetch('/api/memory', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({pin: currentPin})
        });
        const data = await res.json();

        if (data.success) {
            const facts = Object.values(data.facts || {});
            
            // تصنيف البيانات (نفس منطق الواجهة القديمة)
            const meds = facts.filter(v => v.includes('دواء') || v.includes('أسبرين') || v.includes('ديوفان') || v.includes('زايلوفيل'));
            const personal = facts.filter(v => v.includes('عمر') || v.includes('الميلاد') || v.includes('اسم'));
            const other = facts.filter(v => !meds.includes(v) && !personal.includes(v));

            renderList('list-meds', meds, 'لا توجد أدوية مسجلة');
            renderList('list-personal', personal, 'لا توجد معلومات شخصية');
            renderList('list-other', other, 'لا توجد معلومات أخرى');
        }
    } catch (e) {
        console.error('Failed to load sidebar', e);
    }
}

function renderList(elementId, items, emptyText) {
    const el = document.getElementById(elementId);
    if (!items || items.length === 0) {
        el.innerHTML = `<li style="color:#6b7280; list-style:none; margin-right:-15px;">${emptyText}</li>`;
    } else {
        el.innerHTML = items.map(item => `<li>${item}</li>`).join('');
    }
}

// ============ إرسال رسالة ============
async function sendMessage() {
    const input = document.getElementById('msg-input');
    const text = input.value.trim();
    if (!text || !currentPin) return;

    addMessage('user', text);
    input.value = '';
    input.style.height = 'auto';

    const sendBtn = document.getElementById('send-btn');
    sendBtn.disabled = true;
    setStatus('عون يفكر...');

    try {
        const res = await fetch('/api/chat', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                message: text,
                history: chatHistory,
                pin: currentPin,
                voice: document.getElementById('voice-select').value,
                muted: document.getElementById('mute-audio').checked
            })
        });
        const data = await res.json();

        if (data.success) {
            addMessage('bot', data.reply);
            chatHistory.push({role: 'user', content: text});
            chatHistory.push({role: 'assistant', content: data.reply});

            if (data.audio_base64 && !document.getElementById('mute-audio').checked) {
                playAudio(data.audio_base64);
            }
            
            // نحدث القائمة الجانبية لو انحفظ شي جديد
            loadSidebarData();
        } else {
            addMessage('bot', '❌ ' + (data.error || 'حدث خطأ'));
        }
    } catch (e) {
        addMessage('bot', '❌ خطأ في الاتصال بالخادم');
    } finally {
        sendBtn.disabled = false;
        setStatus('');
    }
}

// Enter لإرسال، Shift+Enter لسطر جديد
document.getElementById('msg-input')?.addEventListener('keypress', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

// زيادة ارتفاع textarea تلقائياً
document.getElementById('msg-input')?.addEventListener('input', function() {
    this.style.height = 'auto';
    this.style.height = Math.min(this.scrollHeight, 120) + 'px';
});

// ============ إضافة رسالة للشات ============
function addMessage(role, text) {
    const container = document.getElementById('chat-container');
    const msg = document.createElement('div');
    msg.className = 'message ' + role;
    msg.textContent = text;
    container.appendChild(msg);
    container.scrollTop = container.scrollHeight;
}

// ============ تشغيل الصوت ============
function playAudio(base64Audio) {
    try {
        const audio = document.getElementById('player');
        audio.src = 'data:audio/mp3;base64,' + base64Audio;
        audio.play().catch(e => console.log('Audio play failed:', e));
    } catch (e) {
        console.log('Audio error:', e);
    }
}

// ============ حالة ============
function setStatus(text) {
    document.getElementById('status').textContent = text;
}

// ============ مسح المحادثة ============
function clearChat() {
    chatHistory = [];
    document.getElementById('chat-container').innerHTML = '';
}

// ============ المايك (تسجيل صوتي) ============
async function toggleRecording() {
    if (isRecording) {
        stopRecording();
        return;
    }

    try {
        const stream = await navigator.mediaDevices.getUserMedia({audio: true});
        mediaRecorder = new MediaRecorder(stream);
        audioChunks = [];

        mediaRecorder.ondataavailable = (e) => audioChunks.push(e.data);
        mediaRecorder.onstop = async () => {
            const audioBlob = new Blob(audioChunks, {type: 'audio/webm'});
            await sendAudio(audioBlob);
            stream.getTracks().forEach(t => t.stop());
        };

        mediaRecorder.start();
        isRecording = true;
        document.getElementById('mic-btn').classList.add('recording');
        setStatus('🎤 جاري التسجيل... اضغط مرة أخرى للإيقاف');
    } catch (e) {
        setStatus('❌ لا يمكن الوصول للمايك');
    }
}

function stopRecording() {
    if (mediaRecorder && isRecording) {
        mediaRecorder.stop();
        isRecording = false;
        document.getElementById('mic-btn').classList.remove('recording');
        setStatus('جاري تحويل الصوت...');
    }
}

async function sendAudio(blob) {
    const formData = new FormData();
    formData.append('audio', blob, 'voice.webm');
    formData.append('pin', currentPin);

    try {
        const res = await fetch('/api/transcribe', {
            method: 'POST',
            body: formData
        });
        const data = await res.json();

        if (data.success && data.text) {
            document.getElementById('msg-input').value = data.text;
            sendMessage();
        } else {
            setStatus('❌ لم أفهم الصوت');
        }
    } catch (e) {
        setStatus('❌ خطأ في تحويل الصوت');
    }
}