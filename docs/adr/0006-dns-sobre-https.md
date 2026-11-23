# 0006. DNS sobre HTTPS para entornos sin DNS del sistema

- Estado: aceptada
- Fecha: 2026-11-23

## Contexto

El emisor valida las direcciones a las que resuelve el destino antes de enviar, así que necesita
un `DnsResolver`. En Node y en Python hay DNS del sistema. En Cloudflare Workers, Deno Deploy y las
funciones edge, no: sólo está `fetch`.

Sin un resolver para esos entornos, quien integra tiene una sola salida, y es mala: un resolver
falso que devuelve una dirección pública cualquiera. Eso apaga la validación de direcciones entera,
el mismo problema que ADR 0005 evitó para las redes permitidas.

## Decisión

1. El paquete de TypeScript trae `dohResolver`, que resuelve con DNS sobre HTTPS en el formato JSON
   (`application/dns-json`). Pide A y AAAA y devuelve las direcciones de las dos respuestas.
2. Por defecto usa el servicio de Cloudflare. El servicio se puede cambiar.
3. Un nombre que no existe (NXDOMAIN) da una lista vacía. Cualquier otra falla lanza, y el intento
   cuenta como un error de red, como pide el contrato del puerto.
4. `createSender` no lo usa por defecto: sigue exigiendo un resolver. Resolver por un tercero
   significa mandarle los nombres de los destinos, y eso lo tiene que elegir quien integra.
5. El paquete de Python no lo trae: en Python siempre hay DNS del sistema.

## Consecuencias

- En un Worker la validación de direcciones funciona: un nombre que resuelve a una dirección
  interna queda bloqueado antes de enviar.
- La protección sigue siendo parcial, como con cualquier transporte sobre `fetch`: la conexión no
  se puede fijar a la dirección validada, y entre la validación y la conexión el nombre podría
  resolver a otra cosa. En Workers conviene sumar la opción `global_fetch_strictly_public`, que
  impide que `fetch` llegue a direcciones internas.
- Los nombres de los destinos viajan al servicio de DNS elegido.
