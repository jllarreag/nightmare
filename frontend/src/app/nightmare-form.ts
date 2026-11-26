import { Component, computed, inject, signal } from '@angular/core';
import { MAX_CHARS, MIN_CHARS } from './api';
import { I18n } from './i18n';
import { StoryStore } from './story-store';

@Component({
  selector: 'app-nightmare-form',
  templateUrl: './nightmare-form.html',
})
export class NightmareForm {
  protected readonly i18n = inject(I18n);
  protected readonly store = inject(StoryStore);
  protected readonly max = MAX_CHARS;

  protected readonly text = signal('');
  protected readonly length = computed(() => this.text().trim().length);
  protected readonly valid = computed(() => this.length() >= MIN_CHARS && this.length() <= MAX_CHARS);

  protected onInput(event: Event): void {
    this.text.set((event.target as HTMLTextAreaElement).value);
  }

  protected submit(event: Event): void {
    event.preventDefault();
    if (this.valid() && !this.store.loading()) {
      void this.store.start(this.text().trim());
    }
  }
}
