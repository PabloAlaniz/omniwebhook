import { isBlockedAddress, isIpAddress } from './ip-address';

/** Por qué la política de URLs rechazó un destino (sección 8.1), en el orden en que se revisa. */
export type DestinationProblem =
  | 'invalid_url'
  | 'scheme'
  | 'credentials'
  | 'unresolved'
  | 'blocked_address';

export type DestinationVerdict = 'allowed' | DestinationProblem;

/** Un destino cuya URL pasó la revisión. Falta revisar las direcciones a las que se conecta. */
export interface InspectedDestination {
  /** El host en minúsculas; una IPv6 literal va sin corchetes. */
  readonly host: string;
  /** La dirección, si el host es una IP literal; `null` si es un nombre que hay que resolver. */
  readonly literalAddress: string | null;
}

// La forma de la URL se comprueba acá, carácter por carácter, antes de que la vea el
// analizador de URLs de la plataforma: los analizadores no coinciden entre sí ante una
// URL rara, y esa diferencia es lo que aprovecha quien quiere llegar a una dirección interna.
// biome-ignore lint/suspicious/noControlCharactersInRegex: son justo los que se rechazan
const FORBIDDEN = /[\x00-\x20\x7f\\]/;
const SCHEME = /^([A-Za-z][A-Za-z0-9+.-]*):/;
const AUTHORITY = /^\/\/([^/?#]*)(?:[/?#]|$)/;
const LABEL = /^[A-Za-z0-9_-]{1,63}$/;
const NUMERIC_LABEL = /^(?:[0-9]+|0[xX][0-9A-Fa-f]*)$/;
const PORT = /^[0-9]{1,5}$/;
const MAX_NAME_LENGTH = 253;
const MAX_PORT = 65_535;

function validPort(port: string | null): boolean {
  return port === null || (PORT.test(port) && Number(port) <= MAX_PORT);
}

/** Una IPv6 literal entre corchetes, con puerto opcional. */
function bracketed(hostport: string): InspectedDestination | null {
  const closing = hostport.indexOf(']');
  if (closing === -1) return null;
  const inner = hostport.slice(1, closing);
  const after = hostport.slice(closing + 1);
  const port = after.startsWith(':') ? after.slice(1) : null;
  if ((after !== '' && port === null) || !validPort(port)) return null;
  if (!inner.includes(':') || !isIpAddress(inner)) return null;
  const address = inner.toLowerCase();
  return { host: address, literalAddress: address };
}

/** Una IPv4 literal o un nombre, con puerto opcional. */
function named(hostport: string): InspectedDestination | null {
  const colon = hostport.indexOf(':');
  const name = colon === -1 ? hostport : hostport.slice(0, colon);
  const port = colon === -1 ? null : hostport.slice(colon + 1);
  if (!validPort(port) || name.length > MAX_NAME_LENGTH) return null;
  const labels = (name.endsWith('.') ? name.slice(0, -1) : name).split('.');
  if (!labels.every((label) => LABEL.test(label))) return null;
  if (isIpAddress(name)) return { host: name, literalAddress: name };
  // Hay analizadores que leen como dirección un nombre que termina en un número.
  if (NUMERIC_LABEL.test(labels[labels.length - 1] ?? '')) return null;
  return { host: name.toLowerCase(), literalAddress: null };
}

/** Revisa lo que se puede saber de la URL sola: forma, esquema y credenciales. */
export function inspectDestination(
  url: string,
  options: { allowHttp?: boolean } = {},
): InspectedDestination | Extract<DestinationProblem, 'invalid_url' | 'scheme' | 'credentials'> {
  const scheme = SCHEME.exec(url);
  if (scheme === null || FORBIDDEN.test(url)) return 'invalid_url';
  const name = (scheme[1] ?? '').toLowerCase();
  if (name !== 'https' && !(name === 'http' && options.allowHttp === true)) return 'scheme';

  const authority = AUTHORITY.exec(url.slice(scheme[0].length));
  if (authority === null) return 'invalid_url';
  const whole = authority[1] ?? '';
  const at = whole.lastIndexOf('@');
  const hostport = whole.slice(at + 1);
  const inspected = hostport.startsWith('[') ? bracketed(hostport) : named(hostport);
  if (inspected === null) return 'invalid_url';
  return at === -1 ? inspected : 'credentials';
}

/**
 * Elige la dirección a la que conectarse: tiene que haber alguna y ninguna puede estar
 * bloqueada. Devuelve la primera.
 */
export function selectAddress(
  addresses: readonly string[],
): { readonly address: string } | Extract<DestinationProblem, 'unresolved' | 'blocked_address'> {
  const [address] = addresses;
  if (address === undefined) return 'unresolved';
  return addresses.some(isBlockedAddress) ? 'blocked_address' : { address };
}

/** La política completa, dadas las direcciones a las que resolvió el nombre. */
export function evaluateDestination(
  url: string,
  options: { allowHttp?: boolean; resolved: readonly string[] },
): DestinationVerdict {
  const inspected = inspectDestination(url, options);
  if (typeof inspected === 'string') return inspected;
  const selected = selectAddress(
    inspected.literalAddress === null ? options.resolved : [inspected.literalAddress],
  );
  return typeof selected === 'string' ? selected : 'allowed';
}
