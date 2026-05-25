cat > ~/andro-agent/friend_install.sh << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash
clear
echo ""
echo -e "\033[1;32m╔══════════════════════════════════════╗"
echo -e "║   🤖 IPOENK-AGENT — Auto Installer   ║"
echo -e "╚══════════════════════════════════════╝\033[0m"
echo ""
echo -e "\033[1;33m[1/4] Install packages...\033[0m"
pkg update -y -q 2>/dev/null || true
pkg install -y python git 2>/dev/null || true
pip install --quiet requests psutil 2>/dev/null || true
echo -e "\033[1;33m[2/4] Download Andro-Agent...\033[0m"
rm -rf ~/andro-agent 2>/dev/null || true
git clone "https://github.com/vpsiip001/andro-agent.git" ~/andro-agent
if [ ! -d ~/andro-agent ]; then
    echo -e "\033[1;31m❌ Gagal!\033[0m"; exit 1
fi
echo -e "\033[1;33m[3/4] Setup shortcut...\033[0m"
grep -q "alias agent=" ~/.bashrc 2>/dev/null && sed -i '/alias agent=/d' ~/.bashrc
echo "alias agent='cd ~/andro-agent && python agent_v3.py'" >> ~/.bashrc
echo -e "\033[1;32m╔══════════════════════════════════════╗"
echo -e "║      ✅ INSTALASI SELESAI!           ║"
echo -e "╚══════════════════════════════════════╝\033[0m"
echo ""
echo -e "\033[1;33mJalankan sekarang? (y/n): \033[0m\c"
read -r go
[[ "$go" == "y" ]] && cd ~/andro-agent && python agent_v3.py
EOF
