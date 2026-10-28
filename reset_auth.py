# -*- coding: utf-8 -*-
from pathlib import Path

app_dir = Path(__file__).parent
files_to_delete = ["auth_config.json", "RECOVERY_KEY.txt", "voiceprint.pt"]

print("⚠️ تحذير: سيتم مسح كل بيانات الأمان!")
confirm = input("اكتب (نعم) للمتابعة: ")

if confirm == "نعم":
    for f in files_to_delete:
        p = app_dir / f
        if p.exists():
            p.unlink()
            print(f"🗑️ تم حذف {f}")
    print("✅ تمت إعادة التعيين. شغّل التطبيق لإنشاء كود جديد.")
else:
    print("❌ تم الإلغاء.")
