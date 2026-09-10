#!/usr/bin/env bash
# Выполняется ВНУТРИ контейнера с nginx. Разворачивает новый релиз и переключает
# симлинк docroot атомарно; при любой ошибке возвращает предыдущий релиз и vhost.
# Аргументы: <домен> <id релиза> <путь к архиву>
set -euo pipefail

site=$1 id=$2 archive=$3
docroot="/var/www/sites/$site"
release="/var/www/releases/$site/$id"
vhost="/etc/nginx/sites-enabled/$site"
backup="/tmp/$id.vhost-backup"
legacy="/var/www/releases/$site/legacy-$id"

old_target=''
old_vhost=0
switched=0
legacy_moved=0

[[ -L "$docroot" ]] && old_target=$(readlink "$docroot")
if [[ -e "$vhost" || -L "$vhost" ]]; then cp -a "$vhost" "$backup"; old_vhost=1; fi

rollback() {
  status=$?
  if [[ "$status" != 0 ]]; then
    [[ "$switched" == 1 ]] && rm -f "$docroot"
    if [[ "$legacy_moved" == 1 ]]; then
      mv "$legacy" "$docroot"
    elif [[ "$switched" == 1 && -n "$old_target" ]]; then
      ln -s "$old_target" "$docroot"
    fi
    rm -f "$vhost"
    [[ "$old_vhost" == 1 ]] && cp -a "$backup" "$vhost"
    nginx -t && systemctl reload nginx || true
    echo 'Деплой не удался: предыдущий релиз и vhost восстановлены.' >&2
  fi
  rm -f "$archive" "$backup" "$docroot.next-$id"
  exit "$status"
}
trap rollback EXIT

mkdir -p "$release" "$(dirname "$docroot")"
tar xzf "$archive" -C "$release"
find "$release" -type d -exec chmod 755 {} +
find "$release" -type f -exec chmod 644 {} +

# Пишем новый обычный файл: старый vhost может быть симлинком, его цель трогать нельзя.
rm -f "$vhost"
printf 'server {\n listen 80;\n server_name %s;\n root %s;\n index index.html;\n location / { try_files $uri $uri/ =404; }\n}\n' \
  "$site" "$docroot" > "$vhost"
nginx -t

ln -s "$release" "$docroot.next-$id"
if [[ -d "$docroot" && ! -L "$docroot" ]]; then mv "$docroot" "$legacy"; legacy_moved=1; fi
mv -Tf "$docroot.next-$id" "$docroot"
switched=1
systemctl reload nginx

# Дымовые проверки: сайт должен реально отдавать ключевые файлы.
for path in index.html reader.html reader-links.js files.json \
            vendor/marked.min.js 01-llm-osnovy/book.md labs/tema1-llm-osnovy/01_tokeny.py; do
  code=$(curl --fail --silent --show-error --max-time 15 --output /dev/null \
              --write-out '%{http_code}' "http://127.0.0.1/$path" -H "Host: $site")
  [[ "$code" == 200 ]] || { echo "$path: ожидался 200, получен $code" >&2; exit 1; }
  echo "  $path: $code"
done

# Старые релизы: держим последние 5, остальное убираем.
ls -1dt "/var/www/releases/$site"/*/ 2>/dev/null | tail -n +6 | xargs -r rm -rf --
