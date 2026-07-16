import os
import sys
import time
import queue
import threading
import json
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

# Local Modules
from geocoder import reverse_geocode
from form_filler import IhbarFormFiller
from ocr_helper import analyze_video_metadata
from main import find_video_in_folder, parse_plates_from_filename
from selenium import webdriver

class StdoutRedirector:
    """Redirects stdout prints to a Tkinter Text widget."""
    def __init__(self, text_widget):
        self.text_widget = text_widget

    def write(self, string):
        self.text_widget.configure(state='normal')
        self.text_widget.insert('end', string)
        self.text_widget.see('end')
        self.text_widget.configure(state='disabled')

    def flush(self):
        pass

class IhbarBotGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("112 Trafik İhbar Asistanı")
        self.root.geometry("700x700")
        self.root.minsize(600, 600)
        
        # Grid weight configuration
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)
        
        # Thread & Event Queue
        self.msg_queue = queue.Queue()
        self.wait_event = threading.Event()
        self.wait_step = None
        self.sms_code_result = ""
        
        # Styling / Themes
        self.style = ttk.Style()
        self.style.theme_use('clam')
        self.style.configure('TFrame', background='#f0f2f5')
        self.style.configure('TLabel', background='#f0f2f5', font=('Helvetica', 10))
        self.style.configure('Header.TLabel', background='#f0f2f5', font=('Helvetica', 14, 'bold'), foreground='#1e293b')
        self.style.configure('Status.TLabel', background='#cbd5e1', font=('Helvetica', 9, 'italic'))
        self.style.configure('Action.TButton', font=('Helvetica', 11, 'bold'), background='#0284c7', foreground='white')
        self.style.map('Action.TButton', background=[('active', '#0369a1')])
        
        self.root.configure(background='#f0f2f5')
        
        # UI State Variables
        self.video_path_var = tk.StringVar(value="VIDEO_BULUNAMADI")
        self.coordinates_var = tk.StringVar(value="")
        self.address_var = tk.StringVar(value="Henüz sorgulanmadı.")
        self.plate_var = tk.StringVar(value="")
        self.datetime_var = tk.StringVar(value="")
        self.details_var = tk.StringVar(value="")
        
        # Build UI Sections
        self._build_header()
        self._build_form_inputs()
        self._build_console_log()
        self._build_action_bar()
        
        # Load previous session
        self.session_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "session.json")
        self.load_session()
        
        # Redirect stdout
        sys.stdout = StdoutRedirector(self.console_text)
        
        # Check queue periodically
        self.root.after(100, self.process_queue)
        
        # Auto scan videos on start
        self.root.after(500, self.auto_scan_video)

    def _build_header(self):
        header_frame = ttk.Frame(self.root, padding="15 10 15 10")
        header_frame.grid(row=0, column=0, sticky="ew")
        header_frame.columnconfigure(0, weight=1)
        
        title = ttk.Label(header_frame, text="112 Trafik İhbar Asistanı", style="Header.TLabel")
        title.grid(row=0, column=0, sticky="w")
        
        subtitle = ttk.Label(header_frame, text="Videodan otomatik veri çıkarma ve otomatik form doldurma aracı", font=('Helvetica', 9))
        subtitle.grid(row=1, column=0, sticky="w")

    def _build_form_inputs(self):
        form_frame = ttk.LabelFrame(self.root, text=" İhbar Parametreleri ", padding="15 15 15 15")
        form_frame.grid(row=1, column=0, padx=15, pady=5, sticky="ew")
        form_frame.columnconfigure(1, weight=1)
        
        # 1. Video Seçimi
        ttk.Label(form_frame, text="Seçili Video:").grid(row=0, column=0, sticky="w", pady=5)
        video_entry = ttk.Entry(form_frame, textvariable=self.video_path_var, state="readonly")
        video_entry.grid(row=0, column=1, sticky="ew", padx=(5, 5), pady=5)
        
        video_buttons_frame = ttk.Frame(form_frame)
        video_buttons_frame.grid(row=0, column=2, pady=5)
        
        select_btn = ttk.Button(video_buttons_frame, text="Seç...", command=self.select_video)
        select_btn.pack(side="left", padx=2)
        
        scan_btn = ttk.Button(video_buttons_frame, text="Taramayı Yenile", command=self.auto_scan_video)
        scan_btn.pack(side="left", padx=2)
        
        # 2. Koordinatlar
        ttk.Label(form_frame, text="Koordinatlar (Lat, Lon):").grid(row=1, column=0, sticky="w", pady=5)
        coords_entry = ttk.Entry(form_frame, textvariable=self.coordinates_var)
        coords_entry.grid(row=1, column=1, sticky="ew", padx=(5, 5), pady=5)
        
        coords_btn = ttk.Button(form_frame, text="Adresi Sorgula", command=self.query_address)
        coords_btn.grid(row=1, column=2, sticky="e", pady=5)
        
        # Adres Görüntüleme
        ttk.Label(form_frame, text="Tespit Edilen Adres:").grid(row=2, column=0, sticky="nw", pady=5)
        address_lbl = ttk.Label(form_frame, textvariable=self.address_var, font=('Helvetica', 9, 'bold'), foreground='#0369a1', wraplength=400, justify="left")
        address_lbl.grid(row=2, column=1, columnspan=2, sticky="w", padx=5, pady=5)
        
        # 3. Tarih Saat
        ttk.Label(form_frame, text="İhlal Tarih / Saat:").grid(row=3, column=0, sticky="w", pady=5)
        dt_entry = ttk.Entry(form_frame, textvariable=self.datetime_var)
        dt_entry.grid(row=3, column=1, columnspan=2, sticky="ew", padx=5, pady=5)
        
        # 4. Araç Plakası
        ttk.Label(form_frame, text="Araç Plakası (Örn: 34XYZ999):").grid(row=4, column=0, sticky="w", pady=5)
        plate_entry = ttk.Entry(form_frame, textvariable=self.plate_var)
        plate_entry.grid(row=4, column=1, columnspan=2, sticky="ew", padx=5, pady=5)
        
        # 5. Olay Detayı
        ttk.Label(form_frame, text="Olay Detayı Açıklaması:").grid(row=5, column=0, sticky="nw", pady=5)
        details_entry = ttk.Entry(form_frame, textvariable=self.details_var)
        details_entry.grid(row=5, column=1, columnspan=2, sticky="ew", padx=5, pady=5)

    def _build_console_log(self):
        console_frame = ttk.LabelFrame(self.root, text=" Log Çıktıları ve Durum Bilgisi ", padding="10 10 10 10")
        console_frame.grid(row=2, column=0, padx=15, pady=5, sticky="nsew")
        console_frame.columnconfigure(0, weight=1)
        console_frame.rowconfigure(0, weight=1)
        
        self.console_text = ScrolledText(console_frame, wrap="word", height=10, font=('Courier New', 10), state="disabled", background="#0f172a", foreground="#f8fafc")
        self.console_text.grid(row=0, column=0, sticky="nsew")

    def _build_action_bar(self):
        action_frame = ttk.Frame(self.root, padding="15 10 15 15")
        action_frame.grid(row=3, column=0, sticky="ew")
        action_frame.columnconfigure(0, weight=1)
        
        # Pause Wait step UI (Initially Hidden/Disabled)
        self.interactive_frame = ttk.Frame(action_frame)
        self.interactive_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        
        self.interactive_lbl = ttk.Label(self.interactive_frame, text="Bekleme adımı...", font=('Helvetica', 10, 'bold'), foreground='#b91c1c')
        self.interactive_lbl.pack(side="left", padx=5)
        
        # Entry for SMS if requested
        self.sms_entry = ttk.Entry(self.interactive_frame, width=15)
        self.sms_entry.pack(side="left", padx=5)
        self.sms_entry.pack_forget() # Hidden by default
        
        self.continue_btn = ttk.Button(self.interactive_frame, text="Devam Et", command=self.trigger_resume)
        self.continue_btn.pack(side="right", padx=5)
        self.interactive_frame.grid_remove() # Hidden initially
        
        # Buttons container
        buttons_frame = ttk.Frame(action_frame)
        buttons_frame.grid(row=1, column=0, sticky="ew")
        buttons_frame.columnconfigure(0, weight=1)
        
        # Main Trigger Button
        self.run_btn = ttk.Button(buttons_frame, text="İHBAR OTOMASYONUNU BAŞLAT", style="Action.TButton", command=self.start_automation)
        self.run_btn.grid(row=0, column=0, sticky="ew", ipady=8, padx=(0, 10))
        
        # Clear Button
        self.clear_btn = ttk.Button(buttons_frame, text="TÜMÜNÜ TEMİZLE", command=self.clear_fields)
        self.clear_btn.grid(row=0, column=1, sticky="e", ipady=8)

    def clear_fields(self):
        if messagebox.askyesno("Onay", "Tüm alanları ve kayıtlı geçmişi temizlemek istediğinize emin misiniz?"):
            self.video_path_var.set("VIDEO_BULUNAMADI")
            self.coordinates_var.set("")
            self.address_var.set("Henüz sorgulanmadı.")
            self.plate_var.set("")
            self.datetime_var.set("")
            self.details_var.set("")
            self.address_info = None
            self.save_session()

            # Yarım kalmış bir bekleme adımı (hCaptcha/SMS) varsa sıfırla:
            # bekleyen thread'i serbest bırak ve BAŞLAT butonunu tekrar aktif et.
            self.wait_step = None
            self.sms_code_result = ""
            self.automation_cancelled = True
            self.wait_event.set()
            self.interactive_frame.grid_remove()
            self.run_btn.configure(state="normal")

            self.console_text.configure(state='normal')
            self.console_text.delete(1.0, 'end')
            self.console_text.configure(state='disabled')
            print("[INFO] Tüm alanlar ve kayıtlı oturum temizlendi.")

    def select_video(self):
        file_path = filedialog.askopenfilename(
            title="Video Seç",
            filetypes=[("Video Dosyaları", "*.mp4 *.avi *.mkv *.mov *.webm *.3gp *.mpeg *.mpg")]
        )
        if file_path:
            self.video_path_var.set(file_path)
            self.run_ocr_thread(file_path)

    def auto_scan_video(self):
        videolar_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "videolar")
        video_path = find_video_in_folder(videolar_folder)
        if video_path and video_path != self.video_path_var.get():
            self.video_path_var.set(video_path)
            self.run_ocr_thread(video_path)
        elif not video_path:
            # Sadece video yoksa uyarı ver, eğer son oturumdan video kaldıysa üzerine yazma
            if self.video_path_var.get() == "VIDEO_BULUNAMADI" or not os.path.exists(self.video_path_var.get()):
                self.video_path_var.set("VIDEO_BULUNAMADI")
                print("[INFO] 'videolar' klasöründe herhangi bir video bulunamadı. Lütfen üstteki 'Seç...' butonuyla bir video ekleyin.")

    def run_ocr_thread(self, video_path):
        print(f"\n[INFO] Seçilen video: {video_path}")

        # Dosya adından plaka(ları) oku (örn: '09AID146.mp4', '34ABC123 06XYZ789.mp4')
        plates = parse_plates_from_filename(video_path)
        if plates:
            self.plate_var.set(", ".join(plates))
            print(f"[INFO] Plaka dosya adından otomatik okundu: {', '.join(plates)}")

        print("[INFO] Videodan GPS koordinatları ve tarih/saat otomatik okunuyor...")
        
        def ocr_task():
            gps_coords, ocr_dt = analyze_video_metadata(video_path)
            self.msg_queue.put(("ocr_result", (gps_coords, ocr_dt)))
            
        threading.Thread(target=ocr_task, daemon=True).start()

    def query_address(self):
        coords = self.coordinates_var.get().strip()
        if not coords:
            return
        try:
            lat_str, lon_str = coords.split(',')
            lat = float(lat_str.strip())
            lon = float(lon_str.strip())
            
            print(f"[INFO] Koordinatlar sorgulanıyor: ({lat}, {lon})...")
            
            def geocode_task():
                addr = reverse_geocode(lat, lon)
                self.msg_queue.put(("geocode_result", addr))
                
            threading.Thread(target=geocode_task, daemon=True).start()
        except ValueError:
            messagebox.showerror("Hata", "Koordinat formatı geçersiz! Lütfen 'Enlem, Boylam' şeklinde girin (Örn: 40.9330, 29.3019)")

    def process_queue(self):
        try:
            while True:
                task, val = self.msg_queue.get_nowait()
                if task == "ocr_result":
                    gps_coords, ocr_dt = val
                    if gps_coords and gps_coords[0] is not None and gps_coords[1] is not None:
                        lat, lon = gps_coords
                        self.coordinates_var.set(f"{lat}, {lon}")
                        print(f"[OCR] Başarılı: Otomatik koordinatlar okundu -> {lat}, {lon}")
                        self.query_address()
                    else:
                        print("[OCR] Koordinatlar videodan otomatik okunamadı.")
                        
                    if ocr_dt:
                        self.datetime_var.set(ocr_dt)
                        print(f"[OCR] Başarılı: Otomatik tarih/saat okundu -> {ocr_dt}")
                    else:
                        self.datetime_var.set("")
                        print("[OCR] Tarih/saat videodan otomatik okunamadı. Lütfen elle girin (Örn: 30.06.2026 17:21).")
                            
                elif task == "geocode_result":
                    self.address_info = val
                    addr_str = f"{val.get('il', 'Bilinmiyor')} / {val.get('ilçe', 'Bilinmiyor')} / {val.get('mahalle', 'Bilinmiyor')} / {val.get('sokak', 'Bilinmiyor')}"
                    self.address_var.set(addr_str)
                    print(f"[INFO] Adres çözümlendi: {addr_str}")
                    
                elif task == "wait_step":
                    step, prompt_text = val
                    self.wait_step = step
                    self.interactive_lbl.configure(text=prompt_text)
                    
                    if step == "sms":
                        self.sms_entry.pack(side="left", padx=5)
                        self.sms_entry.delete(0, tk.END)
                        self.continue_btn.configure(text="Onayla")
                    else:
                        self.sms_entry.pack_forget()
                        self.continue_btn.configure(text="Devam Et")
                        
                    self.interactive_frame.grid() # Show prompt
                    self.run_btn.configure(state="disabled")
                    
                elif task == "automation_done":
                    if getattr(self, 'automation_cancelled', False):
                        self.automation_cancelled = False
                    else:
                        messagebox.showinfo("Başarılı", "İhbar formu hazırlığı tamamlandı! Tarayıcı kontrolünüz için açık bırakılmıştır.")
                    self.run_btn.configure(state="normal")
                    self.interactive_frame.grid_remove()

                elif task == "automation_error":
                    if getattr(self, 'automation_cancelled', False):
                        self.automation_cancelled = False
                    else:
                        messagebox.showerror("Hata", f"Otomasyon çalışırken hata oluştu:\n{val}")
                    self.run_btn.configure(state="normal")
                    self.interactive_frame.grid_remove()
                    
        except queue.Empty:
            pass
        self.root.after(100, self.process_queue)

    def trigger_resume(self):
        if self.wait_step == "sms":
            self.sms_code_result = self.sms_entry.get().strip()
        self.interactive_frame.grid_remove()
        self.run_btn.configure(state="normal")
        self.wait_event.set() # Signals background thread to resume

    def wait_callback(self, step, prompt_text):
        """Called by background thread. Pauses and waits for user interaction."""
        self.wait_event.clear()
        self.msg_queue.put(("wait_step", (step, prompt_text)))
        self.wait_event.wait() # Block thread until GUI signals event
        return self.sms_code_result

    def load_session(self):
        if os.path.exists(self.session_file):
            try:
                with open(self.session_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.video_path_var.set(data.get("video_path", "VIDEO_BULUNAMADI"))
                    self.coordinates_var.set(data.get("coordinates", ""))
                    self.address_var.set(data.get("address_str", "Henüz sorgulanmadı."))
                    self.plate_var.set(data.get("plate", ""))
                    self.datetime_var.set(data.get("datetime", ""))
                    self.details_var.set(data.get("details", ""))
                    self.address_info = data.get("address_info", None)
            except Exception as e:
                print(f"[ERROR] Session yüklenirken hata: {e}")

    def save_session(self):
        try:
            data = {
                "video_path": self.video_path_var.get(),
                "coordinates": self.coordinates_var.get(),
                "address_str": self.address_var.get(),
                "plate": self.plate_var.get(),
                "datetime": self.datetime_var.get(),
                "details": self.details_var.get(),
                "address_info": getattr(self, 'address_info', None)
            }
            with open(self.session_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"[ERROR] Session kaydedilirken hata: {e}")

    def start_automation(self):
        # Validation checks
        video_path = self.video_path_var.get()
        coords = self.coordinates_var.get().strip()
        plaka = self.plate_var.get().strip().upper()
        dt_str = self.datetime_var.get().strip()
        olay_detayi = self.details_var.get().strip()
        
        if not coords:
            messagebox.showerror("Hata", "Lütfen koordinat alanını doldurun!")
            return
        if not plaka:
            messagebox.showerror("Hata", "Lütfen araç plakası bilgisini girin!")
            return
        if not dt_str:
            messagebox.showerror("Hata", "Tarih/saat videodan okunamadı. Lütfen ihlal tarih ve saatini elle girin! (Örn: 30.06.2026 17:21)")
            return
        if not olay_detayi:
            messagebox.showerror("Hata", "Lütfen olay detayı açıklaması girin!")
            return
            
        try:
            lat_str, lon_str = coords.split(',')
            lat = float(lat_str.strip())
            lon = float(lon_str.strip())
        except ValueError:
            messagebox.showerror("Hata", "Koordinat formatı geçersiz!")
            return
            
        # Compile description
        description_text = f"Tarih/Saat: {dt_str}\nPlaka: {plaka}\nOlay Detayı: {olay_detayi}"
        
        # Build address dict
        if not hasattr(self, 'address_info') or self.address_info is None:
            self.address_info = {'il': 'Bilinmiyor', 'ilçe': 'Bilinmiyor', 'mahalle': 'Bilinmiyor', 'sokak': 'Bilinmiyor'}
            
        # Save session right before automation starts
        self.save_session()
            
        print("\n" + "="*50)
        print("[INFO] Selenium Otomasyonu Başlatılıyor...")
        print("="*50)
        
        self.run_btn.configure(state="disabled")
        
        def run_selenium():
            try:
                options = webdriver.ChromeOptions()
                options.add_experimental_option("detach", True)
                options.add_argument("--disable-gpu")
                options.add_argument("--no-sandbox")
                options.add_argument("--disable-dev-shm-usage")
                
                # Keep a reference to prevent garbage collection from closing browser
                self.current_driver = webdriver.Chrome(options=options)
                filler = IhbarFormFiller(self.current_driver)
                
                # Fill form
                filler.fill_form(self.address_info, video_path, description_text, wait_callback=self.wait_callback)
                self.msg_queue.put(("automation_done", None))
            except Exception as e:
                self.msg_queue.put(("automation_error", str(e)))
                
        threading.Thread(target=run_selenium, daemon=True).start()

if __name__ == "__main__":
    root = tk.Tk()
    app = IhbarBotGUI(root)
    root.mainloop()
