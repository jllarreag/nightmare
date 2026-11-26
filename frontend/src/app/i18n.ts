import { computed, Injectable, signal } from '@angular/core';
import { ErrorKey, Lang } from './api';

const ES = {
  appName: 'Nightmare Resolver',
  skip: 'Saltar al contenido',
  language: 'Idioma',
  languageLocked: 'El idioma se fija al empezar la historia',
  tagline: 'Reescribe el final de tu pesadilla',
  intro:
    'Cuéntanos una pesadilla que se repite. Te guiaremos en cinco pasos para revivirla con calma, ' +
    'recuperar el control y darle un final nuevo.',
  formLabel: 'Describe tu pesadilla',
  formHint:
    'Con tus palabras, sin nombres ni datos personales. Entre 20 y 2000 caracteres.',
  placeholder: 'Por ejemplo: sueño que camino por un pasillo que no se acaba y algo me sigue…',
  chars: 'caracteres',
  start: 'Empezar',
  privacy:
    'No guardamos tu texto original: solo un resumen anónimo de la sesión, que se borra en 24 horas.',
  loading: 'La niebla se está moviendo…',
  step: 'Paso',
  of: 'de',
  progress: 'Progreso de la historia',
  imagePending: 'Aquí aparecerá la ilustración de este momento',
  choose: '¿Qué haces ahora?',
  learning: 'Lo que te llevas',
  copingTip: 'Para tu día a día',
  finished: 'Has llegado al final de esta historia. Puedes volver a ensayar el nuevo final cuando quieras.',
  restart: 'Empezar otra historia',
  stoppedTitle: 'Paramos aquí',
  riskTitle: 'Mereces apoyo',
  backToStart: 'Volver al inicio',
  retry: 'Reintentar',
  disclaimer:
    'Herramienta de autoayuda. No es un tratamiento médico ni sustituye la ayuda de un profesional.',
  err_busy: 'El servicio está ocupado. Espera unos segundos y vuelve a intentarlo.',
  err_unavailable: 'El servicio no está disponible ahora mismo. Inténtalo de nuevo en un rato.',
  err_nightmare_length: 'El texto debe tener entre 20 y 2000 caracteres.',
  err_session_not_found: 'Esta sesión ha caducado. Puedes empezar una historia nueva.',
  err_session_finished: 'Esta historia ya terminó. Puedes empezar una nueva.',
  err_network: 'No hemos podido conectar con el servicio. Revisa tu conexión.',
  err_config: 'Falta la configuración de la aplicación (config.json).',
  err_generic: 'Algo ha fallado. Vuelve a intentarlo.',
};

type Messages = typeof ES;
export type MsgKey = keyof Messages;

const EN: Messages = {
  appName: 'Nightmare Resolver',
  skip: 'Skip to content',
  language: 'Language',
  languageLocked: 'The language is fixed once the story starts',
  tagline: 'Rewrite the ending of your nightmare',
  intro:
    'Tell us about a nightmare that keeps coming back. We will guide you through five steps to ' +
    'revisit it calmly, take back control and give it a new ending.',
  formLabel: 'Describe your nightmare',
  formHint: 'In your own words, without names or personal data. Between 20 and 2000 characters.',
  placeholder: 'For example: I dream I walk down a corridor that never ends and something follows me…',
  chars: 'characters',
  start: 'Begin',
  privacy:
    'We do not store your original text: only an anonymous summary of the session, deleted after 24 hours.',
  loading: 'The fog is shifting…',
  step: 'Step',
  of: 'of',
  progress: 'Story progress',
  imagePending: 'The illustration for this moment will appear here',
  choose: 'What do you do now?',
  learning: 'What you take with you',
  copingTip: 'For your everyday life',
  finished: 'You have reached the end of this story. You can rehearse the new ending whenever you like.',
  restart: 'Start another story',
  stoppedTitle: "Let's pause here",
  riskTitle: 'You deserve support',
  backToStart: 'Back to start',
  retry: 'Try again',
  disclaimer: 'Self-help tool. It is not a medical treatment and does not replace professional help.',
  err_busy: 'The service is busy. Wait a few seconds and try again.',
  err_unavailable: 'The service is not available right now. Please try again later.',
  err_nightmare_length: 'The text must be between 20 and 2000 characters.',
  err_session_not_found: 'This session has expired. You can start a new story.',
  err_session_finished: 'This story has already ended. You can start a new one.',
  err_network: 'We could not reach the service. Check your connection.',
  err_config: 'The app configuration (config.json) is missing.',
  err_generic: 'Something went wrong. Please try again.',
};

const STORAGE_KEY = 'nr-lang';

function initialLang(): Lang {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === 'es' || saved === 'en') return saved;
  } catch {
    // localStorage unavailable (private mode, tests)
  }
  const nav = typeof navigator !== 'undefined' ? navigator.language : 'es';
  return nav.toLowerCase().startsWith('en') ? 'en' : 'es';
}

/** Runtime ES/EN dictionary. The story language follows the UI language at session start. */
@Injectable({ providedIn: 'root' })
export class I18n {
  readonly lang = signal<Lang>(initialLang());
  private readonly messages = computed(() => (this.lang() === 'es' ? ES : EN));

  constructor() {
    document.documentElement.lang = this.lang();
  }

  t(key: MsgKey): string {
    return this.messages()[key];
  }

  error(key: ErrorKey): string {
    return this.messages()[`err_${key}`];
  }

  setLang(lang: Lang): void {
    this.lang.set(lang);
    document.documentElement.lang = lang;
    try {
      localStorage.setItem(STORAGE_KEY, lang);
    } catch {
      // ignore
    }
  }
}
