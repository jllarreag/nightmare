import { HttpClient, HttpHeaders, HttpParams } from '@angular/common/http';
import { inject, Injectable, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ErrorKey, GALLERY_PAGE_SIZE, GalleryPage, GalleryStory } from './api';
import { ConfigService } from './config';
import { I18n } from './i18n';
import { toErrorKey } from './story-store';

/** Public gallery: paginated list in the UI language, newest first. */
@Injectable({ providedIn: 'root' })
export class GalleryStore {
  private readonly http = inject(HttpClient);
  private readonly config = inject(ConfigService);
  private readonly i18n = inject(I18n);

  readonly stories = signal<GalleryStory[]>([]);
  readonly nextCursor = signal<string | null>(null);
  readonly loading = signal(false);
  readonly loaded = signal(false);
  readonly error = signal<ErrorKey | null>(null);

  /** Ignores answers of requests that were replaced by a newer one (e.g. language change). */
  private generation = 0;

  /** `reset` loads the first page; otherwise the next page with the saved cursor. */
  async load(reset: boolean): Promise<void> {
    if (!this.config.apiUrl) {
      this.error.set('config');
      return;
    }
    const cursor = reset ? null : this.nextCursor();
    if (!reset && !cursor) return;
    const generation = ++this.generation;
    if (reset) {
      this.stories.set([]);
      this.nextCursor.set(null);
      this.loaded.set(false);
    }
    this.loading.set(true);
    this.error.set(null);
    let params = new HttpParams()
      .set('language', this.i18n.lang())
      .set('limit', GALLERY_PAGE_SIZE);
    if (cursor) params = params.set('cursor', cursor);
    try {
      const page = await firstValueFrom(
        this.http.get<GalleryPage>(`${this.config.apiUrl}/gallery`, { params }),
      );
      if (generation !== this.generation) return;
      this.stories.update((list) => [...list, ...page.stories]);
      this.nextCursor.set(page.next_cursor);
      this.loaded.set(true);
    } catch (error) {
      if (generation !== this.generation) return;
      this.error.set(toErrorKey(error));
    } finally {
      if (generation === this.generation) this.loading.set(false);
    }
  }

  /** Deletes a story with its private token. Returns null on success or the error to show. */
  async remove(id: string, token: string): Promise<ErrorKey | null> {
    if (!this.config.apiUrl) return 'config';
    try {
      await firstValueFrom(
        this.http.delete(`${this.config.apiUrl}/gallery/${encodeURIComponent(id)}`, {
          headers: new HttpHeaders({ 'x-delete-token': token }),
        }),
      );
      this.stories.update((list) => list.filter((s) => s.id !== id));
      return null;
    } catch (error) {
      return toErrorKey(error);
    }
  }
}
