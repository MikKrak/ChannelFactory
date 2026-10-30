"""Явный запуск одного long polling получателя; не запускается веб-сервером.

Использование после подключения схемы и разрешения владельца:
  .venv/bin/python inbox_worker.py --bot-id ID --confirm-offsets --batches 1
Никаких реальных сообщений/текстов в stdout. Каждый пакет сначала сохраняется.
"""
import argparse
import json
import os
import signal
import time
from threading import Event
from incoming import private_directory
from inbox import InboxReader, InboxRepository, receive_loop
from inbox_state import read_state, state_directory, write_state


def main():
    parser = argparse.ArgumentParser(description='Получить согласованное число пакетов обращений')
    parser.add_argument('--bot-id', required=True, type=int)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--batches', type=int, choices=range(1, 101), metavar='1..100')
    mode.add_argument('--run', action='store_true', help='Получать до Control+C')
    mode.add_argument('--status', action='store_true', help='Только состояние, без БД и Telegram')
    parser.add_argument('--seconds', type=int, help='Ограничить время работы, например 600')
    parser.add_argument('--confirm-offsets', action='store_true',
                        help='Разрешено подтверждать ранее сохранённые события Telegram')
    args = parser.parse_args()
    if args.status:
        label = {'running': 'работает', 'stopped': 'остановлен', 'error': 'ошибка, нужна проверка', 'unknown': 'состояние не подтверждено'}
        print('Получатель: ' + label[read_state(args.bot_id)['state']]); return
    if not args.confirm_offsets:
        parser.error('Нужно отдельно разрешить --confirm-offsets')
    if args.seconds is not None and args.seconds < 1:
        parser.error('--seconds должен быть положительным')
    if os.environ.get('CF_INBOX_RECEIVE_ENABLED') != '1':
        parser.exit(1, 'Получение обращений ещё не включено владельцем.\n')
    try:
        import database  # Конфигурация загружается только при явном запуске.
        reader = InboxReader(os.environ['TELEGRAM_BOT_TOKEN'])
        repo = InboxRepository(database.db)
        stop = Event()
        def request_stop(signum, frame): stop.set()
        signal.signal(signal.SIGINT, request_stop)
        signal.signal(signal.SIGTERM, request_stop)
        deadline = time.monotonic() + args.seconds if args.seconds else None
        with private_directory(state_directory(args.bot_id)) as directory:
            announced = False
            def progress(**values):
                nonlocal announced
                write_state(directory, **values)
                if values.get('phase') == 'waiting' and not announced:
                    print('Получатель работает. Для остановки нажми Control+C.', flush=True)
                    announced = True
            try:
                progress(state='running', phase='starting')
                result = receive_loop(repo, reader, args.bot_id,
                                      max_batches=None if args.run else (args.batches or 1),
                                      stopped=lambda: stop.is_set() or (deadline is not None and time.monotonic() >= deadline),
                                      progress=progress)
                progress(state='stopped', phase='released', received=result['received'])
                print('Получатель остановлен. Сохранено событий: ' + str(result['received']))
            except BaseException:
                progress(state='error', phase='check_required')
                raise
    except Exception:
        parser.exit(1, 'Получение остановлено после ошибки. Проверь БД и потребителя; автоматического повтора нет.\n')


if __name__ == '__main__':
    main()
