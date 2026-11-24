import type { Verifier } from '../../application/ports';
import { ConfigurationError } from '../../domain/errors';
import { eventKey } from '../../domain/event-key';
import { pickSingles } from '../../domain/fields';
import { fieldValues, type IncomingRequest } from '../../domain/incoming-request';
import { utf8 } from '../crypto/web-crypto';
import { bodyFingerprint } from './event-keys';
import {
  type Reading,
  type SchemeConfig,
  type SchemeDefinition,
  schemeVerifier,
} from './scheme-verifier';

const decoder = new TextDecoder();

/**
 * Arma el verificador de un esquema de token compartido (sección 5.12): el secreto es el token
 * y lo esperado es el secreto mismo. Así el recorrido de la sección 4.1 (el orden, la rotación
 * y la comparación en tiempo constante) es el mismo que el de los esquemas que firman.
 */
export function tokenVerifier(
  read: SchemeDefinition<Reading>['read'],
  config: SchemeConfig,
): Verifier {
  return schemeVerifier<Reading>(
    { keyOf: utf8, read, expected: (key) => decoder.decode(key) },
    { secrets: config.secrets },
  );
}

/** Un nombre de cabecera, de parámetro o de esquema: un texto que no está en blanco. */
export function checkedName(option: string, value: unknown): string {
  if (typeof value !== 'string' || value.trim() === '') {
    throw new ConfigurationError(`${option} no puede estar vacío`);
  }
  return value;
}

export interface SharedTokenOptions extends SchemeConfig {
  /** La cabecera que trae el token. Hay que dar `header` o `query`, y sólo uno de los dos. */
  readonly header?: string;
  /** El parámetro de la URL que trae el token. */
  readonly query?: string;
  /** El nombre del esquema en la clave del evento. Por defecto, `shared-token`. */
  readonly name?: string;
  /** La cabecera que identifica el evento. Sin ella, la clave es la huella del cuerpo. */
  readonly idHeader?: string;
}

/**
 * Verifica a un emisor que manda un token secreto, tal cual, en una cabecera o en la URL
 * (sección 5.12).
 *
 * El token no cubre el cuerpo ni las demás cabeceras: conviene tratar el aviso como una señal
 * de cambio y consultar el recurso al emisor antes de actuar. Un token en la URL suele quedar
 * en los logs de acceso.
 */
export function sharedTokenScheme(options: SharedTokenOptions): Verifier {
  if ((options.header === undefined) === (options.query === undefined)) {
    throw new ConfigurationError('hay que configurar header o query, y sólo uno de los dos');
  }
  const inQuery = options.query !== undefined;
  const field = inQuery
    ? checkedName('query', options.query)
    : checkedName('header', options.header);
  const name = checkedName('name', options.name ?? 'shared-token');
  const idHeader =
    options.idHeader === undefined ? undefined : checkedName('idHeader', options.idHeader);

  return tokenVerifier((request: IncomingRequest) => {
    const fields = pickSingles(
      { token: fieldValues(inQuery ? request.query : request.headers, field) },
      { id: idHeader === undefined ? [] : fieldValues(request.headers, idHeader) },
    );
    if (typeof fields === 'string') return fields;
    const { id } = fields;
    return {
      timestamp: null,
      received: [fields.token],
      eventKey: () => (id === undefined ? bodyFingerprint(name, request.body) : eventKey(name, id)),
    };
  }, options);
}
