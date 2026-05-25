#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════╗
║   ANDRO-AGENT Memory + Skill Manager v3         ║
║   Persistent Memory │ GDrive Backup │ Skills    ║
╚══════════════════════════════════════════════════╝
"""

import os, json, time, threading, requests, hashlib
from datetime import datetime, timedelta
from pathlib import Path

# ─── Paths ─────────────────────────────────────────────────────
BASE_DIR    = Path.home() / ".andro_agent"
MEMORY_FILE = BASE_DIR / "memory.json"
SKILL_DIR   = BASE_DIR / "skills"
CONFIG_FILE = BASE_DIR / "config.json"
BACKUP_LOG  = BASE_DIR / "backup.log"

BASE_DIR.mkdir(parents=True, exist_ok=True)
SKILL_DIR.mkdir(parents=True, exist_ok=True)

C = {"r":"\033[0m","g":"\033[1;32m","c":"\033[1;36m","y":"\033[1;33m",
     "re":"\033[1;31m","gr":"\033[0;90m","w":"\033[1;37m","p":"\033[1;35m"}
def c(k,t): return f"{C.get(k,'')}{t}{C['r']}"

# ════════════════════════════════════════════════════════════════
# MEMORY SYSTEM — Persistent + Long-term
# ════════════════════════════════════════════════════════════════

DEFAULT_MEMORY = {
    "version": 3,
    "created": datetime.now().isoformat(),
    "last_updated": datetime.now().isoformat(),
    "last_backup": None,
    # Long-term facts tentang user
    "user_profile": {
        "name": None,
        "preferences": {},
        "devices": [],
        "notes": []
    },
    # Percakapan per session (persistent)
    "conversations": {},
    # Ringkasan otomatis percakapan lama
    "summaries": {},
    # Hasil scan keamanan historis
    "scan_history": [],
    # Skill yang terinstall
    "installed_skills": [],
    # Event/reminder
    "reminders": [],
    # Pengetahuan yang dipelajari
    "learned_facts": []
}

def load_memory():
    if MEMORY_FILE.exists():
        try:
            with open(MEMORY_FILE) as f:
                mem = json.load(f)
            # Merge dengan default untuk key yang belum ada
            for k, v in DEFAULT_MEMORY.items():
                if k not in mem:
                    mem[k] = v
            return mem
        except:
            pass
    return DEFAULT_MEMORY.copy()

def save_memory(mem):
    mem["last_updated"] = datetime.now().isoformat()
    with open(MEMORY_FILE, "w") as f:
        json.dump(mem, f, indent=2, ensure_ascii=False)

def get_history(mem, sid, max_turns=15):
    """Ambil histori + ringkasan jika ada"""
    key = str(sid)
    hist = mem["conversations"].get(key, [])
    
    # Jika ada ringkasan lama, tambahkan sebagai konteks
    summary = mem["summaries"].get(key, "")
    if summary and len(hist) < 4:
        # Inject ringkasan sebagai pesan sistem
        return [{"role": "user", "content": f"[Ringkasan percakapan sebelumnya: {summary}]"},
                {"role": "assistant", "content": "Baik, saya ingat konteks sebelumnya."}] + hist[-max_turns*2:]
    
    return hist[-max_turns*2:]

def add_history(mem, sid, role, content):
    key = str(sid)
    mem["conversations"].setdefault(key, [])
    mem["conversations"][key].append({
        "role": role,
        "content": content,
        "time": datetime.now().isoformat()
    })
    
    # Auto-summarize jika terlalu panjang (>40 pesan)
    if len(mem["conversations"][key]) > 40:
        _auto_summarize(mem, key)
    
    save_memory(mem)

def _auto_summarize(mem, sid):
    """Ringkas percakapan lama, simpan sebagai summary"""
    hist = mem["conversations"].get(sid, [])
    if len(hist) < 20: return
    
    # Ambil 20 pesan lama untuk diringkas
    old_msgs = hist[:20]
    summary_text = f"Percakapan pada {old_msgs[0].get('time','')[:10]}: "
    topics = []
    for m in old_msgs:
        content = m.get("content", "")[:100]
        if m["role"] == "user" and len(content) > 10:
            topics.append(content)
    
    summary_text += " | ".join(topics[:5])
    
    # Simpan ringkasan
    existing = mem["summaries"].get(sid, "")
    mem["summaries"][sid] = (existing + " ... " + summary_text)[-1000:]
    
    # Hapus pesan lama, simpan 20 terakhir
    mem["conversations"][sid] = hist[20:]

def remember_fact(mem, fact, category="general"):
    """Simpan fakta yang dipelajari"""
    mem["learned_facts"].append({
        "fact": fact,
        "category": category,
        "time": datetime.now().isoformat()
    })
    # Max 100 fakta
    if len(mem["learned_facts"]) > 100:
        mem["learned_facts"] = mem["learned_facts"][-100:]
    save_memory(mem)

def get_user_context(mem):
    """Buat konteks user untuk AI"""
    profile = mem.get("user_profile", {})
    facts = mem.get("learned_facts", [])[-10:]
    scans = mem.get("scan_history", [])[-3:]
    
    ctx = []
    if profile.get("name"):
        ctx.append(f"Nama user: {profile['name']}")
    if profile.get("preferences"):
        ctx.append(f"Preferensi: {json.dumps(profile['preferences'])}")
    if facts:
        ctx.append("Fakta yang diketahui: " + "; ".join(f["fact"] for f in facts))
    if scans:
        last = scans[-1]
        ctx.append(f"Scan terakhir: {last.get('time','')[:10]} Score:{last.get('score','?')} Grade:{last.get('grade','?')}")
    
    return "\n".join(ctx) if ctx else ""

# ════════════════════════════════════════════════════════════════
# GOOGLE DRIVE BACKUP
# ════════════════════════════════════════════════════════════════

class GDriveBackup:
    """Backup memory ke Google Drive via rclone atau gdrive CLI"""
    
    def __init__(self, config):
        self.config = config
        self.method = config.get("gdrive_method", "rclone")  # rclone atau api
        self.folder_id = config.get("gdrive_folder_id", "")
        self.token = config.get("gdrive_token", "")
        self.auto_interval = config.get("backup_interval_hours", 6)
        self._timer = None
    
    def is_configured(self):
        if self.method == "rclone":
            import subprocess
            r = subprocess.run("which rclone", shell=True, capture_output=True)
            return r.returncode == 0
        return bool(self.token)
    
    def backup_now(self, mem):
        """Jalankan backup sekarang"""
        try:
            if self.method == "rclone":
                return self._backup_rclone()
            else:
                return self._backup_api(mem)
        except Exception as e:
            return False, str(e)
    
    def _backup_rclone(self):
        """Backup menggunakan rclone (direkomendasikan)"""
        import subprocess
        
        # Backup memory.json
        cmd = f'rclone copy "{MEMORY_FILE}" "gdrive:AndroAgent/" --drive-use-trash=false'
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        
        if r.returncode == 0:
            # Catat waktu backup
            with open(BACKUP_LOG, "a") as f:
                f.write(f"{datetime.now().isoformat()} - rclone backup OK\n")
            return True, "Backup berhasil via rclone"
        else:
            return False, f"rclone error: {r.stderr[:200]}"
    
    def _backup_api(self, mem):
        """Backup via Google Drive API langsung"""
        if not self.token:
            return False, "Token GDrive tidak dikonfigurasi"
        
        # Cek apakah file sudah ada
        headers = {"Authorization": f"Bearer {self.token}"}
        
        # Search file
        search_url = "https://www.googleapis.com/drive/v3/files"
        params = {"q": "name='andro_agent_memory.json'", "fields": "files(id,name)"}
        r = requests.get(search_url, headers=headers, params=params, timeout=15)
        
        content = json.dumps(mem, indent=2, ensure_ascii=False).encode("utf-8")
        
        if r.ok and r.json().get("files"):
            # Update file yang ada
            file_id = r.json()["files"][0]["id"]
            upload_url = f"https://www.googleapis.com/upload/drive/v3/files/{file_id}?uploadType=media"
            r2 = requests.patch(upload_url, headers={**headers, "Content-Type": "application/json"},
                               data=content, timeout=30)
            if r2.ok:
                with open(BACKUP_LOG, "a") as f:
                    f.write(f"{datetime.now().isoformat()} - API update OK\n")
                return True, "Memory diupdate di GDrive"
        else:
            # Buat file baru
            meta = {"name": "andro_agent_memory.json", "mimeType": "application/json"}
            if self.folder_id:
                meta["parents"] = [self.folder_id]
            
            # Multipart upload
            import io
            boundary = "boundary123"
            body = (f"--{boundary}\r\nContent-Type: application/json\r\n\r\n" +
                   json.dumps(meta) + f"\r\n--{boundary}\r\nContent-Type: application/json\r\n\r\n" +
                   content.decode() + f"\r\n--{boundary}--")
            
            upload_url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart"
            r2 = requests.post(upload_url,
                headers={**headers, "Content-Type": f"multipart/related; boundary={boundary}"},
                data=body.encode(), timeout=30)
            if r2.ok:
                with open(BACKUP_LOG, "a") as f:
                    f.write(f"{datetime.now().isoformat()} - API create OK\n")
                return True, "Memory diupload ke GDrive"
        
        return False, "Backup gagal"
    
    def restore_from_drive(self):
        """Restore memory dari GDrive"""
        try:
            if self.method == "rclone":
                import subprocess
                cmd = f'rclone copy "gdrive:AndroAgent/memory.json" "{BASE_DIR}/" --drive-use-trash=false'
                r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
                return r.returncode == 0, r.stdout or r.stderr
            else:
                if not self.token: return False, "Token tidak ada"
                headers = {"Authorization": f"Bearer {self.token}"}
                params = {"q": "name='andro_agent_memory.json'", "fields": "files(id)"}
                r = requests.get("https://www.googleapis.com/drive/v3/files",
                               headers=headers, params=params, timeout=15)
                if r.ok and r.json().get("files"):
                    fid = r.json()["files"][0]["id"]
                    r2 = requests.get(f"https://www.googleapis.com/drive/v3/files/{fid}?alt=media",
                                    headers=headers, timeout=30)
                    if r2.ok:
                        with open(MEMORY_FILE, "w") as f:
                            f.write(r2.text)
                        return True, "Memory berhasil direstore dari GDrive"
                return False, "File tidak ditemukan di GDrive"
        except Exception as e:
            return False, str(e)
    
    def start_auto_backup(self, mem_getter):
        """Mulai auto backup terjadwal"""
        def _do_backup():
            while True:
                time.sleep(self.auto_interval * 3600)
                try:
                    mem = mem_getter()
                    ok, msg = self.backup_now(mem)
                    mem["last_backup"] = datetime.now().isoformat()
                    save_memory(mem)
                    print(c("g" if ok else "re", f"\n  {'✅' if ok else '❌'} Auto-backup: {msg}"))
                except Exception as e:
                    print(c("re", f"\n  ❌ Auto-backup error: {e}"))
        
        t = threading.Thread(target=_do_backup, daemon=True)
        t.start()
        print(c("g", f"  ✅ Auto-backup setiap {self.auto_interval} jam aktif"))

# ════════════════════════════════════════════════════════════════
# SKILL SYSTEM
# ════════════════════════════════════════════════════════════════

# Skills yang tersedia (mirip ClawHub tapi untuk Andro-Agent)
SKILL_REGISTRY = {
    "web_search": {
        "name": "Web Search",
        "description": "Cari informasi dari internet secara realtime",
        "version": "1.0",
        "author": "Andro-Agent",
        "category": "productivity",
        "trigger": ["cari", "search", "googling", "cek berita"],
        "requires": ["requests"],
        "icon": "🌐"
    },
    "crypto_monitor": {
        "name": "Crypto Monitor",
        "description": "Pantau harga crypto BTC, ETH, dll realtime",
        "version": "1.0",
        "author": "Andro-Agent",
        "category": "finance",
        "trigger": ["crypto", "bitcoin", "harga coin", "btc", "eth"],
        "requires": ["requests"],
        "icon": "₿"
    },
    "weather": {
        "name": "Weather Info",
        "description": "Info cuaca kota manapun di Indonesia",
        "version": "1.0",
        "author": "Andro-Agent",
        "category": "utility",
        "trigger": ["cuaca", "weather", "hujan", "panas"],
        "requires": ["requests"],
        "icon": "🌤️"
    },
    "file_manager": {
        "name": "File Manager",
        "description": "Kelola file HP via Telegram (list, rename, delete, zip)",
        "version": "1.0",
        "author": "Andro-Agent",
        "category": "system",
        "trigger": ["file", "folder", "ls", "hapus file"],
        "requires": [],
        "icon": "📁"
    },
    "scheduler": {
        "name": "Task Scheduler",
        "description": "Jadwalkan perintah otomatis (cron-like)",
        "version": "1.0",
        "author": "Andro-Agent",
        "category": "automation",
        "trigger": ["jadwal", "schedule", "setiap", "reminder", "ingatkan"],
        "requires": [],
        "icon": "⏰"
    },
    "network_monitor": {
        "name": "Network Monitor",
        "description": "Monitor koneksi jaringan, deteksi intrusi, ping monitor",
        "version": "1.0",
        "author": "Andro-Agent",
        "category": "security",
        "trigger": ["network", "jaringan", "ping", "koneksi", "bandwidth"],
        "requires": ["psutil"],
        "icon": "🔌"
    },
    "sms_reader": {
        "name": "SMS Reader",
        "description": "Baca SMS via termux-sms-list (butuh termux-api)",
        "version": "1.0",
        "author": "Andro-Agent",
        "category": "communication",
        "trigger": ["sms", "pesan masuk", "baca sms"],
        "requires": ["termux-api"],
        "icon": "💬"
    },
    "battery_guard": {
        "name": "Battery Guard",
        "description": "Monitor baterai, notif saat low/full, statistik penggunaan",
        "version": "1.0",
        "author": "Andro-Agent",
        "category": "system",
        "trigger": ["baterai", "battery", "charging", "cas"],
        "requires": ["termux-api"],
        "icon": "🔋"
    },
    "ai_vision": {
        "name": "AI Vision",
        "description": "Analisis gambar/foto yang dikirim ke Telegram",
        "version": "1.0",
        "author": "Andro-Agent",
        "category": "ai",
        "trigger": ["analisis foto", "lihat gambar", "apa ini"],
        "requires": ["requests"],
        "icon": "👁️"
    },
    "security_watch": {
        "name": "Security Watchdog",
        "description": "Monitor HP 24/7, alert jika ada aktivitas mencurigakan",
        "version": "1.0",
        "author": "Andro-Agent",
        "category": "security",
        "trigger": ["monitor keamanan", "watchdog", "pantau hp"],
        "requires": ["psutil"],
        "icon": "🛡️"
    }
}

class SkillManager:
    def __init__(self, mem):
        self.mem = mem
        self.loaded_skills = {}
    
    def list_available(self, category=None):
        """Daftar skill yang tersedia"""
        skills = SKILL_REGISTRY
        if category:
            skills = {k:v for k,v in skills.items() if v["category"]==category}
        return skills
    
    def list_installed(self):
        """Skill yang sudah terinstall"""
        return self.mem.get("installed_skills", [])
    
    def is_installed(self, skill_id):
        return skill_id in self.list_installed()
    
    def install(self, skill_id):
        """Install skill"""
        if skill_id not in SKILL_REGISTRY:
            return False, f"Skill '{skill_id}' tidak ditemukan"
        
        if self.is_installed(skill_id):
            return False, f"Skill '{skill_id}' sudah terinstall"
        
        skill = SKILL_REGISTRY[skill_id]
        
        # Cek requirements
        missing = []
        for req in skill.get("requires", []):
            if req == "termux-api":
                import subprocess
                if subprocess.run("which termux-battery-status", shell=True, capture_output=True).returncode != 0:
                    missing.append("termux-api (pkg install termux-api)")
            else:
                try: __import__(req)
                except ImportError: missing.append(f"{req} (pip install {req})")
        
        if missing:
            return False, f"Requirements kurang: {', '.join(missing)}"
        
        # Buat file skill
        skill_file = SKILL_DIR / f"{skill_id}.json"
        with open(skill_file, "w") as f:
            json.dump({**skill, "id": skill_id, "installed_at": datetime.now().isoformat()}, f, indent=2)
        
        # Tambah ke installed list
        installed = self.mem.get("installed_skills", [])
        installed.append(skill_id)
        self.mem["installed_skills"] = installed
        save_memory(self.mem)
        
        return True, f"✅ Skill '{skill['name']}' berhasil diinstall!"
    
    def uninstall(self, skill_id):
        """Uninstall skill"""
        installed = self.mem.get("installed_skills", [])
        if skill_id not in installed:
            return False, "Skill tidak terinstall"
        
        installed.remove(skill_id)
        self.mem["installed_skills"] = installed
        save_memory(self.mem)
        
        skill_file = SKILL_DIR / f"{skill_id}.json"
        if skill_file.exists():
            skill_file.unlink()
        
        return True, f"Skill '{skill_id}' diuninstall"
    
    def run_skill(self, skill_id, params=None):
        """Jalankan skill"""
        if not self.is_installed(skill_id):
            return f"Skill '{skill_id}' belum diinstall. Ketik /skill install {skill_id}"
        
        params = params or {}
        
        try:
            if skill_id == "web_search":
                return self._skill_web_search(params.get("query", ""))
            elif skill_id == "crypto_monitor":
                return self._skill_crypto(params.get("coin", "bitcoin"))
            elif skill_id == "weather":
                return self._skill_weather(params.get("city", "Jakarta"))
            elif skill_id == "file_manager":
                return self._skill_file_manager(params.get("path", "~"), params.get("action", "list"))
            elif skill_id == "scheduler":
                return self._skill_scheduler(params)
            elif skill_id == "network_monitor":
                return self._skill_network()
            elif skill_id == "sms_reader":
                return self._skill_sms()
            elif skill_id == "battery_guard":
                return self._skill_battery()
            else:
                return f"Skill '{skill_id}' terdaftar tapi belum ada implementasi"
        except Exception as e:
            return f"❌ Skill error: {e}"
    
    def _skill_web_search(self, query):
        if not query: return "❌ Query kosong"
        try:
            r = requests.get("https://ddg-api.herokuapp.com/search",
                           params={"query": query, "limit": 3}, timeout=10)
            if r.ok:
                results = r.json()
                lines = [f"🌐 *Hasil pencarian: {query}*\n"]
                for i, res in enumerate(results[:3], 1):
                    lines.append(f"{i}. *{res.get('title','')}*")
                    lines.append(f"   {res.get('snippet','')[:150]}")
                    lines.append(f"   🔗 {res.get('link','')}")
                return "\n".join(lines)
        except:
            pass
        # Fallback: DuckDuckGo instant answer
        try:
            r = requests.get("https://api.duckduckgo.com/",
                           params={"q": query, "format": "json", "no_html": 1}, timeout=10)
            data = r.json()
            answer = data.get("AbstractText", "") or data.get("Answer", "")
            if answer:
                return f"🌐 *{query}*\n\n{answer[:500]}"
            return f"🌐 Tidak ada hasil instan untuk: {query}"
        except Exception as e:
            return f"❌ Search error: {e}"
    
    def _skill_crypto(self, coin="bitcoin"):
        try:
            r = requests.get(f"https://api.coingecko.com/api/v3/simple/price",
                           params={"ids": coin, "vs_currencies": "usd,idr",
                                  "include_24hr_change": "true"}, timeout=10)
            data = r.json()
            if coin in data:
                d = data[coin]
                change = d.get("usd_24h_change", 0)
                arrow = "📈" if change > 0 else "📉"
                return (f"₿ *{coin.upper()}*\n"
                       f"💵 USD: ${d.get('usd',0):,.2f}\n"
                       f"💰 IDR: Rp{d.get('idr',0):,.0f}\n"
                       f"{arrow} 24h: {change:.2f}%")
            return f"❌ Coin '{coin}' tidak ditemukan"
        except Exception as e:
            return f"❌ Crypto error: {e}"
    
    def _skill_weather(self, city="Jakarta"):
        try:
            r = requests.get("https://wttr.in/" + city,
                           params={"format": "j1"}, timeout=10)
            data = r.json()
            curr = data["current_condition"][0]
            desc = curr["weatherDesc"][0]["value"]
            temp = curr["temp_C"]
            feels = curr["FeelsLikeC"]
            humid = curr["humidity"]
            wind = curr["windspeedKmph"]
            return (f"🌤️ *Cuaca {city}*\n"
                   f"🌡️ Suhu: {temp}°C (terasa {feels}°C)\n"
                   f"💧 Kelembaban: {humid}%\n"
                   f"💨 Angin: {wind} km/h\n"
                   f"📝 {desc}")
        except Exception as e:
            return f"❌ Weather error: {e}"
    
    def _skill_file_manager(self, path="~", action="list"):
        import subprocess
        p = Path(path).expanduser()
        if action == "list":
            try:
                items = list(p.iterdir())
                lines = [f"📁 *{p}*\n"]
                dirs = [i for i in items if i.is_dir()][:10]
                files = [i for i in items if i.is_file()][:10]
                for d in dirs: lines.append(f"📂 {d.name}/")
                for f in files:
                    size = f.stat().st_size
                    sz = f"{size//1024}KB" if size > 1024 else f"{size}B"
                    lines.append(f"📄 {f.name} ({sz})")
                return "\n".join(lines)
            except Exception as e:
                return f"❌ {e}"
        return f"Action '{action}' belum tersedia"
    
    def _skill_network(self):
        import subprocess
        lines = ["🔌 *Network Monitor*\n"]
        # Koneksi aktif
        out = subprocess.run("ss -tnp 2>/dev/null | grep ESTAB | head -10",
                           shell=True, capture_output=True, text=True).stdout
        if out:
            lines.append("*Koneksi Aktif:*")
            for l in out.splitlines()[:5]:
                parts = l.split()
                if len(parts) >= 5:
                    lines.append(f"  {parts[4]}")
        # Ping Google
        ping = subprocess.run("ping -c 1 -W 2 8.8.8.8 2>/dev/null | tail -1",
                            shell=True, capture_output=True, text=True).stdout
        if ping: lines.append(f"\n🏓 Ping Google: {ping.strip()}")
        return "\n".join(lines)
    
    def _skill_sms(self):
        import subprocess
        out = subprocess.run("termux-sms-list -l 5 2>/dev/null",
                           shell=True, capture_output=True, text=True).stdout
        try:
            sms_list = json.loads(out)
            lines = ["💬 *5 SMS Terakhir:*\n"]
            for sms in sms_list[:5]:
                lines.append(f"📱 *{sms.get('number','?')}*")
                lines.append(f"   {sms.get('body','')[:100]}")
                lines.append(f"   _{sms.get('received','')[:16]}_\n")
            return "\n".join(lines)
        except:
            return "❌ Gagal baca SMS. Pastikan termux-api terinstall dan izin SMS diberikan."
    
    def _skill_battery(self):
        import subprocess
        out = subprocess.run("termux-battery-status 2>/dev/null",
                           shell=True, capture_output=True, text=True).stdout
        try:
            bat = json.loads(out)
            pct = bat.get("percentage", 0)
            status = bat.get("status", "?")
            health = bat.get("health", "?")
            temp = bat.get("temperature", 0)
            plug = bat.get("plugged", "?")
            
            icon = "🔋" if pct > 50 else ("🪫" if pct < 20 else "🔋")
            warn = ""
            if pct < 15: warn = "\n⚠️ *BATERAI KRITIS!*"
            if temp > 40: warn += "\n🌡️ *Baterai terlalu panas!*"
            
            return (f"{icon} *Battery Status*\n"
                   f"Kapasitas: {pct}%\n"
                   f"Status: {status}\n"
                   f"Kesehatan: {health}\n"
                   f"Suhu: {temp}°C\n"
                   f"Charger: {plug}{warn}")
        except:
            return "❌ Gagal baca baterai"
    
    def _skill_scheduler(self, params):
        """Simple scheduler - simpan di memory"""
        action = params.get("action", "list")
        if action == "list":
            reminders = self.mem.get("reminders", [])
            if not reminders: return "⏰ Belum ada jadwal"
            lines = ["⏰ *Jadwal Aktif:*\n"]
            for r in reminders:
                lines.append(f"• {r.get('time','')} — {r.get('task','')}")
            return "\n".join(lines)
        return "⏰ Scheduler: gunakan /remind <waktu> <tugas>"
    
    def format_skill_list(self, installed_only=False):
        """Format daftar skill untuk ditampilkan"""
        skills = SKILL_REGISTRY
        installed = self.list_installed()
        lines = []
        
        categories = {}
        for sid, skill in skills.items():
            cat = skill["category"]
            categories.setdefault(cat, []).append((sid, skill))
        
        for cat, items in categories.items():
            lines.append(f"\n*{cat.upper()}*")
            for sid, skill in items:
                is_inst = "✅" if sid in installed else "⬜"
                lines.append(f"{is_inst} {skill['icon']} `{sid}` — {skill['description'][:50]}")
        
        return "\n".join(lines)

# ════════════════════════════════════════════════════════════════
# SETUP GDRIVE
# ════════════════════════════════════════════════════════════════

def setup_gdrive_interactive():
    """Wizard setup GDrive backup"""
    print(c("cyan", "\n  ╔══════════════════════════════════════╗"))
    print(c("cyan", "  ║   📦 Setup Google Drive Backup       ║"))
    print(c("cyan", "  ╚══════════════════════════════════════╝\n"))
    
    print(c("yellow", "  Pilih metode backup:"))
    print(c("white", "  [1] rclone (direkomendasikan, lebih mudah)"))
    print(c("white", "  [2] Google Drive API token langsung"))
    print(c("white", "  [0] Skip\n"))
    
    ch = input(c("green", "  Pilihan: ")).strip()
    
    cfg = {}
    
    if ch == "1":
        print(c("cyan", "\n  Setup rclone untuk GDrive:\n"))
        print(c("gray", "  1. Jalankan: pkg install rclone"))
        print(c("gray", "  2. Jalankan: rclone config"))
        print(c("gray", "  3. Pilih: n (new remote)"))
        print(c("gray", "  4. Name: gdrive"))
        print(c("gray", "  5. Storage: 18 (Google Drive)"))
        print(c("gray", "  6. Ikuti instruksi OAuth di browser"))
        print(c("gray", "  7. Setelah selesai, kembali ke sini\n"))
        
        done = input(c("yellow", "  Sudah setup rclone? (y/n): ")).strip()
        if done.lower() == "y":
            cfg["gdrive_method"] = "rclone"
            cfg["gdrive_configured"] = True
            print(c("green", "  ✅ rclone GDrive dikonfigurasi!"))
    
    elif ch == "2":
        print(c("cyan", "\n  Cara dapat token:"))
        print(c("gray", "  1. Buka: https://developers.google.com/oauthplayground"))
        print(c("gray", "  2. Pilih scope: https://www.googleapis.com/auth/drive.file"))
        print(c("gray", "  3. Authorize dan copy Access Token\n"))
        
        token = input(c("white", "  Paste Access Token: ")).strip()
        folder = input(c("white", "  GDrive Folder ID (Enter=root): ")).strip()
        
        if token:
            cfg["gdrive_method"] = "api"
            cfg["gdrive_token"] = token
            cfg["gdrive_folder_id"] = folder
            cfg["gdrive_configured"] = True
            print(c("green", "  ✅ GDrive API dikonfigurasi!"))
    
    interval = input(c("white", "\n  Auto-backup setiap berapa jam? [6]: ")).strip()
    cfg["backup_interval_hours"] = int(interval) if interval.isdigit() else 6
    
    return cfg

# ════════════════════════════════════════════════════════════════
# COMMAND HANDLERS untuk Telegram/WhatsApp
# ════════════════════════════════════════════════════════════════

def handle_skill_command(text, skill_mgr):
    """Handle /skill commands"""
    parts = text.strip().split()
    
    if len(parts) < 2:
        installed = skill_mgr.list_installed()
        return (f"🧩 *Skill Manager*\n\n"
                f"Terinstall: {len(installed)} skill\n\n"
                f"Commands:\n"
                f"`/skill list` — semua skill\n"
                f"`/skill installed` — yang terinstall\n"
                f"`/skill install <id>` — install skill\n"
                f"`/skill remove <id>` — hapus skill\n"
                f"`/skill run <id>` — jalankan skill\n"
                f"`/skill info <id>` — detail skill")
    
    cmd = parts[1].lower()
    
    if cmd == "list":
        return f"🧩 *Daftar Skill Tersedia:*\n{skill_mgr.format_skill_list()}"
    
    elif cmd == "installed":
        installed = skill_mgr.list_installed()
        if not installed: return "📭 Belum ada skill terinstall.\nGunakan `/skill list` untuk lihat yang tersedia."
        lines = ["✅ *Skill Terinstall:*\n"]
        for sid in installed:
            s = SKILL_REGISTRY.get(sid, {})
            lines.append(f"• {s.get('icon','🔧')} `{sid}` — {s.get('name', sid)}")
        return "\n".join(lines)
    
    elif cmd == "install" and len(parts) >= 3:
        skill_id = parts[2].lower()
        ok, msg = skill_mgr.install(skill_id)
        return msg
    
    elif cmd == "remove" and len(parts) >= 3:
        skill_id = parts[2].lower()
        ok, msg = skill_mgr.uninstall(skill_id)
        return msg
    
    elif cmd == "run" and len(parts) >= 3:
        skill_id = parts[2].lower()
        query = " ".join(parts[3:]) if len(parts) > 3 else ""
        return skill_mgr.run_skill(skill_id, {"query": query, "city": query, "coin": query or "bitcoin"})
    
    elif cmd == "info" and len(parts) >= 3:
        skill_id = parts[2].lower()
        s = SKILL_REGISTRY.get(skill_id)
        if not s: return f"❌ Skill '{skill_id}' tidak ditemukan"
        inst = "✅ Terinstall" if skill_mgr.is_installed(skill_id) else "⬜ Belum install"
        return (f"{s['icon']} *{s['name']}* {inst}\n\n"
               f"📝 {s['description']}\n"
               f"🏷️ Kategori: {s['category']}\n"
               f"📦 Version: {s['version']}\n"
               f"⚡ Trigger: {', '.join(s['trigger'][:4])}\n"
               f"📌 ID: `{skill_id}`\n\n"
               f"Install: `/skill install {skill_id}`")
    
    return "❓ Command tidak dikenal. Ketik `/skill` untuk bantuan."

def handle_memory_command(text, mem):
    """Handle /memory commands"""
    parts = text.strip().split()
    
    if len(parts) < 2:
        facts = len(mem.get("learned_facts", []))
        convs = len(mem.get("conversations", {}))
        notes = len(mem.get("user_profile", {}).get("notes", []))
        last_backup = mem.get("last_backup", "Belum pernah")
        if last_backup and last_backup != "Belum pernah":
            last_backup = last_backup[:16]
        return (f"🧠 *Memory Status*\n\n"
               f"💬 Sesi tersimpan: {convs}\n"
               f"📝 Catatan: {notes}\n"
               f"💡 Fakta dipelajari: {facts}\n"
               f"💾 Backup terakhir: {last_backup}\n\n"
               f"Commands:\n"
               f"`/memory backup` — backup ke GDrive\n"
               f"`/memory restore` — restore dari GDrive\n"
               f"`/memory clear` — hapus semua\n"
               f"`/memory note <teks>` — simpan catatan\n"
               f"`/memory notes` — lihat catatan")
    
    cmd = parts[1].lower()
    
    if cmd == "note" and len(parts) >= 3:
        note = " ".join(parts[2:])
        mem["user_profile"].setdefault("notes", []).append({
            "text": note, "time": datetime.now().isoformat()
        })
        save_memory(mem)
        return f"📝 Catatan disimpan: _{note}_"
    
    elif cmd == "notes":
        notes = mem.get("user_profile", {}).get("notes", [])
        if not notes: return "📭 Belum ada catatan."
        lines = ["📝 *Catatan Tersimpan:*\n"]
        for n in notes[-10:]:
            lines.append(f"• {n['text']} _{n.get('time','')[:10]}_")
        return "\n".join(lines)
    
    elif cmd == "clear":
        mem["conversations"] = {}
        mem["summaries"] = {}
        save_memory(mem)
        return "🗑️ Memory percakapan dihapus."
    
    return "❓ Command tidak dikenal. Ketik `/memory` untuk bantuan."

if __name__ == "__main__":
    print(c("cyan", "\n  Testing Memory + Skill Manager...\n"))
    mem = load_memory()
    sm = SkillManager(mem)
    
    print(c("green", "  ✅ Memory loaded"))
    print(c("green", f"  ✅ Skills available: {len(SKILL_REGISTRY)}"))
    print(c("green", f"  ✅ Skills installed: {len(sm.list_installed())}"))
    print()
    print(sm.format_skill_list())
