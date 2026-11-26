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
  | 'network'
  | 'config'
  | 'generic';
