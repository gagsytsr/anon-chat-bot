import telegram

try:
    print(f"РЕАЛЬНАЯ ВЕРСИЯ python-telegram-bot: {telegram.__version__}")
except Exception as e:
    print(f"Не удалось определить версию: {e}")

