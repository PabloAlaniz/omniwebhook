/**
 * Telemetría con OpenTelemetry. Vive en una entrada aparte porque es la única que necesita
 * `@opentelemetry/api`.
 */
export {
  OTEL_NAMES,
  otelDeliveryLedger,
  otelReceptionObserver,
  otelTransport,
} from './adapters/telemetry/otel';
