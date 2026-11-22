import { readFileSync } from 'node:fs';
import type { IncomingRequest } from '../../src/index';

const RAIZ = new URL('../../../spec/vectors/', import.meta.url);

export interface VectorFile<C> {
  readonly spec: string;
  readonly id: string;
  readonly kind: string;
  readonly cases: readonly C[];
}

export function loadVector<C>(id: string): VectorFile<C> {
  return JSON.parse(readFileSync(new URL(`${id}.json`, RAIZ), 'utf8')) as VectorFile<C>;
}

export interface RequestVector {
  readonly headers: ReadonlyArray<readonly [string, string]>;
  readonly query: ReadonlyArray<readonly [string, string]>;
  readonly body: string;
}

export function toRequest(vector: RequestVector): IncomingRequest {
  return {
    headers: vector.headers,
    query: vector.query,
    body: new TextEncoder().encode(vector.body),
  };
}

export interface VerifyCase {
  readonly name: string;
  readonly scheme: string;
  readonly options?: Readonly<Record<string, unknown>>;
  readonly secrets: readonly string[];
  readonly now: number;
  readonly request: RequestVector;
  readonly expected: {
    readonly outcome: string;
    readonly event_key?: string;
    readonly timestamp?: number | null;
  };
}

export type StoreStep =
  | {
      readonly op: 'claim';
      readonly key: string;
      readonly token: string;
      readonly now: number;
      readonly lease_seconds: number;
      readonly expected: string;
    }
  | {
      readonly op: 'complete';
      readonly key: string;
      readonly token: string;
      readonly now: number;
      readonly retention_seconds: number;
      readonly expected: boolean;
    }
  | {
      readonly op: 'release';
      readonly key: string;
      readonly token: string;
      readonly expected: boolean;
    };
