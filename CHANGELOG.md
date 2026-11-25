# Changelog

## [0.5.0](https://github.com/PabloAlaniz/omniwebhook/compare/v0.4.0...v0.5.0) (2026-11-25)


### Features

* adaptadores de entrada para node:http, WSGI y Django ([683a45c](https://github.com/PabloAlaniz/omniwebhook/commit/683a45c178302e7c5780e2598022615d713fe953))
* almacén de reservas sobre cualquier clave-valor ([46aa219](https://github.com/PabloAlaniz/omniwebhook/commit/46aa21943aa8a8312cd49eec8c886426a738c631))
* almacén de reservas sobre Redis ([f0b4183](https://github.com/PabloAlaniz/omniwebhook/commit/f0b4183bcab593466d3f4b2e22d7e029aaf37ef0))
* esquema de firma de Discord ([1176bb0](https://github.com/PabloAlaniz/omniwebhook/commit/1176bb0f893c2ee59b7b3b74fdab13ce083b427a))
* esquemas de firma de Slack y Shopify ([6c242ba](https://github.com/PabloAlaniz/omniwebhook/commit/6c242baaef67c89d7ee0cbe03d923402e7bb3f51))
* esquemas de token compartido y de Google ([#12](https://github.com/PabloAlaniz/omniwebhook/issues/12)) ([59ce080](https://github.com/PabloAlaniz/omniwebhook/commit/59ce0805c24c5571a4eef86231f68f8976626cc7))
* línea de comandos para firmar, verificar y enviar ([d8baf8f](https://github.com/PabloAlaniz/omniwebhook/commit/d8baf8f3bab6e6e1201f925c41df3a5535d0aab8))
* módulo de pruebas con pedidos firmados para cada esquema ([713a294](https://github.com/PabloAlaniz/omniwebhook/commit/713a2940f01ecd37958cea0a58280e442bc10110))
* **spec:** bandeja de salida y despacho de una tanda ([a62c2f2](https://github.com/PabloAlaniz/omniwebhook/commit/a62c2f2e4e5479d81023f099372fab3370b2766d))
* **spec:** firma asimétrica al emitir ([16aeb56](https://github.com/PabloAlaniz/omniwebhook/commit/16aeb56e2078b51c632ce98ba13d431a23fa9ace))
* **spec:** firma asimétrica del formato estándar (v2a, Ed25519) ([6ca1252](https://github.com/PabloAlaniz/omniwebhook/commit/6ca125279fb149818a1abe957f17c4b856954224))
* **spec:** límites de tamaño al recibir y al emitir, y user-agent propio ([3259b28](https://github.com/PabloAlaniz/omniwebhook/commit/3259b28c8214f9c5bc0a9fab65b64387d827c481))
* **spec:** observador de la recepción ([771f75a](https://github.com/PabloAlaniz/omniwebhook/commit/771f75a11011bc01ca01b4fa54597a2b0e19368f))
* **spec:** salud de los destinos y reenvío por rango de tiempo ([9f7eda0](https://github.com/PabloAlaniz/omniwebhook/commit/9f7eda0b398477ff7fc718f7d0f575b57a43f4e7))
* **spec:** tipos de evento y patrones de suscripción ([28a57fb](https://github.com/PabloAlaniz/omniwebhook/commit/28a57fb5cc9e979bbf1615d214223704acd4c348))
* **spec:** validación opcional del payload, antes de reservar ([3a2528e](https://github.com/PabloAlaniz/omniwebhook/commit/3a2528ee186a36e4ec6f3a34ce5bfa4d889d19fd))
* **spec:** varios emisores en una misma ruta ([18e3fab](https://github.com/PabloAlaniz/omniwebhook/commit/18e3fabd182f0aeaf5bbbe44519b16739346acec))
* telemetría con OpenTelemetry ([8333524](https://github.com/PabloAlaniz/omniwebhook/commit/833352477369baa43f2eb7f4428291704ec7996b))


### Bug Fixes

* lo que falló en la primera corrida de la integración continua ([2a1fbf1](https://github.com/PabloAlaniz/omniwebhook/commit/2a1fbf17df5136f9bcb6dff8ba3827bb285b516c))

## [0.4.0](https://github.com/PabloAlaniz/omniwebhook/compare/v0.3.0...v0.4.0) (2026-11-23)


### Features

* esquema de firma de TikTok ([#10](https://github.com/PabloAlaniz/omniwebhook/issues/10)) ([2ac87cd](https://github.com/PabloAlaniz/omniwebhook/commit/2ac87cda1da73c7f9b3f0ae7035ad40d1a648ad3))

## [0.3.0](https://github.com/PabloAlaniz/omniwebhook/compare/v0.2.0...v0.3.0) (2026-11-23)


### Features

* almacén de reservas y registro de entregas sobre SQLite, también D1 ([#7](https://github.com/PabloAlaniz/omniwebhook/issues/7)) ([d2b2439](https://github.com/PabloAlaniz/omniwebhook/commit/d2b2439ddeb466f2dff12bf2b51f5044dbf4a4da))
* **ts:** resolver de DNS sobre HTTPS para Workers y funciones edge ([#8](https://github.com/PabloAlaniz/omniwebhook/issues/8)) ([1b90135](https://github.com/PabloAlaniz/omniwebhook/commit/1b90135aeba054eb5a047f289b76320038400552))

## [0.2.0](https://github.com/PabloAlaniz/omniwebhook/compare/v0.1.1...v0.2.0) (2026-11-23)


### Features

* registro de entregas sobre PostgreSQL, compartido entre paquetes ([#4](https://github.com/PabloAlaniz/omniwebhook/issues/4)) ([0fcd23e](https://github.com/PabloAlaniz/omniwebhook/commit/0fcd23ec64c9097451cf42595e2aeb0678813d0c))
* **spec:** redes permitidas en la política de URLs de destino ([#3](https://github.com/PabloAlaniz/omniwebhook/issues/3)) ([ebe8697](https://github.com/PabloAlaniz/omniwebhook/commit/ebe869746e0b88d124f4b5194b3286db718fe832))


### Bug Fixes

* el tiempo de espera es el plazo del intento completo ([#5](https://github.com/PabloAlaniz/omniwebhook/issues/5)) ([df23095](https://github.com/PabloAlaniz/omniwebhook/commit/df230959b1008d9719f1a3cc292f36d358732173))

## [0.1.1](https://github.com/PabloAlaniz/omniwebhook/compare/v0.1.0...v0.1.1) (2026-11-23)


### Bug Fixes

* **python:** enlazar issues y changelog desde la página de PyPI ([7900ac4](https://github.com/PabloAlaniz/omniwebhook/commit/7900ac4be11027625f7f1070be97e318e997ddab))

## 0.1.0 (2026-11-23)


### Features

* **python:** recepción y emisión de webhooks con las mismas reglas que TypeScript ([e5eb9ca](https://github.com/PabloAlaniz/omniwebhook/commit/e5eb9ca51e13b149894a1fc4aaf97caf19019f5d))
* **spec:** gramática estricta de la URL de destino y prueba de interoperabilidad ([cfe185b](https://github.com/PabloAlaniz/omniwebhook/commit/cfe185bf713cf8a8e83e1235d9eca56c77206c19))
* **ts:** emisión de webhooks con firma estándar, política de URLs y reintentos ([12d5929](https://github.com/PabloAlaniz/omniwebhook/commit/12d59298e42f408dce262ecaf5e45e01c53ccca2))
* **ts:** recepción de webhooks con verificación, frescura e idempotencia ([4bc7358](https://github.com/PabloAlaniz/omniwebhook/commit/4bc7358b975a0e4e1b5e7a15a2d73b0217f0916e))


### Bug Fixes

* **spec:** precisar qué es un espacio, el JSON del cuerpo y las cabeceras extra ([3c0b704](https://github.com/PabloAlaniz/omniwebhook/commit/3c0b704d99d332469610e7c2e8cbec4f7eb85a04))

## Changelog

Los cambios de cada versión se registran acá. El archivo lo mantiene la herramienta de versiones a
partir de los mensajes de commit.
