import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { computed, inject, Injectable, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiResponse, ErrorKey, Step, StoppedResponse } from './api';
import { ConfigService } from './config';
import { I18n } from './i18n';

export type Phase = 'intro' | 'story' | 'stopped';

const KNOWN_ERRORS: readonly ErrorKey[] = [
  'busy',
  'unavailable',
  'nightmare_length',
  'session_not_found',
  'session_finished',
];

/** Errors after which retrying the same call makes no sense. */
const FINAL_ERRORS: readonly ErrorKey[] = ['session_not_found', 'session_finished', 'config'];

function toErrorKey(error: unknown): ErrorKey {
  if (error instanceof HttpErrorResponse) {
    if (error.status === 0) return 'network';
    const code = (error.error as { error?: unknown } | null)?.error;
    if (typeof code === 'string' && (KNOWN_ERRORS as string[]).includes(code)) {
      return code as ErrorKey;
    }
  }
  return 'generic';
}

/** State of the current story. One session at a time, nothing persisted in the browser. */
@Injectable({ providedIn: 'root' })
export class StoryStore {
  private readonly http = inject(HttpClient);
  private readonly config = inject(ConfigService);
  private readonly i18n = inject(I18n);

  readonly phase = signal<Phase>('intro');
  readonly steps = signal<Step[]>([]);
  readonly current = computed<Step | null>(() => this.steps().at(-1) ?? null);
  readonly finished = signal(false);
  readonly loading = signal(false);
  readonly error = signal<ErrorKey | null>(null);
  readonly stop = signal<StoppedResponse | null>(null);
  /** Last raw response or error, shown in the debug panel (?debug). */
  readonly lastResponse = signal<unknown>(null);

  private sessionId: string | null = null;
  private lastCall: (() => Promise<void>) | null = null;

  readonly canRetry = computed(() => {
    const err = this.error();
    return err !== null && !FINAL_ERRORS.includes(err);
  });

  start(nightmare: string): Promise<void> {
    const body = { nightmare, language: this.i18n.lang() };
    return this.run(() => this.send('/sessions', body));
  }

  choose(choiceId: string): Promise<void> {
    const id = this.sessionId;
    if (!id || this.loading()) return Promise.resolve();
    return this.run(() => this.send(`/sessions/${encodeURIComponent(id)}/steps`, { choice_id: choiceId }));
  }

  retry(): Promise<void> {
    return this.lastCall ? this.run(this.lastCall) : Promise.resolve();
  }

  reset(): void {
    this.phase.set('intro');
    this.steps.set([]);
    this.finished.set(false);
    this.error.set(null);
    this.stop.set(null);
    this.sessionId = null;
    this.lastCall = null;
  }

  private async run(call: () => Promise<void>): Promise<void> {
    this.lastCall = call;
    await call();
  }

  private async send(path: string, body: object): Promise<void> {
    if (!this.config.apiUrl) {
      this.error.set('config');
      return;
    }
    this.loading.set(true);
    this.error.set(null);
    try {
      const res = await firstValueFrom(
        this.http.post<ApiResponse>(this.config.apiUrl + path, body),
      );
      this.lastResponse.set(res);
      this.lastCall = null;
      if (res.status === 'stopped') {
        this.sessionId = null;
        this.stop.set(res);
        this.phase.set('stopped');
      } else {
        this.sessionId = res.session_id;
        this.steps.update((steps) => [...steps, res.step]);
        this.finished.set(res.finished ?? false);
        this.phase.set('story');
      }
    } catch (error) {
      this.lastResponse.set(
        error instanceof HttpErrorResponse
          ? { httpStatus: error.status, body: error.error }
          : String(error),
      );
      this.error.set(toErrorKey(error));
    } finally {
      this.loading.set(false);
    }
  }
}
