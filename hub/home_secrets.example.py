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
