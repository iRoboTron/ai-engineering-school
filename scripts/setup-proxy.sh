#!/usr/bin/env bash
# Установка прослойки к OpenRouter в контейнер сайта (CT 109).
# Запускать со своей машины: нужен ssh-алиас pxhome.
#
# Ключ OpenRouter и коды классов НЕ хранятся в репозитории: они попадают только
# в /etc/ai9-proxy.env внутри контейнера, права 600, владелец root.
#
# Повторный запуск обновляет код прослойки и перезапускает сервис; секреты
# сохраняются, если не переданы заново.
set -euo pipefail

SITE_CT="${SITE_CT:-109}"
APP_DIR="${APP_DIR:-/opt/ai9-proxy}"
ENV_FILE="${ENV_FILE:-/etc/ai9-proxy.env}"
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "== Секреты =="
if ssh pxhome "pct exec $SITE_CT -- test -f $ENV_FILE" 2>/dev/null; then
  echo "  $ENV_FILE уже есть — секреты не трогаю"
  WRITE_ENV=0
else
  WRITE_ENV=1
  # Читаем без эха: ключ не должен попасть ни в историю оболочки, ни на экран.
  read -rsp "Ключ OpenRouter (sk-or-...): " OPENROUTER_KEY; echo
  [[ "$OPENROUTER_KEY" == sk-or-* ]] || { echo 'Ключ должен начинаться с sk-or-' >&2; exit 1; }
  read -rp  "Коды классов через запятую (их дашь ученикам, например 9a-2026,9b-2026): " CLASS_TOKENS
  [[ -n "$CLASS_TOKENS" ]] || { echo 'Нужен хотя бы один код класса' >&2; exit 1; }
fi

echo "== Код прослойки =="
STAGE=$(mktemp -d)
trap 'rm -rf -- "$STAGE"' EXIT
tar -C "$ROOT_DIR/proxy" -czf "$STAGE/proxy.tar.gz" .
REMOTE=$(ssh pxhome 'mktemp -d -t ai9proxy.XXXXXXXX')
scp -q "$STAGE/proxy.tar.gz" "pxhome:$REMOTE/proxy.tar.gz"
ssh pxhome "pct push $SITE_CT '$REMOTE/proxy.tar.gz' /tmp/ai9-proxy.tar.gz && rm -rf -- '$REMOTE'"

if [[ "$WRITE_ENV" == 1 ]]; then
  # Файл с секретами пишем отдельным шагом через stdin, чтобы значения не попали
  # ни в аргументы команды, ни в логи ssh.
  printf 'OPENROUTER_API_KEY=%s\nAI9_CLASS_TOKENS=%s\n' "$OPENROUTER_KEY" "$CLASS_TOKENS" |
    ssh pxhome "pct exec $SITE_CT -- bash -c 'umask 077 && cat > $ENV_FILE && chown root:root $ENV_FILE'"
  echo "  записан $ENV_FILE (права 600)"
fi

echo "== Установка в контейнере =="
ssh pxhome "pct exec $SITE_CT -- bash -s" <<REMOTE
set -euo pipefail
app='$APP_DIR'
mkdir -p "\$app" /var/log/ai9-proxy
tar xzf /tmp/ai9-proxy.tar.gz -C "\$app"
rm -f /tmp/ai9-proxy.tar.gz

# Виртуальное окружение: пакеты прослойки не смешиваем с системными.
if [[ ! -x "\$app/.venv/bin/python" ]]; then
  apt-get update -qq
  apt-get install -y -qq python3-venv >/dev/null
  python3 -m venv "\$app/.venv"
fi
"\$app/.venv/bin/pip" install -q --upgrade pip
"\$app/.venv/bin/pip" install -q -r "\$app/requirements.txt"

install -m 644 "\$app/ai9-proxy.service" /etc/systemd/system/ai9-proxy.service
systemctl daemon-reload
systemctl enable -q ai9-proxy
systemctl restart ai9-proxy
sleep 2
systemctl is-active ai9-proxy
curl -fsS --max-time 10 http://127.0.0.1:8099/api/health
echo
REMOTE

echo
echo "== Проверка снаружи =="
if curl -fsS --max-time 15 "https://ai9.adelfos.ru/api/health"; then
  echo
  echo "Готово: https://ai9.adelfos.ru/api/health отвечает."
else
  echo "Локально сервис поднялся, но снаружи не отвечает." >&2
  echo "Скорее всего, нужен свежий деплой сайта (./deploy-pxhome.sh) — vhost с /api/ пишет он." >&2
fi
