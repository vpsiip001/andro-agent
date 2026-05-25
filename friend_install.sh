#!/data/data/com.termux/files/usr/bin/bash
pkg update -y -q 2>/dev/null || true
pkg install -y python git 2>/dev/null || true
pip install --quiet requests psutil 2>/dev/null || true
rm -rf ~/andro-agent 2>/dev/null || true
git clone https://github.com/vpsiip001/andro-agent.git ~/andro-agent
echo "alias agent='cd ~/andro-agent && python agent_v3.py'" >> ~/.bashrc
echo "Selesai! Jalankan: cd ~/andro-agent && python agent_v3.py"
