"""Small original musical cues, synthesized as mono signed 16-bit PCM."""
import array
import math
import sys

SCORES = {
    'codex': ((72, .16), (76, .16), (79, .28)),
    'web': ((79, .14), (84, .18), (83, .28)),
    'claude': ((69, .18), (72, .18), (77, .30)),
    'grok': ((74, .14), (81, .14), (78, .30)),
    'low': ((76, .20), (0, .08), (73, .24)),
    'empty': ((64, .22), (60, .22), (57, .34)),
    'restored': ((72, .13), (76, .13), (79, .13), (84, .34)),
    'battery-75': ((76, .13), (72, .20)),
    'battery-50': ((74, .18), (69, .22), (65, .28)),
    'battery-25': ((70, .20), (64, .24), (57, .34)),
    'battery-10': ((67, .15), (60, .17), (52, .24), (0, .06), (52, .24)),
}
RATE = 48000


def pcm(tone):
    if tone not in SCORES: raise ValueError('Som desconhecido')
    samples = array.array('h')
    for midi, duration in SCORES[tone]:
        frequency = 440 * 2 ** ((midi - 69) / 12)
        for i in range(round(RATE * duration)):
            t = i / RATE
            envelope = min(1, t / .012, (duration - t) / .04) * math.exp(-2 * t)
            signal = math.sin(2 * math.pi * frequency * t) + .18 * math.sin(4 * math.pi * frequency * t)
            samples.append(round(8500 * envelope * signal) if midi else 0)
    if sys.byteorder != 'little': samples.byteswap()
    return samples.tobytes()
