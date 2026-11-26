import {
  afterNextRender,
  Component,
  effect,
  ElementRef,
  inject,
  untracked,
  viewChild,
} from '@angular/core';
import { I18n } from './i18n';
import { GalleryStore } from './gallery-store';

/** Public gallery of anonymized stories. Images are optional: none exist until task 5. */
@Component({
  selector: 'app-gallery',
  templateUrl: './gallery.html',
})
export class Gallery {
  protected readonly i18n = inject(I18n);
  protected readonly gallery = inject(GalleryStore);

  private readonly heading = viewChild.required<ElementRef<HTMLElement>>('heading');

  constructor() {
    afterNextRender(() => this.heading().nativeElement.focus());
    // Loads the first page on entry and again whenever the UI language changes.
    effect(() => {
      this.i18n.lang();
      untracked(() => void this.gallery.load(true));
    });
  }

  protected date(seconds: number): string {
    return new Date(seconds * 1000).toLocaleDateString(this.i18n.lang());
  }

  protected iso(seconds: number): string {
    return new Date(seconds * 1000).toISOString().slice(0, 10);
  }
}
