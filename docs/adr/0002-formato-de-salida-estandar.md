# 0002. Formato de salida estándar, con la librería de referencia detrás de un puerto

- Estado: aceptada
- Fecha: 2026-11-22

## Contexto

Al emitir un webhook hay que elegir cómo se firma. Un formato propio obliga a cada receptor a
escribir su verificador. La especificación abierta [Standard Webhooks](https://www.standardwebhooks.com/)
ya define cabeceras, contenido firmado, formato de secretos y rotación, y existen verificadores en
muchos lenguajes.

Esa especificación tiene una librería de referencia (`standardwebhooks`) en los lenguajes de este
proyecto. Usarla evita reescribir criptografía ya probada; depender de ella sin cuidado ata la API
pública del paquete a un tercero.

## Decisión

1. Lo que el paquete emite se firma con el formato Standard Webhooks. Los formatos propios de cada
   proveedor existen sólo como verificadores de entrada.
2. Verificar y firmar son puertos (`Verifier` y `MessageSigner`). El formato estándar es un
   adaptador más de esos puertos.
3. La librería de referencia sólo se importa dentro de ese adaptador. Una regla de arquitectura lo
   hace cumplir.
4. La API pública no expone tipos ni excepciones de la librería: el adaptador traduce todo a los
   resultados tipados del dominio.
5. La librería es una dependencia opcional del adaptador, no del núcleo.
6. Los vectores de conformidad del esquema estándar son el contrato del adaptador. Cualquier
   implementación que los pase es válida.

## Consecuencias

- Reemplazar la librería por una implementación propia es un cambio interno: mismos vectores, misma
  API, sin versión mayor.
- Quien recibe un webhook emitido con este paquete puede verificarlo con cualquier implementación
  de la especificación abierta.
- El adaptador tiene una capa de traducción que mantener. Es chica y está cubierta por los vectores.
