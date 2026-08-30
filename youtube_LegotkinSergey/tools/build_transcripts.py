#!/usr/bin/env python3
"""Собирает папку с транскриптами канала из сырых данных yt-dlp."""
import json, os, re, csv, sys, glob

RAW = "/tmp/claude-0/-home-user-New-folder-2-/30eb1a79-b270-5dd6-98ab-3d8b279c8821/scratchpad/raw"
OUT = "/home/user/New-folder-2-/youtube_LegotkinSergey"
TDIR = os.path.join(OUT, "transcripts")

TRANSLIT = {
    'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'e','ж':'zh','з':'z','и':'i',
    'й':'y','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r','с':'s','т':'t',
    'у':'u','ф':'f','х':'h','ц':'ts','ч':'ch','ш':'sh','щ':'sch','ъ':'','ы':'y','ь':'',
    'э':'e','ю':'yu','я':'ya',
}

def slugify(title, maxlen=60):
    s = title.lower()
    s = ''.join(TRANSLIT.get(c, c) for c in s)
    s = re.sub(r'[^a-z0-9]+', '-', s).strip('-')
    return s[:maxlen].strip('-') or 'video'

def hhmmss(sec):
    if sec is None:
        return ''
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

def parse_json3(path):
    """json3 -> [(start_ms, text)] без дублей скользящего окна."""
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    out = []
    for ev in data.get('events', []):
        if ev.get('aAppend'):          # служебная строка-повтор
            continue
        segs = ev.get('segs')
        if not segs:
            continue
        text = ''.join(s.get('utf8', '') for s in segs)
        text = text.replace('\n', ' ').strip()
        if not text:
            continue
        out.append((ev.get('tStartMs', 0), text))
    return out

def to_paragraphs(cues, window_ms=30000):
    """Группирует реплики в абзацы по ~30 секунд."""
    paras, cur, start = [], [], None
    for ts, text in cues:
        if start is None:
            start = ts
        cur.append(text)
        if ts - start >= window_ms:
            paras.append((start, ' '.join(cur)))
            cur, start = [], None
    if cur:
        paras.append((start or 0, ' '.join(cur)))
    return paras

def load_extra_meta():
    """upload_date/duration/views из отдельного прохода yt-dlp без lang=ru.

    С аргументом lang=ru yt-dlp отдаёт локализованную дату ("17 авг. 2026 г.")
    и не может её разобрать, поэтому upload_date приходит пустым — даты
    добираются вторым, метаданным проходом.
    """
    path = os.path.join(os.path.dirname(RAW), 'dates.tsv')
    meta = {}
    if not os.path.exists(path):
        return meta
    with open(path, encoding='utf-8') as f:
        for line in f:
            parts = line.rstrip('\n').split('\t')
            if len(parts) < 5:
                continue
            vid, upload, dur, views, likes = parts[:5]
            def num(x):
                return int(x) if x.isdigit() else None
            meta[vid] = {
                'upload_date': upload if upload.isdigit() and len(upload) == 8 else '',
                'duration': num(dur),
                'view_count': num(views),
                'like_count': num(likes),
            }
    return meta


def write_readme(records):
    ok = [r for r in records if r['has_transcript']]
    miss = [r for r in records if not r['has_transcript']]
    dates = sorted(r['upload_date'] for r in records if r['upload_date'])
    total_words = sum(r['word_count'] for r in records)
    total_sec = sum(r['duration_sec'] or 0 for r in records)
    lines = [
        "# Архив канала «Сергей Леготкин» (@LegotkinSergey)",
        "",
        "Полная выгрузка всех видео канала с автоматическими субтитрами (транскриптами).",
        "",
        "| | |",
        "|---|---|",
        f"| Канал | [@LegotkinSergey](https://www.youtube.com/@LegotkinSergey) |",
        f"| ID канала | `UC0B8hyR2nAa-KXJ3RNGZiWQ` |",
        f"| Всего видео | {len(records)} |",
        f"| С транскриптом | {len(ok)} |",
        f"| Без субтитров | {len(miss)} |",
        f"| Период | {dates[0] if dates else 'н/д'} — {dates[-1] if dates else 'н/д'} |",
        f"| Суммарная длительность | {total_sec // 3600} ч {(total_sec % 3600) // 60} мин |",
        f"| Слов в транскриптах | ~{total_words:,} |".replace(',', ' '),
        "",
        "## Структура",
        "",
        "```",
        "youtube_LegotkinSergey/",
        "├── README.md      — этот файл",
        "├── index.csv      — таблица всех видео (открывается в Excel)",
        "├── index.json     — то же + описания видео, машиночитаемо",
        "└── transcripts/   — по одному .txt на видео",
        "```",
        "",
        "Имя файла транскрипта: `ГГГГ-ММ-ДД_<videoId>_<slug>.txt`, поэтому",
        "сортировка по имени = хронологический порядок.",
        "",
        "## Формат транскрипта",
        "",
        "Шапка с метаданными (название, ссылка, дата, длительность, просмотры,",
        "язык субтитров), затем текст, разбитый на абзацы примерно по 30 секунд",
        "с тайм-кодами вида `[MM:SS]` / `[HH:MM:SS]`.",
        "",
        "## Как это собрано",
        "",
        "* Список видео — `yt-dlp --flat-playlist` по вкладке `/videos`",
        "  (вкладок `/shorts` и `/streams` у канала нет).",
        "* Субтитры — автоматические распознанные YouTube (`ru-orig`), формат `json3`,",
        "  служебные строки скользящего окна (`aAppend`) отброшены.",
        "* Скрипты сборки: `tools/fetch_channel.sh` и `tools/build_transcripts.py`.",
        "",
        "> Субтитры автоматические, поэтому в тексте встречаются ошибки распознавания,",
        "> особенно в тикерах и терминах. Пунктуация расставлена YouTube.",
        "",
    ]
    if miss:
        lines += ["## Видео без субтитров", ""]
        lines += [f"* [{r['title']}]({r['url']}) — {r['upload_date'] or 'дата н/д'}" for r in miss]
        lines += [""]
    with open(os.path.join(OUT, 'README.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def main():
    order = json.load(open(os.path.join(os.path.dirname(RAW), 'tab_videos.json')))['entries']
    order_ids = [e['id'] for e in order]
    titles_ru = {e['id']: e['title'] for e in order}

    extra = load_extra_meta()

    os.makedirs(TDIR, exist_ok=True)
    for old in glob.glob(os.path.join(TDIR, '*.txt')):
        os.remove(old)

    records = []
    for vid in order_ids:
        info_path = os.path.join(RAW, f"{vid}.info.json")
        info = {}
        if os.path.exists(info_path):
            with open(info_path, encoding='utf-8') as f:
                info = json.load(f)

        ex = extra.get(vid, {})
        title = titles_ru.get(vid) or info.get('title') or vid
        upload = ex.get('upload_date') or info.get('upload_date') or ''
        date_iso = f"{upload[:4]}-{upload[4:6]}-{upload[6:8]}" if len(upload) == 8 else ''
        duration = ex.get('duration') or info.get('duration')
        views = ex.get('view_count') if ex.get('view_count') is not None else info.get('view_count')
        likes = ex.get('like_count')
        desc = (info.get('description') or '').strip()

        sub_path, sub_lang = None, None
        for lang in ('ru-orig', 'ru', 'en'):
            p = os.path.join(RAW, f"{vid}.{lang}.json3")
            if os.path.exists(p) and os.path.getsize(p) > 0:
                sub_path, sub_lang = p, lang
                break

        fname = f"{date_iso or '0000-00-00'}_{vid}_{slugify(title)}.txt"
        rec = {
            'id': vid,
            'title': title,
            'url': f"https://www.youtube.com/watch?v={vid}",
            'upload_date': date_iso,
            'duration_sec': duration,
            'duration': hhmmss(duration),
            'view_count': views,
            'like_count': likes,
            'subtitle_lang': sub_lang,
            'has_transcript': bool(sub_path),
            'transcript_file': f"transcripts/{fname}" if sub_path else None,
            'description': desc,
        }

        if sub_path:
            cues = parse_json3(sub_path)
            paras = to_paragraphs(cues)
            rec['word_count'] = sum(len(t.split()) for _, t in paras)
            header = [
                f"Название:   {title}",
                f"Канал:      Сергей Леготкин (@LegotkinSergey)",
                f"URL:        {rec['url']}",
                f"Дата:       {date_iso or 'н/д'}",
                f"Длительность: {rec['duration'] or 'н/д'}",
                f"Просмотров: {views if views is not None else 'н/д'}",
                f"Субтитры:   {sub_lang} (автоматические, YouTube ASR)",
                "=" * 78,
                "",
            ]
            body = [f"[{hhmmss(ms // 1000)}] {t}" for ms, t in paras]
            with open(os.path.join(TDIR, fname), 'w', encoding='utf-8') as f:
                f.write('\n'.join(header) + '\n\n'.join(body) + '\n')
        else:
            rec['word_count'] = 0

        records.append(rec)

    records.sort(key=lambda r: (r['upload_date'] or '9999-99-99', r['title']))

    with open(os.path.join(OUT, 'index.json'), 'w', encoding='utf-8') as f:
        json.dump({
            'channel': 'Сергей Леготкин',
            'channel_url': 'https://www.youtube.com/@LegotkinSergey',
            'channel_id': 'UC0B8hyR2nAa-KXJ3RNGZiWQ',
            'video_count': len(records),
            'with_transcript': sum(1 for r in records if r['has_transcript']),
            'videos': records,
        }, f, ensure_ascii=False, indent=2)

    cols = ['id', 'upload_date', 'title', 'duration', 'view_count', 'like_count',
            'subtitle_lang', 'word_count', 'url', 'transcript_file']
    with open(os.path.join(OUT, 'index.csv'), 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction='ignore')
        w.writeheader()
        for r in records:
            w.writerow(r)

    write_readme(records)

    ok = sum(1 for r in records if r['has_transcript'])
    print(f"видео: {len(records)}, с транскриптом: {ok}, без: {len(records)-ok}")
    for r in records:
        if not r['has_transcript']:
            print("  нет субтитров:", r['id'], r['title'])

if __name__ == '__main__':
    main()
