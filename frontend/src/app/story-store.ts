import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { computed, inject, Injectable, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiResponse, ErrorKey, PublishResponse, Step, StoppedResponse } from './api';
import { ConfigService } from './config';
import { I18n } from './i18n';

export type Phase = 'intro' | 'story' | 'stopped';

const KNOWN_ERRORS: readonly ErrorKey[] = [
  'busy',
  'unavailable',
  'nightmare_length',
  'session_not_found',
  'session_finished',
  'session_not_finished',
  'already_published',
  'not_publishable',
  'not_found',
  'consent',
];

/** Errors after which retrying the same call makes no sense. */
const FINAL_ERRORS: readonly ErrorKey[] = [
  'session_not_found',
  'session_finished',
  'session_not_finished',
  'already_published',
  'not_publishable',
  'config',
];

export function toErrorKey(error: unknown): ErrorKey {
  if (error instanceof HttpErrorResponse) {
    if (error.status === 0) return 'network';
    const code = (error.error as { error?: unknown } | null)?.error;
    if (typeof code === 'string' && (KNOWN_ERRORS as string[]).includes(code)) {
      return code as ErrorKey;
    }
  }
  return 'generic';
}

/** Result of publishing: the deletion link lives in memory only, never in storage. */
export interface Published {
  storyId: string;
  token: string;
  link: string;
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
  readonly publishing = signal(false);
  readonly published = signal<Published | null>(null);
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

  /** Opt-in: publishes the finished story anonymized and returns a private deletion link. */
  publish(): Promise<void> {
    const id = this.sessionId;
    if (!id || this.publishing() || this.published()) return Promise.resolve();
    return this.run(() => this.sendPublish(id));
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
    this.published.set(null);
    this.sessionId = null;
    this.lastCall = null;
  }

  private async run(call: () => Promise<void>): Promise<void> {
    this.lastCall = call;
    await call();
  }

  private async sendPublish(id: string): Promise<void> {
    if (!this.config.apiUrl) {
      this.error.set('config');
      return;
    }
    this.publishing.set(true);
    this.error.set(null);
    try {
      const res = await firstValueFrom(
        this.http.post<PublishResponse>(
          `${this.config.apiUrl}/sessions/${encodeURIComponent(id)}/publish`,
          { consent: true },
        ),
      );
      this.lastCall = null;
      const link = `${location.origin}${location.pathname}#/delete/${res.story_id}/${res.delete_token}`;
      this.published.set({ storyId: res.story_id, token: res.delete_token, link });
    } catch (error) {
      this.error.set(toErrorKey(error));
    } finally {
      this.publishing.set(false);
    }
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
