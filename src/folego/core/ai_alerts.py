"""Confirmed AI transitions. Pure state, no Qt, input or audio effects."""
from . import ai_sessions
import time

TONES = ('codex', 'web', 'claude', 'grok', 'low', 'empty', 'restored',
         'battery-75', 'battery-50', 'battery-25', 'battery-10')


class AlertTracker:
    def __init__(self, *, now=None):
        self.started_at = time.time() if now is None else now
        self.quotas = {}
        self.deliveries = {}

    def quota_changes(self, items, now=None):
        sounds = []
        for item in items:
            provider = item.get('provider')
            account = item.get('account_id')
            if provider not in ai_sessions.NAMES or not account: continue
            left = ai_sessions.effective(item, now=now)
            if left is None: continue
            key = (provider, account)
            previous = self.quotas.get(key)
            current = dict(left=left, at=item['observed_at'],
                           windows={w['name']: (w['remaining'], w['resets_at']) for w in item['windows']})
            if previous and current['at'] <= previous['at']: continue
            self.quotas[key] = current
            if previous is None: continue  # startup establishes a silent baseline
            old = previous['left']
            reset = any(name in previous['windows'] and remaining > previous['windows'][name][0]
                        and at > previous['windows'][name][1]
                        for name, (remaining, at) in current['windows'].items())
            if left == 0 and old > 0: sounds.append('empty')
            elif 0 < left <= 20 < old: sounds.append('low')
            elif left > old and (old == 0 or old <= 20 < left or reset): sounds.append('restored')
        return list(dict.fromkeys(sounds))

    def delivery_changes(self, rows, now=None):
        now = time.time() if now is None else now
        sounds = []
        for row in rows:
            provider = row.get('provider')
            if provider not in ai_sessions.NAMES or row.get('count') is None: continue
            pending = {p['event'] for p in row.get('pending', []) if isinstance(p.get('event'), str)}
            successful = {p['event'] for p in row.get('pending', [])
                          if isinstance(p.get('event'), str) and not p.get('reported_web_mcp_error')}
            seen = self.deliveries.get(provider)
            if seen is None:
                self.deliveries[provider] = pending
                # A provider may have no readable session at startup. A native
                # receipt explicitly completed after we started is still new.
                if any(p.get('event') in successful and
                       (at := ai_sessions.timestamp(p.get('at'))) is not None and self.started_at <= at <= now
                       for p in row.get('pending', [])):
                    sounds.append(provider)
                continue
            if successful - seen: sounds.append(provider)
            # Acknowledgment, partial reads and new requests must not replay old
            # completion sounds. Overflow protects instead of silently evicting.
            if len(seen | pending) > 16384:
                raise ValueError('Histórico sonoro excede o limite; reinicie para estabelecer uma nova referência')
            seen.update(pending)
        return sounds
