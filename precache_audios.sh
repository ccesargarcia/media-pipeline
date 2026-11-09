#!/data/data/com.termux/files/usr/bin/bash
FTP_AUTH="admin:63274c0954"

encode_season_url() {
    local season="${1:-Segunda Temporada}"
    local encoded_season="${season// /%20}"
    echo "ftp://192.168.0.1:21/G/Series/Longe%20demais%20-%20${encoded_season}"
}

precache_one() {
    local stem="$1"
    local season="${2:-Segunda Temporada}"
    local ftp_url_base="$(encode_season_url "$season")"
    local tmp_mp4="$HOME/tmp_${stem}.mp4"
    local tmp_out="$HOME/${stem}.audio.m4a"

    echo "[$(date +%H:%M:%S)] [$season] 1/3 Lendo ${stem}.mp4 na rede local Wi-Fi..."
    local t0=$(date +%s)
    if nice -n 19 curl -sS --fail --ftp-pasv -u "$FTP_AUTH" "${ftp_url_base}/${stem}.mp4" -o "$tmp_mp4"; then
        echo "[$(date +%H:%M:%S)] [$season] 2/3 Separando faixa de audio (Stream Copy, sem recodificar)..."
        if nice -n 19 ffmpeg -hide_banner -loglevel error -y -i "$tmp_mp4" -vn -c:a copy "$tmp_out"; then
            rm -f "$tmp_mp4"
            local sz_mb=$(( $(stat -c%s "$tmp_out") / 1024 / 1024 ))
            echo "[$(date +%H:%M:%S)] [$season] 3/3 Salvando ${stem}.audio.m4a (${sz_mb} MB) no FTP..."
            if curl -sS --fail --ftp-pasv -u "$FTP_AUTH" -T "$tmp_out" "${ftp_url_base}/${stem}.audio.m4a"; then
                local t1=$(date +%s)
                rm -f "$tmp_out"
                echo "✅ [$(date +%H:%M:%S)] [$season] Pre-cache concluido em $((t1 - t0))s: ${stem}.audio.m4a (${sz_mb} MB) salvo no FTP!"
                return 0
            fi
        fi
    fi
    rm -f "$tmp_mp4" "$tmp_out"
    echo "❌ [$season] Falha ao gerar pre-cache de $stem"
    return 1
}

if [ -n "$1" ]; then
    precache_one "$1" "${2:-Segunda Temporada}"
    exit $?
fi

# Modo automatico: percorre Segunda Temporada, Terceira Temporada e Primeira Temporada
for SEASON in "Segunda Temporada" "Terceira Temporada" "Primeira Temporada"; do
    FTP_URL_BASE="$(encode_season_url "$SEASON")"
    LIST=$(curl -s --list-only -u "$FTP_AUTH" "${FTP_URL_BASE}/" 2>/dev/null | tr -d "\r")
    [ -z "$LIST" ] && continue
    for mp4 in $(echo "$LIST" | grep "^Uzak_Sehir_-_Episode_.*\.mp4$" | sort -V); do
        stem="${mp4%.mp4}"
        if ! echo "$LIST" | grep -qx "${stem}.pt-BR.srt"; then
            if ! echo "$LIST" | grep -qx "${stem}.audio.m4a"; then
                precache_one "$stem" "$SEASON"
            fi
        fi
    done
done
