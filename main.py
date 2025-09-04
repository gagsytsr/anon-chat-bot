# main.py

import sys
import time

print("--- ТЕСТ ИМПОРТОВ ЗАПУЩЕН ---")
sys.stdout.flush()

try:
    print("Импортируем системные библиотеки (os, asyncio, logging)...")
    import os
    import asyncio
    import logging
    sys.stdout.flush()
    print("...Успешно.")
    
    print("\nИмпортируем python-telegram-bot...")
    from telegram.ext import Application
    sys.stdout.flush()
    print("...Успешно.")

    print("\nИмпортируем asyncpg...")
    import asyncpg
    sys.stdout.flush()
    print("...Успешно.")
    
    print("\nИмпортируем локальные файлы: database, keyboards...")
    # Убедись, что эти файлы существуют и в них нет синтаксических ошибок
    import database
    import keyboards
    sys.stdout.flush()
    print("...Успешно.")

    print("\n--- ВСЕ ИМПОРТЫ ПРОШЛИ УСПЕШНО! ---")

except Exception as e:
    print(f"\n!!! ПРОИЗОШЛА ОШИБКА ВО ВРЕМЯ ИМПОРТА: {e}")
    import traceback
    traceback.print_exc()

finally:
    sys.stdout.flush()
    print("\nТест завершен. Скрипт будет работать еще 2 минуты.")
    time.sleep(120)

