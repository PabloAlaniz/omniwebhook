# Seguridad

## Reportar una vulnerabilidad

No abras un issue público. Usá el
[reporte privado de vulnerabilidades](https://github.com/PabloAlaniz/omniwebhook/security/advisories/new)
de GitHub. Vas a tener una primera respuesta dentro de los 7 días.

Incluí, si podés: la versión afectada, el lenguaje, los pasos para reproducirlo y el impacto que
ves.

## Versiones con soporte

Hasta la 1.0 sólo recibe correcciones la última versión publicada.

## Qué cuenta como vulnerabilidad

- Aceptar un webhook con firma inválida, vencida o ambigua.
- Procesar dos veces un evento que el almacén ya había reservado.
- Filtrar un secreto o una URL de destino en un error, un log o un resultado.
- Entregar a una dirección que la política de URLs salientes debía bloquear.
- Una comparación de firmas que no sea en tiempo constante.

## Garantías de diseño

- La verificación no se puede desactivar: sin secreto configurado, el resultado es un rechazo.
- El cuerpo se verifica crudo, tal como llegó, antes de interpretarlo.
- Los secretos y las URLs de destino no aparecen en mensajes de error.
