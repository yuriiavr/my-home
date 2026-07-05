# ═══ Синхронізація вебзастосунку на плату ESP32 ═══
# Копіює файли з webapp\ (єдине джерело правди) у firmware\data\,
# звідки PlatformIO заливає їх у файлову систему плати (LittleFS).
#
# Запуск:  .\sync-board.ps1        (з кореня проєкту, ПКМ → Run with PowerShell теж працює)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$web  = Join-Path $root 'webapp'
$data = Join-Path $root 'firmware\data'

if (-not (Test-Path $web))  { Write-Error "Не знайдено папку webapp: $web" }
if (-not (Test-Path $data)) { New-Item -ItemType Directory -Force $data | Out-Null }

# config.js — секрети ЛИШЕ для хмари; на плату його не копіюємо ніколи.
Copy-Item (Join-Path $web '*') $data -Exclude 'config.js' -Force

Write-Host ''
Write-Host 'Скопійовано webapp\ -> firmware\data\ :' -ForegroundColor Green
Get-ChildItem $data | ForEach-Object { Write-Host ("   {0,-22} {1,7} байт" -f $_.Name, $_.Length) }

Write-Host ''
Write-Host 'Тепер залий файли на плату (плата підключена по USB):' -ForegroundColor Cyan
Write-Host ''
Write-Host '   cd firmware'
Write-Host '   pio run -e esp32dev -t uploadfs    # веб-файли (LittleFS) — саме це потрібно зараз'
Write-Host '   pio run -e esp32dev -t upload      # сама прошивка — лише якщо мінявся код у src\'
Write-Host ''
Write-Host '(без USB можна по WiFi: env esp32dev_ota, деталі в firmware\platformio.ini)'
