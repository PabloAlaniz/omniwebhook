/** Un identificador de mensaje nuevo: aleatorio, sin puntos y con prefijo `msg_`. */
export function randomMessageId(): string {
  return `msg_${crypto.randomUUID().replaceAll('-', '')}`;
}
