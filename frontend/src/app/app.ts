import { JsonPipe } from '@angular/common';
import { Component, inject } from '@angular/core';
import { Lang } from './api';
import { I18n } from './i18n';
import { NightmareForm } from './nightmare-form';
import { StopNotice } from './stop-notice';
import { StoryStep } from './story-step';
import { StoryStore } from './story-store';

@Component({
  selector: 'app-root',
  imports: [JsonPipe, NightmareForm, StopNotice, StoryStep],
  templateUrl: './app.html',
})
export class App {
  protected readonly i18n = inject(I18n);
  protected readonly store = inject(StoryStore);
  protected readonly langs: readonly Lang[] = ['es', 'en'];
  /** Add ?debug to the URL to see the raw API responses. */
  protected readonly debug = new URLSearchParams(location.search).has('debug');
}
