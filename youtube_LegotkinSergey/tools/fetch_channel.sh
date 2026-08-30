#!/bin/bash
# Выгружает список всех видео канала и автоматические субтитры к ним.
#   pip install yt-dlp
#   ./fetch_channel.sh <каталог-для-сырых-данных>
set -euo pipefail

CHANNEL="https://www.youtube.com/@LegotkinSergey"
RAW="${1:-raw}"
mkdir -p "$RAW"

# 1. Список видео (только вкладка /videos — других у канала нет)
yt-dlp --flat-playlist -J --extractor-args "youtube:lang=ru" \
  "$CHANNEL/videos" > "$RAW/../tab_videos.json"

python3 - "$RAW/../tab_videos.json" "$RAW/../urls.txt" <<'PY'
import json, sys
ids = [e['id'] for e in json.load(open(sys.argv[1]))['entries']]
open(sys.argv[2], 'w').write('\n'.join('https://www.youtube.com/watch?v=' + i for i in ids) + '\n')
print(len(ids), 'видео')
PY

# 2. Субтитры + метаданные.
#    player_client=web_embedded — единственный клиент, который на облачных IP
#    не упирается в "Sign in to confirm you're not a bot".
yt-dlp \
  --batch-file "$RAW/../urls.txt" \
  --skip-download --ignore-no-formats-error --ignore-errors --no-warnings \
  --write-auto-subs --write-subs --sub-langs "ru-orig,ru" --sub-format json3 \
  --write-info-json \
  --extractor-args "youtube:player_client=web_embedded;lang=ru" \
  --sleep-requests 1 --retries 5 --extractor-retries 3 \
  --no-overwrites \
  -o "$RAW/%(id)s.%(ext)s"

# 3. Даты публикации, длительность, просмотры, лайки.
#    Отдельным проходом и БЕЗ lang=ru: с этим аргументом yt-dlp получает
#    локализованную дату ("17 авг. 2026 г.") и не может её разобрать,
#    так что upload_date приходит пустым.
yt-dlp --batch-file "$RAW/../urls.txt" \
  --skip-download --ignore-no-formats-error --ignore-errors --no-warnings \
  --extractor-args "youtube:player_client=web_embedded" \
  --sleep-requests 1 --retries 5 --extractor-retries 3 \
  --print "%(id)s	%(upload_date)s	%(duration)s	%(view_count)s	%(like_count)s" \
  > "$RAW/../dates.tsv"
