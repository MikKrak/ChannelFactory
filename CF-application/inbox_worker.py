"""Явный ограниченный запуск получения обращений; не запускается веб-сервером.

Использование после подключения схемы и разрешения владельца:
  .venv/bin/python inbox_worker.py --bot-id ID --confirm-offsets --batches 1
Никаких реальных сообщений/текстов в stdout. Каждый пакет сначала сохраняется.
"""
import argparse
import json
import os
from inbox import InboxReader, InboxRepository, receive_batch


def main():
    parser = argparse.ArgumentParser(description='Получить согласованное число пакетов обращений')
    parser.add_argument('--bot-id', required=True, type=int)
    parser.add_argument('--batches', type=int, default=1, choices=range(1, 101), metavar='1..100')
    parser.add_argument('--confirm-offsets', action='store_true', required=True,
                        help='Разрешено подтверждать ранее сохранённые события Telegram')
    args = parser.parse_args()
    if os.environ.get('CF_INBOX_RECEIVE_ENABLED') != '1':
        parser.exit(1, 'Получение обращений ещё не включено владельцем.\n')
    try:
        import database  # Конфигурация загружается только при явном запуске.
        reader = InboxReader(os.environ['TELEGRAM_BOT_TOKEN'])
        repo = InboxRepository(database.db)
        for _ in range(args.batches):
            print(json.dumps(receive_batch(repo, reader, args.bot_id)))
    except KeyboardInterrupt:
        parser.exit(1, 'Получение остановлено. Проверь сохранённый курсор и захват перед новым запуском.\n')
    except Exception:
        parser.exit(1, 'Получение остановлено после ошибки. Проверь БД и потребителя; автоматического повтора нет.\n')


if __name__ == '__main__':
    main()
