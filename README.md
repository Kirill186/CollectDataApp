# CollectDataApp

CLI-приложение для ручного пополнения датасета детекции AI/Python-кода.

## Что делает `collect_data.py`

1. Принимает URL репозитория и commit/tag.
2. Клонирует репозиторий и делает checkout нужного состояния в `work/<repo_name>`.
3. Создаёт структуру:

```text
<dataset-root>/
  raw/
    human/<repo_name>/
    ai/<repo_name>/
  work/<repo_name>/
```

4. Копирует **все `.py` файлы в одну папку** `raw/human/<repo_name>` (flattened-формат), даже если в оригинале они были в разных подпапках.
5. Генерирует в `raw/ai/<repo_name>` `.txt` файлы с **псевдокодом** (не промпты и не исходный код), где есть:
   - точные импорты,
   - примерный каркас (классы/функции),
   - подробное описание что генерировать.
6. Создаёт:
   - `PROMPT.txt` (общие правила),
   - `mapping.json` (соответствие original path -> flattened имя).

## Файлы-утилиты

### `generate_pseudocode_txt.py`
Генерирует `.txt`-псевдокоды на основе `mapping.json` и исходников из `work`.

Пример:

```bash
python3 generate_pseudocode_txt.py --work-root dataset/work/my_repo --ai-root dataset/raw/ai/my_repo --mapping-file dataset/raw/ai/my_repo/mapping.json
```

### `txt_to_py.py`
Читает `.txt`-псевдокоды и генерирует по ним `.py` черновики.

Пример:

```bash
python3 txt_to_py.py --ai-root dataset/raw/ai/my_repo
```

Если нужно удалить `.txt` после генерации `.py`:

```bash
python3 txt_to_py.py --ai-root dataset/raw/ai/my_repo --replace
```

## Основной запуск

```bash
python3 collect_data.py <repo_url> <commit> [--dataset-root dataset]
```

## Важно

- В `.txt` нет исходника, только псевдокод + точные импорты + структура.
- JSON-метаданные (`human_json`, `ai_json`) и `dataset.jsonl` не создаются.
