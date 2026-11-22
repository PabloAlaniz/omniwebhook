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
  readonly host: string;
  /** La dirección, si el host es una IP literal; `null` si es un nombre que hay que resolver. */
  readonly literalAddress: string | null;
}

/** Revisa lo que se puede saber de la URL sola: forma, esquema y credenciales. */
export function inspectDestination(
  url: string,
  options: { allowHttp?: boolean } = {},
): InspectedDestination | Extract<DestinationProblem, 'invalid_url' | 'scheme' | 'credentials'> {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return 'invalid_url';
  }
  if (parsed.hostname === '') return 'invalid_url';

  const allowed =
    parsed.protocol === 'https:' || (parsed.protocol === 'http:' && options.allowHttp === true);
  if (!allowed) return 'scheme';
  if (parsed.username !== '' || parsed.password !== '') return 'credentials';

  const host =
    parsed.hostname.startsWith('[') && parsed.hostname.endsWith(']')
      ? parsed.hostname.slice(1, -1)
      : parsed.hostname;
  return { host, literalAddress: isIpAddress(host) ? host : null };
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
