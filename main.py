# main.py

import time
import sys
import os

print("--- ЭКСПЕРИМЕНТ ЗАПУЩЕН ---")
print(f"Версия Python: {sys.version}")

# Проверим, видит ли скрипт переменные окружения
bot_token_present = "ДА" if os.environ.get("BOT_TOKEN") else "НЕТ"
print(f"Переменная BOT_TOKEN найдена: {bot_token_present}")

print("Это самый простой Python скрипт.")
print("Если ты видишь это сообщение в 'Deploy Logs', значит, окружение Railway РАБОТАЕТ.")

# Принудительно отправляем всё напечатанное в лог, чтобы ничего не потерялось
sys.stdout.flush()

# Поддерживаем жизнь скрипта, чтобы доказать, что он не падает сразу
count = 0
while count < 120:  # Работаем 2 минуты
    print(f"Эксперимент в процессе... прошло {count + 1} сек.")
    sys.stdout.flush()
    time.sleep(1)
    count += 1

print("--- ЭКСПЕРИМЕНТ УСПЕШНО ЗАВЕРШЕН ---")
