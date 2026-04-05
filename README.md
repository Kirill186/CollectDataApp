# CollectDataApp

CLI-приложение для пополнения датасета детекции AI/Python-кода.

## Что делает

1. Принимает URL репозитория и commit/tag.
2. Клонирует репозиторий и делает checkout нужного состояния.
3. Создаёт структуру датасета:

```text
<dataset-root>/
  raw/<repo_name>/
    human/
    ai/sample_XXX/
    human_json/
    ai_json/
  manifests/dataset.jsonl
  work/<repo_name>/
```

4. Копирует snapshot проекта в `human/`.
5. Создаёт JSON-мета-файлы по каждому Python-файлу (`human_json`/`ai_json`).
6. Генерирует AI-вариант проекта:
   - через OpenAI API (`/v1/responses`), если задан API ключ;
   - локальным fallback-методом, если ключ не задан.
7. Добавляет записи в `manifests/dataset.jsonl`.

## Запуск

```bash
python3 collect_data.py <repo_url> <commit> [--dataset-root dataset] [--api-key-env CollectData] [--model gpt-4.1-mini]
```

По умолчанию, если OpenAI API вернет ошибку (например `429 insufficient_quota`), приложение автоматически переключится на локальную fallback-генерацию и продолжит выполнение. Чтобы принудительно завершать выполнение при ошибке API, добавьте `--fail-on-api-error`.

### Linux / macOS (bash, zsh)

```bash
export CollectData="<your_openai_api_key>"
python3 collect_data.py https://github.com/pallets/flask.git 2.0.0
```

### Windows PowerShell

```powershell
$env:CollectData = "<your_openai_api_key>"
python .\collect_data.py https://github.com/pallets/flask.git 2.0.0
```

### Windows cmd.exe

```cmd
set CollectData=<your_openai_api_key>
python collect_data.py https://github.com/pallets/flask.git 2.0.0
```

## Формат JSONL

Каждая строка — один Python-файл:

```json
{
  "id": "repo_h_0001",
  "repo": "repo",
  "label": "human",
  "file_relpath": "raw/repo/human/app.py",
  "split": "train",
  "lang": "python"
}
```

Аналогично для `label: "ai"`.

## Важно

- split назначается детерминированно на уровне репозитория (`train/val/test`).
- Приложение **дописывает** `dataset.jsonl` на каждом запуске.
- Не храните API-ключи в репозитории; используйте переменные окружения.
