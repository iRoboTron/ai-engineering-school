#!/usr/bin/env bash
# Учит контейнер сайта (CT 109) резолвить имена через DNS-over-HTTPS.
#
# Зачем: OpenRouter отвечает на запросы из РФ отказом 403. В CT 120 эта задача уже
# решена — там стоит dnsproxy с DoH-профилем, и нужные имена приходят через релей
# провайдера DNS. Здесь мы повторяем ровно ту же схему для CT 109.
#
# Адрес DoH-профиля — личная настройка, поэтому в репозитории его нет: скрипт берёт
# его из уже работающего контейнера (или из переменной AI9_DOH_URL) и кладёт только
# в unit-файл внутри контейнера.
set -euo pipefail

SITE_CT="${SITE_CT:-109}"
DONOR_CT="${DONOR_CT:-120}"     # контейнер, где схема уже работает
PROBE_HOST="${PROBE_HOST:-openrouter.ai}"

echo "== 1/4 Откуда берём настройки =="
DOH_URL="${AI9_DOH_URL:-}"
if [[ -z "$DOH_URL" ]]; then
  # Берём именно из строки запуска: в Description тот же адрес стоит в скобках,
  # и закрывающая скобка попадает в значение.
  DOH_URL=$(ssh pxhome "pct exec $DONOR_CT -- sed -nE 's#^ExecStart=.*--?u(pstream)?[= ](https://[^ ]+).*#\\2#p' /etc/systemd/system/dnsproxy.service | head -1")
  DOH_URL="${DOH_URL%)}"
fi
[[ "$DOH_URL" == https://* ]] || { echo 'Не нашёл адрес DoH. Задай AI9_DOH_URL=...' >&2; exit 1; }
echo "  DoH-профиль получен (адрес не печатаю)"

echo "== 2/4 Переносим dnsproxy в CT $SITE_CT =="
ssh pxhome "bash -s -- '$DONOR_CT' '$SITE_CT'" <<'HOST'
set -euo pipefail
donor=$1 site=$2
tmp=$(mktemp -d)
trap 'rm -rf -- "$tmp"' EXIT
pct pull "$donor" /usr/local/bin/dnsproxy "$tmp/dnsproxy"
pct push "$site" "$tmp/dnsproxy" /usr/local/bin/dnsproxy
pct exec "$site" -- chmod 755 /usr/local/bin/dnsproxy
HOST
echo "  бинарь на месте"

echo "== 3/4 Настраиваем и запускаем =="
# Адрес профиля подставляем прямо в текст скрипта: он уходит по ssh как stdin,
# поэтому не попадает ни в аргументы команд, ни в список процессов на хосте.
# (Передать его отдельным каналом нельзя: heredoc и так занимает stdin.)
ssh pxhome "pct exec $SITE_CT -- bash -s" <<REMOTE
set -euo pipefail

cat > /etc/systemd/system/dnsproxy.service <<'UNIT'
[Unit]
Description=DNS proxy to DNS-over-HTTPS
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/local/bin/dnsproxy --listen=127.0.0.1 --port=53 --upstream=$DOH_URL --bootstrap=8.8.8.8:53 --cache --cache-size=4096
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
chmod 644 /etc/systemd/system/dnsproxy.service

systemctl daemon-reload
systemctl enable -q dnsproxy
systemctl restart dnsproxy
sleep 3
# is-active при неудаче возвращает ненулевой код и обрывает скрипт, поэтому
# состояние печатаем, а решение принимаем по проверке на шаге 4.
systemctl is-active dnsproxy || true

# Сам контейнер должен спрашивать у локального dnsproxy...
printf 'nameserver 127.0.0.1\n' > /etc/resolv.conf
# ...и не терять эту настройку при получении адреса по DHCP.
if ! grep -q '^supersede domain-name-servers 127.0.0.1;' /etc/dhcp/dhclient.conf 2>/dev/null; then
  echo 'supersede domain-name-servers 127.0.0.1;' >> /etc/dhcp/dhclient.conf
fi
REMOTE

echo "== 4/4 Проверка =="
ssh pxhome "pct exec $SITE_CT -- bash -s -- '$PROBE_HOST'" <<'REMOTE'
set -euo pipefail
host=$1
echo -n "  $host резолвится в: "; getent hosts "$host" | head -1 | awk '{print $1}'
echo -n "  ответ от $host: "; curl -s -m 20 -o /dev/null -w '%{http_code}\n' "https://$host/api/v1/models"
systemctl restart ai9-proxy 2>/dev/null || true
REMOTE

echo
echo "Если код ответа 200 — геоблок обойдён, прослойка снова работает."
