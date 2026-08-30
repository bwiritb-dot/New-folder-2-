# Архив канала «Сергей Леготкин» (@LegotkinSergey)

Полная выгрузка всех видео канала с автоматическими субтитрами (транскриптами).

| | |
|---|---|
| Канал | [@LegotkinSergey](https://www.youtube.com/@LegotkinSergey) |
| ID канала | `UC0B8hyR2nAa-KXJ3RNGZiWQ` |
| Всего видео | 515 |
| С транскриптом | 500 |
| Без субтитров | 15 |
| Период | 2026-07-02 — 2026-07-16 |
| Суммарная длительность | 142 ч 26 мин |
| Слов в транскриптах | ~1 076 722 |

## Структура

```
youtube_LegotkinSergey/
├── README.md      — этот файл
├── index.csv      — таблица всех видео (открывается в Excel)
├── index.json     — то же + описания видео, машиночитаемо
└── transcripts/   — по одному .txt на видео
```

Имя файла транскрипта: `ГГГГ-ММ-ДД_<videoId>_<slug>.txt`, поэтому
сортировка по имени = хронологический порядок.

## Формат транскрипта

Шапка с метаданными (название, ссылка, дата, длительность, просмотры,
язык субтитров), затем текст, разбитый на абзацы примерно по 30 секунд
с тайм-кодами вида `[MM:SS]` / `[HH:MM:SS]`.

## Как это собрано

* Список видео — `yt-dlp --flat-playlist` по вкладке `/videos`
  (вкладок `/shorts` и `/streams` у канала нет).
* Субтитры — автоматические распознанные YouTube (`ru-orig`), формат `json3`,
  служебные строки скользящего окна (`aAppend`) отброшены.
* Скрипты сборки: `tools/fetch_channel.sh` и `tools/build_transcripts.py`.

> Субтитры автоматические, поэтому в тексте встречаются ошибки распознавания,
> особенно в тикерах и терминах. Пунктуация расставлена YouTube.

## Видео без субтитров

* [Объявление для ютуба](https://www.youtube.com/watch?v=Nrv9pcq2sRc) — дата н/д
* [Останавливающее действие рынка. Блок "Ловушка" часть 1](https://www.youtube.com/watch?v=iVBVd2cSYHE) — дата н/д
* [25 ноября 2019 обзор рынка BR, RTS, SI, SR на основе кластерного анализа](https://www.youtube.com/watch?v=cBEHAmMcGBI) — дата н/д
* [23 августа 2019. Хроники торгов на М5 по BR и RTS](https://www.youtube.com/watch?v=5wuDTjagDJI) — дата н/д
* [02 августа 2019. Хроники торгов на М5 по BR и RTS](https://www.youtube.com/watch?v=u2dBv6fRL7o) — дата н/д
* [Хроники торгов. Поиск ключевых зон и уровней по нефти BR от 2019-06-18](https://www.youtube.com/watch?v=KBLf_ONEGfo) — дата н/д
* [Хроники торгов. Поиск ключевых зон и уровней по нефти BR от 2019-05-24](https://www.youtube.com/watch?v=PL0J1l52uoQ) — дата н/д
* [Утренний обзор нефти BR от 2019-05-22](https://www.youtube.com/watch?v=xtnTc2XwFxc) — дата н/д
* [Утренний обзор нефти BR от 2019-05-16](https://www.youtube.com/watch?v=OSdI-Snf790) — дата н/д
* [Утренний обзор нефти BR от 2019-04-01](https://www.youtube.com/watch?v=iJ1mXvpFVjw) — дата н/д
* [Утренний обзор нефти BR от 2019-03-22](https://www.youtube.com/watch?v=CGXBZyzz434) — дата н/д
* [Утренний обзор нефти BR от 2019-01-15](https://www.youtube.com/watch?v=GB6_btXq5xU) — дата н/д
* [Утренний обзор SI от 25 декабря 2018](https://www.youtube.com/watch?v=c_HTZDTgKVo) — дата н/д
* [Отзыв #6: тетрадь трейдера](https://www.youtube.com/watch?v=-TKYpgSRflk) — дата н/д
* [Отзыв #2: курс "Основы побарного анализа и сигналов VSA"](https://www.youtube.com/watch?v=_wGWjyIlaCg) — дата н/д
