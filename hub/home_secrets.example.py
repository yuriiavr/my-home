"""
ШАБЛОН секретів хаба. Скопіюй цей файл як secrets.py і заповни своїми значеннями.
secrets.py не потрапляє в git.
"""

# Кондиціонер Gree/Cooper&Hunter — локальний WiFi-доступ.
# IP/MAC знайди через devices.gree.scan(), ключ отримай через devices.gree.bind().
AC_IP = "192.168.0.109"
AC_MAC = "aabbccddeeff"
AC_KEY = "REPLACE_DEVICE_KEY"
AC_ENC = "gcm"   # "gcm" для нових прошивок (2022+), "ecb" для старих

# Плата ESP32 (датчик клімату DHT22 + ІЧ). IP може мінятись (DHCP) — хаб сам
# знайде плату скануванням, якщо тут застаріє.
BOARD_IP = "192.168.0.108"

# ПК користувача — для Wake-on-LAN (голосом «увімкни комп'ютер»).
# MAC мережевої карти ПК (Ethernet). Дізнатись: getmac /v  або ipconfig /all.
PC_MAC = "AA-BB-CC-DD-EE-FF"

# Gemini API для голосового керування (voice.py)
GEMINI_API_KEY = "REPLACE_GEMINI_KEY"

# Picovoice Porcupine wake-word (console.picovoice.ai -> AccessKey)
PICOVOICE_KEY = "REPLACE_PICOVOICE_KEY"

# Розумна розетка TP-Link Tapo P110 — локальний WiFi-доступ.
# Email+пароль — від акаунта Tapo. У застосунку Tapo увімкни для розетки
# «Сумісність зі сторонніми» (Third-Party Compatibility), інакше буде 403.
# Перевірка: python -m devices.tapo
TAPO_EMAIL = ""
TAPO_PASSWORD = ""
TAPO_IP = "192.168.0.120"
