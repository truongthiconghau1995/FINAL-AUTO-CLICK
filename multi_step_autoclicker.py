"""
Multi-Step Auto Clicker - Hỗ trợ Copy mã DIETCOKE, Hotkey F11/F12 & Chọn nơi lưu/tải cấu hình
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

ACTIONS = [
    "1. Chỉ click",
    "2. Copy mã 'DIETCOKE' vào bộ nhớ tạm",
    "3. Click + Dán (Ctrl+V)",
    "4. Click + Copy (Ctrl+C)",
    "5. Click + Nhập văn bản tùy chỉnh",
]

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001

def keep_alive():
    try:
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
    except Exception:
        pass


class Step:
    def __init__(self, action=ACTIONS[0], x=None, y=None, text="", press_enter=False):
        self.action = action
        self.x = x
        self.y = y
        self.text = text
        self.press_enter = press_enter

    def to_dict(self):
        return {
            "action": self.action,
            "x": self.x,
            "y": self.y,
            "text": self.text,
            "press_enter": self.press_enter,
        }

    @staticmethod
    def from_dict(d):
        return Step(d["action"], d["x"], d["y"], d.get("text", ""), d.get("press_enter", False))

    def label(self):
        pos = f"({self.x},{self.y})" if self.x is not None else "(không cần tọa độ)"
        extra = ""
        if self.action == "5. Click + Nhập văn bản tùy chỉnh":
            extra = f" | text='{self.text}'"
        if self.press_enter:
            extra += " + [Enter]"
        return f"{self.action} @ {pos}{extra}"


class App:
    def __init__(self, root):
        self.root = root
        root.title("Multi-Step Auto Clicker (F11: Start | F12: Stop)")
        root.geometry("580x670")

        self.steps = []
        self.running = False
        self.stop_flag = threading.Event()
        self.msg_queue = queue.Queue()
        self.action_queue = queue.Queue()

        # ---- Danh sách bước ----
        frame_list = ttk.LabelFrame(root, text="Các bước thực hiện (theo thứ tự)")
        frame_list.pack(fill="both", expand=True, padx=10, pady=8)

        self.listbox = tk.Listbox(frame_list, height=9)
        self.listbox.pack(fill="both", expand=True, padx=6, pady=6)

        btns = ttk.Frame(frame_list)
        btns.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(btns, text="↑", width=3, command=self.move_up).pack(side="left")
        ttk.Button(btns, text="↓", width=3, command=self.move_down).pack(side="left")
        ttk.Button(btns, text="Xóa bước", command=self.delete_step).pack(side="left", padx=6)

        # ---- Editor cho 1 bước ----
        frame_edit = ttk.LabelFrame(root, text="Thêm / sửa bước")
        frame_edit.pack(fill="x", padx=10, pady=6)

        ttk.Label(frame_edit, text="Hành động:").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.action_var = tk.StringVar(value=ACTIONS[0])
        ttk.Combobox(frame_edit, textvariable=self.action_var, values=ACTIONS, state="readonly", width=32)\
            .grid(row=0, column=1, columnspan=2, sticky="w", padx=6, pady=4)

        ttk.Label(frame_edit, text="Tọa độ (x, y):").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        self.pos_label = ttk.Label(frame_edit, text="Chưa đặt")
        self.pos_label.grid(row=1, column=1, sticky="w", padx=6, pady=4)
        ttk.Button(frame_edit, text="Lấy vị trí (đợi 3s rê chuột)",
                   command=self.capture_position).grid(row=1, column=2, sticky="w", padx=6, pady=4)

        ttk.Label(frame_edit, text="Văn bản riêng (nếu dùng loại 5):").grid(row=2, column=0, sticky="w", padx=6, pady=4)
        self.text_entry = ttk.Entry(frame_edit, width=25)
        self.text_entry.grid(row=2, column=1, columnspan=2, sticky="w", padx=6, pady=4)

        self.enter_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame_edit, text="Nhấn Enter sau khi thực hiện hành động này", variable=self.enter_var)\
            .grid(row=3, column=1, columnspan=2, sticky="w", padx=6, pady=4)

        self._pending_x = None
        self._pending_y = None

        ttk.Button(frame_edit, text="➕ Thêm bước này vào danh sách", command=self.add_step)\
            .grid(row=4, column=0, columnspan=3, sticky="we", padx=6, pady=6)

        # ---- Cấu hình chạy & Hotkey ----
        frame_run = ttk.LabelFrame(root, text="Điều khiển & Phím tắt Global Hotkeys")
        frame_run.pack(fill="x", padx=10, pady=6)

        ttk.Label(frame_run, text="Độ trễ giữa các bước (giây):").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.delay_entry = ttk.Entry(frame_run, width=8)
        self.delay_entry.insert(0, "0.4")
        self.delay_entry.grid(row=0, column=1, sticky="w", padx=6, pady=4)

        ttk.Label(frame_run, text="Số lần lặp (0 = vô hạn):").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        self.loop_entry = ttk.Entry(frame_run, width=8)
        self.loop_entry.insert(0, "0")
        self.loop_entry.grid(row=1, column=1, sticky="w", padx=6, pady=4)

        ttk.Button(frame_run, text="▶ Bắt đầu (F11)", command=self.start).grid(row=2, column=0, padx=6, pady=8)
        ttk.Button(frame_run, text="⏹ Dừng (F12)", command=self.stop).grid(row=2, column=1, padx=6, pady=8)

        self.status_var = tk.StringVar(value="Sẵn sàng. Nhấn F11 (Bắt đầu) / F12 (Dừng).")
        ttk.Label(root, textvariable=self.status_var, foreground="blue", font=("Segoe UI", 9, "bold")).pack(padx=10, pady=4)

        footer_frame = ttk.Frame(root)
        footer_frame.pack(fill="x", padx=10, pady=4)
        ttk.Button(footer_frame, text="💾 Lưu cấu hình thành file...", command=self.save_config_dialog).pack(side="left", padx=4)
        ttk.Button(footer_frame, text="📂 Tải cấu hình từ file...", command=self.load_config_dialog).pack(side="left", padx=4)

        self.refresh_listbox()

        self.check_queue()
        self.start_hotkey_listener()

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
        except queue.Empty:
            pass

        self.root.after(100, self.check_queue)

    def capture_position(self):
        self.msg_queue.put("Đang đợi 3 giây... rê chuột tới vị trí cần lấy!")

        def worker():
            time.sleep(3)
            try:
                x, y = pyautogui.position()
                self._pending_x, self._pending_y = x, y
                self.pos_label.config(text=f"({x}, {y})")
                self.msg_queue.put(f"Đã lấy vị trí ({x}, {y}). Bấm 'Thêm bước này' để lưu.")
            except Exception as e:
                self.msg_queue.put(f"Lỗi lấy vị trí: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def add_step(self):
        act = self.action_var.get()
        if act != "2. Copy mã 'DIETCOKE' vào bộ nhớ tạm" and self._pending_x is None:
            messagebox.showwarning("Thiếu vị trí", "Hãy bấm 'Lấy vị trí' và rê chuột tới mục tiêu trước.")
            return

        step = Step(
            action=act,
            x=self._pending_x,
            y=self._pending_y,
            text=self.text_entry.get(),
            press_enter=self.enter_var.get(),
        )
        self.steps.append(step)
        self.refresh_listbox()
        self._pending_x = None
        self._pending_y = None
        self.pos_label.config(text="Chưa đặt")
        self.text_entry.delete(0, "end")
        self.enter_var.set(False)
        self.msg_queue.put(f"Đã thêm bước #{len(self.steps)}.")

    def refresh_listbox(self):
        self.listbox.delete(0, "end")
        for i, s in enumerate(self.steps, 1):
            self.listbox.insert("end", f"{i}. {s.label()}")

    def get_selected_index(self):
        sel = self.listbox.curselection()
        return sel[0] if sel else None

    def delete_step(self):
        i = self.get_selected_index()
        if i is None:
            return
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
        """Mở cửa sổ chọn thư mục và đặt tên file lưu (Save As)"""
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
            self.msg_queue.put("✅ Đã lưu cấu hình thành công!")
            messagebox.showinfo("Thông báo", "Đã lưu cấu hình thành file!")
        except Exception as e:
            messagebox.showerror("Lỗi lưu", str(e))

    def load_config_dialog(self):
        """Mở cửa sổ chọn file cấu hình sẵn có để tải vào (Open File)"""
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
            self.msg_queue.put(f"📂 Đã tải {len(self.steps)} bước từ file.")
            messagebox.showinfo("Thông báo", "Đã tải cấu hình thành công!")
        except Exception as e:
            messagebox.showerror("Lỗi tải", str(e))

    def start(self):
        if self.running:
            return
        if not self.steps:
            self.msg_queue.put("⚠️ Chưa có bước nào để chạy!")
            return
        try:
            delay = float(self.delay_entry.get())
        except ValueError:
            delay = 0.4
        try:
            loop_count = int(self.loop_entry.get())
        except ValueError:
            loop_count = 0

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
                try:
                    self.execute_step(step)
                except Exception:
                    pass
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

            if step.action == "2. Copy mã 'DIETCOKE' vào bộ nhớ tạm":
                pyperclip.copy("DIETCOKE")

            elif step.action == "3. Click + Dán (Ctrl+V)":
                time.sleep(0.1)
                pyautogui.hotkey("ctrl", "v")
                time.sleep(0.1)

            elif step.action == "4. Click + Copy (Ctrl+C)":
                time.sleep(0.1)
                pyautogui.hotkey("ctrl", "c")
                time.sleep(0.1)

            elif step.action == "5. Click + Nhập văn bản tùy chỉnh":
                if step.text:
                    time.sleep(0.1)
                    pyperclip.copy(step.text)
                    pyautogui.hotkey("ctrl", "v")
                    time.sleep(0.1)

            if step.press_enter:
                pyautogui.press("enter")
        except Exception:
            pass


if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()
