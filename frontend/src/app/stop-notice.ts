import { afterNextRender, Component, ElementRef, inject, input, viewChild } from '@angular/core';
import { StoppedResponse } from './api';
import { I18n } from './i18n';
import { StoryStore } from './story-store';

/** Shown when moderation ends the session. Risk cases list help resources, never a cold cut-off. */
@Component({
  selector: 'app-stop-notice',
  templateUrl: './stop-notice.html',
})
export class StopNotice {
  readonly stop = input.required<StoppedResponse>();

  protected readonly i18n = inject(I18n);
  protected readonly store = inject(StoryStore);

  private readonly heading = viewChild.required<ElementRef<HTMLElement>>('heading');

  constructor() {
    afterNextRender(() => this.heading().nativeElement.focus());
  }

  protected href(contact: string): string {
    return contact.startsWith('https://') ? contact : `tel:${contact.replace(/\s+/g, '')}`;
  }
}
