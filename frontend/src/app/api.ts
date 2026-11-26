/** Contract of the backend API (backend/src/nightmare/handler.py and story.py). */

export type Lang = 'es' | 'en';

export interface Choice {
  id: string;
  label: string;
}

export interface Step {
  step: number;
  title: string;
  narration: string;
  technique: 'recreate' | 'control' | 'decision' | 'rewrite' | 'closing' | string;
  choices: Choice[];
  learning: string | null;
  coping_tip: string | null;
  has_image: boolean;
}

export interface HelpResource {
  label: string;
  contact: string;
}

export interface OkResponse {
  status: 'ok';
  session_id: string;
  step: Step;
  finished?: boolean;
}

export interface StoppedResponse {
  status: 'stopped';
  category: 'not_serious' | 'forbidden_content' | 'risk' | string;
  message: string;
  resources: HelpResource[];
}

export type ApiResponse = OkResponse | StoppedResponse;

export const TOTAL_STEPS = 5;
export const MIN_CHARS = 20;
export const MAX_CHARS = 2000;

/** Error codes the UI knows how to explain. Unknown backend codes map to `generic`. */
export type ErrorKey =
  | 'busy'
  | 'unavailable'
  | 'nightmare_length'
  | 'session_not_found'
  | 'session_finished'
  | 'session_not_finished'
  | 'already_published'
  | 'not_publishable'
  | 'not_found'
  | 'consent'
  | 'network'
  | 'config'
  | 'generic';

/** POST /sessions/{id}/publish. The token is shown once and never stored by the backend. */
export interface PublishResponse {
  status: 'ok';
  story_id: string;
  delete_token: string;
  expires_at: number | null;
}

/** A published step: anonymized text only. `image` is filled once images exist (task 5). */
export interface GalleryStep {
  step: number;
  title: string;
  narration: string;
  learning: string | null;
  coping_tip: string | null;
  has_image: boolean;
  image: string | null;
}

export interface GalleryStory {
  id: string;
  language: Lang;
  created_at: number;
  steps: GalleryStep[];
}

export interface GalleryPage {
  stories: GalleryStory[];
  next_cursor: string | null;
}

export const GALLERY_PAGE_SIZE = 6;
