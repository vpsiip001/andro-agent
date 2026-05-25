#!/usr/bin/env python3
import subprocess,json,os,time,re
from datetime import datetime
from pathlib import Path

def c(col,txt):
    codes={"red":"\033[1;31m","green":"\033[1;32m","yellow":"\033[1;33m",
           "cyan":"\033[1;36m","white":"\033[1;37m","gray":"\033[0;90m",
           "purple":"\033[1;35m","blue":"\033[1;34m","orange":"\033[38;5;214m"}
    return f"{codes.get(col,'')}{txt}\033[0m"

def sh(cmd,timeout=20):
    try:
        r=subprocess.run(cmd,shell=True,capture_output=True,text=True,timeout=timeout)
        return (r.stdout+r.stderr).strip()
    except subprocess.TimeoutExpired: return "__TIMEOUT__"
    except Exception as e: return f"__ERR__:{e}"

def sh_ok(cmd,timeout=10):
    try:
        r=subprocess.run(cmd,shell=True,capture_output=True,timeout=timeout)
        return r.returncode==0
    except: return False

def is_rooted():
    checks=[sh_ok("which su"),sh_ok("ls /system/bin/su"),sh_ok("ls /system/xbin/su"),
            sh_ok("ls /sbin/su"),sh_ok("ls /data/local/bin/su"),
            Path("/system/app/Superuser.apk").exists(),
            "test-keys" in sh("getprop ro.build.tags")]
    return any(checks)

def check_adb_enabled():
    out=sh("getprop persist.service.adb.enable")
    if "1" in out: return True
    return "1" in sh("settings get global adb_enabled 2>/dev/null")

def check_developer_options():
    return "1" in sh("settings get global development_settings_enabled 2>/dev/null")

def check_unknown_sources():
    if "1" in sh("settings get secure install_non_market_apps 2>/dev/null"): return True
    return "1" in sh("settings get global install_packages_from_unknown_sources 2>/dev/null")

def check_screen_lock():
    out=sh("settings get secure lockscreen.password_type 2>/dev/null")
    try: return int(out.strip())>0
    except: return False

def check_encryption():
    return sh("getprop ro.crypto.state").strip().lower()=="encrypted"

def check_selinux():
    out=sh("getenforce 2>/dev/null")
    if not out or "__ERR__" in out:
        out=sh("cat /sys/fs/selinux/enforce 2>/dev/null")
    return out.strip().lower()

def check_open_ports():
    out=sh("ss -tulnp 2>/dev/null || netstat -tulnp 2>/dev/null")
    ports=[]
    for line in out.splitlines():
        if "LISTEN" in line or "0.0.0.0" in line:
            for p in line.split():
                if ":" in p:
                    port=p.split(":")[-1]
                    if port.isdigit() and int(port)>0:
                        ports.append(port)
    return list(set(ports))

def check_suspicious_apps():
    SUSPICIOUS=["spyware","keylogger","stalkerware","monitor","trackme",
                "flexispy","mspy","nethunter","tcpdump","interceptor","sslstrip"]
    out=sh("pm list packages 2>/dev/null | sed 's/package://'")
    found=[]
    for pkg in out.lower().splitlines():
        for kw in SUSPICIOUS:
            if kw in pkg: found.append(pkg.strip())
    return found

def check_wifi_security():
    out=sh("termux-wifi-connectioninfo 2>/dev/null")
    try:
        info=json.loads(out)
        return {"ssid":info.get("ssid","?"),"security":info.get("security_type","?"),
                "ip":info.get("ip","?")}
    except: return {"ssid":"Unknown","security":"N/A","ip":"N/A"}

def check_battery():
    out=sh("termux-battery-status 2>/dev/null")
    try: return json.loads(out)
    except:
        pct=sh("cat /sys/class/power_supply/battery/capacity 2>/dev/null")
        return {"percentage":pct or "?","status":"unknown"}

def check_storage():
    out=sh("df -h / 2>/dev/null")
    result={}
    for line in out.splitlines()[1:]:
        parts=line.split()
        if len(parts)>=5:
            mp=parts[5] if len(parts)>5 else parts[0]
            result[mp]={"size":parts[1],"used":parts[2],"free":parts[3],"use%":parts[4]}
    return result

def check_android_version():
    return {"version":sh("getprop ro.build.version.release"),
            "sdk":sh("getprop ro.build.version.sdk"),
            "security_patch":sh("getprop ro.build.version.security_patch"),
            "model":sh("getprop ro.product.model"),
            "brand":sh("getprop ro.product.brand"),
            "build":sh("getprop ro.build.tags")}

def full_health_scan():
    report={"timestamp":datetime.now().isoformat(),"checks":[],
            "score":0,"max_score":0,"risks":[],"recommendations":[]}
    checks=[]
    av=check_android_version()
    report["device"]=av
    try:
        sdk=int(av.get("sdk","0"))
        if sdk>=33: checks.append(("Android Version",True,f"Android {av['version']} (API {sdk})","Up to date"))
        elif sdk>=29: checks.append(("Android Version",True,f"Android {av['version']} (API {sdk})","Acceptable"))
        else: checks.append(("Android Version",False,f"Android {av['version']} (API {sdk})","Outdated!"))
    except: checks.append(("Android Version",None,av.get("version","?"),"Unknown"))

    rooted=is_rooted()
    checks.append(("Root Access",not rooted,"Rooted" if rooted else "Not rooted",
                   "⚠️ Root bypasses all sandboxes!" if rooted else "✅ Safe"))
    if rooted:
        report["risks"].append("CRITICAL: Device is rooted")
        report["recommendations"].append("Consider unrooting if not intentional")

    adb=check_adb_enabled()
    checks.append(("USB Debugging (ADB)",not adb,"ENABLED" if adb else "Disabled",
                   "⚠️ ADB = full device control via USB!" if adb else "✅ Safe"))
    if adb:
        report["risks"].append("HIGH: ADB (USB Debugging) is enabled")
        report["recommendations"].append("Settings → Developer Options → USB Debugging → OFF")

    dev=check_developer_options()
    checks.append(("Developer Options",not dev,"ENABLED" if dev else "Disabled",
                   "Consider disabling" if dev else "✅ Safe"))
    if dev:
        report["risks"].append("MEDIUM: Developer Options enabled")
        report["recommendations"].append("Disable Developer Options when not in use")

    unk=check_unknown_sources()
    checks.append(("Unknown Sources",not unk,"ALLOWED" if unk else "Blocked",
                   "⚠️ Any APK can be installed!" if unk else "✅ Safe"))
    if unk:
        report["risks"].append("HIGH: Unknown sources allowed")
        report["recommendations"].append("Settings → Security → Unknown sources → OFF")

    lock=check_screen_lock()
    checks.append(("Screen Lock",lock,"Configured" if lock else "NOT SET",
                   "✅ Active" if lock else "⚠️ No lock = full physical access!"))
    if not lock:
        report["risks"].append("CRITICAL: No screen lock")
        report["recommendations"].append("Settings → Security → Screen lock → Set PIN/Password")

    enc=check_encryption()
    checks.append(("Storage Encryption",enc,"Encrypted" if enc else "NOT Encrypted",
                   "✅ Encrypted" if enc else "⚠️ Data readable if stolen!"))
    if not enc:
        report["risks"].append("HIGH: Storage not encrypted")
        report["recommendations"].append("Settings → Security → Encrypt phone")

    sel=check_selinux()
    enforcing=sel in["enforcing","1"]
    checks.append(("SELinux",enforcing,sel.capitalize() or "Unknown",
                   "✅ Enforcing" if enforcing else f"⚠️ {sel} — less protection"))
    if not enforcing:
        report["risks"].append("MEDIUM: SELinux not enforcing")

    ports=check_open_ports()
    dangerous=[p for p in ports if p in["22","23","80","8080","3306","6379","27017"]]
    checks.append(("Open Ports",len(dangerous)==0,
                   f"{len(ports)} open ({','.join(ports[:6]) if ports else 'none'})",
                   f"⚠️ Risky: {','.join(dangerous)}" if dangerous else "✅ OK"))
    if dangerous:
        report["risks"].append(f"MEDIUM: Dangerous ports open: {','.join(dangerous)}")
        report["recommendations"].append(f"Close services on ports: {','.join(dangerous)}")

    sus=check_suspicious_apps()
    checks.append(("Suspicious Apps",len(sus)==0,
                   f"{len(sus)} found" if sus else "None detected",
                   f"⚠️ Found: {','.join(sus)}" if sus else "✅ Clean"))
    if sus:
        report["risks"].append(f"HIGH: Suspicious apps: {','.join(sus)}")
        report["recommendations"].append(f"Remove: {','.join(sus)}")

    wifi=check_wifi_security()
    sec=wifi.get("security","").upper()
    wifi_safe="WPA3" in sec or "WPA2" in sec
    checks.append(("WiFi Security",wifi_safe if sec!="N/A" else None,
                   f"SSID:{wifi.get('ssid','?')} Sec:{sec}",
                   "✅ Secure" if wifi_safe else "⚠️ Weak/open WiFi!"))
    if not wifi_safe and sec not in["N/A","UNKNOWN",""]:
        report["risks"].append("MEDIUM: Insecure WiFi connection")
        report["recommendations"].append("Use WPA2/WPA3 networks only")

    patch=av.get("security_patch","")
    try:
        pd=datetime.strptime(patch,"%Y-%m-%d")
        months=(datetime.now()-pd).days//30
        ok=months<=6
        checks.append(("Security Patch",ok,f"{patch} ({months}mo ago)",
                       "✅ Recent" if ok else f"⚠️ {months} months old!"))
        if not ok:
            report["risks"].append(f"HIGH: Security patch {months} months old")
            report["recommendations"].append("Settings → About → System update")
    except: checks.append(("Security Patch",None,patch or "Unknown","Cannot parse"))

    score=sum(10 for n,r,v,d in checks if r is True)
    max_score=sum(10 for n,r,v,d in checks if r is not None)
    report["checks"]=checks
    report["score"]=score
    report["max_score"]=max_score
    report["grade"]=_grade(score,max_score)
    report["battery"]=check_battery()
    report["storage"]=check_storage()
    return report

def _grade(s,m):
    if m==0: return "?"
    p=(s/m)*100
    if p>=90: return "A — Excellent 🛡️"
    if p>=75: return "B — Good ✅"
    if p>=60: return "C — Fair ⚠️"
    if p>=40: return "D — Poor 🔴"
    return "F — Critical ☠️"

HARDENING_ACTIONS={
    "disable_adb":{"name":"Disable ADB","risk":"HIGH",
        "cmd":"settings put global adb_enabled 0",
        "desc":"Cegah akses penuh via USB kabel"},
    "disable_dev_options":{"name":"Disable Developer Options","risk":"MEDIUM",
        "cmd":"settings put global development_settings_enabled 0",
        "desc":"Sembunyikan opsi developer"},
    "disable_unknown_sources":{"name":"Block Unknown Sources","risk":"HIGH",
        "cmd":"settings put secure install_non_market_apps 0 && settings put global install_packages_from_unknown_sources 0",
        "desc":"Blokir instalasi APK luar Play Store"},
    "enable_selinux":{"name":"SELinux Enforcing","risk":"MEDIUM",
        "cmd":"setenforce 1",
        "desc":"Aktifkan SELinux enforcing"},
    "harden_dns":{"name":"DNS-over-TLS Cloudflare","risk":"MEDIUM",
        "cmd":"settings put global private_dns_mode hostname && settings put global private_dns_specifier one.one.one.one",
        "desc":"Cegah DNS hijacking pakai 1.1.1.1"},
    "disable_wifi_scan":{"name":"Disable WiFi Background Scan","risk":"LOW",
        "cmd":"settings put global wifi_scan_always_enabled 0",
        "desc":"Cegah pelacakan lokasi via WiFi scan"},
    "enable_mac_randomization":{"name":"Enable MAC Randomization","risk":"MEDIUM",
        "cmd":"settings put global wifi_enhanced_mac_randomization_enabled 1",
        "desc":"Acak MAC address di setiap jaringan WiFi"},
    "set_screen_timeout":{"name":"Screen Timeout 60s","risk":"LOW",
        "cmd":"settings put system screen_off_timeout 60000",
        "desc":"Layar kunci otomatis setelah 60 detik"},
    "disable_mock_location":{"name":"Disable Mock Location","risk":"LOW",
        "cmd":"settings put secure allow_mock_location 0",
        "desc":"Cegah pemalsuan GPS"},
    "restrict_bg_data":{"name":"Restrict Background Data","risk":"MEDIUM",
        "cmd":"settings put global restrict_background_data 1",
        "desc":"Batasi app kirim data di background"},
    "disable_nfc":{"name":"Disable NFC","risk":"LOW",
        "cmd":"svc nfc disable",
        "desc":"Matikan NFC jika tidak digunakan"},
    "disable_bluetooth":{"name":"Disable Bluetooth","risk":"LOW",
        "cmd":"svc bluetooth disable",
        "desc":"Matikan Bluetooth jika tidak digunakan"},
    "enable_play_protect":{"name":"Enable Play Protect","risk":"MEDIUM",
        "cmd":"settings put global package_verifier_enable 1 && settings put global verifier_verify_adb_installs 1",
        "desc":"Aktifkan verifikasi otomatis Google"},
    "clear_clipboard":{"name":"Clear Clipboard","risk":"LOW",
        "cmd":"termux-clipboard-set '' 2>/dev/null || true",
        "desc":"Hapus data clipboard sensitif"},
    "disable_usb_tether":{"name":"Disable USB Tethering","risk":"LOW",
        "cmd":"svc usb disable 2>/dev/null || true",
        "desc":"Matikan USB tethering"},
    "firewall_iptables":{"name":"Basic iptables Firewall","risk":"HIGH",
        "cmd":"iptables -F INPUT 2>/dev/null; iptables -P INPUT DROP 2>/dev/null; iptables -A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT 2>/dev/null; iptables -A INPUT -i lo -j ACCEPT 2>/dev/null; echo done",
        "desc":"DROP semua koneksi masuk (butuh root)"},
    "kill_suspicious":{"name":"Kill Suspicious Processes","risk":"MEDIUM",
        "cmd":"for pkg in $(pm list packages 2>/dev/null | sed 's/package://' | grep -E 'spy|monitor|stalk|keylog'); do am force-stop $pkg 2>/dev/null && echo Stopped:$pkg; done; echo done",
        "desc":"Paksa hentikan proses mencurigakan"},
}

def run_hardening_action(action_id):
    if action_id not in HARDENING_ACTIONS:
        return False,"Action tidak ditemukan"
    a=HARDENING_ACTIONS[action_id]
    result=sh(a["cmd"])
    if any(x in result for x in["Permission denied","not permitted","__ERR__"]):
        return False,f"Gagal: {result[:150]}"
    return True,result[:200] or "OK"

def run_auto_hardening(report):
    safe_actions=["set_screen_timeout","harden_dns","disable_wifi_scan",
                  "enable_mac_randomization","disable_mock_location","restrict_bg_data",
                  "clear_clipboard","enable_play_protect","disable_unknown_sources",
                  "disable_adb","disable_dev_options","kill_suspicious"]
    results=[]
    for aid in safe_actions:
        if aid not in HARDENING_ACTIONS: continue
        ok,msg=run_hardening_action(aid)
        results.append({"id":aid,"name":HARDENING_ACTIONS[aid]["name"],
                        "success":ok,"message":msg,"risk":HARDENING_ACTIONS[aid]["risk"]})
    return results

def format_report_terminal(report):
    lines=[""]
    lines.append(c("cyan","  ╔══════════════════════════════════════════════════╗"))
    lines.append(c("cyan","  ║     🛡️  ANDROID SECURITY HEALTH REPORT          ║"))
    lines.append(c("cyan","  ╚══════════════════════════════════════════════════╝"))
    dev=report.get("device",{})
    lines.append(c("gray",f"  📱 {dev.get('brand','?')} {dev.get('model','?')} | Android {dev.get('version','?')} | Patch: {dev.get('security_patch','?')}"))
    lines.append(c("gray",f"  🕒 Scan: {report.get('timestamp','')[:19]}"))
    lines.append("")
    score=report.get("score",0); ms=report.get("max_score",100)
    pct=int((score/ms)*100) if ms else 0
    grade=report.get("grade","?")
    filled=int((pct/100)*30)
    bc="green" if pct>=75 else ("yellow" if pct>=50 else "red")
    bar=c(bc,"█"*filled)+c("gray","░"*(30-filled))
    lines.append(c("white",f"  Security Score: ")+ f"[{bar}] {c(bc,str(pct)+'%')}  {c('white',grade)}")
    lines.append("")
    lines.append(c("cyan","  ─── SECURITY CHECKS ───────────────────────────────"))
    for name,result,val,detail in report.get("checks",[]):
        icon=c("green","  ✅") if result is True else (c("red","  ❌") if result is False else c("yellow","  ⚠️ "))
        lines.append(f"{icon} {c('white',f'{name:<28}')} {c('gray',val[:38])}")
        if result is False: lines.append(c("yellow",f"     └─ {detail}"))
    lines.append("")
    risks=report.get("risks",[])
    if risks:
        lines.append(c("red","  ⚠️  RISKS:"))
        for r in risks:
            lv="red" if "CRITICAL" in r or "HIGH" in r else "yellow"
            lines.append(c(lv,f"  • {r}"))
        lines.append("")
    recs=report.get("recommendations",[])
    if recs:
        lines.append(c("cyan","  💡 REKOMENDASI:"))
        for i,r in enumerate(recs,1):
            lines.append(c("white",f"  {i}. {r}"))
    bat=report.get("battery",{})
    lines.append(c("gray",f"\n  🔋 Battery: {bat.get('percentage','?')}%  Status: {bat.get('status','?')}"))
    for mp,info in list(report.get("storage",{}).items())[:1]:
        if isinstance(info,dict):
            lines.append(c("gray",f"  💾 Storage: {info.get('used','?')} used / {info.get('size','?')} total ({info.get('use%','?')})"))
    lines.append("")
    return "\n".join(lines)

def format_report_text(report):
    dev=report.get("device",{})
    score=report.get("score",0); ms=report.get("max_score",100)
    pct=int((score/ms)*100) if ms else 0
    lines=[f"🛡️ *ANDROID SECURITY REPORT*",
           f"📱 {dev.get('brand','?')} {dev.get('model','?')}",
           f"🤖 Android {dev.get('version','?')} | Patch: {dev.get('security_patch','?')}",
           f"","f🎯 *Score: {pct}% — {report.get('grade','?')}*","","*📋 CHECKS:*"]
    for name,result,val,detail in report.get("checks",[]):
        icon="✅" if result is True else ("❌" if result is False else "⚠️")
        lines.append(f"{icon} {name}: {val}")
    risks=report.get("risks",[])
    if risks:
        lines+=["","*⚠️ RISKS:*"]+[f"• {r}" for r in risks]
    recs=report.get("recommendations",[])
    if recs:
        lines+=["","*💡 REKOMENDASI:*"]+[f"{i}. {r}" for i,r in enumerate(recs,1)]
    bat=report.get("battery",{})
    lines+=["",f"🔋 Battery: {bat.get('percentage','?')}%"]
    return "\n".join(lines)

if __name__=="__main__":
    import sys
    if "--scan" in sys.argv:
        print(c("yellow","\n  🔍 Scanning..."))
        report=full_health_scan()
        print(format_report_terminal(report))
    elif "--harden" in sys.argv:
        print(c("yellow","\n  🔒 Hardening..."))
        report=full_health_scan()
        results=run_auto_hardening(report)
        ok=sum(1 for r in results if r["success"])
        for r in results:
            print(f"  {'✅' if r['success'] else '❌'} {r['name']}: {r['message'][:60]}")
        print(c("green",f"\n  Done: {ok}/{len(results)} succeeded"))
    else:
        print(c("cyan","\n  Security Module — commands: --scan  --harden\n"))
