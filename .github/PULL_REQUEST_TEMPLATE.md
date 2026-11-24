## Qué cambia y por qué

<!-- Lo que alguien necesita saber para revisar esto sin leer la conversación previa. -->

## Lista

- [ ] Si cambia el comportamiento, la especificación y los vectores cambiaron primero.
- [ ] El cambio está en los dos paquetes, o explico acá por qué sólo en uno.
- [ ] Cada regla nueva entra con el vector o el test que la demuestra.
- [ ] `pnpm check` pasa en la raíz, y en `python/` pasan ruff, mypy, lint-imports y pytest.
- [ ] Si toqué la política de URLs, los esquemas o los almacenes, corrí `pnpm test:interop`.
- [ ] Si es una decisión de diseño nueva, agregué un archivo en `docs/adr/`.
- [ ] No hay secretos, URLs ni datos de sistemas reales.
