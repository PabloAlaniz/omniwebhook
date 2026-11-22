# 0001. Arquitectura en capas con dependencias hacia adentro

- Estado: aceptada
- Fecha: 2026-11-22

## Contexto

El paquete tiene que servir igual con cualquier proveedor de webhooks, cualquier base de datos,
cualquier cliente HTTP y cualquier framework, y en más de un lenguaje. Las reglas (qué se acepta,
cuándo se reintenta, qué cuenta como duplicado) no cambian con ninguna de esas elecciones; las
elecciones sí cambian con el tiempo.

## Decisión

Cada paquete se organiza en cuatro capas, y las dependencias sólo apuntan hacia adentro:

```
entrypoints → adapters → application → domain
```

- **domain**: reglas puras. Sin entrada/salida, sin reloj, sin red y sin paquetes externos.
- **application**: los casos de uso (recibir, enviar, reenviar) y los puertos que necesitan.
  Depende sólo del dominio.
- **adapters**: implementaciones de los puertos: esquemas de firma, almacenes, transporte HTTP,
  resolución de nombres.
- **entrypoints**: atajos finos para montar un caso de uso en un framework. Son opcionales.

Reglas que se desprenden:

1. Un esquema de firma nuevo es un adaptador nuevo con sus vectores. No se toca el núcleo.
2. Los puertos son chicos y separados: quien sólo recibe no depende de nada de la emisión.
3. El reloj, el generador de identificadores, la red y la resolución de nombres se inyectan. Los
   tests del núcleo no tocan la red ni el tiempo real.
4. Los adaptadores con dependencias pesadas se publican como entradas opcionales del paquete. El
   núcleo no tiene dependencias en tiempo de ejecución.

La dirección de las dependencias se verifica en la integración continua, no por convención:
`dependency-cruiser` en TypeScript, `import-linter` y un test de imports del dominio en Python.

## Consecuencias

- Cambiar de base, de cliente HTTP o de librería de firmas es escribir otro adaptador.
- Hay más archivos y más indirección que en una implementación directa. Se acepta: el costo es
  fijo y chico, y el beneficio crece con cada proveedor y cada almacén que se suma.
- Las dos implementaciones comparten estructura, así que una regla se busca en el mismo lugar en
  cualquiera de los dos lenguajes.
