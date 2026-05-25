#!/usr/bin/env python3
"""ANDRO-AGENT v3 — Memory + GDrive + Skills + Security"""
import os,sys,json,time,threading,subprocess
import requests
from datetime import datetime
from pathlib import Path

# ─── Import modules ────────────────────────────────────────────
def _import_local(name):
    import importlib.util
    p=os.path.join(os.path.dirname(os.path.abspath(__file__)),f"{name}.py")
    if not os.path.exists(p): return None
    spec=importlib.util.spec_from_file_location(name,p)
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod

_sm = _import_local("security_module")
_ms = _import_local("memory_skill")

if _sm:
    full_health_scan=_sm.full_health_scan; run_auto_hardening=_sm.run_auto_hardening
    run_hardening_action=_sm.run_hardening_action; HARDENING_ACTIONS=_sm.HARDENING_ACTIONS
    format_report_terminal=_sm.format_report_terminal; format_report_text=_sm.format_report_text
    SECURITY_OK=True
else:
    SECURITY_OK=False

if _ms:
    load_memory=_ms.load_memory; save_memory=_ms.save_memory
    get_history=_ms.get_history; add_history=_ms.add_history
    get_user_context=_ms.get_user_context; remember_fact=_ms.remember_fact
    SkillManager=_ms.SkillManager; GDriveBackup=_ms.GDriveBackup
    handle_skill_command=_ms.handle_skill_command; handle_memory_command=_ms.handle_memory_command
    MEMORY_OK=True
else:
    # Fallback memory sederhana
    MEMORY_FILE=Path.home()/".andro_agent"/"memory.json"
    def load_memory():
        if MEMORY_FILE.exists():
            with open(MEMORY_FILE) as f: return json.load(f)
        return {"conversations":{},"notes":[],"scan_history":[],"installed_skills":[]}
    def save_memory(m):
        with open(MEMORY_FILE,"w") as f: json.dump(m,f,indent=2,ensure_ascii=False)
    def get_history(mem,sid,n=15): return mem["conversations"].get(str(sid),[])[-n*2:]
    def add_history(mem,sid,role,content):
        k=str(sid); mem["conversations"].setdefault(k,[]).append({"role":role,"content":content})
        mem["conversations"][k]=mem["conversations"][k][-60:]; save_memory(mem)
    def get_user_context(mem): return ""
    def remember_fact(mem,fact,cat=""): pass
    MEMORY_OK=False

CONFIG_FILE=Path.home()/".andro_agent"/"config.json"
SCAN_FILE=Path.home()/".andro_agent"/"last_scan.json"
CONFIG_FILE.parent.mkdir(parents=True,exist_ok=True)

BANNER="""
\033[1;32m  ╔══════════════════════════════════════════════════╗
  ║   🛡️  ANDRO-AGENT v3                           ║
  ║   Memory │ GDrive │ Skills │ Security           ║
  ╚══════════════════════════════════════════════════╝\033[0m"""

C={"r":"\033[0m","g":"\033[1;32m","c":"\033[1;36m","y":"\033[1;33m",
   "re":"\033[1;31m","gr":"\033[0;90m","w":"\033[1;37m","p":"\033[1;35m"}
def c(k,t): return f"{C.get(k,'')}{t}{C['r']}"

def sh(cmd,timeout=20):
    try:
        r=subprocess.run(cmd,shell=True,capture_output=True,text=True,timeout=timeout)
        return (r.stdout+r.stderr).strip()
    except: return ""

def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f: return json.load(f)
    return {}

def save_config(cfg):
    with open(CONFIG_FILE,"w") as f: json.dump(cfg,f,indent=2)

def get_sysinfo():
    try:
        import psutil
        cpu=psutil.cpu_percent(interval=0.3); vm=psutil.virtual_memory()
        return {"cpu":f"{cpu}%","ram":f"{round(vm.used/1024**2)}MB/{round(vm.total/1024**2)}MB",
                "time":datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    except: return {"time":datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

def call_claude(api_key, messages, user_context=""):
    cfg = load_config()
    base = cfg.get("api_base_url","https://api.anthropic.com/v1")
    model = cfg.get("api_model","claude-haiku-4-5")
    key = cfg.get("claude_api_key", api_key)

    # Buat system prompt dengan konteks user
    sys_prompt = SYSTEM_PROMPT
    if user_context:
        sys_prompt += f"\n\n## Konteks User:\n{user_context}"

    # Trim messages - max 10 pesan, max 1500 char per pesan
    msgs = messages[-10:] if len(messages)>10 else messages
    clean = []
    for m in msgs:
        ct = str(m.get("content",""))
        # Filter karakter yang bermasalah
        ct = ct.encode('utf-8','ignore').decode('utf-8')[:1500]
        clean.append({"role":m["role"],"content":ct})

    try:
        if "anthropic.com" in base:
            r=requests.post(f"{base}/messages",
                headers={"x-api-key":key,"anthropic-version":"2023-06-01","content-type":"application/json"},
                json={"model":model,"max_tokens":800,"system":sys_prompt,"messages":clean},
                timeout=30)
        else:
            # OpenAI-compatible (koboillm, litellm, openrouter)
            all_msgs=[{"role":"system","content":sys_prompt}]+clean
            r=requests.post(f"{base}/chat/completions",
                headers={"Authorization":f"Bearer {key}","content-type":"application/json"},
                json={"model":model,"max_tokens":800,"messages":all_msgs},
                timeout=30)
        r.raise_for_status()
        data=r.json()
        if "content" in data: return data["content"][0]["text"]
        return data["choices"][0]["message"]["content"]
    except requests.exceptions.HTTPError as e:
        if "400" in str(e):
            # Retry dengan 1 pesan saja
            try:
                last_msg=clean[-1]["content"] if clean else "halo"
                msgs_retry=[{"role":"user","content":last_msg}]
                if "anthropic.com" in base:
                    r2=requests.post(f"{base}/messages",
                        headers={"x-api-key":key,"anthropic-version":"2023-06-01","content-type":"application/json"},
                        json={"model":model,"max_tokens":800,"system":sys_prompt,"messages":msgs_retry},
                        timeout=30)
                else:
                    r2=requests.post(f"{base}/chat/completions",
                        headers={"Authorization":f"Bearer {key}","content-type":"application/json"},
                        json={"model":model,"max_tokens":800,"messages":[{"role":"system","content":sys_prompt}]+msgs_retry},
                        timeout=30)
                r2.raise_for_status()
                data=r2.json()
                if "content" in data: return data["content"][0]["text"]
                return data["choices"][0]["message"]["content"]
            except Exception as e2: return f"❌ Error: {e2}"
        return f"❌ API Error: {e}"
    except Exception as e: return f"❌ Error: {e}"

SYSTEM_PROMPT="""Kamu adalah Andro-Agent v3, asisten AI dan Android Security Guardian yang berjalan di Android via Termux.

Keahlian utama:
1. Android Security Expert — attack vectors, hardening, forensics
2. System Health Analyst — diagnose device, performance, security
3. Skill Manager — kelola dan jalankan skill/plugin
4. Memory Manager — ingat fakta penting tentang user
5. General Assistant — coding, pertanyaan umum, analisis

Tool use — balas HANYA dengan JSON saat pakai tool:
{"tool":"shell","cmd":"perintah"}
{"tool":"security_scan"}
{"tool":"security_harden"}
{"tool":"security_action","action_id":"nama_aksi"}
{"tool":"sysinfo"}
{"tool":"run_skill","skill_id":"nama_skill","params":{"query":"..."}}
{"tool":"remember","fact":"fakta penting tentang user","category":"kategori"}
{"tool":"read_file","path":"/path"}
{"tool":"write_file","path":"/path","content":"isi"}

Aturan:
- Jawab singkat dan padat (mobile device)
- Gunakan Bahasa Indonesia kecuali user pakai bahasa lain
- Jika user menyebut nama atau info pribadi, gunakan tool remember
- Untuk pertanyaan keamanan: gunakan security tools
- Selalu jelaskan hasil dengan bahasa sederhana"""

def process_agent(api_key, user_input, history, sid, mem, skill_mgr=None):
    user_ctx = get_user_context(mem) if MEMORY_OK else ""
    messages = list(history) + [{"role":"user","content":user_input}]

    for _ in range(6):
        response = call_claude(api_key, messages, user_ctx)
        s = response.strip()

        if s.startswith("{") and s.endswith("}"):
            try:
                tc=json.loads(s); tool=tc.get("tool",""); result=""

                if tool=="shell":
                    result=f"[shell]\n{sh(tc.get('cmd',''))}"

                elif tool=="security_scan" and SECURITY_OK:
                    print(c("y","\n  🔍 Scanning...\n"))
                    rpt=full_health_scan()
                    with open(SCAN_FILE,"w") as f: json.dump(rpt,f,default=str)
                    print(format_report_terminal(rpt))
                    mem.setdefault("scan_history",[]).append(
                        {"time":datetime.now().isoformat(),"score":rpt.get("score"),"grade":rpt.get("grade")})
                    save_memory(mem)
                    result=f"[scan]\n{format_report_text(rpt)}"

                elif tool=="security_harden" and SECURITY_OK:
                    rpt=json.load(open(SCAN_FILE)) if Path(SCAN_FILE).exists() else full_health_scan()
                    results=run_auto_hardening(rpt); ok=sum(1 for r in results if r["success"])
                    for r in results: print(f"  {'✅' if r['success'] else '❌'} {r['name']}")
                    result=f"[harden] {ok}/{len(results)} berhasil"

                elif tool=="security_action" and SECURITY_OK:
                    aid=tc.get("action_id","")
                    ok,msg=run_hardening_action(aid)
                    result=f"[action] {'OK' if ok else 'FAIL'}: {msg}"

                elif tool=="sysinfo":
                    result=f"[sysinfo]\n{json.dumps(get_sysinfo(),indent=2)}"

                elif tool=="run_skill" and skill_mgr:
                    sid_sk=tc.get("skill_id","")
                    result=skill_mgr.run_skill(sid_sk, tc.get("params",{}))

                elif tool=="remember" and MEMORY_OK:
                    remember_fact(mem, tc.get("fact",""), tc.get("category","general"))
                    result="[remembered]"

                elif tool=="read_file":
                    p=Path(tc.get("path","")).expanduser()
                    result=p.read_text(errors="replace")[:2000] if p.exists() else "File not found"

                elif tool=="write_file":
                    p=Path(tc.get("path","")).expanduser()
                    p.parent.mkdir(parents=True,exist_ok=True); p.write_text(tc.get("content",""))
                    result=f"Written to {p}"

                else: result=f"Tool unavailable: {tool}"

                messages.append({"role":"assistant","content":response})
                messages.append({"role":"user","content":f"Tool result: {str(result)[:500]}"})
                continue
            except json.JSONDecodeError: pass

        add_history(mem,sid,"user",user_input)
        add_history(mem,sid,"assistant",response)
        return response

    return "⚠️ Selesai."

# ─── Telegram Bot ──────────────────────────────────────────────
class TelegramBot:
    def __init__(self,token,api_key,mem,skill_mgr,gdrive=None):
        self.token=token; self.api_key=api_key; self.mem=mem
        self.skill_mgr=skill_mgr; self.gdrive=gdrive
        self.base=f"https://api.telegram.org/bot{token}"; self.offset=0

    def send(self,cid,txt):
        for chunk in [txt[i:i+4000] for i in range(0,len(txt),4000)]:
            try: requests.post(f"{self.base}/sendMessage",
                json={"chat_id":cid,"text":chunk,"parse_mode":"Markdown"},timeout=10)
            except: pass

    def get_updates(self):
        try:
            r=requests.get(f"{self.base}/getUpdates",
                params={"offset":self.offset,"timeout":30},timeout=35)
            return r.json().get("result",[])
        except: return []

    def handle(self,upd):
        msg=upd.get("message") or upd.get("edited_message")
        if not msg: return
        cid=msg["chat"]["id"]; text=msg.get("text","").strip()
        uname=msg.get("from",{}).get("first_name","User")
        if not text: return

        # ── Commands ──
        if text=="/start":
            self.send(cid,
                f"🤖 *Andro-Agent v3*\n\nHalo {uname}!\n\n"
                f"*Security:*\n`/scan` `/harden` `/sysinfo`\n\n"
                f"*Skills:*\n`/skill list` `/skill install <id>`\n`/skill run <id>`\n\n"
                f"*Memory:*\n`/memory` `/memory note <teks>`\n`/memory backup`\n\n"
                f"*Shell:*\n`/shell <cmd>`\n\n"
                f"Atau chat biasa dengan AI! 🚀")
            return

        if text=="/scan":
            self.send(cid,"🔍 _Scanning... ~30 detik..._")
            try:
                rpt=full_health_scan()
                with open(SCAN_FILE,"w") as f: json.dump(rpt,f,default=str)
                self.mem.setdefault("scan_history",[]).append(
                    {"time":datetime.now().isoformat(),"score":rpt.get("score"),"grade":rpt.get("grade")})
                save_memory(self.mem)
                self.send(cid,format_report_text(rpt))
            except Exception as e: self.send(cid,f"❌ {e}")
            return

        if text=="/harden":
            self.send(cid,"🛡️ _Hardening..._")
            try:
                rpt=json.load(open(SCAN_FILE)) if Path(SCAN_FILE).exists() else full_health_scan()
                results=run_auto_hardening(rpt); ok=sum(1 for r in results if r["success"])
                lines=[f"🛡️ *Hardening: {ok}/{len(results)} berhasil*\n"]
                for r in results: lines.append(f"{'✅' if r['success'] else '❌'} {r['name']}")
                lines.append("\n_/scan untuk cek perubahan_")
                self.send(cid,"\n".join(lines))
            except Exception as e: self.send(cid,f"❌ {e}")
            return

        if text=="/sysinfo":
            info=get_sysinfo()
            self.send(cid,"📊 *System*\n```\n"+"\n".join(f"{k}: {v}" for k,v in info.items())+"\n```")
            return

        if text.startswith("/skill"):
            self.send(cid,handle_skill_command(text,self.skill_mgr))
            return

        if text.startswith("/memory"):
            if "/memory backup" in text:
                if self.gdrive and self.gdrive.is_configured():
                    self.send(cid,"💾 _Backup ke GDrive..._")
                    ok,msg=self.gdrive.backup_now(self.mem)
                    if ok:
                        self.mem["last_backup"]=datetime.now().isoformat()
                        save_memory(self.mem)
                    self.send(cid,f"{'✅' if ok else '❌'} {msg}")
                else:
                    self.send(cid,"❌ GDrive belum dikonfigurasi.\nSetup di Termux: pilih menu [6] Setup GDrive")
                return
            if "/memory restore" in text:
                if self.gdrive and self.gdrive.is_configured():
                    self.send(cid,"📥 _Restore dari GDrive..._")
                    ok,msg=self.gdrive.restore_from_drive()
                    if ok: self.mem.update(load_memory())
                    self.send(cid,f"{'✅' if ok else '❌'} {msg}")
                else:
                    self.send(cid,"❌ GDrive belum dikonfigurasi.")
                return
            self.send(cid,handle_memory_command(text,self.mem))
            return

        if text=="/clear":
            self.mem["conversations"].pop(str(cid),None); save_memory(self.mem)
            self.send(cid,"🗑️ Histori dihapus!")
            return

        if text.startswith("/shell "):
            self.send(cid,f"⚙️ `{text[7:]}`\n```\n{sh(text[7:])[:3000]}\n```")
            return

        # Cek auto-skill trigger
        if self.skill_mgr:
            installed=self.skill_mgr.list_installed()
            from memory_skill import SKILL_REGISTRY
            for sid_sk in installed:
                skill=SKILL_REGISTRY.get(sid_sk,{})
                triggers=skill.get("trigger",[])
                if any(t.lower() in text.lower() for t in triggers):
                    self.send(cid,f"⚡ _Auto-skill: {skill.get('name','')}_")
                    result=self.skill_mgr.run_skill(sid_sk,{"query":text,"city":text,"coin":text})
                    self.send(cid,result)
                    return

        # AI chat
        self.send(cid,"⏳ _Memproses..._")
        hist=get_history(self.mem,cid)
        resp=process_agent(self.api_key,text,hist,cid,self.mem,self.skill_mgr)
        self.send(cid,resp)

    def run(self):
        print(c("g","  ✅ Telegram Bot v3 aktif..."))
        while True:
            try:
                for upd in self.get_updates():
                    self.offset=upd["update_id"]+1
                    threading.Thread(target=self.handle,args=(upd,),daemon=True).start()
            except Exception as e:
                print(c("re",f"  Telegram err: {e}")); time.sleep(5)

# ─── Setup ─────────────────────────────────────────────────────
def setup():
    print(BANNER); print()
    cfg=load_config()
    print(c("c","\n  ⚙️  SETUP v3\n"))

    print(c("c","  [1/5] Base URL API"))
    print(c("gr","  Default Anthropic: https://api.anthropic.com/v1"))
    print(c("gr","  KoboillM: https://lite.koboillm.com/v1"))
    url=input(c("w","  Base URL: ")).strip()
    if url: cfg["api_base_url"]=url

    print(c("c","\n  [2/5] Model"))
    print(c("gr","  Contoh: gemini/gemini-2.5-flash | claude-haiku-4-5 | gpt-4o-mini"))
    model=input(c("w","  Model: ")).strip()
    if model: cfg["api_model"]=model

    print(c("c","\n  [3/5] API Key"))
    key=input(c("w","  API Key: ")).strip()
    if key: cfg["claude_api_key"]=key

    print(c("c","\n  [4/5] Telegram Bot Token (@BotFather)"))
    tg=input(c("w","  Token: ")).strip()
    if tg: cfg["telegram_token"]=tg

    print(c("c","\n  [5/5] Setup GDrive Backup? (y/n)"))
    if input(c("w","  Setup GDrive: ")).strip().lower()=="y":
        if _ms:
            gdrive_cfg=_ms.setup_gdrive_interactive()
            cfg.update(gdrive_cfg)

    save_config(cfg)
    print(c("g","\n  ✅ Tersimpan!\n"))
    return cfg

def main():
    print(BANNER)
    cfg=load_config()
    if not cfg.get("claude_api_key"): cfg=setup()

    api_key=cfg.get("claude_api_key","")
    mem=load_memory()
    skill_mgr=SkillManager(mem) if MEMORY_OK else None

    # Setup GDrive backup
    gdrive=None
    if cfg.get("gdrive_configured") and _ms:
        gdrive=GDriveBackup(cfg)
        gdrive.start_auto_backup(load_memory)

    while True:
        print(c("c","\n  ╔══════════════════════════════════════════╗"))
        print(c("c","  ║   ANDRO-AGENT v3 — Memory+Skills+Guard  ║"))
        print(c("c","  ╚══════════════════════════════════════════╝"))
        print(c("w","  [1] 💬 Chat CLI"))
        print(c("re","  [2] 🛡️  Security Guardian"))
        print(c("b","  [3] 🤖 Telegram Bot"))
        print(c("g","  [4] 📱 WhatsApp (Fonnte)"))
        print(c("p","  [5] 🚀 All-in-One"))
        print(c("y","  [6] 📦 Skill Manager"))
        print(c("y","  [7] 🧠 Memory & GDrive"))
        print(c("gr","  [8] ⚙️  Setup Ulang"))
        print(c("gr","  [0] Keluar"))
        ch=input(c("g","\n  Pilihan: ")).strip(); print()

        if ch=="0": sys.exit(0)

        elif ch=="1":
            print(c("c","\n  💬 Chat — ketik 'exit' untuk keluar\n"))
            sid="cli"
            while True:
                try: inp=input(c("g","  You: ")).strip()
                except(EOFError,KeyboardInterrupt): print(); break
                if not inp: continue
                if inp.lower() in["exit","quit"]: break
                if inp.lower()=="clear":
                    mem["conversations"].pop(sid,None); save_memory(mem)
                    print(c("gr","  [Histori dihapus]\n")); continue
                print(c("gr","  Agent: "),end="",flush=True)
                print(c("w",process_agent(api_key,inp,get_history(mem,sid),sid,mem,skill_mgr))); print()

        elif ch=="2":
            if SECURITY_OK:
                # Security menu inline
                while True:
                    print(c("re","\n  🛡️  SECURITY GUARDIAN"))
                    print(c("y","  [1] Full Scan  [2] Auto-Harden  [3] Aksi Manual  [0] Kembali"))
                    sc=input(c("g","  Pilihan: ")).strip()
                    if sc=="0": break
                    elif sc=="1":
                        print(c("y","  🔍 Scanning..."))
                        rpt=full_health_scan()
                        with open(SCAN_FILE,"w") as f: json.dump(rpt,f,default=str)
                        print(format_report_terminal(rpt))
                    elif sc=="2":
                        rpt=json.load(open(SCAN_FILE)) if Path(SCAN_FILE).exists() else full_health_scan()
                        results=run_auto_hardening(rpt); ok=sum(1 for r in results if r["success"])
                        for r in results: print(f"  {'✅' if r['success'] else '❌'} {r['name']}")
                        print(c("g",f"\n  ✅ {ok}/{len(results)} berhasil"))
            else: print(c("re","  ❌ security_module.py tidak ada!"))

        elif ch=="3":
            tok=cfg.get("telegram_token") or input(c("y","  Token: ")).strip()
            cfg["telegram_token"]=tok; save_config(cfg)
            try: TelegramBot(tok,api_key,mem,skill_mgr,gdrive).run()
            except KeyboardInterrupt: print(c("y","\n  Stopped."))

        elif ch=="5":
            if cfg.get("telegram_token"):
                threading.Thread(
                    target=TelegramBot(cfg["telegram_token"],api_key,mem,skill_mgr,gdrive).run,
                    daemon=True).start()
            print(c("g","  ✅ Running. Masuk CLI...\n")); time.sleep(1)
            # CLI
            sid="cli_all"
            while True:
                try: inp=input(c("g","  You: ")).strip()
                except(EOFError,KeyboardInterrupt): print(); break
                if not inp or inp.lower() in["exit","quit"]: break
                print(c("gr","  Agent: "),end="",flush=True)
                print(c("w",process_agent(api_key,inp,get_history(mem,sid),sid,mem,skill_mgr))); print()

        elif ch=="6":
            if skill_mgr:
                print(c("p","\n  🧩 SKILL MANAGER"))
                print(skill_mgr.format_skill_list())
                print(c("gr","\n  Perintah: install <id> | remove <id> | run <id>"))
                cmd=input(c("g","  > ")).strip()
                if cmd:
                    print(handle_skill_command("/skill "+cmd, skill_mgr))
            else: print(c("re","  ❌ memory_skill.py tidak ada!"))

        elif ch=="7":
            if MEMORY_OK:
                facts=len(mem.get("learned_facts",[]))
                convs=len(mem.get("conversations",{}))
                last=mem.get("last_backup","Belum pernah")
                print(c("c",f"\n  🧠 Memory: {convs} sesi | {facts} fakta | Backup: {last[:16] if last and last!='Belum pernah' else 'Belum pernah'}"))
                print(c("y","  [1] Backup GDrive  [2] Restore  [3] Lihat catatan  [0] Kembali"))
                mc=input(c("g","  Pilihan: ")).strip()
                if mc=="1" and gdrive:
                    ok,msg=gdrive.backup_now(mem)
                    if ok: mem["last_backup"]=datetime.now().isoformat(); save_memory(mem)
                    print(c("g" if ok else "re",f"  {'✅' if ok else '❌'} {msg}"))
                elif mc=="2" and gdrive:
                    ok,msg=gdrive.restore_from_drive()
                    if ok: mem.update(load_memory())
                    print(c("g" if ok else "re",f"  {'✅' if ok else '❌'} {msg}"))
                elif mc=="3":
                    notes=mem.get("user_profile",{}).get("notes",[])
                    for n in notes[-10:]: print(c("w",f"  • {n['text']}"))
            else: print(c("re","  ❌ memory_skill.py tidak ada!"))

        elif ch=="8": cfg=setup(); api_key=cfg.get("claude_api_key","")

if __name__=="__main__":
    try: main()
    except KeyboardInterrupt: print(c("y","\n\n  Bye! 👋\n"))
