import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { App } from './app';
import { ConfigService } from './config';
import { I18n } from './i18n';
import { StoryStore } from './story-store';

const API = 'https://api.test';

const closing = {
  step: 5,
  title: 'Cierre',
  narration: 'Respiras hondo.',
  technique: 'closing',
  choices: [],
  learning: 'El miedo se encoge.',
  coping_tip: 'Ensaya el final.',
  has_image: false,
};

function galleryStory(id: string, title: string, image: string | null = null) {
  return {
    id,
    language: 'es',
    created_at: 1_700_000_000,
    steps: [
      {
        step: 1,
        title,
        narration: 'Un pasillo largo.',
        learning: null,
        coping_tip: null,
        has_image: true,
        image,
      },
    ],
  };
}

describe('Gallery', () => {
  let http: HttpTestingController;

  async function setup(hash = ''): Promise<ComponentFixture<App>> {
    location.hash = hash;
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
    TestBed.inject(ConfigService).apiUrl = API;
    TestBed.inject(I18n).setLang('es');
    http = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    return fixture;
  }

  afterEach(() => {
    TestBed.inject(StoryStore).reset();
    http.verify();
    location.hash = '';
  });

  async function finishStory(fixture: ComponentFixture<App>): Promise<void> {
    const store = TestBed.inject(StoryStore);
    const started = store.start('Sueño que me persigue una sombra por un pasillo');
    http.expectOne(`${API}/sessions`).flush({
      status: 'ok',
      session_id: 's1',
      step: { ...closing, step: 1, technique: 'recreate', has_image: true },
    });
    await started;
    const done = store.choose('a');
    http
      .expectOne(`${API}/sessions/s1/steps`)
      .flush({ status: 'ok', session_id: 's1', step: closing, finished: true });
    await done;
    fixture.detectChanges();
  }

  it('keeps the share button disabled until the consent box is checked, then publishes', async () => {
    const fixture = await setup();
    await finishStory(fixture);
    const el = fixture.nativeElement as HTMLElement;
    const button = el.querySelector('.share button.btn') as HTMLButtonElement;
    expect(button.disabled).toBe(true);

    const checkbox = el.querySelector('.share input[type=checkbox]') as HTMLInputElement;
    checkbox.click();
    fixture.detectChanges();
    expect(button.disabled).toBe(false);

    button.click();
    const req = http.expectOne(`${API}/sessions/s1/publish`);
    expect(req.request.body).toEqual({ consent: true });
    req.flush({ status: 'ok', story_id: 'abc', delete_token: 'tok123', expires_at: null });
    await fixture.whenStable();
    fixture.detectChanges();

    const link = el.querySelector('input.link-input') as HTMLInputElement;
    expect(link.value).toContain('#/delete/abc/tok123');
  });

  it('shows an error message when the story cannot be published', async () => {
    const fixture = await setup();
    await finishStory(fixture);
    const store = TestBed.inject(StoryStore);
    const published = store.publish();
    http
      .expectOne(`${API}/sessions/s1/publish`)
      .flush({ error: 'not_publishable' }, { status: 422, statusText: 'Unprocessable' });
    await published;
    fixture.detectChanges();
    expect(store.error()).toBe('not_publishable');
    expect(store.canRetry()).toBe(false);
    expect((fixture.nativeElement as HTMLElement).querySelector('.alert')?.textContent).toContain(
      'No hemos podido preparar',
    );
  });

  it('lists stories and loads more with the cursor', async () => {
    const fixture = await setup('#/gallery');
    const first = http.expectOne((r) => r.url === `${API}/gallery`);
    expect(first.request.params.get('language')).toBe('es');
    expect(first.request.params.get('limit')).toBe('6');
    expect(first.request.params.has('cursor')).toBe(false);
    first.flush({ stories: [galleryStory('a', 'Historia A')], next_cursor: 'c1' });
    await fixture.whenStable();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelectorAll('article.gallery-card').length).toBe(1);
    expect(el.querySelector('article h2')?.textContent).toContain('Historia A');
    expect(el.querySelector('article img')).toBeNull();

    (el.querySelector('button.load-more') as HTMLButtonElement).click();
    const next = http.expectOne((r) => r.url === `${API}/gallery`);
    expect(next.request.params.get('cursor')).toBe('c1');
    next.flush({ stories: [galleryStory('b', 'Historia B')], next_cursor: null });
    await fixture.whenStable();
    fixture.detectChanges();
    expect(el.querySelectorAll('article.gallery-card').length).toBe(2);
    expect(el.querySelector('button.load-more')).toBeNull();
  });

  it('shows the step-1 image as card cover and still works without image', async () => {
    const fixture = await setup('#/gallery');
    http.expectOne((r) => r.url === `${API}/gallery`).flush({
      stories: [
        galleryStory('a', 'Con imagen', 'https://img.test/a.jpg'),
        galleryStory('b', 'Sin imagen'),
      ],
      next_cursor: null,
    });
    await fixture.whenStable();
    fixture.detectChanges();
    const cards = (fixture.nativeElement as HTMLElement).querySelectorAll('article.gallery-card');
    const cover = cards[0].querySelectorAll('img');
    expect(cover.length).toBe(1);
    expect(cover[0].getAttribute('src')).toBe('https://img.test/a.jpg');
    expect(cover[0].getAttribute('alt')).toBe('Ilustración de la historia');
    expect(cover[0].getAttribute('loading')).toBe('lazy');
    expect(cards[1].querySelector('img')).toBeNull();
  });

  it('shows the empty state when there are no stories', async () => {
    const fixture = await setup('#/gallery');
    http.expectOne((r) => r.url === `${API}/gallery`).flush({ stories: [], next_cursor: null });
    await fixture.whenStable();
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).querySelector('.empty')?.textContent).toContain(
      'Todavía no hay historias',
    );
  });

  it('opens a deletion link, asks first and sends the token in a header', async () => {
    const fixture = await setup('#/delete/abc/tok');
    const el = fixture.nativeElement as HTMLElement;
    http.expectNone(`${API}/gallery/abc`);
    const button = el.querySelector('button.btn.primary') as HTMLButtonElement;
    expect(button.textContent).toContain('Borrar mi historia');

    button.click();
    const req = http.expectOne(`${API}/gallery/abc`);
    expect(req.request.method).toBe('DELETE');
    expect(req.request.headers.get('x-delete-token')).toBe('tok');
    req.flush({ status: 'deleted' });
    await fixture.whenStable();
    fixture.detectChanges();
    expect(el.querySelector('[role=status]')?.textContent).toContain('se ha borrado');
    expect(location.hash).not.toContain('tok');
  });

  it('explains when the story to delete does not exist', async () => {
    const fixture = await setup('#/delete/abc/bad');
    const el = fixture.nativeElement as HTMLElement;
    (el.querySelector('button.btn.primary') as HTMLButtonElement).click();
    http
      .expectOne(`${API}/gallery/abc`)
      .flush({ error: 'not_found' }, { status: 404, statusText: 'Not Found' });
    await fixture.whenStable();
    fixture.detectChanges();
    expect(el.querySelector('.alert')?.textContent).toContain('No encontramos esta historia');
    expect(el.querySelector('button.btn.primary')).toBeNull();
  });
});
