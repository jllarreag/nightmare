import { JsonPipe } from '@angular/common';
import { Component, computed, inject } from '@angular/core';
import { Lang } from './api';
import { DeleteStory } from './delete-story';
import { Gallery } from './gallery';
import { I18n } from './i18n';
import { Nav } from './nav';
import { NightmareForm } from './nightmare-form';
import { StopNotice } from './stop-notice';
import { StoryStep } from './story-step';
import { StoryStore } from './story-store';

@Component({
  selector: 'app-root',
  imports: [JsonPipe, NightmareForm, StopNotice, StoryStep, Gallery, DeleteStory],
  templateUrl: './app.html',
})
export class App {
  protected readonly i18n = inject(I18n);
  protected readonly store = inject(StoryStore);
  protected readonly nav = inject(Nav);
  /** The story language is fixed once a story starts, but stays free in the gallery. */
  protected readonly languageLocked = computed(
    () => this.nav.view() === 'home' && this.store.phase() !== 'intro',
  );
  protected readonly langs: readonly Lang[] = ['es', 'en'];
  /** Add ?debug to the URL to see the raw API responses. */
  protected readonly debug = new URLSearchParams(location.search).has('debug');
}
