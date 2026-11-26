import { afterRenderEffect, Component, ElementRef, inject, input, viewChild } from '@angular/core';
import { Step, TOTAL_STEPS } from './api';
import { I18n } from './i18n';
import { SharePanel } from './share-panel';
import { StoryStore } from './story-store';

@Component({
  selector: 'app-story-step',
  imports: [SharePanel],
  templateUrl: './story-step.html',
})
export class StoryStep {
  readonly step = input.required<Step>();
  readonly finished = input(false);

  protected readonly i18n = inject(I18n);
  protected readonly store = inject(StoryStore);
  protected readonly total = TOTAL_STEPS;
  protected readonly dots = Array.from({ length: TOTAL_STEPS }, (_, i) => i + 1);

  private readonly heading = viewChild.required<ElementRef<HTMLElement>>('heading');

  constructor() {
    // Move focus to the new step title so keyboard and screen-reader users follow the story.
    afterRenderEffect(() => {
      this.step();
      this.heading().nativeElement.focus();
    });
  }
}
