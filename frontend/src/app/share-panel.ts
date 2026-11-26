import {
  afterRenderEffect,
  Component,
  ElementRef,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { I18n } from './i18n';
import { StoryStore } from './story-store';

/** Opt-in sharing of a finished story. Shows the private deletion link once, in memory only. */
@Component({
  selector: 'app-share-panel',
  templateUrl: './share-panel.html',
})
export class SharePanel {
  protected readonly i18n = inject(I18n);
  protected readonly store = inject(StoryStore);
  protected readonly consent = signal(false);
  protected readonly copied = signal(false);

  private readonly doneHeading = viewChild<ElementRef<HTMLElement>>('doneHeading');
  private readonly linkInput = viewChild<ElementRef<HTMLInputElement>>('linkInput');

  constructor() {
    // Move focus to the result so keyboard and screen-reader users find the link.
    afterRenderEffect(() => this.doneHeading()?.nativeElement.focus());
  }

  protected onConsent(event: Event): void {
    this.consent.set((event.target as HTMLInputElement).checked);
  }

  protected share(): void {
    if (this.consent()) void this.store.publish();
  }

  protected async copy(link: string): Promise<void> {
    try {
      await navigator.clipboard.writeText(link);
    } catch {
      this.linkInput()?.nativeElement.select();
      return;
    }
    this.copied.set(true);
  }
}
