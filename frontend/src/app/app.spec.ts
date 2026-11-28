import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { App } from './app';
import { ConfigService } from './config';
import { I18n } from './i18n';
import { StoryStore } from './story-store';

const API = 'https://api.test';

const step1 = {
  step: 1,
  title: 'Recrear el sueño',
  narration: 'Un pasillo largo.',
  technique: 'recreate',
  choices: [
    { id: 'a', label: 'Mirar' },
    { id: 'b', label: 'Escuchar' },
  ],
  learning: null,
  coping_tip: null,
  has_image: true,
};

describe('App', () => {
  let http: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
    TestBed.inject(ConfigService).apiUrl = API;
    TestBed.inject(I18n).setLang('es');
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    TestBed.inject(StoryStore).reset();
    vi.useRealTimers();
    http.verify();
  });

  it('shows the nightmare form and the disclaimer', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('textarea#nightmare')).toBeTruthy();
    expect(el.querySelector('.site-footer')?.textContent).toContain('No es un tratamiento médico');
  });

  it('starts a session and renders the first step with its choices', async () => {
    const fixture = TestBed.createComponent(App);
    const store = TestBed.inject(StoryStore);
    const done = store.start('Sueño que me persigue una sombra por un pasillo');

    const req = http.expectOne(`${API}/sessions`);
    expect(req.request.body).toEqual({
      nightmare: 'Sueño que me persigue una sombra por un pasillo',
      language: 'es',
    });
    req.flush({ status: 'ok', session_id: 's1', step: step1 });
    await done;
    await fixture.whenStable();

    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('h1')?.textContent).toContain('Recrear el sueño');
    expect(el.querySelectorAll('button.choice').length).toBe(2);
  });

  it('posts the chosen option to the session steps route', async () => {
    const store = TestBed.inject(StoryStore);
    const started = store.start('Sueño que me persigue una sombra por un pasillo');
    http.expectOne(`${API}/sessions`).flush({ status: 'ok', session_id: 's1', step: step1 });
    await started;

    const chosen = store.choose('b');
    const req = http.expectOne(`${API}/sessions/s1/steps`);
    expect(req.request.body).toEqual({ choice_id: 'b' });
    req.flush({ status: 'ok', session_id: 's1', step: { ...step1, step: 2 }, finished: false });
    await chosen;
    expect(store.current()?.step).toBe(2);
  });

  it('shows help resources when the session is stopped for risk', async () => {
    const fixture = TestBed.createComponent(App);
    const store = TestBed.inject(StoryStore);
    const done = store.start('texto de prueba suficientemente largo');
    http.expectOne(`${API}/sessions`).flush({
      status: 'stopped',
      category: 'risk',
      message: 'Gracias por contarlo.',
      resources: [{ label: 'Emergencias', contact: '112' }],
    });
    await done;
    await fixture.whenStable();

    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('h1')?.textContent).toContain('Mereces apoyo');
    expect(el.querySelector('.resources a')?.getAttribute('href')).toBe('tel:112');
  });

  it('maps backend error codes and allows retrying', async () => {
    const store = TestBed.inject(StoryStore);
    const first = store.start('texto de prueba suficientemente largo');
    http
      .expectOne(`${API}/sessions`)
      .flush({ error: 'busy' }, { status: 429, statusText: 'Too Many Requests' });
    await first;
    expect(store.error()).toBe('busy');
    expect(store.canRetry()).toBe(true);

    const again = store.retry();
    http.expectOne(`${API}/sessions`).flush({ status: 'ok', session_id: 's1', step: step1 });
    await again;
    expect(store.error()).toBeNull();
    expect(store.phase()).toBe('story');
  });

  describe('images', () => {
    async function startWithImage() {
      vi.useFakeTimers();
      const fixture = TestBed.createComponent(App);
      const store = TestBed.inject(StoryStore);
      const done = store.start('Sueño que me persigue una sombra por un pasillo');
      http.expectOne(`${API}/sessions`).flush({ status: 'ok', session_id: 's1', step: step1 });
      await done;
      return { fixture, store };
    }

    async function poll(images: object) {
      await vi.advanceTimersByTimeAsync(4000);
      http.expectOne(`${API}/sessions/s1/images`).flush({ images });
      await vi.advanceTimersByTimeAsync(0);
    }

    it('polls the images route after 4 s and shows the image with alt text when ready', async () => {
      const { fixture } = await startWithImage();
      await vi.advanceTimersByTimeAsync(3999);
      http.expectNone(`${API}/sessions/s1/images`);
      fixture.detectChanges();
      const el = fixture.nativeElement as HTMLElement;
      expect(el.querySelector('.illustration.pending')).toBeTruthy();
      await poll({ '1': { status: 'ready', url: 'https://img.test/1.jpg' } });
      fixture.detectChanges();
      const img = el.querySelector('img.illustration-img') as HTMLImageElement;
      expect(img.getAttribute('src')).toBe('https://img.test/1.jpg');
      expect(img.alt).not.toBe('');
    });

    it('shows a neutral block when the image failed and never raises an error', async () => {
      const { fixture, store } = await startWithImage();
      await poll({ '1': { status: 'failed', url: null } });
      fixture.detectChanges();
      const el = fixture.nativeElement as HTMLElement;
      expect(el.querySelector('.illustration.neutral')?.textContent).toContain('no hay ilustración');
      expect(el.querySelectorAll('button.choice').length).toBe(2);
      expect(store.error()).toBeNull();
    });

    it('keeps polling silently when the request fails', async () => {
      const { store } = await startWithImage();
      await vi.advanceTimersByTimeAsync(4000);
      http
        .expectOne(`${API}/sessions/s1/images`)
        .flush({ error: 'x' }, { status: 500, statusText: 'Server Error' });
      await vi.advanceTimersByTimeAsync(0);
      expect(store.error()).toBeNull();
      await vi.advanceTimersByTimeAsync(4000);
      http.expectOne(`${API}/sessions/s1/images`).flush({ images: {} });
    });

    it('reuses the earlier ready image as decoration on a step without image', async () => {
      const { fixture, store } = await startWithImage();
      await poll({ '1': { status: 'ready', url: 'https://img.test/1.jpg' } });
      const chosen = store.choose('a');
      http.expectOne(`${API}/sessions/s1/steps`).flush({
        status: 'ok',
        session_id: 's1',
        step: { ...step1, step: 2, has_image: false },
        finished: false,
      });
      await chosen;
      fixture.detectChanges();
      const img = (fixture.nativeElement as HTMLElement).querySelector(
        'img.illustration-img',
      ) as HTMLImageElement;
      expect(img.getAttribute('src')).toBe('https://img.test/1.jpg');
      expect(img.getAttribute('alt')).toBe('');
    });
  });
});
