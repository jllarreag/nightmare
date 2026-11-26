import { Injectable, signal } from '@angular/core';

export type View = 'home' | 'gallery' | 'delete';

export interface DeleteParams {
  id: string;
  token: string;
}

const DELETE_HASH = /^#\/delete\/([A-Za-z0-9_-]+)\/([A-Za-z0-9_-]+)$/;

/**
 * Tiny hash-based views (no router): `#/gallery` and `#/delete/<id>/<token>`.
 * The hash never reaches a server, so the deletion token stays out of CloudFront logs.
 */
@Injectable({ providedIn: 'root' })
export class Nav {
  readonly view = signal<View>('home');
  readonly deleteParams = signal<DeleteParams | null>(null);

  constructor() {
    this.read();
    window.addEventListener('hashchange', () => this.read());
  }

  /** Removes the token from the address bar once it is no longer needed. */
  scrubToken(): void {
    history.replaceState(null, '', `${location.pathname}${location.search}#/deleted`);
  }

  private read(): void {
    const hash = location.hash;
    const del = DELETE_HASH.exec(hash);
    if (del) {
      this.deleteParams.set({ id: del[1], token: del[2] });
      this.view.set('delete');
    } else if (hash === '#/deleted') {
      // The token was scrubbed from the address bar: stay on the delete view, without params.
      this.deleteParams.set(null);
      this.view.set('delete');
    } else if (hash === '#/gallery') {
      this.deleteParams.set(null);
      this.view.set('gallery');
    } else {
      this.deleteParams.set(null);
      this.view.set('home');
    }
  }
}
