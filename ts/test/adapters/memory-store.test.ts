import { MemoryIdempotencyStore } from '../../src/index';
import { describeIdempotencyStore } from '../contracts/idempotency-store';

describeIdempotencyStore('MemoryIdempotencyStore', () => new MemoryIdempotencyStore());
