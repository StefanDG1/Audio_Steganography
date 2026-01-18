# Audio Steganography - Code Documentation

## Overview

This application hides data inside WAV audio files using four different algorithms. The hidden data is invisible to listeners but can be extracted by the decoder.

---

## Header Protocol

Every encoded file uses a **15-byte header** stored at the start of the audio (samples 0-119) using LSB encoding:

| Bytes | Field | Description |
|-------|-------|-------------|
| 0-1 | Magic | `st` - identifies stego file |
| 2 | Algorithm ID | 1=LSB, 2=Echo, 3=Phase, 4=DSSS |
| 3-4 | Param 1 | Algorithm-specific (e.g. chunk_size) |
| 5-6 | Param 2 | Algorithm-specific (e.g. delay_0) |
| 7-8 | Param 3 | Algorithm-specific (e.g. delay_1) |
| 9-12 | Payload Length | Size of hidden data in bytes |
| 13-14 | CRC | Checksum for header validation |

The header tells the decoder which algorithm was used and the payload size, allowing automatic extraction.

---

## Algorithms

### 1. LSB (Least Significant Bit)

**Theory**: Replace the least significant bit of each audio sample with a data bit. The change is imperceptible (~0.003% amplitude change).

**Encoding**: `audio[i] = (audio[i] & ~1) | bit`

**Decoding**: `bit = audio[i] & 1`

**Capacity**: 1 bit per sample (~5.5 KB/sec at 44.1kHz)

---

### 2. Echo Hiding

**Theory**: Hide data by adding echoes at different delays. The human ear perceives this as subtle reverb.

**Encoding**:
- Split audio into chunks
- For each bit, apply echo using convolution:
  - bit 0: echo at delay `d0` samples
  - bit 1: echo at delay `d1` samples
- Echo kernel: `[0, 0, ..., 0, alpha]` with delay zeros before alpha

**Decoding**: 
- Compute **cepstrum** (frequency of frequencies) of each chunk
- Compare cepstrum values at d0 vs d1:
  - `cepstrum[d0] >= cepstrum[d1]` → bit 0
  - else → bit 1

**Capacity**: 1 bit per chunk (~21 bits/sec with chunk=2048)

---

### 3. Phase Coding

**Theory**: Encode data in the phase of frequency components. Human ears are insensitive to absolute phase.

**Encoding**:
- Segment audio into 256-sample blocks
- FFT each block
- Modify phase of frequency bins 20-27:
  - bit 0: phase = -90°
  - bit 1: phase = +90°
- Inverse FFT to reconstruct

**Decoding**:
- FFT each segment
- Read phase of bins 20-27:
  - phase > 0 → bit 1
  - phase ≤ 0 → bit 0

**Capacity**: 8 bits per 256 samples (~1.4 KB/sec)

---

### 4. Spread Spectrum (DSSS)

**Theory**: Spread each bit across many samples using a pseudo-random sequence. Very robust to noise but low capacity.

**Encoding**:
- Generate PN sequence with fixed seed (same for encode/decode)
- For each bit:
  - bit 1: add `alpha * sequence` to frame
  - bit 0: subtract `alpha * sequence` from frame

**Decoding**:
- Correlate each frame with the same PN sequence
- Positive correlation → bit 1
- Negative correlation → bit 0

**Capacity**: 1 bit per 8192 samples (~5 bits/sec)

---

## Key Functions

### Encoding

| Function | Description |
|----------|-------------|
| `process_steganography()` | Main encode function - writes header + payload |
| `create_smart_header()` | Generates 15-byte header with CRC |
| `algo_lsb_encode()` | LSB bit replacement |
| `algo_echo_encode()` | Echo hiding with lfilter |
| `algo_phase_encode()` | Phase modification via FFT |
| `algo_spread_spectrum_encode()` | DSSS spreading |

### Decoding

| Function | Description |
|----------|-------------|
| `extract_file()` | Main decode - reads header, routes to algorithm |
| `read_smart_header()` | Validates header magic and CRC |
| `algo_lsb_decode()` | LSB bit extraction |
| `algo_echo_decode()` | Cepstrum-based echo detection |
| `algo_phase_decode()` | Phase angle extraction |
| `algo_spread_spectrum_decode()` | PN correlation |

### Utilities

| Function | Description |
|----------|-------------|
| `load_carrier()` | Load WAV file |
| `load_payload()` | Load file to hide |
| `save_stego_audio()` | Save encoded WAV |
| `play_audio()` | Playback with sounddevice |
| `update_plots()` | Waveform/spectrum visualization |

---

## File Type Detection

When decoding, magic bytes detect file type:

| Magic Bytes | Extension |
|-------------|-----------|
| `\x89PNG` | .png |
| `\xFF\xD8\xFF` | .jpg |
| `%PDF` | .pdf |
| `PK\x03\x04` | .zip |
| (none matched) | .txt (default) |
