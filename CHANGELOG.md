# Changelog

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
