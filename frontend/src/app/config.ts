import { Injectable } from '@angular/core';

/**
 * Runtime config read from /config.json, so the same build works in any account.
 * The deploy script writes it next to index.html; for `ng serve` create public/config.json.
 */
@Injectable({ providedIn: 'root' })
export class ConfigService {
  apiUrl = '';

  async load(): Promise<void> {
    try {
      const res = await fetch('config.json', { cache: 'no-store' });
      if (!res.ok) return;
      const data: unknown = await res.json();
      const url = (data as { apiUrl?: unknown } | null)?.apiUrl;
      if (typeof url === 'string') this.apiUrl = url.replace(/\/+$/, '');
    } catch {
      // Missing or invalid config: the store reports a `config` error on first call.
    }
  }
}
