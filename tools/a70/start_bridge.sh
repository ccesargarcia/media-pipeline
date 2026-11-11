#!/data/data/com.termux/files/usr/bin/bash
# Trava de suspensao do Android (impede CPU doze quando a tela apaga)
command -v termux-wake-lock >/dev/null && termux-wake-lock

# Garante SSH ativo
pgrep -x sshd >/dev/null || sshd

# Finaliza instâncias antigas
pkill -f microsocks || true
pkill -f socat || true
pkill -f monitor_a70_resources.py || true
pkill -f whatsapp_bot.py || true
sleep 1

# Inicia daemons desacoplados de TTY/pts
nohup microsocks -i 0.0.0.0 -p 1080 </dev/null > ~/microsocks.log 2>&1 & disown
nohup socat TCP-LISTEN:2121,fork,reuseaddr TCP:192.168.0.1:21 </dev/null > ~/socat_ftp.log 2>&1 & disown
nohup socat TCP-LISTEN:5555,fork,reuseaddr TCP:192.168.0.218:5555 </dev/null > ~/socat_firetv.log 2>&1 & disown
nohup python3 -u ~/whatsapp_bot.py </dev/null > ~/whatsapp_bot.log 2>&1 & disown
nohup python3 -u ~/monitor_a70_resources.py </dev/null > ~/monitor_a70_resources.log 2>&1 & disown

echo "Bridge, WhatsApp Bot & Kuma Resource Monitor started successfully with wake-lock!"
