"""
Multi-Step Auto Clicker - Giao diện nút bấm nhanh + Hotkey F11/F12 + Nơi lưu file
"""

import json
import os
import queue
import threading
import time
import ctypes
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import pyautogui
import pyperclip
from pynput import keyboard

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.05

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001

def keep_alive():
    try:
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
    except Exception:
        pass


class Step:
    def __init__(self, action_type, x=None, y=None, text="", press_enter=False):
        self.action_type = action_type  # 'click', 'dietcoke', 'paste', 'copy', 'text'
        self.x = x
        self.y = y
        self.text = text
        self.press_enter = press_enter

    def to_dict(self):
        return {
            "action_type": self.action_type,
            "x": self.x,
            "y": self.y,
            "text": self.text,
            "press_enter": self.press_enter,
        }

    @staticmethod
    def from_dict(d):
        return Step(d["action_type"], d["x"], d["y"], d.get("text", ""), d.get("press_enter", False))

    def label(self):
        pos = f"({self.x}, {self.y})" if self.x is not None else "(không cần tọa độ)"
        extra = " + [Enter]" if self.press_enter else ""
        
        descriptions = {
            "click": f"Chỉ Click @ {pos}",
            "dietcoke": "Copy mã 'DIETCOKE' vào bộ nhớ tạm",
            "paste": f"Click + Dán (Ctrl+V) @ {pos}",
            "copy": f"Click + Copy (Ctrl+C) @ {pos}",
            "text": f"Click + Nhập '{self.text}' @ {pos}"
        }
        return descriptions.get(self.action_type, f"Hành động @ {pos}") + extra


class App:
    def __init__(self, root):
        self.root = root
        root.title("Multi-Step Auto Clicker (F11: Start | F12: Stop)")
        root.geometry("620x720")

        self.steps = []
        self.running = False
        self.stop_flag = threading.Event()
        self.msg_queue = queue.Queue()
        self.action_queue = queue.Queue()

        # ---- Danh sách các bước ----
        frame_list = ttk.LabelFrame(root, text="Danh sách bước thực hiện")
        frame_list.pack(fill="both", expand=True, padx=10, pady=6)

        self.listbox = tk.Listbox(frame_list, height=8)
        self.listbox.pack(fill="both", expand=True, padx=6, pady=6)

        btns = ttk.Frame(frame_list)
        btns.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(btns, text="↑ Lên", width=8, command=self.move_up).pack(side="left", padx=2)
        ttk.Button(btns, text="↓ Xuống", width=8, command=self.move_down).pack(side="left", padx=2)
        ttk.Button(btns, text="❌ Xóa bước", command=self.delete_step).pack(side="left", padx=10)

        # ---- Khu vực Nút bấm nhanh ----
        frame_actions = ttk.LabelFrame(root, text="Bấm chọn hành động (Tự động đợi 3s lấy vị trí)")
        frame_actions.pack(fill="x", padx=10, pady=6)

        # Hàng tùy chọn phụ: Enter & Nhập Text
        option_frame = ttk.Frame(frame_actions)
        option_frame.pack(fill="x", padx=6, pady=4)
        
        self.enter_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(option_frame, text="Tự động nhấn [Enter] sau hành động", variable=self.enter_var).pack(side="left")

        text_frame = ttk.Frame(frame_actions)
        text_frame.pack(fill="x", padx=6, pady=4)
        ttk.Label(text_frame, text="Văn bản riêng (dùng cho Nút 5):").pack(side="left")
        self.text_entry = ttk.Entry(text_frame, width=30)
        self.text_entry.pack(side="left", padx=6)

        # Các nút bấm hành động trực tiếp
        btn_grid = ttk.Frame(frame_actions)
        btn_grid.pack(fill="x", padx=6, pady=6)

        ttk.Button(btn_grid, text="🖱️ 1. Chỉ Click", command=lambda: self.capture_and_add("click")).grid(row=0, column=0, padx=4, pady=4, sticky="we")
        ttk.Button(btn_grid, text="📋 2. Copy mã DIETCOKE", command=lambda: self.add_direct_step("dietcoke")).grid(row=0, column=1, padx=4, pady=4, sticky="we")
        ttk.Button(btn_grid, text="📥 3. Click + Dán (Ctrl+V)", command=lambda: self.capture_and_add("paste")).grid(row=1, column=0, padx=4, pady=4, sticky="we")
        ttk.Button(btn_grid, text="📤 4. Click + Copy (Ctrl+C)", command=lambda: self.capture_and_add("copy")).grid(row=1, column=1, padx=4, pady=4, sticky="we")
        ttk.Button(btn_grid, text="✍️ 5. Click + Nhập văn bản", command=lambda: self.capture_and_add("text")).grid(row=2, column=0, columnspan=2, padx=4, pady=4, sticky="we")

        btn_grid.columnconfigure(0, weight=1)
        btn_grid.columnconfigure(1, weight=1)

        # ---- Cấu hình chạy & Hotkey ----
        frame_run = ttk.LabelFrame(root, text="Điều khiển & Phím tắt (F11 / F12)")
        frame_run.pack(fill="x", padx=10, pady=6)

        ttk.Label(frame_run, text="Độ trễ (giây):").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.delay_entry = ttk.Entry(frame_run, width=8)
        self.delay_entry.insert(0, "0.4")
        self.delay_entry.grid(row=0, column=1, sticky="w", padx=6, pady=4)

        ttk.Label(frame_run, text="Số lần lặp (0 = vô hạn):").grid(row=0, column=2, sticky="w", padx=6, pady=4)
        self.loop_entry = ttk.Entry(frame_run, width=8)
        self.loop_entry.insert(0, "0")
        self.loop_entry.grid(row=0, column=3, sticky="w", padx=6, pady=4)

        ttk.Button(frame_run, text="▶ Bắt đầu (F11)", command=self.start).grid(row=1, column=0, columnspan=2, padx=6, pady=8, sticky="we")
        ttk.Button(frame_run, text="⏹ Dừng (F12)", command=self.stop).grid(row=1, column=2, columnspan=2, padx=6, pady=8, sticky="we")

        self.status_var = tk.StringVar(value="Sẵn sàng. Nhấn F11 (Bắt đầu) / F12 (Dừng).")
        ttk.Label(root, textvariable=self.status_var, foreground="blue", font=("Segoe UI", 9, "bold")).pack(padx=10, pady=2)

        footer_frame = ttk.Frame(root)
        footer_frame.pack(fill="x", padx=10, pady=6)
        ttk.Button(footer_frame, text="💾 Lưu cấu hình thành file...", command=self.save_config_dialog).pack(side="left", padx=4)
        ttk.Button(footer_frame, text="📂 Tải cấu hình từ file...", command=self.load_config_dialog).pack(side="left", padx=4)

        self.check_queue()
        self.start_hotkey_listener()

    def capture_and_add(self, action_type):
        """Đếm ngược 3 giây, lấy vị trí con trỏ chuột và tự động thêm bước"""
        if action_type == "text" and not self.text_entry.get().strip():
            messagebox.showwarning("Thiếu văn bản", "Vui lòng nhập văn bản cần gõ vào ô trước!")
            return

        def worker():
            for i in range(3, 0, -1):
                self.msg_queue.put(f"⏳ Đang đợi {i} giây... Đặt chuột vào vị trí cần bấm!")
                time.sleep(1)
            
            x, y = pyautogui.position()
            step = Step(
                action_type=action_type,
                x=x,
                y=y,
                text=self.text_entry.get() if action_type == "text" else "",
                press_enter=self.enter_var.get()
            )
            self.steps.append(step)
            self.action_queue.put("REFRESH")
            self.msg_queue.put(f"✅ Đã thêm bước: {step.label()}")

        threading.Thread(target=worker, daemon=True).start()

    def add_direct_step(self, action_type):
        """Thêm các bước không cần tọa độ chuột (như copy DIETCOKE)"""
        step = Step(action_type=action_type, press_enter=self.enter_var.get())
        self.steps.append(step)
        self.refresh_listbox()
        self.status_var.set(f"✅ Đã thêm bước: {step.label()}")

    def start_hotkey_listener(self):
        def on_press(key):
            try:
                if key == keyboard.Key.f11:
                    self.action_queue.put("START")
                elif key == keyboard.Key.f12:
                    self.action_queue.put("STOP")
            except Exception:
                pass

        listener = keyboard.Listener(on_press=on_press)
        listener.daemon = True
        listener.start()

    def check_queue(self):
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                self.status_var.set(msg)
        except queue.Empty:
            pass

        try:
            while True:
                act = self.action_queue.get_nowait()
                if act == "START":
                    self.start()
                elif act == "STOP":
                    self.stop()
                elif act == "REFRESH":
                    self.refresh_listbox()
        except queue.Empty:
            pass

        self.root.after(100, self.check_queue)

    def refresh_listbox(self):
        self.listbox.delete(0, "end")
        for i, s in enumerate(self.steps, 1):
            self.listbox.insert("end", f"{i}. {s.label()}")

    def get_selected_index(self):
        sel = self.listbox.curselection()
        return sel[0] if sel else None

    def delete_step(self):
        i = self.get_selected_index()
        if i is not None:
            del self.steps[i]
            self.refresh_listbox()

    def move_up(self):
        i = self.get_selected_index()
        if i is None or i == 0:
            return
        self.steps[i - 1], self.steps[i] = self.steps[i], self.steps[i - 1]
        self.refresh_listbox()
        self.listbox.select_set(i - 1)

    def move_down(self):
        i = self.get_selected_index()
        if i is None or i == len(self.steps) - 1:
            return
        self.steps[i + 1], self.steps[i] = self.steps[i], self.steps[i + 1]
        self.refresh_listbox()
        self.listbox.select_set(i + 1)

    def save_config_dialog(self):
        if not self.steps:
            messagebox.showwarning("Cảnh báo", "Chưa có bước nào trong danh sách để lưu!")
            return

        file_path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Chọn nơi lưu file cấu hình"
        )
        if not file_path:
            return

        data = [s.to_dict() for s in self.steps]
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            messagebox.showinfo("Thông báo", "Đã lưu cấu hình thành file!")
        except Exception as e:
            messagebox.showerror("Lỗi lưu", str(e))

    def load_config_dialog(self):
        file_path = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Chọn file cấu hình để mở"
        )
        if not file_path:
            return

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.steps = [Step.from_dict(d) for d in data]
            self.refresh_listbox()
            messagebox.showinfo("Thông báo", "Đã tải cấu hình thành công!")
        except Exception as e:
            messagebox.showerror("Lỗi tải", str(e))

    def start(self):
        if self.running or not self.steps:
            return
        try:
            delay = float(self.delay_entry.get())
            loop_count = int(self.loop_entry.get())
        except ValueError:
            delay, loop_count = 0.4, 0

        keep_alive()
        self.running = True
        self.stop_flag.clear()
        self.msg_queue.put("🚀 Đang chạy... (Ấn F12 để dừng)")
        threading.Thread(target=self.run_loop, args=(delay, loop_count), daemon=True).start()

    def stop(self):
        if not self.running:
            return
        self.stop_flag.set()
        self.running = False
        self.msg_queue.put("🛑 Đã dừng.")

    def run_loop(self, delay, loop_count):
        count = 0
        while not self.stop_flag.is_set():
            for step in self.steps:
                if self.stop_flag.is_set():
                    break
                self.execute_step(step)
                time.sleep(delay)
            count += 1
            self.msg_queue.put(f"🚀 Đang chạy... Đã lặp {count} lần. (F12 để dừng)")
            if loop_count != 0 and count >= loop_count:
                break
        self.running = False
        if not self.stop_flag.is_set():
            self.msg_queue.put(f"✅ Hoàn tất {count} lần lặp.")

    def execute_step(self, step: Step):
        try:
            if step.x is not None and step.y is not None:
                pyautogui.click(step.x, step.y)

            if step.action_type == "dietcoke":
                pyperclip.copy("DIETCOKE")

            elif step.action_type == "paste":
                time.sleep(0.1)
                pyautogui.hotkey("ctrl", "v")

            elif step.action_type == "copy":
                time.sleep(0.1)
                pyautogui.hotkey("ctrl", "c")

            elif step.action_type == "text" and step.text:
                time.sleep(0.1)
                pyperclip.copy(step.text)
                pyautogui.hotkey("ctrl", "v")

            if step.press_enter:
                time.sleep(0.1)
                pyautogui.press("enter")
        except Exception:
            pass


if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()
