import { afterNextRender, Component, ElementRef, inject, signal, viewChild } from '@angular/core';
import { ErrorKey } from './api';
import { GalleryStore } from './gallery-store';
import { I18n } from './i18n';
import { Nav } from './nav';

/**
 * Opened from the private deletion link. It never deletes on load (link previews and
 * prefetchers would trigger it): the person has to press the button.
 */
@Component({
  selector: 'app-delete-story',
  templateUrl: './delete-story.html',
})
export class DeleteStory {
  protected readonly i18n = inject(I18n);
  protected readonly nav = inject(Nav);
  private readonly gallery = inject(GalleryStore);

  protected readonly busy = signal(false);
  protected readonly done = signal(false);
  protected readonly error = signal<ErrorKey | null>(null);

  private readonly heading = viewChild.required<ElementRef<HTMLElement>>('heading');

  constructor() {
    afterNextRender(() => this.heading().nativeElement.focus());
    // Opened without a valid id/token (bad link, or reloaded after deleting).
    if (!this.nav.deleteParams()) this.error.set('not_found');
  }

  protected async confirm(): Promise<void> {
    const params = this.nav.deleteParams();
    if (!params || this.busy()) return;
    this.busy.set(true);
    this.error.set(null);
    const error = await this.gallery.remove(params.id, params.token);
    this.busy.set(false);
    if (error === null) {
      this.done.set(true);
      this.nav.scrubToken();
    } else {
      this.error.set(error);
      if (error === 'not_found') this.nav.scrubToken();
    }
  }
}
