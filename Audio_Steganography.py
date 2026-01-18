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
        
        # Dynamic sizing based on screen resolution
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        
        # Use 70% of screen size, with min/max bounds
        win_width = int(screen_width * 0.5)
        win_height = int(screen_height * 0.85)
        
        # Center the window on screen
        x_pos = (screen_width - win_width) // 2
        y_pos = (screen_height - win_height) // 2
        
        self.root.geometry(f"{win_width}x{win_height}+{x_pos}+{y_pos}")
        self.root.minsize(800, 650)

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
        self.comparison_file_path = None  # Optional file for BER comparison
        
        # Echo Hiding Parameters
        self.echo_chunk_size = tk.IntVar(value=2048)
        self.echo_delay_0 = tk.IntVar(value=50)
        self.echo_delay_1 = tk.IntVar(value=200)
        self.echo_alpha = tk.DoubleVar(value=0.5)
        
        # Magic bytes for file type detection
        self.MAGIC_BYTES = {
            b'\x89PNG': ('.png', 'PNG Image'),
            b'\xFF\xD8\xFF': ('.jpg', 'JPEG Image'),
            b'GIF87a': ('.gif', 'GIF Image'),
            b'GIF89a': ('.gif', 'GIF Image'),
            b'%PDF': ('.pdf', 'PDF Document'),
            b'PK\x03\x04': ('.zip', 'ZIP Archive'),
            b'PK\x05\x06': ('.zip', 'ZIP Archive (empty)'),
            b'Rar!\x1a\x07': ('.rar', 'RAR Archive'),
            b'RIFF': ('.wav', 'WAV Audio'),
            b'\x00\x00\x00\x1c': ('.mp4', 'MP4 Video'),
            b'\x00\x00\x00\x20': ('.mp4', 'MP4 Video'),
            b'ID3': ('.mp3', 'MP3 Audio'),
            b'\xff\xfb': ('.mp3', 'MP3 Audio'),
            b'\x1f\x8b': ('.gz', 'GZIP Archive'),
            b'BM': ('.bmp', 'BMP Image'),
            b'\x00\x00\x01\x00': ('.ico', 'ICO Icon'),
            b'MZ': ('.exe', 'Windows Executable'),
            b'\x7fELF': ('.elf', 'Linux Executable'),
        }
        
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
        self.algo_menu['values'] = ("LSB (Least Significant Bit)", "Echo Hiding", "Phase Coding", "Spread Spectrum")
        self.algo_menu.grid(row=0, column=1, sticky="ew", padx=10)
        
        # Binds - use a wrapper to ensure both functions fire
        self.algo_menu.bind("<<ComboboxSelected>>", self.on_algo_change)

        self.algo_desc_lbl = ttk.Label(algo_frame, text="Best for: Maximum Capacity. Fragile (breaks with edits).", font=("Segoe UI", 9, "italic"), foreground="#555")
        self.algo_desc_lbl.grid(row=1, column=0, columnspan=2, sticky="w", pady=(5, 5))

        self.status_lbl = ttk.Label(algo_frame, text="Waiting for inputs...", style="Bold.TLabel", foreground="#d9534f")
        self.status_lbl.grid(row=2, column=0, columnspan=2, sticky="w", pady=(5, 0))
        
        # --- Advanced Settings (Echo Hiding) ---
        self.advanced_frame = ttk.Frame(algo_frame, padding=5)
        self.advanced_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.advanced_frame.columnconfigure(1, weight=1)
        self.advanced_visible = False
        self.advanced_content = ttk.Frame(self.advanced_frame)
        
        # Toggle button (indicates this is for Echo Hiding)
        self.btn_toggle_advanced = ttk.Button(self.advanced_frame, text="▶ Echo Hiding: Show Advanced Settings", command=self.toggle_advanced_settings)
        self.btn_toggle_advanced.grid(row=0, column=0, columnspan=2, sticky="w")
        
        # Chunk Size
        ttk.Label(self.advanced_content, text="Chunk Size:").grid(row=0, column=0, sticky="w", pady=3)
        self.spin_chunk = ttk.Spinbox(self.advanced_content, from_=256, to=8192, increment=256, textvariable=self.echo_chunk_size, width=8)
        self.spin_chunk.grid(row=0, column=1, sticky="w", padx=5)
        ttk.Label(self.advanced_content, text="Samples per bit. Smaller = more capacity.", font=("Segoe UI", 8), foreground="#666").grid(row=0, column=2, sticky="w", padx=5)
        
        # Delay 0
        ttk.Label(self.advanced_content, text="Delay 0:").grid(row=1, column=0, sticky="w", pady=3)
        self.spin_d0 = ttk.Spinbox(self.advanced_content, from_=10, to=500, increment=10, textvariable=self.echo_delay_0, width=8)
        self.spin_d0.grid(row=1, column=1, sticky="w", padx=5)
        ttk.Label(self.advanced_content, text="Echo delay for bit 0.", font=("Segoe UI", 8), foreground="#666").grid(row=1, column=2, sticky="w", padx=5)
        
        # Delay 1
        ttk.Label(self.advanced_content, text="Delay 1:").grid(row=2, column=0, sticky="w", pady=3)
        self.spin_d1 = ttk.Spinbox(self.advanced_content, from_=50, to=1000, increment=50, textvariable=self.echo_delay_1, width=8)
        self.spin_d1.grid(row=2, column=1, sticky="w", padx=5)
        ttk.Label(self.advanced_content, text="Echo delay for bit 1. Should differ from Delay 0.", font=("Segoe UI", 8), foreground="#666").grid(row=2, column=2, sticky="w", padx=5)
        
        # Alpha (changed from slider to spinbox)
        ttk.Label(self.advanced_content, text="Alpha:").grid(row=3, column=0, sticky="w", pady=3)
        self.spin_alpha = ttk.Spinbox(self.advanced_content, from_=0.1, to=1.0, increment=0.1, textvariable=self.echo_alpha, width=8, format="%.2f")
        self.spin_alpha.grid(row=3, column=1, sticky="w", padx=5)
        ttk.Label(self.advanced_content, text="Echo strength (0.1-1.0). Higher = more reliable but audible.", font=("Segoe UI", 8), foreground="#666").grid(row=3, column=2, sticky="w", padx=5)
        
        # Bind chunk size changes to update capacity
        self.echo_chunk_size.trace_add("write", lambda *args: self.update_capacity_check())
        
        # Reset button
        ttk.Button(self.advanced_content, text="Reset to Defaults", command=self.reset_echo_defaults).grid(row=4, column=0, columnspan=2, sticky="w", pady=(10, 0))

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
        # Auto-update preview if possible
        if self.audio_data is not None:
             # Use a thread to avoid freezing UI for large files
             threading.Thread(target=self.generate_preview, daemon=True).start()


    
    def toggle_advanced_settings(self):
        """Toggle visibility of the advanced settings panel."""
        if self.advanced_visible:
            self.advanced_content.grid_forget()
            self.btn_toggle_advanced.config(text="▶ Echo Hiding: Show Advanced Settings")
            self.advanced_visible = False
        else:
            self.advanced_content.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(5, 0))
            self.btn_toggle_advanced.config(text="▼ Echo Hiding: Hide Advanced Settings")
            self.advanced_visible = True
    
    def reset_echo_defaults(self):
        """Reset echo hiding parameters."""
        self.echo_chunk_size.set(2048)
        self.echo_delay_0.set(50)
        self.echo_delay_1.set(200)
        self.echo_alpha.set(0.5)
        self.update_capacity_check()

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
        ttk.Label(dec_frame, text="Algorithm:").grid(row=1, column=0, sticky="w", pady=10)
        ttk.Label(dec_frame, text="Auto-Detected from Smart Header", font=("Segoe UI", 9, "italic"), foreground="#555").grid(row=1, column=1, sticky="w", padx=10)
        # self.decode_algo_var was used but logic now ignores it

        # Optional: Comparison file for BER calculation
        compare_frame = ttk.LabelFrame(self.tab_decode, text=" 2. BER Comparison (Optional) ", padding=10)
        compare_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=5)
        compare_frame.columnconfigure(1, weight=1)
        
        ttk.Button(compare_frame, text="Select Original File", command=self.load_comparison_file).grid(row=0, column=0, sticky="w")
        self.lbl_compare_file = ttk.Label(compare_frame, text="No file selected (decode will work without this)", foreground="#666")
        self.lbl_compare_file.grid(row=0, column=1, sticky="w", padx=10)
        ttk.Button(compare_frame, text="Clear", command=self.clear_comparison_file).grid(row=0, column=2, sticky="e")
        
        self.lbl_ber_result = ttk.Label(compare_frame, text="", font=("Segoe UI", 10, "bold"))
        self.lbl_ber_result.grid(row=1, column=0, columnspan=3, sticky="w", pady=(5, 0))

        # Action
        self.btn_extract = ttk.Button(self.tab_decode, text="Extract Hidden File", command=self.extract_file, state="disabled")
        self.btn_extract.grid(row=2, column=0, sticky="ew", padx=10, pady=(10, 0))

        # Log
        log_frame = ttk.LabelFrame(self.tab_decode, text=" Activity Log ", padding=10)
        log_frame.grid(row=3, column=0, sticky="nsew", padx=10, pady=10)
        self.tab_decode.rowconfigure(3, weight=1)

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
                # Trigger auto-preview
                threading.Thread(target=self.generate_preview, daemon=True).start()
            except Exception as e:
                messagebox.showerror("Error", str(e))

    def load_payload(self):
        path = filedialog.askopenfilename()
        if path:
            self.payload_path = path
            size_kb = os.path.getsize(path) / 1024
            self.lbl_payload.config(text=f"{os.path.basename(path)} ({size_kb:.2f} KB)", foreground="#28a745")
            self.update_capacity_check()
            # Trigger auto-preview
            threading.Thread(target=self.generate_preview, daemon=True).start()

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

    def load_comparison_file(self):
        """Load optional comparison file for BER calculation."""
        path = filedialog.askopenfilename(filetypes=[("All files", "*.*")])
        if path:
            self.comparison_file_path = path
            size_kb = os.path.getsize(path) / 1024
            self.lbl_compare_file.config(text=f"{os.path.basename(path)} ({size_kb:.2f} KB)", foreground="#28a745")
            self.lbl_ber_result.config(text="")

    def clear_comparison_file(self):
        """Clear comparison file selection."""
        self.comparison_file_path = None
        self.lbl_compare_file.config(text="No file selected (decode will work without this)", foreground="#666")
        self.lbl_ber_result.config(text="")

    def calculate_ber(self, original_bytes, decoded_bytes):
        """Calculate Bit Error Rate between two byte sequences."""
        orig_bits = np.unpackbits(np.frombuffer(original_bytes, dtype=np.uint8))
        dec_bits = np.unpackbits(np.frombuffer(decoded_bytes, dtype=np.uint8))
        
        min_len = min(len(orig_bits), len(dec_bits))
        if min_len == 0:
            return 0, 0, 0
        
        errors = np.sum(orig_bits[:min_len] != dec_bits[:min_len])
        ber = errors / min_len * 100
        return ber, errors, min_len


    # =============================================================================
    # CORE LOGIC SECTION
    # =============================================================================
    # This section contains the main steganography logic including:
    # - Capacity calculations for each algorithm
    # - Smart Header creation and parsing (15-byte protocol)
    # - Encoding and decoding algorithms (LSB, Echo Hiding, Phase Coding, DSSS)
    #
    # Algorithm implementations are inspired by the MATLAB library:
    # https://github.com/ktekeli/audio-steganography-algorithms
    # by Kadir Tekeli (MIT License 2016-2017)
    # =============================================================================

    def update_algo_description(self, event=None):
        """
        Update the algorithm description label in the UI based on selected algorithm.
        
        Each algorithm has different trade-offs:
        - LSB: Maximum capacity (1 bit/sample), but fragile to any modification
        - Echo Hiding: More robust (survives some compression), lower capacity
        - Spread Spectrum (DSSS): Very robust to noise, very low capacity 
        - Phase Coding: Good imperceptibility, moderate capacity
        """
        algo = self.algo_var.get()
        desc = ""
        if "LSB" in algo:
            desc = "Best for: Capacity. Fragile. 1 bit per sample."
        elif "Echo Hiding" in algo:
            chunk = self.echo_chunk_size.get()
            desc = f"Best for: Robustness. Adds tiny echoes (1 bit per {chunk} samples)."
        elif "Spread Spectrum" in algo:
            desc = "Best for: Noise resistance. Uses DSSS (1 bit per 8192 samples)."
        elif "Phase Coding" in algo:
            desc = "Best for: Imperceptibility. Hides in Phase (8 bits per 256 samples)."
        self.algo_desc_lbl.config(text=desc)

    def get_max_kb(self):
        """
        Calculate the maximum payload capacity in kilobytes for the selected algorithm.
        
        Capacity varies dramatically between algorithms:
        - LSB: 1 bit per audio sample (highest capacity)
        - Echo Hiding: 1 bit per chunk (chunk_size samples per bit)
        - DSSS: 1 bit per 8192 samples (very low capacity, but robust)
        - Phase Coding: 8 bits per 256-sample segment
        
        Returns:
            float: Maximum payload size in kilobytes (KB)
        """
        if self.audio_data is None: return 0
        total_samples = self.audio_data.size
        algo = self.algo_var.get()
        
        # Reserve 4 bytes for header overhead plus safety margin
        header_bytes = 4
        bytes_avail = 0

        if "LSB" in algo:
            # LSB: Each audio sample can hold 1 bit of data
            # Total bits = total_samples, so bytes = total_samples / 8
            bytes_avail = (total_samples // 8) - header_bytes
            
        elif "Echo Hiding" in algo:
            # Echo Hiding: Each chunk encodes 1 bit
            # Configurable chunk_size (default 2048) determines capacity
            chunk_len = self.echo_chunk_size.get()
            bits = total_samples // chunk_len
            bytes_avail = (bits // 8) - header_bytes
            
        elif "Spread Spectrum" in algo:
            # DSSS: Each 8192-sample frame encodes 1 bit
            # Very low capacity but extremely robust to noise
            bits = total_samples // 8192
            bytes_avail = (bits // 8) - header_bytes
            
        elif "Phase Coding" in algo:
            # Phase Coding: Each 256-sample segment encodes 8 bits (1 byte)
            # Uses frequency bins 20-27 to store data in phase angles
            segment_len = 256
            bytes_avail = (total_samples // segment_len) - header_bytes

        # Return capacity in kilobytes, never negative
        return max(0, bytes_avail / 1024)

    # =============================================================================
    # SMART HEADER PROTOCOL
    # =============================================================================
    # The Smart Header is a 15-byte metadata block stored at the beginning of the
    # stego audio using LSB encoding. It allows the decoder to automatically detect:
    # - Which algorithm was used (algo_id)
    # - Algorithm-specific parameters (chunk size, delays, etc.)
    # - Payload length (how many bytes of hidden data)
    # - CRC checksum for validation
    #
    # Header is written starting at sample 0, payload data starts at HEADER_OFFSET.
    # =============================================================================
    
    def create_smart_header(self, algo_id, param1, param2, param3, payload_len):
        """
        Create a 15-byte Smart Header for the stego file.
        
        The header is structured as follows (little-endian byte order):
        ┌─────────┬──────────┬─────────┬─────────┬─────────┬─────────────┬─────────┐
        │ Bytes   │ 0-1      │ 2       │ 3-4     │ 5-6     │ 7-8         │ 9-12    │ 13-14   │
        ├─────────┼──────────┼─────────┼─────────┼─────────┼─────────────┼─────────┤
        │ Field   │ Magic    │ Algo ID │ Param1  │ Param2  │ Param3      │ Length  │ CRC     │
        │ Type    │ 2s char  │ B uint8 │ H uint16│ H uint16│ H uint16    │ I uint32│ H uint16│
        └─────────┴──────────┴─────────┴─────────┴─────────┴─────────────┴─────────┘
        
        struct.pack format string: '<2sBHHHI'
        - '<' = Little-endian byte order (LSB first)
        - '2s' = 2-byte string (the magic bytes 'st')
        - 'B' = Unsigned char/byte (0-255) for algorithm ID
        - 'H' = Unsigned short (0-65535) for parameters
        - 'I' = Unsigned int (0-4294967295) for payload length
        
        Args:
            algo_id: Algorithm identifier (1=LSB, 2=Echo, 3=Phase, 4=DSSS)
            param1, param2, param3: Algorithm-specific parameters
                - Echo: chunk_size, delay_0, delay_1
                - Phase: segment_size, start_bin, unused
                - DSSS: frame_size, unused, unused
            payload_len: Size of hidden data in bytes
            
        Returns:
            bytes: 15-byte header ready for LSB encoding
        """
        # Magic bytes 'st' identify this as a steganography file
        magic = b'st'
        
        # Pack the header data (13 bytes without CRC)
        # Format: little-endian, 2-char string, 1 byte, 3 unsigned shorts, 1 unsigned int
        data = struct.pack('<2sBHHHI', magic, algo_id, param1, param2, param3, payload_len)
        
        # Calculate simple checksum: sum of all bytes, masked to 16 bits
        # This allows detection of header corruption during decoding
        checksum = sum(data) & 0xFFFF
        
        # Append CRC as final 2 bytes (unsigned short)
        full_header = data + struct.pack('<H', checksum)
        return full_header  # Total: 13 + 2 = 15 bytes

    # Fixed offset where payload data starts (samples 0-999 reserved for header)
    # Header only needs 120 bits (15 bytes * 8), but we use 1000 for safety margin
    HEADER_OFFSET = 1000

    def calculate_header_offset(self):
        """Return the fixed header offset constant (1000 samples)."""
        return self.HEADER_OFFSET

    def read_smart_header(self, audio):
        """
        Read and validate the 15-byte Smart Header from the beginning of stego audio.
        
        The header is encoded in the LSB of the first 120 audio samples (15 bytes * 8 bits).
        This function extracts those bits, reconstructs the header, and validates it.
        
        Decoding Process:
        1. Extract LSB (bit 0) from first 120 samples → 120 bits = 15 bytes
        2. Pack bits back into bytes using np.packbits()
        3. Unpack the header structure using struct.unpack()
        4. Validate magic bytes ('st') and CRC checksum
        
        Returns:
            dict: {'algo_id', 'p1', 'p2', 'p3', 'payload_len'} if valid, None otherwise
        """
        try:
            header_len = 15  # 15 bytes total
            bits_needed = header_len * 8  # 120 bits
            
            # Audio must have at least 120 samples for the header
            if len(audio) < bits_needed: return None
            
            # Extract LSB from each of the first 120 samples
            # audio[:bits_needed] & 1 performs bitwise AND with 1, isolating bit 0
            # This gives an array of 120 values, each being 0 or 1
            header_bits = audio[:bits_needed] & 1
            
            # Convert 120 individual bits back into 15 bytes
            # np.packbits() groups every 8 bits into a single byte (MSB first)
            # .tobytes() converts the numpy array to a Python bytes object
            header_bytes = np.packbits(header_bits).tobytes()
            
            # Unpack the 15-byte structure using the same format as create_smart_header
            # Format: '<2sBHHHIH' adds the 2-byte CRC at the end
            # - '<' = little-endian
            # - '2s' = 2-byte string (magic)
            # - 'B' = 1-byte unsigned (algo_id)
            # - 'HHH' = 3 unsigned shorts (params)
            # - 'I' = unsigned int (payload length)
            # - 'H' = unsigned short (CRC)
            magic, algo_id, p1, p2, p3, length, crc = struct.unpack('<2sBHHHIH', header_bytes)
            
            # Validate magic bytes - must be 'st' to confirm this is a stego file
            if magic != b'st': return None
            
            # Validate CRC checksum
            # CRC is calculated over the first 13 bytes (everything except the CRC itself)
            data_part = header_bytes[:-2]  # First 13 bytes
            calc_crc = sum(data_part) & 0xFFFF  # Sum of bytes, masked to 16 bits
            if calc_crc != crc: return None  # CRC mismatch = corrupted header
            
            # Return parsed header as a dictionary for easy access
            return {'algo_id': algo_id, 'p1': p1, 'p2': p2, 'p3': p3, 'payload_len': length}
            
        except Exception:
            # Any parsing error means invalid/corrupted header
            return None

    def update_capacity_check(self, event=None):
        """
        Update the UI status label to show if the payload fits in the carrier audio.
        
        Compares the payload file size against the maximum capacity calculated by
        get_max_kb(). Enables or disables the encode button based on capacity.
        """
        if not self.carrier_path: return

        limit_kb = self.get_max_kb()
        self.update_algo_description()
        
        if not self.payload_path:
            # No payload selected yet, just show maximum available capacity
            self.status_lbl.config(text=f"Max Capacity: {limit_kb:.2f} KB", foreground="#333")
            return

        # Calculate payload size in KB
        payload_kb = os.path.getsize(self.payload_path) / 1024
        # Reserve 32 bytes of overhead for header + safety margin
        header_kb = 32 / 1024 
        
        if payload_kb + header_kb > limit_kb: 
            # Payload too large - disable encoding buttons
            self.status_lbl.config(text=f"Error: File too large! ({payload_kb:.2f} KB > {limit_kb:.2f} KB)", foreground="#d9534f")
            self.btn_bake.state(['disabled'])
            self.btn_play_stego.state(['disabled'])
        else:
            # Payload fits - enable encoding buttons
            self.status_lbl.config(text=f"Ready: File fits ({payload_kb:.2f} KB / {limit_kb:.2f} KB)", foreground="#28a745")
            self.btn_bake.state(['!disabled'])
            self.btn_play_stego.state(['!disabled'])

    def process_steganography(self):
        """
        Main encoding function: embed payload into audio using selected algorithm.
        
        Encoding Workflow:
        1. Load the payload file as raw bytes
        2. Convert bytes to a bit array using np.unpackbits()
        3. Create the 15-byte Smart Header with algorithm parameters
        4. Embed header at samples 0-119 using LSB encoding
        5. Embed payload starting at sample 1000 using the selected algorithm
        
        The header is ALWAYS LSB-encoded regardless of the payload algorithm.
        This allows the decoder to read the header first and determine which
        algorithm to use for the payload.
        
        Returns:
            np.ndarray: Modified audio with embedded data, or None on error
        """
        if self.audio_data is None or self.payload_path is None: return None

        # =================================================================
        # STEP 1: Load Payload as Raw Bytes
        # =================================================================
        with open(self.payload_path, 'rb') as f:
            data = f.read()
        payload_len = len(data)

        # =================================================================
        # STEP 2: Convert Payload Bytes to Bit Array
        # =================================================================
        # np.frombuffer() interprets the bytes as unsigned 8-bit integers (0-255)
        byte_array = np.frombuffer(data, dtype=np.uint8)
        # np.unpackbits() expands each byte into 8 individual bits (MSB first)
        # Example: byte 0x4D (77) becomes [0,1,0,0,1,1,0,1]
        bits_to_encode = np.unpackbits(byte_array)
        
        # Create a copy of audio to modify (preserve original for comparison)
        audio_copy = self.audio_data.copy()
        algo_name = self.algo_var.get()
        start_offset = self.HEADER_OFFSET  # 1000 samples
        
        # =================================================================
        # STEP 3: Determine Algorithm ID and Parameters
        # =================================================================
        # Algorithm IDs: 1=LSB, 2=Echo, 3=Phase, 4=DSSS
        algo_id = 1
        p1, p2, p3 = 0, 0, 0  # Default parameters
        
        if "Echo" in algo_name:
            algo_id = 2
            p1 = self.echo_chunk_size.get()  # Samples per bit (default: 2048)
            p2 = self.echo_delay_0.get()     # Echo delay for bit 0 (default: 50)
            p3 = self.echo_delay_1.get()     # Echo delay for bit 1 (default: 200)
        elif "Spread Spectrum" in algo_name:
            algo_id = 4
            p1 = 8192  # Frame size (fixed, 8192 samples per bit)
            p2 = 0
            p3 = 0
        elif "Phase" in algo_name:
            algo_id = 3
            p1 = 256  # Segment size (256 samples)
            p2 = 20   # Starting frequency bin
            p3 = 0
            
        # =================================================================
        # STEP 4: Create and Embed Header (Always LSB)
        # =================================================================
        header = self.create_smart_header(algo_id, p1, p2, p3, payload_len)
        # Convert header bytes to bits for LSB embedding
        header_bits = np.unpackbits(np.frombuffer(header, dtype=np.uint8))
        
        # Check audio is long enough for header + payload offset
        if len(audio_copy) < len(header_bits) + start_offset:
            self.update_status("Error: Audio too short.")
            return None
        
        # Embed header using LSB encoding at the start of audio (samples 0-119)
        # This line performs bitwise manipulation to replace the LSB of each sample:
        #
        # audio_copy[:len(header_bits)]         - Select first 120 audio samples
        # & ~1                                   - Clear bit 0 (AND with 11111110)
        #                                        ~1 is bitwise NOT of 1 = ...11111110
        # | header_bits                         - Set bit 0 to header bit value (OR)
        #
        # Example: sample = 1234 (binary: 10011010010)
        #          header_bit = 1
        #          (1234 & ~1) | 1 = (1234 & -2) | 1 = 1234 | 1 = 1235
        audio_copy[:len(header_bits)] = (audio_copy[:len(header_bits)] & ~1) | header_bits
        
        # =================================================================
        # STEP 5: Encode Payload Using Selected Algorithm
        # =================================================================
        # Payload data starts at HEADER_OFFSET (sample 1000) to avoid header
        if algo_id == 2:  # Echo Hiding
            return self.algo_echo_encode(audio_copy, bits_to_encode, start_offset=start_offset, payload_len=payload_len)
        elif algo_id == 4:  # Spread Spectrum (DSSS)
            return self.algo_spread_spectrum_encode(audio_copy, bits_to_encode, start_offset=start_offset)
        elif algo_id == 3:  # Phase Coding
            return self.algo_phase_encode(audio_copy, bits_to_encode, start_offset=start_offset)
        elif algo_id == 1:  # LSB (default)
            return self.algo_lsb_encode(audio_copy, bits_to_encode, start_index=start_offset)
        
        return audio_copy

    def generate_preview(self):
        """
        Generate a preview of the steganography effect without a real payload.
        
        This function creates a quick preview by encoding dummy random data
        into the audio. It's used to visualize how the selected algorithm
        affects the waveform before actually encoding a real file.
        
        The preview helps users understand the trade-offs of each algorithm:
        - LSB: Almost invisible modification
        - Echo: Visible amplitude changes where echoes are added
        - Phase: Minimal visible change (phase is imperceptible)
        - DSSS: Wide-spread low-amplitude noise
        """
        if self.audio_data is None: return
        
        # Use 512 bytes as dummy payload size for preview visualization
        dummy_len = 512
        audio_copy = self.audio_data.copy()
        algo_name = self.algo_var.get()
        start_offset = self.HEADER_OFFSET
        
        # Create a header for the preview (same format as real encoding)
        # This ensures the preview matches what the actual output would look like
        algo_id = 1
        p1=0; p2=0; p3=0
        if "Echo" in algo_name: 
            algo_id = 2
            p1=self.echo_chunk_size.get(); p2=100; p3=150
        elif "Spread Spectrum" in algo_name:
            algo_id = 4
            p1=8192
        elif "Phase" in algo_name: 
            algo_id = 3
            p1=256; p2=20
            
        # Create and embed the header in LSB
        header = self.create_smart_header(algo_id, p1, p2, p3, dummy_len)
        header_bits = np.unpackbits(np.frombuffer(header, dtype=np.uint8))
        audio_copy[:len(header_bits)] = (audio_copy[:len(header_bits)] & ~1) | header_bits
        
        # Generate 1000 random bits (0 or 1) as dummy payload data
        bits = np.random.randint(0, 2, 1000)
        
        try:
            # Encode dummy bits using the selected algorithm
            if algo_id == 2:
                self.processed_audio = self.algo_echo_encode(audio_copy, bits, start_offset=start_offset, payload_len=125)
            elif algo_id == 4:
                self.processed_audio = self.algo_spread_spectrum_encode(audio_copy, bits, start_offset=start_offset)
            elif algo_id == 3:
                self.processed_audio = self.algo_phase_encode(audio_copy, bits, start_offset=start_offset)
            else:
                self.processed_audio = self.algo_lsb_encode(audio_copy, bits, start_index=start_offset)
            
            # Schedule UI update on the main thread (required for Tkinter)
            self.root.after(0, self.update_plots)
        except Exception as e:
            print(f"Preview Error: {e}")


    # =============================================================================
    # ENCODING ALGORITHMS
    # =============================================================================
    # These algorithms implement different steganography techniques to hide data
    # in audio. Each has trade-offs between capacity, robustness, and imperceptibility.
    #
    # Algorithm implementations inspired by the MATLAB library:
    # https://github.com/ktekeli/audio-steganography-algorithms
    # by Kadir Tekeli (MIT License 2016-2017)
    # =============================================================================

    def algo_lsb_encode(self, audio, bits, start_index=0):
        """
        LSB (Least Significant Bit) Encoding Algorithm.
        
        Theory:
        - Each 16-bit audio sample has a value from -32768 to 32767
        - The LSB (bit 0) contributes only ±1 to the value, which is imperceptible
        - We replace the LSB of each sample with a payload bit
        
        This is the simplest and highest-capacity steganography method, but it's
        fragile - any modification to the audio (compression, normalization, etc.)
        will destroy the hidden data.
        
        Args:
            audio: Audio sample array (modified in-place)
            bits: Array of bits (0 or 1) to embed
            start_index: Sample index to start embedding (default: 0)
        
        Returns:
            np.ndarray: Modified audio with embedded bits
        """
        num_bits = len(bits)
        available = len(audio) - start_index
        
        # Truncate bits if we don't have enough audio samples
        if num_bits > available:
            bits = bits[:available]
        
        # LSB Embedding with Numpy vectorized operation:
        # 
        # audio[start_index:start_index+len(bits)]  - Select samples to modify
        # & ~1                                       - Clear bit 0 (AND with ...11111110)
        # | bits                                     - Set bit 0 to payload value (OR)
        #
        # This is equivalent to the loop:
        #   for i, bit in enumerate(bits):
        #       sample = audio[start_index + i]
        #       audio[start_index + i] = (sample & 0xFFFE) | bit
        #
        # Example breakdown:
        #   sample = 12345 (binary: 0b11000000111001)
        #   ~1     =       (binary: 0b11111111111110)  # All 1s except bit 0
        #   sample & ~1 = 12344                        # Clear bit 0
        #   12344 | 1   = 12345                        # Set bit 0 to 1
        #   12344 | 0   = 12344                        # Set bit 0 to 0
        audio[start_index:start_index+len(bits)] = (audio[start_index:start_index+len(bits)] & ~1) | bits
        return audio

    # NOTE: The _create_mixer_signal function below was ported from the MATLAB
    # library's mixer.m but is NOT currently used in this implementation.
    # It was intended for smooth transitions between echo hiding segments.
    # Kept for reference but could be removed to clean up the codebase.

    def algo_echo_encode(self, audio, bits, start_offset=1000, payload_len=None):
        """
        Echo Hiding Encoding Algorithm.
        
        Theory:
        Echo hiding embeds data by adding a delayed copy (echo) of the audio
        to itself. Different delay values encode different bit values.
        Human ears perceive this as subtle reverb/room acoustics.
        
        Algorithm (inspired by MATLAB echo_encoding.m):
        1. Divide audio into chunks (each chunk encodes 1 bit)
        2. For each chunk, add an echo using convolution with an impulse response:
           - bit 0: echo delayed by d0 samples (e.g., 50)
           - bit 1: echo delayed by d1 samples (e.g., 200)
        3. Echo is created using an FIR filter: [0, 0, ..., 0, alpha]
           where the number of zeros equals the delay
        
        The echo kernel is an impulse response like: [0, 0, ..., 0, 0.5]
        When convolved with audio, this adds a delayed, scaled copy of the signal.
        
        Decoding uses cepstrum analysis to detect which delay was used.
        
        Args:
            audio: Audio sample array (will be copied, not modified in-place)
            bits: Array of bits (0 or 1) to embed
            start_offset: Sample index to start embedding (default: 1000)
            payload_len: Unused, kept for API compatibility
        
        Returns:
            np.ndarray: New audio array with embedded echoes
        """
        # Import lfilter here to avoid slow startup (lazy import)
        from scipy.signal import lfilter
        
        # Get user-configurable echo parameters from UI
        chunk_size = self.echo_chunk_size.get()  # Samples per bit (default: 2048)
        d0 = self.echo_delay_0.get()             # Delay for bit 0 (default: 50 samples)
        d1 = self.echo_delay_1.get()             # Delay for bit 1 (default: 200 samples)
        alpha = self.echo_alpha.get()            # Echo strength 0.0-1.0 (default: 0.5)
        
        num_bits = len(bits)
        total_samples = num_bits * chunk_size
        
        # Check if we have enough audio for all bits
        if start_offset + total_samples > len(audio):
            available = len(audio) - start_offset
            num_bits = available // chunk_size
            bits = bits[:num_bits]
            if num_bits <= 0:
                return audio
        
        # Create echo kernels (impulse responses)
        # Each kernel is [0, 0, ..., 0, alpha] with 'delay' zeros before alpha
        #
        # When convolved with audio signal x[n], this produces:
        #   y[n] = x[n-delay] * alpha
        # which is exactly an echo delayed by 'delay' samples with amplitude 'alpha'
        #
        # Example: d0=50, alpha=0.5 creates kernel of length 51
        # kernel = [0, 0, 0, ... (50 zeros) ..., 0.5]
        kernel_d0 = np.zeros(d0 + 1, dtype=np.float32)
        kernel_d0[-1] = alpha  # Set last element to alpha
        kernel_d1 = np.zeros(d1 + 1, dtype=np.float32)
        kernel_d1[-1] = alpha
        
        # Work with float32 for precision during convolution
        output = audio.copy().astype(np.float32)
        
        # Process each bit by adding echo to its corresponding chunk
        for i, bit in enumerate(bits):
            chunk_start = start_offset + i * chunk_size
            chunk_end = chunk_start + chunk_size
            
            if chunk_end > len(audio):
                break
            
            # Extract the chunk to process
            chunk = audio[chunk_start:chunk_end].astype(np.float32)
            
            # Select kernel based on bit value
            kernel = kernel_d0 if bit == 0 else kernel_d1
            
            # lfilter performs 1D convolution (FIR filtering)
            # lfilter(b, a, x) computes: y[n] = sum(b[k] * x[n-k]) / sum(a[k] * y[n-k])
            # With a=1.0, this simplifies to pure FIR (no feedback): y = conv(b, x)
            # Result is the echo signal, which we add to the output
            echo = lfilter(kernel, 1.0, chunk)
            output[chunk_start:chunk_end] += echo
        
        # Clip to int16 range and convert back to integer samples
        return np.clip(output, -32768, 32767).astype(np.int16)

    def algo_phase_encode(self, audio, bits, start_offset=1000):
        """
        Phase Coding Encoding Algorithm.
        
        Theory:
        Human ears are very sensitive to amplitude and frequency changes, but
        relatively insensitive to absolute phase of frequency components.
        This algorithm hides data in the phase of specific frequency bins.
        
        Algorithm (inspired by MATLAB phase_encoding.m):
        1. Segment audio into 256-sample blocks
        2. Apply FFT to transform each block to frequency domain
        3. Modify the phase angle of frequency bins 20-27 (8 bins = 8 bits/segment)
        4. Use BPSK (Binary Phase Shift Keying) modulation:
           - bit 0 → phase = -90° (-π/2 radians)
           - bit 1 → phase = +90° (+π/2 radians)
        5. Reconstruct audio using inverse FFT
        
        Why bins 20-27?
        - Low bins (0-19) are skipped because they contain most audio energy
        - Modifying them would cause audible artifacts
        - Bins 20-27 are in the mid-frequency range where changes are less noticeable
        
        Hard-coded values:
        - segment_size = 256: FFT window size (power of 2 for efficiency)
        - start_bin = 20: First frequency bin to use for data
        - bits_per_segment = 8: Number of bits embedded per segment
        - min_magnitude = 500: Minimum magnitude to ensure decodability
        
        Args:
            audio: Audio sample array (will be copied, not modified in-place)
            bits: Array of bits (0 or 1) to embed
            start_offset: Sample index to start embedding (default: 1000)
        
        Returns:
            np.ndarray: New audio array with phase-encoded data
        """
        segment_size = 256      # FFT window size (256 samples ≈ 5.8ms at 44.1kHz)
        start_bin = 20          # Skip bins 0-19 (low frequencies with high energy)
        bits_per_segment = 8    # Use 8 frequency bins per segment = 1 byte
        min_magnitude = 500     # Boost weak bins to ensure reliable decoding
        
        # Work with float64 for FFT precision
        output = audio.copy().astype(np.float64)
        bit_idx = 0
        pos = start_offset
        
        # Process audio in 256-sample segments
        while bit_idx < len(bits) and pos + segment_size <= len(audio):
            # Extract segment for processing
            segment = output[pos:pos + segment_size]
            
            # Forward FFT: transform from time domain to frequency domain
            # rfft returns only positive frequencies (symmetric for real signals)
            # Result is array of complex numbers: magnitude + phase
            spectrum = np.fft.rfft(segment)
            
            # Decompose complex spectrum into magnitude and phase components
            # Complex number z = |z| * e^(i*θ) = magnitude * e^(i*phase)
            magnitude = np.abs(spectrum)  # |z| = sqrt(real² + imag²)
            phase = np.angle(spectrum)    # θ = atan2(imag, real)
            
            # Embed 8 bits into frequency bins 20-27
            for i in range(bits_per_segment):
                if bit_idx >= len(bits):
                    break
                freq_bin = start_bin + i
                if freq_bin >= len(magnitude):
                    break
                
                # Boost weak frequency bins to ensure reliable decoding
                # If a bin has very low magnitude, phase becomes noisy
                if magnitude[freq_bin] < min_magnitude:
                    magnitude[freq_bin] = min_magnitude
                
                # BPSK modulation: encode bit as phase angle
                # bit 0 → phase = -π/2 (-90°)
                # bit 1 → phase = +π/2 (+90°)
                phase[freq_bin] = -np.pi/2 if bits[bit_idx] == 0 else np.pi/2
                bit_idx += 1
            
            # Reconstruct complex spectrum from magnitude and phase
            # Using Euler's formula: z = magnitude * e^(i*phase)
            # np.exp(1j * phase) creates unit complex number at angle 'phase'
            # Multiplying by magnitude scales it to correct amplitude
            new_spectrum = magnitude * np.exp(1j * phase)
            
            # Inverse FFT: transform back from frequency to time domain
            # irfft expects the positive-frequency half and reconstructs real signal
            output[pos:pos + segment_size] = np.fft.irfft(new_spectrum, n=segment_size)
            pos += segment_size
        
        # Clip to int16 range and convert back to integer samples
        return np.clip(output, -32768, 32767).astype(np.int16)

    # --- Decoding Logic ---

    def log(self, msg):
        self.log_txt.config(state="normal")
        self.log_txt.insert("end", msg + "\n")
        self.log_txt.see("end")
        self.log_txt.config(state="disabled")

    def extract_file(self):
        """Standard Decoder (Stable Protocol)."""
        if self.decode_audio_data is None: return
        
        try:
            audio = self.decode_audio_data
            
            # 1. Read Header
            header = self.read_smart_header(audio)
            
            if not header:
                self.log("Error: No valid Smart Header found.")
                return

            algo_id = header['algo_id']
            payload_len = header['payload_len']
            start_offset = self.HEADER_OFFSET
            
            self.log(f"Header Found! AlgoID: {algo_id}, Len: {payload_len} bytes")
            
            decoded_bits = []
            
            if algo_id == 2: # Echo Hiding
                chunk = header['p1']
                d0 = header['p2']
                d1 = header['p3']
                self.log(f"Algorithm: Echo Hiding (Chunk={chunk}, D0={d0}, D1={d1})")
                decoded_bits = self.algo_echo_decode(audio, start_offset=start_offset, chunk_size=chunk, d0=d0, d1=d1)
                
            elif algo_id == 3: # Phase Coding
                segment = header['p1']
                start_bin = header['p2']
                self.log(f"Algorithm: Phase Coding (Segment={segment}, StartBin={start_bin})")
                decoded_bits = self.algo_phase_decode(audio, start_offset=start_offset, segment_size=segment, start_bin=start_bin)
            
            elif algo_id == 4: # Spread Spectrum
                frame_size = header['p1']
                self.log(f"Algorithm: Spread Spectrum (FrameSize={frame_size})")
                decoded_bits = self.algo_spread_spectrum_decode(audio, start_offset=start_offset, frame_size=frame_size)
            
            elif algo_id == 1: # LSB
                self.log("Algorithm: LSB")
                decoded_bits = self.algo_lsb_decode(audio, start_index=start_offset)
                
            else:
                self.log(f"Error: Unknown Algorithm ID {algo_id}")
                return

            # 2. Trim/Process Bits
            if len(decoded_bits) == 0:
                 self.log("Error: Decoder returned no data.")
                 return

            # Debug: Log first few bits
            preview_bits = decoded_bits[:32]
            bit_str = ''.join(map(str, preview_bits))
            self.log(f"Debug - First 32 bits: {bit_str}")

            # 3. Reconstruct Payload
            total_bits_needed = payload_len * 8
            if len(decoded_bits) < total_bits_needed:
                self.log(f"Warning: Extracted {len(decoded_bits)} bits, needed {total_bits_needed}.")
                decoded_bits = np.pad(decoded_bits, (0, total_bits_needed - len(decoded_bits)))
            
            payload_bits = decoded_bits[:total_bits_needed]
            payload_bytes = np.packbits(payload_bits).tobytes()
            
            # Detect file type from magic bytes (default to .txt for text files)
            ext = ".txt"
            type_name = "Text File"
            for magic, (extension, name) in self.MAGIC_BYTES.items():
                if payload_bytes.startswith(magic):
                    ext = extension
                    type_name = name
                    self.log(f"Detected File Type: {name} ({extension})")
                    break
            
            # Show save dialog with detected file type
            filetypes = [(type_name, f"*{ext}"), ("All Files", "*.*")]
            save_path = filedialog.asksaveasfilename(
                defaultextension=ext,
                filetypes=filetypes,
                initialfile=f"decoded{ext}"
            )
            if save_path:
                with open(save_path, 'wb') as f:
                    f.write(payload_bytes)
                self.log(f"Success! Saved to {save_path}")
                
                # Calculate BER if comparison file was provided
                if self.comparison_file_path:
                    try:
                        with open(self.comparison_file_path, 'rb') as f:
                            original_bytes = f.read()
                        ber, errors, total_bits = self.calculate_ber(original_bytes, payload_bytes)
                        
                        if ber == 0:
                            result_text = f"✓ Perfect Match! BER = 0% (0/{total_bits} bits)"
                            result_color = "#28a745"
                        else:
                            result_text = f"BER = {ber:.2f}% ({errors}/{total_bits} bit errors)"
                            result_color = "#dc3545" if ber > 5 else "#ffc107"
                        
                        self.lbl_ber_result.config(text=result_text, foreground=result_color)
                        self.log(f"BER Comparison: {result_text}")
                    except Exception as e:
                        self.log(f"Error calculating BER: {e}")
                
        except Exception as e:
            self.log(f"Error extracting: {e}")
            import traceback
            traceback.print_exc()

    
    def detect_file_type(self, data):
        """Detect file type from magic bytes.
        Returns (extension, description) or (None, None) if not detected.
        """
        if not data or len(data) < 2:
            return None, None
        
        for magic, (ext, desc) in self.MAGIC_BYTES.items():
            if data[:len(magic)] == magic:
                return ext, desc
        
        # Check for text file (printable ASCII)
        try:
            sample = data[:min(100, len(data))]
            if all(32 <= b < 127 or b in (9, 10, 13) for b in sample):
                return '.txt', 'Text File'
        except Exception:
            pass
        
        return None, None

    def algo_lsb_decode(self, audio, start_index=0):
        """
        LSB (Least Significant Bit) Decoding Algorithm.
        
        Extraction is the inverse of embedding:
        - For each audio sample, extract bit 0 (the LSB)
        - audio & 1 performs bitwise AND with 1, isolating only the LSB
        
        Example: 
            sample = 12345 (binary: 0b11000000111001)
            12345 & 1 = 1  (the LSB is 1)
        
        Args:
            audio: Audio sample array to extract from
            start_index: Sample index to start extraction (default: 0)
        
        Returns:
            np.ndarray: Array of extracted bits (0 or 1)
        """
        if start_index > 0:
            # Extract LSB from samples starting at start_index
            return audio[start_index:] & 1
        # Extract LSB from all samples
        return audio & 1


    def algo_echo_decode(self, audio, start_offset=1000, chunk_size=512, d0=100, d1=150):
        """
        Echo Hiding Decoding Algorithm using Cepstrum Analysis.
        
        Theory (ported from MATLAB echo_decoding.m):
        The cepstrum is the "spectrum of a spectrum". It reveals periodicities
        in the frequency spectrum, which correspond to echo delays in the time domain.
        
        Algorithm:
        1. For each chunk, compute the cepstrum:
           cepstrum = |IFFT(log(|FFT(chunk)|))|
        2. Compare cepstrum values at delay positions d0 and d1
        3. Higher cepstrum value indicates that delay was used for the echo
           - cepstrum[d0] >= cepstrum[d1] → bit 0
           - cepstrum[d0] < cepstrum[d1] → bit 1
        
        Why cepstrum works:
        - An echo at delay d creates a periodic ripple in the frequency spectrum
        - The cepstrum detects this periodicity as a peak at position d
        - We compare peaks at d0 vs d1 to determine which echo was added
        
        Args:
            audio: Audio sample array to decode
            start_offset: Sample index where payload begins (default: 1000)
            chunk_size: Samples per bit (must match encoder)
            d0: Delay for bit 0 (must match encoder)
            d1: Delay for bit 1 (must match encoder)
        
        Returns:
            np.ndarray: Array of decoded bits (0 or 1)
        """
        audio_length = len(audio)
        decoded_bits = []
        current_sample = start_offset
        
        # Process each chunk to decode 1 bit
        while current_sample + chunk_size <= audio_length:
            chunk = audio[current_sample:current_sample+chunk_size]
            
            # =================================================================
            # Real Cepstrum Calculation (Matlab Port of echo_decoding.m)
            # =================================================================
            # Step 1: FFT - Transform chunk to frequency domain
            spectrum = np.fft.fft(chunk)
            
            # Step 2: Log of magnitude (add epsilon to avoid log(0))
            # The log operation converts multiplication (convolution) to addition
            # This separates the original signal from the echo
            log_mag = np.log(np.abs(spectrum) + 1e-8)
            
            # Step 3: Inverse FFT of log magnitude
            # This gives us the cepstrum (quefrency domain)
            # Peaks in cepstrum correspond to echo delays
            cepstrum = np.abs(np.fft.ifft(log_mag)).real
            
            # Compare cepstrum values at the two possible delay positions
            val0 = cepstrum[d0]  # Cepstrum value at delay d0
            val1 = cepstrum[d1]  # Cepstrum value at delay d1
            
            # The delay with higher cepstrum value was used for this bit
            decoded_bits.append(0 if val0 >= val1 else 1)
            current_sample += chunk_size
            
        return np.array(decoded_bits, dtype=np.uint8)

    def algo_phase_decode(self, audio, start_offset=1000, segment_size=256, start_bin=20):
        """
        Phase Coding Decoding Algorithm.
        
        Theory:
        This is the inverse of phase encoding. We extract the phase angle
        from each frequency bin and determine the encoded bit based on
        whether the phase is positive or negative.
        
        Algorithm:
        1. For each 256-sample segment, compute FFT
        2. Extract phase angle of frequency bins 20-27
        3. Decode bit based on phase:
           - phase > 0 → bit 1 (was encoded as +90°)
           - phase <= 0 → bit 0 (was encoded as -90°)
        
        Args:
            audio: Audio sample array to decode
            start_offset: Sample index where payload begins (default: 1000)
            segment_size: FFT window size (must match encoder, default: 256)
            start_bin: First frequency bin with data (must match encoder, default: 20)
        
        Returns:
            np.ndarray: Array of decoded bits (0 or 1)
        """
        bits_per_segment = 8  # 8 frequency bins used per segment
        decoded_bits = []
        pos = start_offset
        
        # Process each segment to decode 8 bits
        while pos + segment_size <= len(audio):
            # FFT to get frequency domain representation
            spectrum = np.fft.rfft(audio[pos:pos + segment_size])
            
            # Extract phase angles (in radians, range -π to +π)
            phase = np.angle(spectrum)
            
            # Decode 8 bits from frequency bins 20-27
            for i in range(bits_per_segment):
                freq_bin = start_bin + i
                if freq_bin >= len(phase):
                    break
                # Positive phase was used for bit 1, negative for bit 0
                decoded_bits.append(1 if phase[freq_bin] > 0 else 0)
            
            pos += segment_size
        
        return np.array(decoded_bits, dtype=np.uint8)

    def algo_spread_spectrum_encode(self, audio, bits, start_offset=1000, frame_size=8192):
        """
        DSSS (Direct Sequence Spread Spectrum) Encoding Algorithm.
        
        Theory:
        Spread spectrum hides data by spreading each bit across many samples
        using a pseudo-random noise (PN) sequence. This makes the signal
        appear as random noise, providing excellent robustness to attacks
        but at the cost of very low capacity.
        
        Algorithm (inspired by MATLAB DSSS implementation):
        1. Generate a deterministic PN sequence using a fixed seed
        2. For each bit, add or subtract the PN sequence from a frame:
           - bit 1: add (α * PN_sequence) to frame
           - bit 0: subtract (α * PN_sequence) from frame
        3. The decoder correlates with the same PN sequence to extract bits
        
        Hard-coded values:
        - frame_size = 8192: Samples per bit (very low capacity, 1 bit per 8192 samples)
        - seed = 12345: Fixed seed for deterministic PN sequence
        - alpha = 500.0: Embedding strength
        
        Args:
            audio: Audio sample array (will be copied, not modified in-place)
            bits: Array of bits (0 or 1) to embed
            start_offset: Sample index to start embedding (default: 1000)
            frame_size: Samples per bit (default: 8192)
        
        Returns:
            np.ndarray: New audio array with spread-spectrum embedded data
        """
        alpha = 500.0  # Embedding strength (higher = more reliable, more audible)
        
        # Check if we have enough audio for all bits
        if start_offset + len(bits) * frame_size > len(audio):
            available = len(audio) - start_offset
            bits = bits[:available // frame_size]
            if len(bits) <= 0:
                return audio
        
        # Generate deterministic PN (Pseudo-random Noise) sequence
        # Using fixed seed ensures encoder and decoder generate identical sequences
        rng = np.random.default_rng(seed=12345)
        
        # Create bipolar sequence: values are either -1 or +1
        # rng.integers(0, 2, frame_size) generates 0s and 1s
        # * 2 - 1 transforms: 0 → -1, 1 → +1
        spread_seq = (rng.integers(0, 2, frame_size) * 2 - 1).astype(np.float32)
        
        output = audio.copy().astype(np.float32)
        
        # Embed each bit by adding or subtracting the PN sequence
        for i, bit in enumerate(bits):
            start = start_offset + i * frame_size
            end = start + frame_size
            if end > len(audio):
                break
            
            if bit == 1:
                # bit 1: positive correlation with PN sequence
                output[start:end] += alpha * spread_seq
            else:
                # bit 0: negative correlation with PN sequence
                output[start:end] -= alpha * spread_seq
        
        return np.clip(output, -32768, 32767).astype(np.int16)

    def algo_spread_spectrum_decode(self, audio, start_offset=1000, frame_size=8192):
        """
        DSSS (Direct Sequence Spread Spectrum) Decoding Algorithm.
        
        Theory:
        Decoding uses correlation with the same PN sequence used for encoding.
        When we multiply the audio frame by the PN sequence and sum, the
        embedded signal reinforces (high correlation) while noise averages out.
        
        Algorithm:
        1. Generate the same PN sequence (same seed as encoder)
        2. For each frame, compute correlation: sum(frame * PN_sequence) / frame_size
        3. The sign of the correlation determines the bit:
           - correlation >= 0 → bit 1 (positive correlation = PN was added)
           - correlation < 0 → bit 0 (negative correlation = PN was subtracted)
        
        Why this works:
        - If PN was added: frame ≈ original + α*PN
          Correlation = (original + α*PN) · PN ≈ 0 + α*(PN · PN) = positive
        - If PN was subtracted: frame ≈ original - α*PN
          Correlation = (original - α*PN) · PN ≈ 0 - α*(PN · PN) = negative
        
        Args:
            audio: Audio sample array to decode
            start_offset: Sample index where payload begins (default: 1000)
            frame_size: Samples per bit (must match encoder, default: 8192)
        
        Returns:
            np.ndarray: Array of decoded bits (0 or 1)
        """
        decoded_bits = []
        
        # Regenerate the exact same PN sequence used by encoder
        rng = np.random.default_rng(seed=12345)
        spread_seq = (rng.integers(0, 2, frame_size) * 2 - 1).astype(np.float32)
        
        pos = start_offset
        while pos + frame_size <= len(audio):
            # Extract frame for this bit
            frame = audio[pos:pos + frame_size].astype(np.float32)
            
            # Compute correlation: dot product of frame and PN sequence
            # Divide by frame_size to normalize (optional for comparison)
            correlation = np.sum(frame * spread_seq) / frame_size
            
            # Positive correlation means PN was added (bit 1)
            # Negative correlation means PN was subtracted (bit 0)
            decoded_bits.append(1 if correlation >= 0 else 0)
            pos += frame_size
        
        return np.array(decoded_bits, dtype=np.uint8)

    # --- Playback/Save ---
    
    def play_audio(self, original=True):
        if self.is_playing:
            self.stop_audio()
        
        if original:
            if self.audio_data is None:
                return
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