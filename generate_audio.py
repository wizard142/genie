#!/usr/bin/env python3
"""Generate a copyright-free soundtrack for the genie promo:
chill ambient pad + synced typing clicks, whooshes, dings and a blocked buzz.
All synthesized with numpy — nothing sampled, nothing licensed."""
import json, sys
import numpy as np

SR = 44100
OFFSET = 0.04           # seconds: nudge SFX to sit just after the visual trigger
dur = float(sys.argv[1]) if len(sys.argv) > 1 else 25.5
N = int((dur + 0.4) * SR)
buf = np.zeros(N, dtype=np.float64)
rng = np.random.default_rng(7)

def add(sig, at):
    i = int(at * SR)
    if i < 0: i = 0
    j = min(N, i + len(sig))
    if j > i:
        buf[i:j] += sig[:j - i]

def env_exp(n, tau):
    t = np.arange(n) / SR
    return np.exp(-t / tau)

def hann(n):
    return np.hanning(n)

# ---------- chill ambient pad ----------
def pad_voice(freqs, n, detune=0.6):
    t = np.arange(n) / SR
    v = np.zeros(n)
    for f in freqs:
        # two slightly detuned sines per note -> slow, warm beating
        v += np.sin(2*np.pi*f*t)
        v += 0.8*np.sin(2*np.pi*(f*(1+detune/1000))*t)
        v += 0.3*np.sin(2*np.pi*2*f*t)          # soft octave shimmer
    # slow tremolo so it breathes gently (not flashing)
    lfo = 0.85 + 0.15*np.sin(2*np.pi*0.08*t)
    return v * lfo

n_pad = N
chordA = [110.0, 220.0, 261.63, 329.63]        # A minor-ish, warm
chordB = [ 87.31, 220.0, 261.63, 329.63]        # F major 7-ish
va = pad_voice(chordA, n_pad)
vb = pad_voice(chordB, n_pad)
# crossfade from A to B across the middle of the clip
xf = np.clip((np.arange(n_pad)/SR - 0.35*dur) / (0.30*dur), 0, 1)
pad = va*(1-xf) + vb*xf
pad /= np.max(np.abs(pad)) + 1e-9
# overall fade in / fade out
fade = np.ones(n_pad)
fi = int(2.0*SR); fo = int(2.0*SR)
fade[:fi] = np.linspace(0, 1, fi)
fade[-fo:] = np.linspace(1, 0, fo)
pad *= fade * 0.16
buf += pad

# ---------- one-shot SFX ----------
def sfx_key(idx):
    n = int(0.03*SR)
    noise = rng.standard_normal(n) * env_exp(n, 0.006)
    t = np.arange(n)/SR
    # a tiny pitched tick on top so it reads as a mechanical key
    pitch = 1600 + (idx*53 % 400)
    tick = 0.5*np.sin(2*np.pi*pitch*t) * env_exp(n, 0.004)
    return (noise*0.6 + tick) * 0.055

def sfx_whoosh():
    n = int(0.5*SR)
    noise = rng.standard_normal(n)
    # smooth it (cheap low-pass) and shape with a hann so it swells and fades
    k = 60
    noise = np.convolve(noise, np.ones(k)/k, mode='same')
    return noise * hann(n) * 0.16

def sfx_boom():
    n = int(0.35*SR)
    t = np.arange(n)/SR
    f = np.linspace(90, 55, n)                  # low falling thump
    s = np.sin(2*np.pi*np.cumsum(f)/SR)
    return s * env_exp(n, 0.10) * 0.22

def sfx_ding():
    n = int(0.6*SR)
    t = np.arange(n)/SR
    s = (np.sin(2*np.pi*987.77*t) + 0.6*np.sin(2*np.pi*1479*t)
         + 0.3*np.sin(2*np.pi*1975*t))
    return s * env_exp(n, 0.16) * 0.14

def sfx_chime():
    n = int(0.5*SR)
    t = np.arange(n)/SR
    s = np.sin(2*np.pi*1318.5*t) + 0.5*np.sin(2*np.pi*1760*t)
    return s * env_exp(n, 0.14) * 0.11

def sfx_buzz():
    n = int(0.5*SR)
    t = np.arange(n)/SR
    # low detuned saw-ish tone for the "blocked" moment
    saw = 2*(t*110 - np.floor(0.5 + t*110))
    saw2 = 2*(t*110.7 - np.floor(0.5 + t*110.7))
    tone = 0.6*saw + 0.4*saw2
    amp = env_exp(n, 0.18) * (0.7 + 0.3*np.sign(np.sin(2*np.pi*22*t)))  # slight rasp
    return tone * amp * 0.16

events = json.load(open('/home/claude/genie/events.json'))
key_i = 0
for t_ms, kind in events:
    at = t_ms/1000.0 + OFFSET
    if kind == 'key':
        add(sfx_key(key_i), at); key_i += 1
    elif kind == 'whoosh': add(sfx_whoosh(), at)
    elif kind == 'boom':   add(sfx_boom(), at)
    elif kind == 'ding':   add(sfx_ding(), at)
    elif kind == 'chime':  add(sfx_chime(), at)
    elif kind == 'buzz':   add(sfx_buzz(), at)

# ---------- master: soft limit + write ----------
peak = np.max(np.abs(buf))
if peak > 0.95:
    buf *= 0.95/peak
buf = np.tanh(buf*1.05)*0.97          # gentle soft-clip for glue
pcm = (buf * 32767).astype(np.int16)

import wave
w = wave.open('/home/claude/genie/audio.wav', 'wb')
w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
w.writeframes(pcm.tobytes()); w.close()
print("wrote audio.wav  keys=%d  peak=%.3f  dur=%.2fs" % (key_i, peak, N/SR))
