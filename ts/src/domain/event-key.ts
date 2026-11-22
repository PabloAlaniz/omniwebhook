/** La clave de un evento que trae su propio identificador (sección 4.6). */
export function eventKey(scheme: string, id: string): string {
  return `${scheme}:${id}`;
}

/** La clave de un evento sin identificador: la huella de su cuerpo. */
export function fingerprintKey(scheme: string, bodySha256Hex: string): string {
  return `${scheme}:sha256:${bodySha256Hex}`;
}
