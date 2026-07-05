/* ШАБЛОН конфігурації хмарного застосунку.
   Скопіюй як config.js і заповни своїми даними брокера (HiveMQ Cloud).
   ⚠️ config.js потрапляє на публічний хостинг разом із сайтом — створи для
   веб-клієнта ОКРЕМИЙ обмежений логін брокера і не публікуй адресу сайту. */
window.HUB_CONFIG = {
  url:      'wss://REPLACE_CLUSTER.s1.eu.hivemq.cloud:8884/mqtt',
  username: 'REPLACE_USER',
  password: 'REPLACE_PASS',
  base:     'smarthome/REPLACE_TOKEN',
};
