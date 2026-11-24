import {
  context,
  type Meter,
  propagation,
  SpanKind,
  SpanStatusCode,
  type Tracer,
  trace,
} from '@opentelemetry/api';
import type {
  AttemptRecord,
  DeliveryLedger,
  EndpointFailureSource,
  HttpTransport,
  ReceptionObservation,
  ReceptionObserver,
  TransportRequest,
  TransportResponse,
} from '../../application/ports';

// Los nombres de las métricas y de los atributos son los mismos en los dos paquetes: los
// paneles y las alertas sirven para un servicio en cualquiera de los dos lenguajes.
export const OTEL_NAMES = {
  receptions: 'omniwebhook.receptions',
  receptionDuration: 'omniwebhook.reception.duration',
  attempts: 'omniwebhook.delivery.attempts',
  attemptDuration: 'omniwebhook.delivery.attempt.duration',
  outcome: 'omniwebhook.reception.outcome',
  deliveryClass: 'omniwebhook.delivery.class',
  deliveryState: 'omniwebhook.delivery.state',
  messageId: 'omniwebhook.message.id',
} as const;

/**
 * Cuenta las recepciones por resultado y mide cuánto tardan (sección 6.4). Va en `observer`.
 *
 * No pone la clave del evento como atributo: cada evento tiene la suya, y una métrica con un
 * valor distinto por evento no se puede agregar.
 */
export function otelReceptionObserver(options: { readonly meter: Meter }): ReceptionObserver {
  const receptions = options.meter.createCounter(OTEL_NAMES.receptions, {
    description: 'Pedidos de webhook recibidos, por resultado',
    unit: '{reception}',
  });
  const duration = options.meter.createHistogram(OTEL_NAMES.receptionDuration, {
    description: 'Cuánto lleva recibir un webhook, incluido el procesamiento',
    unit: 's',
  });

  return {
    onReception({ outcome, durationMs }: ReceptionObservation): void {
      const attributes = { [OTEL_NAMES.outcome]: outcome };
      receptions.add(1, attributes);
      duration.record(durationMs / 1000, attributes);
    },
  };
}

/**
 * Envuelve un registro de entregas: guarda cada intento en el registro de adentro y además
 * cuenta los intentos por clase y estado, y mide su duración. Va en `ledger`.
 *
 * No pone el destino ni el mensaje como atributos, por lo mismo que la recepción.
 */
export function otelDeliveryLedger(
  ledger: DeliveryLedger,
  options: { readonly meter: Meter },
): DeliveryLedger & EndpointFailureSource {
  const attempts = options.meter.createCounter(OTEL_NAMES.attempts, {
    description: 'Intentos de entrega de webhooks, por clase y estado en que quedó la entrega',
    unit: '{attempt}',
  });
  const duration = options.meter.createHistogram(OTEL_NAMES.attemptDuration, {
    description: 'Cuánto lleva un intento de entrega',
    unit: 's',
  });

  return {
    async record(attempt: AttemptRecord): Promise<void> {
      await ledger.record(attempt);
      const attributes = {
        [OTEL_NAMES.deliveryClass]: attempt.deliveryClass,
        [OTEL_NAMES.deliveryState]: attempt.state,
        ...(attempt.status === null ? {} : { 'http.response.status_code': attempt.status }),
      };
      attempts.add(1, attributes);
      duration.record(attempt.durationMs / 1000, attributes);
    },
    // Para que el mismo objeto sirva como fuente de la salud de los destinos.
    async failuresOf(endpointId: string, since: number) {
      const source = ledger as Partial<EndpointFailureSource>;
      if (typeof source.failuresOf !== 'function') {
        throw new Error('el registro envuelto no da el resumen de fallos de un destino');
      }
      return source.failuresOf(endpointId, since);
    },
  };
}

/** Lo que se puede decir del destino sin filtrar su URL: puede llevar un token en la ruta. */
function destination(url: string): Record<string, string | number> {
  try {
    const parsed = new URL(url);
    const standard = parsed.protocol === 'https:' ? 443 : 80;
    return {
      'server.address': parsed.hostname,
      'server.port': parsed.port === '' ? standard : Number(parsed.port),
      'url.scheme': parsed.protocol.replace(':', ''),
    };
  } catch {
    return {};
  }
}

/**
 * Envuelve un transporte: cada intento es un tramo de cliente HTTP, con los atributos de las
 * convenciones semánticas, y lleva la cabecera `traceparent` para que quien recibe lo vea como
 * continuación de la operación que lo originó. Va en `transport`.
 *
 * El tramo nunca lleva la URL completa, ni el cuerpo, ni la firma.
 */
export function otelTransport(
  transport: HttpTransport,
  options: { readonly tracer: Tracer },
): HttpTransport {
  return {
    async post(request: TransportRequest): Promise<TransportResponse> {
      const messageId = request.headers['webhook-id'];
      const span = options.tracer.startSpan('POST', {
        kind: SpanKind.CLIENT,
        attributes: {
          'http.request.method': 'POST',
          ...destination(request.url),
          ...(messageId === undefined ? {} : { [OTEL_NAMES.messageId]: messageId }),
        },
      });
      const fail = (type: string): void => {
        span.setAttribute('error.type', type);
        span.setStatus({ code: SpanStatusCode.ERROR });
      };
      const headers: Record<string, string> = { ...request.headers };
      propagation.inject(trace.setSpan(context.active(), span), headers);

      try {
        const response = await transport.post({ ...request, headers });
        if ('status' in response) {
          span.setAttribute('http.response.status_code', response.status);
          if (response.status >= 400) fail(String(response.status));
        } else {
          fail(response.failure);
        }
        return response;
      } catch (error) {
        fail(error instanceof Error ? error.name : 'error');
        throw error;
      } finally {
        span.end();
      }
    },
  };
}
