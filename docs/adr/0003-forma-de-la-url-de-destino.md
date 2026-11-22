# 0003. La forma de la URL de destino se comprueba con una gramática propia

- Estado: aceptada
- Fecha: 2026-11-22

## Contexto

La URL a la que se entrega un webhook la escribe un tercero. La política de URLs tiene que impedir
que apunte a una dirección interna, y para eso primero hay que saber a qué host apunta.

Cada lenguaje trae su analizador de URLs y no coinciden ante una URL rara: una barra invertida, un
número suelto en lugar de un nombre, una dirección IP abreviada o en hexadecimal, espacios al
principio. Uno ve un host y otro ve otro. Esa diferencia es una vía conocida para llegar a
direcciones internas, y además hacía que los dos paquetes respondieran distinto ante la misma URL.
La prueba de interoperabilidad lo mostró.

## Decisión

1. La especificación define la forma que tiene que tener una URL de destino, con una gramática
   chica. Lo que no tiene esa forma se rechaza con `invalid_url`.
2. La comprobación es parte del dominio de cada paquete y se hace antes de entregarle la URL al
   analizador de la plataforma.
3. Las únicas direcciones literales que se aceptan son la IPv4 de cuatro números decimales y la
   IPv6 entre corchetes. Un nombre que termina en un número se rechaza.
4. Los nombres internacionalizados se aceptan sólo en su forma ASCII.
5. La prueba de interoperabilidad comprueba, para cada URL aceptada, que el analizador de cada
   plataforma ve el mismo host que se validó.

## Consecuencias

- Los dos paquetes dan el mismo resultado para cualquier URL, no sólo para las de los vectores.
- Se rechazan URLs que un navegador aceptaría. Es a propósito: una URL de webhook no necesita esas
  formas.
- Quien registra un destino con un nombre internacionalizado tiene que convertirlo antes.
- El dominio de Python ya no depende del analizador de URLs de la biblioteca estándar.
