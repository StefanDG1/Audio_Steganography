# Audio Steganography Studio

Hide secret files inside WAV audio files using various steganography techniques.

## Features

- **4 Algorithms**: LSB, Echo Hiding, Phase Coding, Spread Spectrum
- **Auto-detection**: Header stores algorithm info for automatic decoding
- **BER Testing**: Optional bit error rate comparison in decoder
- **Visualization**: Real-time waveform and residual noise plots
- **Audio Preview**: Listen to original and stego audio before saving

## Installation

```bash
pip install -r requirements.txt
python Audio_Steganography.py
```

## Requirements

- Python 3.14
- numpy, scipy, matplotlib, sounddevice

## Quick Start

### Encoding
1. Load a WAV carrier file
2. Select a file to hide
3. Choose an algorithm (LSB recommended for beginners)
4. Click "Generate & Save Output File"

### Decoding
1. Load the stego WAV file
2. (Optional) Load original file for BER comparison
3. Click "Extract Hidden File"

## Algorithm Comparison

| Algorithm | Capacity | Robustness | Audio Quality |
|-----------|----------|------------|---------------|
| LSB | High | Low | Excellent |
| Echo | Low | Medium | Good |
| Phase | Medium | High | Good |
| DSSS | Very Low | Very High | Excellent |

## Files

- `Audio_Steganography.py` - Main application
- `DOCUMENTATION.md` - Technical details
- `test_steganography.py` - Automated tests

## License

MIT
