#!/usr/bin/env bash
#
# Installe le bot Telegram + le serveur Flask (pages idtlg_<id>.html + QR)
# comme deux services systemd sur un VPS Ubuntu, avec nginx + HTTPS en option.
#
#   sudo ./install.sh
#
# À lancer depuis le dossier qui contient app.py, bot.py, templates/, requirements.txt.
set -euo pipefail

# ── Réglages (surchageables : APP_DIR=/srv/idtlg sudo -E ./install.sh) ──────
APP_USER="${APP_USER:-idtlg}"          # utilisateur système dédié
APP_DIR="${APP_DIR:-/opt/idtlg}"       # où l'appli est installée
PORT="${PORT:-5000}"                   # port interne de gunicorn
# ────────────────────────────────────────────────────────────────────────────

if [[ $EUID -ne 0 ]]; then
  echo "Ce script doit être lancé avec sudo/root." >&2
  exit 1
fi

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Si page.html a été téléchargé "à plat" (sans le dossier templates/), on le range.
if [[ ! -e "$SRC_DIR/templates/page.html" && -e "$SRC_DIR/page.html" ]]; then
  echo "-> page.html trouvé à plat : création de templates/ et rangement."
  mkdir -p "$SRC_DIR/templates"
  mv "$SRC_DIR/page.html" "$SRC_DIR/templates/page.html"
fi

for f in app.py bot.py requirements.txt templates/page.html; do
  if [[ ! -e "$SRC_DIR/$f" ]]; then
    echo "Fichier manquant à côté du script : $f" >&2
    echo "Le dossier doit contenir : app.py  bot.py  requirements.txt  et  templates/page.html (ou page.html)." >&2
    exit 1
  fi
done

# ── Questions ───────────────────────────────────────────────────────────────
read -rp "Token du bot Telegram (BotFather) : " BOT_TOKEN
[[ -z "$BOT_TOKEN" ]] && { echo "Token requis." >&2; exit 1; }

read -rp "Nom de domaine pointant vers ce VPS (vide = HTTP sur l'IP, test only) : " DOMAIN

if [[ -n "$DOMAIN" ]]; then
  PUBLIC_BASE_URL="https://$DOMAIN"
else
  IP="$(curl -s https://api.ipify.org || echo "IP_DU_VPS")"
  PUBLIC_BASE_URL="http://$IP:$PORT"
fi
echo "-> URL publique (encodée dans le QR) : $PUBLIC_BASE_URL"

# ── Paquets système ─────────────────────────────────────────────────────────
echo "== Installation des paquets système =="
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip curl
[[ -n "$DOMAIN" ]] && apt-get install -y -qq nginx

# ── Utilisateur + fichiers ──────────────────────────────────────────────────
echo "== Préparation de $APP_DIR =="
id -u "$APP_USER" &>/dev/null || adduser --system --group --no-create-home "$APP_USER"
mkdir -p "$APP_DIR"
cp -r "$SRC_DIR/app.py" "$SRC_DIR/bot.py" "$SRC_DIR/requirements.txt" "$SRC_DIR/templates" "$APP_DIR/"
mkdir -p "$APP_DIR/pages" "$APP_DIR/qrcodes"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

# ── Environnement virtuel Python ────────────────────────────────────────────
echo "== Environnement Python =="
sudo -u "$APP_USER" python3 -m venv "$APP_DIR/venv"
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install -q --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/requirements.txt" gunicorn

# ── Service Flask (web) ─────────────────────────────────────────────────────
echo "== Service systemd : idtlg-web =="
cat > /etc/systemd/system/idtlg-web.service <<EOF
[Unit]
Description=idtlg - serveur Flask (pages de validation)
After=network.target

[Service]
User=$APP_USER
WorkingDirectory=$APP_DIR
Environment=PUBLIC_BASE_URL=$PUBLIC_BASE_URL
ExecStart=$APP_DIR/venv/bin/gunicorn -w 2 -b 127.0.0.1:$PORT app:app
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# ── Service bot Telegram ────────────────────────────────────────────────────
echo "== Service systemd : idtlg-bot =="
cat > /etc/systemd/system/idtlg-bot.service <<EOF
[Unit]
Description=idtlg - bot Telegram
After=network.target idtlg-web.service

[Service]
User=$APP_USER
WorkingDirectory=$APP_DIR
Environment=BOT_TOKEN=$BOT_TOKEN
Environment=FLASK_API_URL=http://127.0.0.1:$PORT/api/generate
ExecStart=$APP_DIR/venv/bin/python bot.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now idtlg-web idtlg-bot

# ── nginx + HTTPS (si domaine) ──────────────────────────────────────────────
if [[ -n "$DOMAIN" ]]; then
  echo "== nginx + HTTPS pour $DOMAIN =="
  cat > /etc/nginx/sites-available/idtlg <<EOF
server {
    listen 80;
    server_name $DOMAIN;
    location / {
        proxy_pass http://127.0.0.1:$PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
}
EOF
  ln -sf /etc/nginx/sites-available/idtlg /etc/nginx/sites-enabled/idtlg
  rm -f /etc/nginx/sites-enabled/default
  nginx -t && systemctl reload nginx

  echo "== Certificat Let's Encrypt =="
  apt-get install -y -qq certbot python3-certbot-nginx
  if certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos \
       -m "admin@$DOMAIN" --redirect; then
    echo "HTTPS activé."
  else
    echo "!! certbot a échoué (DNS pas encore propagé ?). Relance plus tard :"
    echo "   sudo certbot --nginx -d $DOMAIN --redirect"
  fi
fi

# ── Résumé ──────────────────────────────────────────────────────────────────
cat <<EOF

============================================================
Installation terminée.

  URL publique   : $PUBLIC_BASE_URL
  Dossier appli  : $APP_DIR
  Pages générées : $APP_DIR/pages/
  QR codes       : $APP_DIR/qrcodes/

Commandes utiles :
  systemctl status idtlg-web idtlg-bot
  journalctl -u idtlg-bot -f      # logs du bot
  journalctl -u idtlg-web -f      # logs du serveur

Va sur Telegram, envoie /start à ton bot pour tester.
============================================================
EOF
