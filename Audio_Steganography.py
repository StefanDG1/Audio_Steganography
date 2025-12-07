import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import numpy as np
import scipy.io.wavfile as wav
import sounddevice as sd
import threading
import os
import struct
import math
import ctypes
import time
import scipy.ndimage

# Matplotlib integration for Tkinter
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

# Attempt to enable High DPI awareness for Windows
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

# FIX: Set higher latency to prevent audio glitches during GUI resizing
sd.default.latency = 'high'

class AudioStegoApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Audio Steganography Studio")
        self.root.geometry("1000x900")
        self.root.minsize(800, 700)

        # Apply a clean theme and configure scaling
        style = ttk.Style()
        style.theme_use('clam')
        
        # Configure fonts for better scaling
        default_font = ("Segoe UI", 10)
        style.configure(".", font=default_font)
        style.configure("Header.TLabel", font=("Segoe UI", 18, "bold"))
        style.configure("SubHeader.TLabel", font=("Segoe UI", 10))
        style.configure("Bold.TLabel", font=("Segoe UI", 10, "bold"))
        
        # Colors
        self.bg_color = "#f4f4f4"
        self.root.configure(bg=self.bg_color)
        
        # State variables
        self.carrier_path = None
        self.payload_path = None
        self.decode_audio_path = None
        self.sample_rate = 0
        self.audio_data = None # Numpy array (Original)
        self.processed_audio = None # Numpy array (Stego)
        self.decode_audio_data = None # Audio loaded for decoding
        self.is_playing = False
        
        # Handle window closing properly to prevent lingering threads/callbacks
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # Layout
        self.create_widgets()

    def create_widgets(self):
        # Main container with padding
        main_container = ttk.Frame(self.root)
        main_container.pack(fill="both", expand=True, padx=15, pady=15)

        # --- Header ---
        header_frame = ttk.Frame(main_container)
        header_frame.pack(fill="x", pady=(0, 15))
        
        ttk.Label(header_frame, text="Audio Steganography", style="Header.TLabel").pack(anchor="w")
        ttk.Label(header_frame, text="Hide and Extract files within audio waveforms", style="SubHeader.TLabel").pack(anchor="w")

        # --- Tabs ---
        self.notebook = ttk.Notebook(main_container)
        self.notebook.pack(fill="both", expand=True)
        # Bind tab change to stop audio
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_change)

        # Tab 1: Encode
        self.tab_encode = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_encode, text="  Encode (Hide)  ")
        self.setup_encode_tab()

        # Tab 2: Decode
        self.tab_decode = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_decode, text="  Decode (Extract)  ")
        self.setup_decode_tab()

    def on_tab_change(self, event):
        """Stops audio when switching tabs."""
        self.stop_audio()

    def on_closing(self):
        """Clean up resources when closing the window."""
        self.stop_audio()
        self.is_playing = False # Ensure loop condition breaks
        self.root.destroy()

    def setup_encode_tab(self):
        # Use grid for flexible layout
        self.tab_encode.columnconfigure(0, weight=1)
        self.tab_encode.rowconfigure(3, weight=1) # Visualization expands

        # 1. Selection Area
        select_frame = ttk.LabelFrame(self.tab_encode, text=" 1. Inputs ", padding=15)
        select_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        select_frame.columnconfigure(1, weight=1)

        # Carrier
        ttk.Button(select_frame, text="Select Carrier Audio (.wav)", command=self.load_carrier).grid(row=0, column=0, sticky="w", pady=5)
        self.lbl_carrier = ttk.Label(select_frame, text="No audio selected", foreground="#666")
        self.lbl_carrier.grid(row=0, column=1, sticky="w", padx=10)

        # Payload
        ttk.Button(select_frame, text="Select File to Hide", command=self.load_payload).grid(row=1, column=0, sticky="w", pady=5)
        self.lbl_payload = ttk.Label(select_frame, text="No payload selected", foreground="#666")
        self.lbl_payload.grid(row=1, column=1, sticky="w", padx=10)

        # 2. Algorithm Area
        algo_frame = ttk.LabelFrame(self.tab_encode, text=" 2. Algorithm & Analysis ", padding=15)
        algo_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=5)
        algo_frame.columnconfigure(1, weight=1)

        ttk.Label(algo_frame, text="Method:").grid(row=0, column=0, sticky="w")
        self.algo_var = tk.StringVar(value="LSB (Least Significant Bit)")
        self.algo_menu = ttk.Combobox(algo_frame, textvariable=self.algo_var, state="readonly")
        self.algo_menu['values'] = ("LSB (Least Significant Bit)", "Echo Hiding", "Phase Coding")
        self.algo_menu.grid(row=0, column=1, sticky="ew", padx=10)
        
        # Binds - use a wrapper to ensure both functions fire
        self.algo_menu.bind("<<ComboboxSelected>>", self.on_algo_change)

        self.algo_desc_lbl = ttk.Label(algo_frame, text="Best for: Maximum Capacity. Fragile (breaks with edits).", font=("Segoe UI", 9, "italic"), foreground="#555")
        self.algo_desc_lbl.grid(row=1, column=0, columnspan=2, sticky="w", pady=(5, 5))

        self.status_lbl = ttk.Label(algo_frame, text="Waiting for inputs...", style="Bold.TLabel", foreground="#d9534f")
        self.status_lbl.grid(row=2, column=0, columnspan=2, sticky="w", pady=(5, 0))

        # 3. Controls
        ctrl_frame = ttk.LabelFrame(self.tab_encode, text=" 3. Actions ", padding=15)
        ctrl_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=5)
        
        btn_box = ttk.Frame(ctrl_frame)
        btn_box.pack(fill="x")
        
        ttk.Button(btn_box, text="▶ Play Original", command=lambda: self.play_audio(original=True)).pack(side="left", fill="x", expand=True, padx=2)
        self.btn_play_stego = ttk.Button(btn_box, text="▶ Preview Stego", command=lambda: self.play_audio(original=False))
        self.btn_play_stego.pack(side="left", fill="x", expand=True, padx=2)
        ttk.Button(btn_box, text="■ Stop", command=self.stop_audio).pack(side="left", padx=2)
        
        self.btn_bake = ttk.Button(ctrl_frame, text="Generate & Save Output File", command=self.save_stego_file, state="disabled")
        self.btn_bake.pack(fill="x", pady=(10, 0))

        # 4. Visualization
        plot_frame = ttk.LabelFrame(self.tab_encode, text=" Visualization ", padding=5)
        plot_frame.grid(row=3, column=0, sticky="nsew", padx=10, pady=10)
        
        self.fig, (self.ax1, self.ax2) = plt.subplots(2, 1, figsize=(5, 4), dpi=100)
        self.fig.patch.set_facecolor(self.bg_color)
        self.fig.tight_layout(pad=3.0)
        
        self.canvas = FigureCanvasTkAgg(self.fig, master=plot_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        # Add Interactive Toolbar
        self.toolbar = NavigationToolbar2Tk(self.canvas, plot_frame)
        self.toolbar.update()
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        self.reset_plots()
        
    def on_algo_change(self, event):
        self.update_capacity_check()
        self.update_algo_description()

    def setup_decode_tab(self):
        self.tab_decode.columnconfigure(0, weight=1)

        # Input
        dec_frame = ttk.LabelFrame(self.tab_decode, text=" 1. Extract File ", padding=15)
        dec_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        dec_frame.columnconfigure(1, weight=1)

        ttk.Button(dec_frame, text="Select Stego Audio (.wav)", command=self.load_decode_audio).grid(row=0, column=0, sticky="w", pady=5)
        self.lbl_decode_file = ttk.Label(dec_frame, text="No file selected", foreground="#666")
        self.lbl_decode_file.grid(row=0, column=1, sticky="w", padx=10)
        
        # Audio Controls for Decode
        btn_dec_audio_box = ttk.Frame(dec_frame)
        btn_dec_audio_box.grid(row=0, column=2, sticky="e", padx=5)
        self.btn_play_decode = ttk.Button(btn_dec_audio_box, text="▶ Play Selected", command=self.play_decode_audio, state="disabled")
        self.btn_play_decode.pack(side="left", padx=2)
        ttk.Button(btn_dec_audio_box, text="■ Stop", command=self.stop_audio).pack(side="left", padx=2)

        # Algo Select
        ttk.Label(dec_frame, text="Algorithm used:").grid(row=1, column=0, sticky="w", pady=10)
        self.decode_algo_var = tk.StringVar(value="LSB (Least Significant Bit)")
        self.decode_menu = ttk.Combobox(dec_frame, textvariable=self.decode_algo_var, state="readonly")
        self.decode_menu['values'] = ("LSB (Least Significant Bit)", "Echo Hiding", "Phase Coding")
        self.decode_menu.grid(row=1, column=1, sticky="ew", padx=10)

        # Action
        self.btn_extract = ttk.Button(dec_frame, text="Extract Hidden File", command=self.extract_file, state="disabled")
        self.btn_extract.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(15, 0))

        # Log
        log_frame = ttk.LabelFrame(self.tab_decode, text=" Activity Log ", padding=10)
        log_frame.grid(row=2, column=0, sticky="nsew", padx=10, pady=10)
        self.tab_decode.rowconfigure(2, weight=1)

        self.log_txt = tk.Text(log_frame, height=10, state="disabled", bg="#fff", font=("Consolas", 9))
        self.log_txt.pack(fill="both", expand=True)

    # --- Visualization Helpers ---

    def reset_plots(self):
        self.ax1.clear()
        self.ax2.clear()
        self.ax1.set_title("Waveform Comparison", fontsize=9)
        self.ax1.set_xlabel("Time (seconds)", fontsize=8)
        self.ax1.set_ylabel("Amplitude", fontsize=8)
        self.ax1.set_facecolor("#f9f9f9")
        self.ax1.tick_params(labelsize=8)
        self.ax1.text(0.5, 0.5, "Load Audio to Visualise", ha='center', fontsize=8)
        
        self.ax2.set_title("Difference (Stego - Original)", fontsize=9)
        self.ax2.set_facecolor("#f9f9f9")
        self.ax2.tick_params(labelsize=8)
        self.ax2.set_ylabel("Amplitude", fontsize=8)
        
        self.canvas.draw()

    def update_plots(self):
        if self.audio_data is None: return
        
        # Performance Fix: Downsample data for plotting
        # Plotting millions of points causes lag. We limit to ~10k points.
        total_points = len(self.audio_data)
        step = max(1, total_points // 10000)
        
        # Downsampled data
        plot_data = self.audio_data[::step]
        
        # Create Time Axis (Seconds)
        duration = total_points / self.sample_rate
        time_axis = np.linspace(0, duration, len(plot_data))
        
        self.ax1.clear()
        self.ax1.set_title("Waveform Comparison", fontsize=9)
        self.ax1.set_xlabel("Time (seconds)", fontsize=8)
        self.ax1.set_ylabel("Amplitude", fontsize=8)
        # Use thinner line for performance
        self.ax1.plot(time_axis, plot_data, label="Original", color="blue", alpha=0.6, linewidth=0.5)
        
        if self.processed_audio is not None:
            # Downsample stego audio too
            stego_plot = self.processed_audio[::step]
            self.ax1.plot(time_axis, stego_plot, label="Stego", color="orange", linestyle="--", alpha=0.8, linewidth=0.5)
            
            diff = self.processed_audio - self.audio_data
            diff_plot = diff[::step]
            
            self.ax2.clear()
            self.ax2.set_title("Residual Noise (Added Signal)", fontsize=9)
            self.ax2.set_xlabel("Time (seconds)", fontsize=8)
            self.ax2.set_ylabel("Amplitude", fontsize=8) 
            self.ax2.plot(time_axis, diff_plot, color="red", linewidth=0.5)
            mx = np.max(np.abs(diff_plot))
            if mx == 0: mx = 1
            self.ax2.set_ylim(-mx*1.2, mx*1.2)
        else:
             self.ax2.clear()
             self.ax2.set_title("Residual Noise (Added Signal)", fontsize=9)
             self.ax2.text(0.5, 0.5, "Generate Preview to see noise", ha='center', fontsize=8)
        
        self.ax1.legend(fontsize=8, loc='upper right')
        self.canvas.draw()

    # --- File Loaders ---

    def load_carrier(self):
        path = filedialog.askopenfilename(filetypes=[("WAV files", "*.wav")])
        if path:
            self.carrier_path = path
            try:
                self.sample_rate, self.audio_data = wav.read(path)
                # Ensure we work with int16 mono for this demo to ensure algorithm stability
                if self.audio_data.dtype != np.int16:
                    self.audio_data = (self.audio_data * 32767).astype(np.int16)
                if len(self.audio_data.shape) > 1:
                    # NOTE: This converts Stereo to Mono, halving the file size.
                    self.audio_data = self.audio_data[:, 0]
                
                duration = self.audio_data.size / self.sample_rate
                info = f"{os.path.basename(path)} | {self.sample_rate}Hz | {duration:.1f}s"
                self.lbl_carrier.config(text=info, foreground="#28a745")
                self.processed_audio = None 
                self.update_capacity_check()
                self.update_plots()
            except Exception as e:
                messagebox.showerror("Error", str(e))

    def load_payload(self):
        path = filedialog.askopenfilename()
        if path:
            self.payload_path = path
            size_kb = os.path.getsize(path) / 1024
            self.lbl_payload.config(text=f"{os.path.basename(path)} ({size_kb:.2f} KB)", foreground="#28a745")
            self.update_capacity_check()

    def load_decode_audio(self):
        path = filedialog.askopenfilename(filetypes=[("WAV files", "*.wav")])
        if path:
            self.decode_audio_path = path
            self.lbl_decode_file.config(text=os.path.basename(path), foreground="#28a745")
            
            # Load into memory for manipulation
            try:
                sr, audio = wav.read(path)
                if len(audio.shape) > 1: audio = audio[:, 0]
                self.decode_audio_data = audio.astype(np.int16)
                self.sample_rate = sr # Update rate for playback
                self.btn_extract.config(state="normal")
                self.btn_play_decode.config(state="normal")
                self.log(f"Loaded {os.path.basename(path)} for decoding.")
            except Exception as e:
                self.log(f"Error loading: {e}")

    # --- Core Logic ---

    def update_algo_description(self, event=None):
        algo = self.algo_var.get()
        desc = ""
        if "LSB" in algo:
            desc = "Best for: Capacity. Fragile. 1 bit/sample."
        elif "Echo Hiding" in algo:
            desc = "Best for: Robustness. Adds tiny echoes (1 bit/2048 samples)."
        elif "Phase Coding" in algo:
            desc = "Best for: Imperceptibility. Hides in Phase (1 bit/512 samples)."
        self.algo_desc_lbl.config(text=desc)

    def get_max_kb(self):
        if self.audio_data is None: return 0
        total_samples = self.audio_data.size
        algo = self.algo_var.get()
        
        bytes_avail = 0
        if "LSB" in algo:
            # 1 bit per sample
            bytes_avail = (total_samples // 8) - 64 
        elif "Echo Hiding" in algo:
            # 1 bit per 2048 samples (Needs space for echo decay/detection)
            bytes_avail = (total_samples // (2048 * 8)) - 64
        elif "Phase Coding" in algo:
            # 512 samples per segment, 1 byte (8 bits) per segment
            # = 512 samples per 8 bits = 64 samples per bit
            bytes_avail = (total_samples // 512) - 64
            
        return max(0, bytes_avail / 1024)

    def update_capacity_check(self, event=None):
        if not self.carrier_path: return

        limit_kb = self.get_max_kb()
        self.update_algo_description()
        
        if not self.payload_path:
            self.status_lbl.config(text=f"Max Capacity: {limit_kb:.2f} KB", foreground="#333")
            return

        payload_kb = os.path.getsize(self.payload_path) / 1024
        header_kb = 32 / 1024 
        
        if payload_kb + header_kb > limit_kb: 
            self.status_lbl.config(text=f"Error: File too large! ({payload_kb:.2f} KB > {limit_kb:.2f} KB)", foreground="#d9534f")
            self.btn_bake.state(['disabled'])
            self.btn_play_stego.state(['disabled'])
        else:
            self.status_lbl.config(text=f"Ready: File fits ({payload_kb:.2f} KB / {limit_kb:.2f} KB)", foreground="#28a745")
            self.btn_bake.state(['!disabled'])
            self.btn_play_stego.state(['!disabled'])

    def process_steganography(self):
        if self.audio_data is None or self.payload_path is None: return None

        with open(self.payload_path, 'rb') as f:
            data = f.read()
        length_header = struct.pack('<I', len(data))
        raw_bytes = length_header + data
        
        byte_array = np.frombuffer(raw_bytes, dtype=np.uint8)
        bits = np.unpackbits(byte_array)
        
        algo = self.algo_var.get()
        audio_copy = self.audio_data.copy()

        if "LSB" in algo:
            return self.algo_lsb_encode(audio_copy, bits)
        elif "Echo Hiding" in algo:
            return self.algo_echo_encode(audio_copy, bits)
        elif "Phase Coding" in algo:
            return self.algo_phase_encode(audio_copy, bits)
        
        return audio_copy

    # --- Encoding Algorithms ---

    def algo_lsb_encode(self, audio, bits):
        n_bits = len(bits)
        if n_bits > len(audio): bits = bits[:len(audio)]
        audio[:len(bits)] = (audio[:len(bits)] & ~1) | bits
        return audio

    def algo_echo_encode(self, audio, bits):
        """Echo Hiding:
        Improved: Chunk size 2048, Alpha 0.6.
        Bit 0 = Delay 128
        Bit 1 = Delay 256
        """
        chunk_len = 2048
        d0 = 128
        d1 = 256
        alpha = 0.6 # Stronger echo for robustness (audible as reverb)
        
        n_bits = len(bits)
        req_samples = n_bits * chunk_len
        
        output = audio.copy().astype(np.float32)
        
        if req_samples > len(audio): return audio

        for i in range(n_bits):
            start = i * chunk_len
            end = start + chunk_len
            
            bit = bits[i]
            delay = d1 if bit == 1 else d0
            
            p_start = start - delay
            p_end = end - delay
            
            if p_start >= 0:
                echo_signal = audio[p_start:p_end].astype(np.float32)
                output[start:end] += alpha * echo_signal
            
        return np.clip(output, -32768, 32767).astype(np.int16)

    def algo_phase_encode(self, audio, bits):
        """Phase Coding: Bins 50-58 (~4kHz). Safe and Robust."""
        segment_len = 512
        start_bin = 50 
        
        n_segments = (len(bits) + 7) // 8
        if n_segments * segment_len > len(audio): return audio

        bit_idx = 0
        for i in range(n_segments):
            s = i * segment_len
            e = s + segment_len
            chunk = audio[s:e]
            if len(chunk) < segment_len: break
            
            spectrum = np.fft.rfft(chunk)
            mag = np.abs(spectrum)
            phase = np.angle(spectrum)
            
            # Encode data
            for b_offset in range(8):
                if bit_idx >= len(bits): break
                bit = bits[bit_idx]
                target = start_bin + b_offset
                
                if target >= len(mag): continue

                # Robustness: Boost magnitude if too low (Higher threshold for save stability)
                if mag[target] < 100:
                    mag[target] = 100

                # BPSK: Force phase
                target_phase = np.pi/2 if bit == 1 else -np.pi/2
                phase[target] = target_phase
                bit_idx += 1
            
            # Reconstruct 
            new_spec = mag * np.exp(1j * phase)
            new_chunk = np.fft.irfft(new_spec, n=segment_len)
            
            audio[s:e] = new_chunk.astype(np.int16)
            
        return audio

    # --- Decoding Logic ---

    def log(self, msg):
        self.log_txt.config(state="normal")
        self.log_txt.insert("end", msg + "\n")
        self.log_txt.see("end")
        self.log_txt.config(state="disabled")

    def extract_file(self):
        if self.decode_audio_data is None: return
        
        try:
            algo = self.decode_algo_var.get()
            self.log(f"Extracting using {algo}...")
            
            audio = self.decode_audio_data
            
            bits = None
            if "LSB" in algo:
                bits = self.algo_lsb_decode(audio)
            elif "Echo Hiding" in algo:
                bits = self.algo_echo_decode(audio)
            elif "Phase Coding" in algo:
                bits = self.algo_phase_decode(audio)
                
            if bits is None: 
                self.log("Extraction failed.")
                return

            byte_data = np.packbits(bits)
            
            if len(byte_data) < 4:
                self.log("Error: Not enough data.")
                return
                
            length_bytes = byte_data[:4].tobytes()
            try:
                content_len = struct.unpack('<I', length_bytes)[0]
            except:
                self.log("Error: Header bytes corrupt.")
                return
            
            if content_len > 100_000_000 or content_len == 0:
                self.log(f"FAILURE: Header corrupt (read length: {content_len}).")
                self.log("Wrong algorithm or data destroyed.")
                return

            self.log(f"Header Valid. Content Length: {content_len} bytes.")
            
            if content_len > len(byte_data) - 4:
                self.log("Error: Payload truncated.")
                return
                
            payload = byte_data[4 : 4 + content_len].tobytes()
            
            save_path = filedialog.asksaveasfilename(title="Save Extracted File")
            if save_path:
                with open(save_path, 'wb') as f:
                    f.write(payload)
                self.log(f"Success! Saved to {save_path}")
                messagebox.showinfo("Success", "File extracted successfully.")

        except Exception as e:
            self.log(f"Error: {e}")

    def algo_lsb_decode(self, audio):
        return audio & 1

    def algo_echo_decode(self, audio):
        """Echo Decoding using Cepstrum Analysis + Windowing.
        Updated: Checks wide range around delay to catch peaks."""
        chunk_len = 2048
        d0 = 128
        d1 = 256
        
        n_chunks = len(audio) // chunk_len
        bits = np.zeros(n_chunks, dtype=np.uint8)
        
        # Use Hanning window to sharpen cepstrum peaks
        window = np.hanning(chunk_len)
        
        for i in range(n_chunks):
            start = i * chunk_len
            end = start + chunk_len
            chunk = audio[start:end].astype(np.float32)
            
            # Apply window
            if len(chunk) == chunk_len:
                chunk = chunk * window
            else:
                continue # Skip partial chunk
            
            # Cepstrum
            spectrum = np.fft.fft(chunk)
            log_spectrum = np.log(np.abs(spectrum) + 1e-6)
            cepstrum = np.fft.ifft(log_spectrum).real
            
            # Check magnitude at delay indices (with small jitter tolerance)
            # We take max of a small range around the target delay
            # Range must handle slightly shifted peaks
            val_0 = np.max(np.abs(cepstrum[d0-4:d0+5]))
            val_1 = np.max(np.abs(cepstrum[d1-4:d1+5]))
            
            bits[i] = 1 if val_1 > val_0 else 0
            
        return bits

    def algo_phase_decode(self, audio):
        """Phase Coding Decode: Strictly reverses Encode logic.
        Uses Bins 50-58."""
        segment_len = 512
        start_bin = 50 # Must match encoder
        n_segments = len(audio) // segment_len
        bits = []
        for i in range(n_segments):
            s = i * segment_len
            e = s + segment_len
            chunk = audio[s:e]
            
            # Exact same FFT process as Encoder
            spectrum = np.fft.rfft(chunk)
            phase = np.angle(spectrum)
            
            for b_offset in range(8):
                target = start_bin + b_offset
                if target >= len(phase): break

                # Reverse BPSK: Check if angle is closer to pi/2 or -pi/2
                p = phase[target]
                
                # Distance to 1 (pi/2) vs 0 (-pi/2)
                dist_1 = abs(p - np.pi/2)
                dist_0 = abs(p - (-np.pi/2))
                
                if dist_1 > np.pi: dist_1 = 2*np.pi - dist_1
                if dist_0 > np.pi: dist_0 = 2*np.pi - dist_0
                
                bits.append(1 if dist_1 < dist_0 else 0)
                
        return np.array(bits, dtype=np.uint8)

    # --- Playback/Save ---

    def play_audio(self, original=True):
        if self.is_playing: self.stop_audio()
        
        if original:
            if self.audio_data is None: return
            data = self.audio_data
            self.update_plots()
        else:
            data = self.process_steganography()
            if data is None: return
            self.processed_audio = data
            self.update_plots()

        # Convert to float32 for more robust playback compatibility
        try:
            data_float = data.astype(np.float32) / 32768.0
        except Exception as e:
            print(f"Conversion error: {e}")
            data_float = data

        self.is_playing = True
        
        def run():
            try:
                sd.play(data_float, self.sample_rate)
                sd.wait()
            except Exception as e: 
                print(f"Playback error: {e}")
            self.is_playing = False
        
        threading.Thread(target=run, daemon=True).start()

    def play_decode_audio(self):
        if self.is_playing: self.stop_audio()
        if self.decode_audio_data is None: return
        
        # Convert to float32
        try:
            data_float = self.decode_audio_data.astype(np.float32) / 32768.0
        except:
            data_float = self.decode_audio_data

        self.is_playing = True
        
        def run():
            try:
                sd.play(data_float, self.sample_rate)
                sd.wait()
            except Exception as e:
                 print(f"Playback error: {e}")
            self.is_playing = False
        threading.Thread(target=run, daemon=True).start()

    def stop_audio(self):
        try:
            sd.stop()
        except: pass
        self.is_playing = False

    def save_stego_file(self):
        save_path = filedialog.asksaveasfilename(defaultextension=".wav", filetypes=[("WAV files", "*.wav")])
        if save_path:
            final_audio = self.process_steganography()
            wav.write(save_path, self.sample_rate, final_audio)
            messagebox.showinfo("Success", f"File saved:\n{save_path}")

if __name__ == "__main__":
    try:
        root = tk.Tk()
        app = AudioStegoApp(root)
        root.mainloop()
    except ImportError:
        print("Install: pip install numpy scipy sounddevice matplotlib")