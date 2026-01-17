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
        self.play_thread = None
        self.decode_thread = None
        self.exiting = False
        
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
        # Signal exit and stop audio playback/streams
        self.exiting = True
        self.stop_audio()

        # Try to join playback threads briefly so resources close cleanly
        try:
            if self.play_thread and self.play_thread.is_alive():
                sd.stop()
                self.play_thread.join(timeout=0.5)
        except Exception:
            pass

        try:
            if self.decode_thread and self.decode_thread.is_alive():
                sd.stop()
                self.decode_thread.join(timeout=0.5)
        except Exception:
            pass

        try:
            self.root.quit()
            self.root.destroy()
        except Exception:
            try:
                os._exit(0)
            except Exception:
                pass

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
        
        # header bytes reserved (4 bytes) and small safety margin
        header_bytes = 4
        bytes_avail = 0

        if "LSB" in algo:
            # 1 bit per sample -> bytes = samples // 8
            bytes_avail = (total_samples // 8) - header_bytes
        elif "Echo Hiding" in algo:
            # 1 bit per chunk (chunk_len)
            chunk_len = 1024
            bits = total_samples // chunk_len
            bytes_avail = (bits // 8) - header_bytes
        elif "Phase Coding" in algo:
            # encoder stores 1 byte per segment (8 bits/segment)
            segment_len = 256
            bytes_avail = (total_samples // segment_len) - header_bytes

        # Return KB available
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

        # Add a short preamble for sync in robust modes (Echo / Phase)
        # Preamble: 8 bytes of 0xAA (10101010) -> 64 bits
        preamble = np.unpackbits(np.frombuffer(b'\xAA'*8, dtype=np.uint8))
        algo = self.algo_var.get()
        if "Echo" in algo or "Phase" in algo:
            bits = np.concatenate([preamble, bits])

        algo = self.algo_var.get()
        audio_copy = self.audio_data.copy()

        # Hybrid: for Echo/Phase, reserve an LSB-redundant header at the start
        # Header contents: 4 bytes payload length, 4 bytes start_chunk
        if "Echo" in algo or "Phase" in algo:
            # We will compute start_chunk inside encoder; for now choose placeholder 0
            # Encoder will return stego audio with chosen start_chunk embedded via LSB header
            pass
        # Enforce max bits that can be embedded based on carrier size
        if "Echo Hiding" in algo:
            chunk_len = 1024
            max_bits = len(audio_copy) // chunk_len
            if len(bits) > max_bits:
                bits = bits[:max_bits]
        elif "Phase Coding" in algo:
            segment_len = 256
            max_bits = (len(audio_copy) // segment_len) * 8
            if len(bits) > max_bits:
                bits = bits[:max_bits]
        else:
            # LSB: 1 bit per sample
            max_bits = len(audio_copy)
            if len(bits) > max_bits:
                bits = bits[:max_bits]

        if "LSB" in algo:
            return self.algo_lsb_encode(audio_copy, bits)
        elif "Echo Hiding" in algo:
            # Encode with echo; pass payload length so encoder can write LSB header
            return self.algo_echo_encode(audio_copy, bits, payload_len=len(data))
        elif "Phase Coding" in algo:
            return self.algo_phase_encode(audio_copy, bits, payload_len=len(data))
        
        return audio_copy

    # --- Encoding Algorithms ---

    def algo_lsb_encode(self, audio, bits):
        n_bits = len(bits)
        if n_bits > len(audio): bits = bits[:len(audio)]
        audio[:len(bits)] = (audio[:len(bits)] & ~1) | bits
        return audio

    def algo_echo_encode(self, audio, bits, forced_start_chunk=None, payload_len=None):
        """Echo Hiding:
        More compact: Chunk size 1024, low alpha to reduce audibility.
        Bit 0 -> short delay (32 samples), Bit 1 -> longer delay (64 samples).
        """
        chunk_len = 1024
        d0 = 32
        d1 = 64
        alpha = 0.12

        n_bits = len(bits)
        audio_len = len(audio)

        output = audio.copy().astype(np.float32)

        # If we cannot fit all bits, encode as many as we can (calling code truncates)
        max_bits = audio_len // chunk_len
        if n_bits > max_bits:
            n_bits = max_bits

        # Find a good starting chunk where the echo source region has energy
        # This avoids encoding header into leading silence. If the caller
        # provides a forced_start_chunk we use that.
        if forced_start_chunk is not None:
            start_chunk = int(forced_start_chunk)
        else:
            energies = np.zeros(max_bits, dtype=np.float32)
            for i in range(max_bits):
                s = i * chunk_len
                e = s + chunk_len
                p_start = s - d0
                p_end = e - d0
                src_s = max(0, p_start)
                src_e = min(audio_len, p_end)
                if src_e > src_s:
                    energies[i] = np.mean(np.abs(audio[src_s:src_e].astype(np.float32)))
                else:
                    energies[i] = 0.0

            median_energy = np.median(energies) if len(energies) > 0 else 0.0
            start_chunk = 0
            if median_energy > 0:
                thresh = max(1.0, median_energy * 0.1)
                candidates = np.where(energies >= thresh)[0]
                if candidates.size > 0:
                    start_chunk = int(candidates[0])

            # Ensure we place payload after a reserved LSB header area
            header_redundancy_samples = 2048
            header_bitlen = 8 * 8  # 8 bytes (content len + start_chunk)
            min_start_chunks = math.ceil(header_redundancy_samples / chunk_len)
            if start_chunk < min_start_chunks:
                start_chunk = min_start_chunks

            # If payload_len provided, write redundant LSB header and full raw bytes
            if payload_len is not None:
                try:
                    # bits contains: [preamble (64 bits)] + [4-byte length + payload bytes]
                    preamble_len = 64
                    raw_bitlen = (4 + int(payload_len)) * 8
                    raw_bits = bits[preamble_len : preamble_len + raw_bitlen]

                    # reconstruct raw bytes (4-byte length + payload)
                    raw_bytes = np.packbits(raw_bits).tobytes()

                    # Build an explicit 8-byte LSB backup header: (content_len, start_chunk)
                    header_bytes = struct.pack('<II', int(payload_len), int(start_chunk))
                    payload_only = raw_bytes[4:]
                    backup_bytes = header_bytes + payload_only
                    backup_bits = np.unpackbits(np.frombuffer(backup_bytes, dtype=np.uint8))

                    # First, write a small 8-byte header repeated across the first 2048 samples
                    small_header_bits = np.unpackbits(np.frombuffer(header_bytes, dtype=np.uint8))
                    small_reps = 2048 // small_header_bits.size
                    small_tile = np.tile(small_header_bits, small_reps)

                    out_int = output.astype(np.int16)
                    if out_int.ndim == 1:
                        n0 = min(len(small_tile), out_int.shape[0])
                        out_int[:n0] = (out_int[:n0] & ~1) | small_tile[:n0]
                    else:
                        n0 = min(len(small_tile), out_int.shape[0])
                        ch0 = out_int[:n0, 0]
                        ch0 = (ch0 & ~1) | small_tile[:n0]
                        out_int[:n0, 0] = ch0

                    # Now write the full backup after the small header (to avoid clobbering)
                    header_redundancy_samples = max(2048, len(backup_bits))
                    reps = header_redundancy_samples // len(backup_bits)
                    if reps >= 1:
                        repeated = np.tile(backup_bits, reps)
                        n = min(len(repeated), out_int.shape[0] - 2048)
                        if out_int.ndim == 1:
                            start = 2048
                            out_int[start:start+n] = (out_int[start:start+n] & ~1) | repeated[:n]
                        else:
                            start = 2048
                            ch0 = out_int[start:start+n, 0]
                            ch0 = (ch0 & ~1) | repeated[:n]
                            out_int[start:start+n, 0] = ch0

                    output[:out_int.shape[0]] = out_int[:out_int.shape[0]]
                except Exception:
                    pass

        # Hanning window to reduce edge artifacts
        window = np.hanning(chunk_len)

        # Ensure we don't walk off the end when applying the start offset
        available_slots = max_bits - start_chunk
        if n_bits > available_slots:
            n_bits = available_slots
        # If a preamble exists (we prepend a 64-bit 0xAA pattern), boost its alpha
        preamble_len = min(64, n_bits)
        alpha_preamble = 0.5

        for bit_index in range(n_bits):
            i = start_chunk + bit_index
            start = i * chunk_len
            end = start + chunk_len

            if end > audio_len:
                break

            bit = int(bits[bit_index])
            delay = d1 if bit == 1 else d0
            # use stronger echo for preamble bits to aid detection
            use_alpha = alpha_preamble if bit_index < preamble_len else alpha

            p_start = start - delay
            p_end = end - delay

            # Zero-padded echo buffer
            echo_signal = np.zeros(chunk_len, dtype=np.float32)

            src_start = max(0, p_start)
            src_end = min(audio_len, p_end)

            if src_end > src_start:
                dest_start = 0 if p_start >= 0 else (-p_start)
                dest_end = dest_start + (src_end - src_start)
                echo_signal[dest_start:dest_end] = audio[src_start:src_end].astype(np.float32)

                # Apply window to both original region and echo to reduce spectral leakage
                sig = echo_signal * window
                output[start:end] += use_alpha * sig

        return np.clip(output, -32768, 32767).astype(np.int16)

    def algo_phase_encode(self, audio, bits, forced_start_seg=None, payload_len=None):
        """Phase Coding: smaller segments for higher capacity.
        Uses small phase shifts to encode bits in a set of frequency bins.
        """
        segment_len = 256
        start_bin = 20
        n_segments = (len(bits) + 7) // 8
        max_segments = len(audio) // segment_len
        if n_segments > max_segments:
            n_segments = max_segments

        # Find starting segment with sufficient energy for reliable encoding
        if forced_start_seg is not None:
            start_seg = int(forced_start_seg)
        else:
            energies = np.zeros(max_segments, dtype=np.float32)
            for i in range(max_segments):
                s = i * segment_len
                e = s + segment_len
                seg = audio[s:e].astype(np.float32)
                energies[i] = np.mean(np.abs(seg))
            median_energy = np.median(energies) if energies.size>0 else 0.0
            start_seg = 0
            if median_energy > 0:
                thresh = max(1.0, median_energy * 0.1)
                cand = np.where(energies >= thresh)[0]
                if cand.size>0:
                    start_seg = int(cand[0])

        # Reserve space for LSB header area and write it if payload_len given
        header_redundancy_samples = 2048
        header_bitlen = 8 * 8
        min_start_seg = math.ceil(header_redundancy_samples / segment_len)
        if start_seg < min_start_seg:
            start_seg = min_start_seg
        if payload_len is not None:
            try:
                # reconstruct raw bits from bits (bits includes preamble + length + payload)
                preamble_len = 64
                raw_bitlen = (4 + int(payload_len)) * 8
                raw_bits = bits[preamble_len : preamble_len + raw_bitlen]

                # reconstruct raw bytes (4-byte length + payload)
                raw_bytes = np.packbits(raw_bits).tobytes()
                # Build explicit 8-byte header (content_len, start_seg)
                header_bytes = struct.pack('<II', int(payload_len), int(start_seg))
                payload_only = raw_bytes[4:]
                backup_bytes = header_bytes + payload_only
                backup_bits = np.unpackbits(np.frombuffer(backup_bytes, dtype=np.uint8))

                # small header repeated in first 2048 samples
                small_header_bits = np.unpackbits(np.frombuffer(header_bytes, dtype=np.uint8))
                small_reps = 2048 // small_header_bits.size
                small_tile = np.tile(small_header_bits, small_reps)

                out_int = audio.astype(np.int16)
                if out_int.ndim == 1:
                    n0 = min(len(small_tile), out_int.shape[0])
                    out_int[:n0] = (out_int[:n0] & ~1) | small_tile[:n0]
                else:
                    n0 = min(len(small_tile), out_int.shape[0])
                    ch0 = out_int[:n0, 0]
                    ch0 = (ch0 & ~1) | small_tile[:n0]
                    out_int[:n0, 0] = ch0

                header_redundancy_samples = max(2048, len(backup_bits))
                reps = header_redundancy_samples // len(backup_bits)
                if reps >= 1:
                    repeated = np.tile(backup_bits, reps)
                    n = min(len(repeated), out_int.shape[0] - 2048)
                    start = 2048
                    if out_int.ndim == 1:
                        out_int[start:start+n] = (out_int[start:start+n] & ~1) | repeated[:n]
                    else:
                        ch0 = out_int[start:start+n, 0]
                        ch0 = (ch0 & ~1) | repeated[:n]
                        out_int[start:start+n, 0] = ch0

                audio[:out_int.shape[0]] = out_int[:out_int.shape[0]]
            except Exception:
                pass

        bit_idx = 0
        # Ensure we don't overrun when starting at start_seg
        available_segments = max_segments - start_seg
        if n_segments > available_segments:
            n_segments = available_segments
        for seg_i in range(n_segments):
            i = start_seg + seg_i
            if i >= max_segments: break
            s = i * segment_len
            e = s + segment_len
            chunk = audio[s:e]
            if len(chunk) < segment_len: break

            spectrum = np.fft.rfft(chunk)
            mag = np.abs(spectrum)
            phase = np.angle(spectrum)

            for b_offset in range(8):
                if bit_idx >= len(bits): break
                bit = int(bits[bit_idx])
                target = start_bin + b_offset
                if target >= len(mag): continue

                if mag[target] < 10:
                    mag[target] = 10

                # Use stronger phase shifts for the preamble (first 64 bits)
                preamble_bits = min(64, len(bits))
                if bit_idx < preamble_bits:
                    target_phase = (np.pi/2) if bit == 1 else (-np.pi/2)
                else:
                    target_phase = (np.pi/4) if bit == 1 else (-np.pi/4)
                phase[target] = target_phase
                bit_idx += 1

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
            # Hybrid: first try to read a redundant LSB header stored in the first samples
            header_valid = False
            header_len_bytes = 8  # 4 bytes length + 4 bytes start_chunk
            header_bitlen = header_len_bytes * 8
            header_redundancy_samples = 2048  # repeat header across this many samples

            if len(audio) >= header_redundancy_samples:
                lsb_window = (audio[:header_redundancy_samples] & 1).astype(np.uint8)
                reps = header_redundancy_samples // header_bitlen
                if reps >= 1:
                    lsb_window = lsb_window[:reps * header_bitlen].reshape((reps, header_bitlen))
                    # majority vote across repetitions
                    votes = np.sum(lsb_window, axis=0)
                    majority = (votes >= (reps // 2 + 1)).astype(np.uint8)
                    try:
                        header_bytes = np.packbits(majority).tobytes()
                        content_len, start_chunk = struct.unpack('<II', header_bytes)
                        if 0 < content_len < 100_000_000 and start_chunk >= 0:
                            header_valid = True
                            self.log(f"LSB header found: content_len={content_len}, start_chunk={start_chunk}")
                    except Exception:
                        header_valid = False

            # If header was valid, prefer using it and decode payload from the start_chunk
            if header_valid:
                if "LSB" in algo:
                    bits = self.algo_lsb_decode(audio)
                elif "Echo Hiding" in algo:
                    # Prefer robust LSB backup if present: read full raw bytes from LSB area
                    try:
                        # compute required raw bits length (8-byte backup header + payload)
                        raw_bitlen = (8 + int(content_len)) * 8
                        header_area = max(2048, raw_bitlen)
                        # Read the backup area placed after the small header (offset)
                        start_off = header_redundancy_samples
                        if len(audio) >= start_off + header_area:
                            lsb_window = (audio[start_off:start_off+header_area] & 1).astype(np.uint8)
                            reps = header_area // raw_bitlen
                            if reps >= 1:
                                lsb_window = lsb_window[:reps*raw_bitlen].reshape((reps, raw_bitlen))
                                votes = np.sum(lsb_window, axis=0)
                                majority = (votes >= (reps // 2 + 1)).astype(np.uint8)
                                raw_bytes = np.packbits(majority).tobytes()
                                # backup format: [4-byte content_len][4-byte start_chunk] + payload
                                payload_bytes = raw_bytes[8:8+content_len]
                                # Save payload directly and exit
                                save_path = filedialog.asksaveasfilename(title="Save Extracted File")
                                if save_path:
                                    with open(save_path, 'wb') as f:
                                        f.write(payload_bytes)
                                    self.log(f"Success! Saved to {save_path}")
                                    messagebox.showinfo("Success", "File extracted successfully.")
                                    return
                    except Exception:
                        bits = None
                    # If backup read failed, fallback to algorithmic decode
                    if bits is None:
                        all_bits, all_conf = self.algo_echo_decode_conf(audio)
                        n_bits_needed = 64 + (content_len * 8)
                        seg_bits = all_bits[start_chunk : start_chunk + n_bits_needed]
                        seg_conf = all_conf[start_chunk : start_chunk + n_bits_needed]

                        # Calibrate mapping using the 64-bit preamble (0xAA pattern)
                        preamble_bits = np.unpackbits(np.frombuffer(b'\xAA'*8, dtype=np.uint8))
                        pre_len = min(64, len(seg_bits))
                        if pre_len == 64:
                            measured = seg_bits[:pre_len].astype(np.uint8)
                            conf_meas = seg_conf[:pre_len]
                            # threshold: take median confidence (robust) or percentile
                            median_conf = float(np.median(conf_meas))
                            thresh = median_conf if median_conf>1e-9 else np.percentile(conf_meas, 75)
                            mask = conf_meas >= thresh
                            if mask.sum() >= max(4, int(pre_len * 0.25)):
                                matches = int(np.sum(measured[mask] == preamble_bits[mask]))
                                inv_matches = int(np.sum((1-measured[mask]) == preamble_bits[mask]))
                                # If inverted mapping matches better, flip all bits
                                if inv_matches > matches:
                                    seg_bits = 1 - seg_bits
                            else:
                                # fallback: evaluate across full preamble if confident mask is too small
                                matches = int(np.sum(measured == preamble_bits))
                                inv_matches = int(np.sum((1-measured) == preamble_bits))
                                if inv_matches > matches:
                                    seg_bits = 1 - seg_bits

                            # For low-confidence positions, use a small-window majority filter
                            low_mask = conf_meas < thresh
                            if low_mask.any():
                                for i in np.where(low_mask)[0]:
                                    # window on the full seg_bits so indices map correctly
                                    w0 = max(0, i-1)
                                    w1 = min(len(seg_bits), i+2)
                                    seg_bits[i] = int(np.round(np.mean(seg_bits[w0:w1])))

                        bits = seg_bits
                elif "Phase Coding" in algo:
                    # Prefer robust LSB backup if present
                    try:
                        # compute required raw bits length (8-byte backup header + payload)
                        raw_bitlen = (8 + int(content_len)) * 8
                        header_area = max(2048, raw_bitlen)
                        # Read the backup area placed after the small header (offset)
                        start_off = header_redundancy_samples
                        if len(audio) >= start_off + header_area:
                            lsb_window = (audio[start_off:start_off+header_area] & 1).astype(np.uint8)
                            reps = header_area // raw_bitlen
                            if reps >= 1:
                                lsb_window = lsb_window[:reps*raw_bitlen].reshape((reps, raw_bitlen))
                                votes = np.sum(lsb_window, axis=0)
                                majority = (votes >= (reps // 2 + 1)).astype(np.uint8)
                                raw_bytes = np.packbits(majority).tobytes()
                                payload_bytes = raw_bytes[8:8+content_len]
                                save_path = filedialog.asksaveasfilename(title="Save Extracted File")
                                if save_path:
                                    with open(save_path, 'wb') as f:
                                        f.write(payload_bytes)
                                    self.log(f"Success! Saved to {save_path}")
                                    messagebox.showinfo("Success", "File extracted successfully.")
                                    return
                    except Exception:
                        bits = None
                    if bits is None:
                        all_bits, all_conf = self.algo_phase_decode_conf(audio)
                        n_bits_needed = 64 + (content_len * 8)
                        # start_chunk stored for Phase is in "segments" units; convert to bits
                        start_bit = int(start_chunk) * 8
                        seg_bits = all_bits[start_bit : start_bit + n_bits_needed]
                        seg_conf = all_conf[start_bit : start_bit + n_bits_needed]

                        preamble_bits = np.unpackbits(np.frombuffer(b'\xAA'*8, dtype=np.uint8))
                        pre_len = min(64, len(seg_bits))
                        if pre_len == 64:
                            measured = seg_bits[:pre_len].astype(np.uint8)
                            conf_meas = seg_conf[:pre_len]
                            median_conf = float(np.median(conf_meas))
                            thresh = median_conf if median_conf>1e-9 else np.percentile(conf_meas, 75)
                            mask = conf_meas >= thresh
                            if mask.sum() >= max(4, int(pre_len * 0.25)):
                                matches = int(np.sum(measured[mask] == preamble_bits[mask]))
                                inv_matches = int(np.sum((1-measured[mask]) == preamble_bits[mask]))
                                if inv_matches > matches:
                                    seg_bits = 1 - seg_bits
                            low_mask = conf_meas < thresh
                            if low_mask.any():
                                for i in np.where(low_mask)[0]:
                                    w0 = max(0, i-1)
                                    w1 = min(len(seg_bits), i+2)
                                    seg_bits[i] = int(np.round(np.mean(seg_bits[w0:w1])))
                        bits = seg_bits
            else:
                # Fallback: original behavior (preamble search / whole-file decode)
                if "LSB" in algo:
                    bits = self.algo_lsb_decode(audio)
                elif "Echo Hiding" in algo:
                    bits = self.algo_echo_decode(audio)
                elif "Phase Coding" in algo:
                    bits = self.algo_phase_decode(audio)
                
            if bits is None: 
                self.log("Extraction failed.")
                return
            # Try packing bits into bytes. If header fails, we'll attempt bit shifts
            byte_data = np.packbits(bits)
            
            if len(byte_data) < 4:
                self.log("Error: Not enough data.")
                return
                

            # Helper: validate header and return content_len or None
            def read_header(bdata):
                if len(bdata) < 4: return None
                try:
                    ln = struct.unpack('<I', bdata[:4].tobytes())[0]
                    if ln == 0 or ln > 100_000_000: return None
                    return ln
                except Exception:
                    return None

            content_len = read_header(byte_data)

            # If header invalid, search for preamble pattern (8 bytes of 0xAA -> 64 bits)
            if content_len is None:
                preamble_bytes = b'\xAA' * 8
                pre_bits = np.unpackbits(np.frombuffer(preamble_bytes, dtype=np.uint8))
                found = False

                # Search for preamble bit sequence in the decoded bits using
                # an approximate match (allow some bit errors). We pick the
                # alignment with the highest number of matching bits and
                # require a strong ratio to accept it.
                pb_len = len(pre_bits)
                best_matches = -1
                best_start = None
                search_len = max(0, len(bits) - pb_len + 1)
                for start in range(search_len):
                    seg = bits[start:start+pb_len]
                    matches = int(np.sum(seg == pre_bits))
                    if matches > best_matches:
                        best_matches = matches
                        best_start = start

                if best_start is not None and best_matches >= int(pb_len * 0.6):
                    shifted = bits[best_start + pb_len:]
                    bdata = np.packbits(shifted)
                    content_len = read_header(bdata)
                    if content_len is not None:
                        bits = shifted
                        byte_data = bdata
                        found = True
                        self.log(f"Header found after preamble approx at bit {best_start} (matches {best_matches}/{pb_len})")
                    else:
                        # Try small fine-grained shifts within the window to locate header
                        max_fine = min(512, len(shifted))
                        for s2 in range(1, max_fine):
                            bdata2 = np.packbits(shifted[s2:])
                            content_len = read_header(bdata2)
                            if content_len is not None:
                                bits = shifted[s2:]
                                byte_data = bdata2
                                found = True
                                self.log(f"Header found after preamble approx at bit {best_start}, fine shift {s2}")
                                break


                if not found:
                    self.log("Error: Header corrupt or wrong algorithm. Tried preamble search and failed.")
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
        """Echo Decoding (compat): returns hard bits. Uses confidence-aware
        routine under the hood for better results. Keep this for backwards
        compatibility."""
        bits, _ = self.algo_echo_decode_conf(audio)
        return bits

    def algo_echo_decode_conf(self, audio):
        """Echo Decoding with confidence scores.
        Returns (bits, conf) where conf is |v1 - v0| per chunk.
        """
        chunk_len = 1024
        d0 = 32
        d1 = 64

        audio_len = len(audio)
        n_chunks = audio_len // chunk_len
        bits = np.zeros(n_chunks, dtype=np.uint8)
        conf = np.zeros(n_chunks, dtype=np.float32)

        window = np.hanning(chunk_len)

        def corr_between(chunk, src):
            c = (chunk - np.mean(chunk)) * window
            s = (src - np.mean(src)) * window
            num = np.sum(c * s)
            den = np.sqrt(np.sum(c*c) * np.sum(s*s)) + 1e-9
            return num / den

        for i in range(n_chunks):
            start = i * chunk_len
            end = start + chunk_len
            if end > audio_len: break

            chunk = audio[start:end].astype(np.float32)

            # Build zero-padded source buffer identical to encoder and apply
            # the same Hanning window before computing the regression.
            def build_src(delay):
                p_start = start - delay
                p_end = end - delay
                src = np.zeros(chunk_len, dtype=np.float32)
                src_s = max(0, p_start)
                src_e = min(audio_len, p_end)
                if src_e > src_s:
                    dest_start = 0 if p_start >= 0 else (-p_start)
                    src[dest_start:dest_start + (src_e - src_s)] = audio[src_s:src_e].astype(np.float32)
                return src * window

            src0 = build_src(d0)
            src1 = build_src(d1)
            c = (chunk.astype(np.float32)) * window

            # Compute least-squares coefficient alpha_hat = sum(c*src) / sum(src*src)
            denom0 = np.sum(src0 * src0) + 1e-9
            denom1 = np.sum(src1 * src1) + 1e-9
            num0 = np.sum(c * src0)
            num1 = np.sum(c * src1)
            a0 = float(num0 / denom0)
            a1 = float(num1 / denom1)

            # Compute normalized residual energy for each hypothesis and pick the smaller.
            res0 = np.sum((c - a0 * src0) ** 2)
            res1 = np.sum((c - a1 * src1) ** 2)
            # normalize by energy to get comparable score
            energy = np.sum(c * c) + 1e-9
            r0 = res0 / energy
            r1 = res1 / energy

            # smaller residual indicates correct hypothesis
            bits[i] = 1 if r1 < r0 else 0
            # confidence is the relative residual difference (higher -> more confident)
            conf[i] = abs(r0 - r1) / (r0 + r1 + 1e-9)

        return bits, conf

    def algo_phase_decode(self, audio):
        """Phase Coding Decode (compat): returns hard bits. Uses confidence-aware
        routine under the hood."""
        bits, _ = self.algo_phase_decode_conf(audio)
        return bits

    def algo_phase_decode_conf(self, audio):
        """Phase Coding decode that also returns a confidence per decoded bit.
        Returns (bits, conf) where conf is the absolute difference in distance
        between the two candidate phases.
        """
        segment_len = 256
        start_bin = 20 # Must match encoder
        n_segments = len(audio) // segment_len
        bits = []
        conf = []
        for i in range(n_segments):
            s = i * segment_len
            e = s + segment_len
            chunk = audio[s:e]
            if len(chunk) < segment_len: break

            spectrum = np.fft.rfft(chunk)
            mag = np.abs(spectrum)
            phase = np.angle(spectrum)

            for b_offset in range(8):
                target = start_bin + b_offset
                if target >= len(phase): break

                p = phase[target]
                # Distances to the two possible encoded phases (payload uses ±pi/4)
                dist_1 = abs(p - (np.pi/4))
                dist_0 = abs(p - (-np.pi/4))
                if dist_1 > np.pi: dist_1 = 2*np.pi - dist_1
                if dist_0 > np.pi: dist_0 = 2*np.pi - dist_0

                bits.append(1 if dist_1 < dist_0 else 0)
                conf.append(abs(dist_1 - dist_0))

        return np.array(bits, dtype=np.uint8), np.array(conf, dtype=np.float32)

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
            finally:
                self.is_playing = False

        self.play_thread = threading.Thread(target=run, daemon=True)
        self.play_thread.start()

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
            finally:
                self.is_playing = False

        self.decode_thread = threading.Thread(target=run, daemon=True)
        self.decode_thread.start()

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