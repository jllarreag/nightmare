import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { computed, DestroyRef, inject, Injectable, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import {
  ApiResponse,
  ErrorKey,
  ImagesResponse,
  ImageState,
  PublishResponse,
  Step,
  StoppedResponse,
} from './api';
import { ConfigService } from './config';
import { I18n } from './i18n';

export type Phase = 'intro' | 'story' | 'stopped';

const IMAGE_POLL_MS = 4000;
const IMAGE_POLL_MAX_TRIES = 15;

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
  private readonly destroyRef = inject(DestroyRef);

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

  /** Image state per step number, filled by polling. Errors while polling are silent. */
  readonly images = signal<Record<string, ImageState>>({});
  /** True when polling ended without every image reaching ready/failed. */
  readonly imagesGaveUp = signal(false);

  private sessionId: string | null = null;
  private pollTimer: ReturnType<typeof setTimeout> | null = null;
  private pollGeneration = 0;
  private polling = false;
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

  /** Image for a step: its own, or the latest ready image of an earlier step (decorative). */
  imageFor(step: Step): { state: ImageState; own: boolean } | null {
    const images = this.images();
    if (step.has_image) {
      const own = images[String(step.step)];
      const gaveUp = this.imagesGaveUp();
      if (own && !(own.status === 'pending' && gaveUp)) return { state: own, own: true };
      return { state: { status: gaveUp ? 'failed' : 'pending', url: null }, own: true };
    }
    for (let n = step.step - 1; n >= 1; n--) {
      const earlier = images[String(n)];
      if (earlier?.status === 'ready' && earlier.url) return { state: earlier, own: false };
    }
    return null;
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
    this.stopPolling();
    this.images.set({});
    this.imagesGaveUp.set(false);
  }

  constructor() {
    this.destroyRef.onDestroy(() => this.stopPolling());
  }

  private stopPolling(): void {
    this.pollGeneration++;
    if (this.pollTimer !== null) clearTimeout(this.pollTimer);
    this.pollTimer = null;
    this.polling = false;
  }

  /** Starts one polling loop for the session unless one is already running. */
  private startPolling(id: string): void {
    if (this.polling || !this.config.apiUrl) return;
    this.polling = true;
    this.imagesGaveUp.set(false);
    const generation = this.pollGeneration;
    const tick = (tries: number): void => {
      this.pollTimer = setTimeout(async () => {
        this.pollTimer = null;
        let settled = false;
        try {
          const res = await firstValueFrom(
            this.http.get<ImagesResponse>(
              `${this.config.apiUrl}/sessions/${encodeURIComponent(id)}/images`,
            ),
          );
          if (generation !== this.pollGeneration) return;
          this.images.set(res.images ?? {});
          settled = this.steps()
            .filter((s) => s.has_image)
            .every((s) => (res.images?.[String(s.step)]?.status ?? 'pending') !== 'pending');
        } catch {
          if (generation !== this.pollGeneration) return;
        }
        if (settled) {
          this.polling = false;
          return;
        }
        if (tries + 1 >= IMAGE_POLL_MAX_TRIES) {
          this.polling = false;
          this.imagesGaveUp.set(true);
          return;
        }
        tick(tries + 1);
      }, IMAGE_POLL_MS);
    };
    tick(0);
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
        if (res.step.has_image) this.startPolling(res.session_id);
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
