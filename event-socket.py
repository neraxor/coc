#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CoC Event Multi-Account – scrollbare Accounts, Punktestatistik,
Sound bei Disconnect, schnelleres Log, Import/Export der Accounts.
Jetzt neu: Verbindungs-URL wird ins Log geschrieben.
"""

import json
import queue
import random
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import List, Tuple

import browser_cookie3
import websocket

try:  # Windows-Beep
    import winsound

    def beep():
        winsound.MessageBeep(winsound.MB_ICONHAND)
except ImportError:  # Fallback
    def beep():
        print("\a", end="", flush=True)


MAX_LOG_LINES = 300
ACCOUNT_FILE = "accounts.txt"


# ════════════════════════════════════════════════════════════
#   Hintergrund-Thread pro Account
# ════════════════════════════════════════════════════════════
class AccountConnection(threading.Thread):
    def __init__(self, host: str, token: str, log_q: queue.Queue, gui_cb):
        super().__init__(daemon=True)
        self.host = host  # nur host:port
        self.token = token
        self.log_q = log_q
        self.gui_cb = gui_cb

        self.ws = None
        self.total_points = 0
        self.answered_ids = set()

    # --------------------------------------------------------
    def run(self):
        url = f"wss://{self.host}/?token={self.token}"

        # >>>>>>>>>>>>>>>  NEU: URL ins Log schreiben  <<<<<<<<<<<<<<
        self.log_q.put(("Info", f"Verbinde zu {url}"))
        self.gui_cb()
        # <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<

        def send_vote(payload: dict):
            self.ws.send(json.dumps(payload))
            self.log_q.put(("Gesendet", payload))
            self.gui_cb()

        # ---- Callbacks -----------------------------------
        def on_message(ws, message):
            try:
                data = json.loads(message)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    mtype = item.get("messageType")
                    if mtype in {"quiz", "poll", "match_prediction"}:
                        self.log_q.put(("Empfangen", item))
                        self.handle_event(item, send_vote)
            except Exception as e:
                self.log_q.put(("Error", f"Parsing: {e}"))
            finally:
                self.gui_cb()

        def on_error(ws, err):
            self.log_q.put(("Error", str(err)))
            self.gui_cb()

        def on_close(ws, code, msg):
            self.log_q.put(("Closed", f"{code} {msg}"))
            self.gui_cb()

        def on_open(ws):
            self.log_q.put(("Info", "Verbunden"))
            self.gui_cb()

        self.ws = websocket.WebSocketApp(
            url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
            header=[
                "Origin: https://event.supercell.com",
                "User-Agent: Mozilla/5.0",
            ],
        )
        self.ws.run_forever()

    # --------------------------------------------------------
    def handle_event(self, item: dict, send_vote):
        mtype = item["messageType"]
        pl = item.get("payload", {})
        type_id = pl.get("typeId")

        if type_id in self.answered_ids:
            return

        ip = int(pl.get("interactionPoints", 0))
        bonus = 0

        if mtype == "quiz":
            alt = pl.get("correctAnswer", {}).get("alternative")
            pts = pl.get("correctAnswer", {}).get("points", 0)
            if alt is not None:
                send_vote(
                    {
                        "messageType": "quiz",
                        "payload": {"typeId": type_id, "alternative": int(alt)},
                        "timestamp": int(time.time() * 1000),
                    }
                )
                bonus = pts

        elif mtype == "poll":
            alts = (
                pl.get("alternatives")
                if isinstance(pl.get("alternatives"), int)
                else len(pl.get("alternatives") or pl.get("options") or [])
                or pl.get("optionsCount")
                or 4
            )
            send_vote(
                {
                    "messageType": "poll",
                    "payload": {
                        "typeId": type_id,
                        "alternative": random.randint(1, alts),
                    },
                    "timestamp": int(time.time() * 1000),
                }
            )

        elif mtype == "match_prediction":
            alts = pl.get("answers", {})
            if alts:
                best = max(alts, key=alts.get)
                bonus = pl.get("correctMatchPredictionPoints", 0)
                send_vote(
                    {
                        "messageType": "match_prediction",
                        "payload": {"typeId": type_id, "alternative": int(best)},
                        "timestamp": int(time.time() * 1000),
                    }
                )

        self.total_points += ip + bonus
        self.answered_ids.add(type_id)


# ════════════════════════════════════════════════════════════
#   GUI-Frame pro Account
# ════════════════════════════════════════════════════════════
class AccountFrame(ttk.Frame):
    def __init__(self, parent, remove_cb):
        super().__init__(parent, relief="groove", padding=4)
        self.remove_cb = remove_cb

        self.conn: AccountConnection | None = None
        self.running = False
        self.log_q = queue.Queue()
        self.log: List[Tuple[str, str | dict]] = []
        self.last_len = 0

        self.host_var = tk.StringVar(value="lb2.socketserver.clashersports.supercell.com:29049")
        self.token_var = tk.StringVar()
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self.render_log())

        self.points_var = tk.IntVar(value=0)

        # Layout ------------------------------------------------
        ttk.Label(self, text="Server-Host:Port").grid(row=0, column=0, sticky="w")
        ttk.Entry(self, textvariable=self.host_var, width=55).grid(row=0, column=1, columnspan=4, sticky="we")

        ttk.Label(self, text="Token").grid(row=1, column=0, sticky="w")
        ttk.Entry(self, textvariable=self.token_var, width=55).grid(row=1, column=1, columnspan=3, sticky="we")
        ttk.Button(self, text="Token aus Browser", command=self.get_token).grid(row=1, column=4, padx=2)

        self.start_b = ttk.Button(self, text="Start", command=self.start)
        self.stop_b = ttk.Button(self, text="Stop", command=self.stop, state=tk.DISABLED)
        self.rem_b = ttk.Button(self, text="Entfernen", command=lambda: self.remove_cb(self))

        self.start_b.grid(row=0, column=5, padx=2)
        self.stop_b.grid(row=1, column=5, padx=2)
        self.rem_b.grid(row=2, column=5, padx=2)

        ttk.Label(self, text="Punkte:").grid(row=2, column=0, sticky="e")
        ttk.Label(self, textvariable=self.points_var, width=10).grid(row=2, column=1, sticky="w")

        ttk.Label(self, text="Filter").grid(row=2, column=2, sticky="e")
        ttk.Entry(self, textvariable=self.filter_var, width=18).grid(row=2, column=3, sticky="w")

        self.log_txt = scrolledtext.ScrolledText(self, height=10, wrap="none", state=tk.DISABLED)
        self.log_txt.grid(row=3, column=0, columnspan=6, sticky="we", pady=4)

        self.columnconfigure(1, weight=1)

    # --------------------------------------------------------
    def get_token(self):
        token = None
        for getter in (browser_cookie3.chrome, browser_cookie3.firefox):
            try:
                cj = getter(domain_name="event.supercell.com")
                token = next((c.value for c in cj if c.name == "token"), None)
                if token:
                    break
            except Exception:
                pass
        if token:
            self.token_var.set(token)
        else:
            messagebox.showerror("Token", "Kein Token in Browser-Cookies gefunden.")

    # --------------------------------------------------------
    def gui_log(self):
        while not self.log_q.empty():
            self.log.append(self.log_q.get())
            self.log = self.log[-MAX_LOG_LINES:]

        if self.conn:
            self.points_var.set(self.conn.total_points)

        if any(t == "Closed" for t, _ in self.log[self.last_len :]):
            self.stop_b.config(state=tk.DISABLED)
            self.start_b.config(state=tk.NORMAL)
            self.running = False
            beep()

        self.render_log(append=True)
        if self.running:
            self.after(400, self.gui_log)

    def render_log(self, append=False):
        filt = self.filter_var.get().lower()
        if not append:
            self.log_txt.config(state=tk.NORMAL)
            self.log_txt.delete(1.0, tk.END)
            self.last_len = 0

        new = self.log[self.last_len :]
        for typ, msg in new:
            raw = json.dumps(msg, ensure_ascii=False) if not isinstance(msg, str) else msg
            if filt and filt not in raw.lower():
                continue
            self.log_txt.config(state=tk.NORMAL)
            self.log_txt.insert(tk.END, f"[{typ:<7}] {raw}\n")
            self.log_txt.config(state=tk.DISABLED)
        if new:
            self.log_txt.see(tk.END)
            self.last_len = len(self.log)

    # --------------------------------------------------------
    def start(self):
        host, token = self.host_var.get().strip(), self.token_var.get().strip()
        if not host or not token:
            messagebox.showwarning("Angaben fehlen", "Bitte Host und Token eintragen.")
            return

        self.conn = AccountConnection(host, token, self.log_q, self.gui_log)
        self.conn.start()

        self.running = True
        self.start_b.config(state=tk.DISABLED)
        self.stop_b.config(state=tk.NORMAL)
        self.after(400, self.gui_log)

    def stop(self):
        if self.conn:
            self.conn.ws and self.conn.ws.close()
        self.running = False
        self.start_b.config(state=tk.NORMAL)
        self.stop_b.config(state=tk.DISABLED)

    # --------------------------------------------------------
    def export_line(self):
        return f"{self.host_var.get().strip()}|{self.token_var.get().strip()}"

    def import_line(self, line: str):
        if "|" in line:
            host, token = line.split("|", 1)
            self.host_var.set(host.strip())
            self.token_var.set(token.strip())

    # --------------------------------------------------------
    def destroy(self):
        self.stop()
        super().destroy()


# ════════════════════════════════════════════════════════════
#   Haupt-Fenster
# ════════════════════════════════════════════════════════════
class MainApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CoC Event Multi-Account")
        self.minsize(900, 600)

        menubar = tk.Menu(self)
        file_m = tk.Menu(menubar, tearoff=False)
        file_m.add_command(label="Accounts laden …", command=self.load_accounts)
        file_m.add_command(label="Accounts speichern …", command=self.save_accounts)
        file_m.add_separator()
        file_m.add_command(label="Beenden", command=self.destroy)
        menubar.add_cascade(label="Datei", menu=file_m)
        self.config(menu=menubar)

        wrapper = ttk.Frame(self)
        wrapper.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(wrapper, highlightthickness=0)
        vsb = ttk.Scrollbar(wrapper, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vsb.set)

        vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.inner = ttk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind(
            "<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        self.canvas.bind_all("<MouseWheel>", self._wheel)

        ttk.Button(self, text="+ Account", command=self.add_account).pack(pady=4)

        self.frames: List[AccountFrame] = []
        self.add_account()

    # --------------------------------------------------------
    def _wheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def add_account(self):
        f = AccountFrame(self.inner, self.remove_account)
        f.pack(fill="x", pady=6, padx=6)
        self.frames.append(f)

    def remove_account(self, frame: AccountFrame):
        frame.destroy()
        self.frames.remove(frame)

    # --------------------------------------------------------
    def load_accounts(self):
        path = filedialog.askopenfilename(
            title="Accounts laden …",
            initialfile=ACCOUNT_FILE,
            filetypes=[("Textdateien", "*.txt"), ("Alle Dateien", "*.*")],
        )
        if not path:
            return
        try:
            lines = Path(path).read_text(encoding="utf-8").splitlines()
            for f in list(self.frames):
                self.remove_account(f)
            for ln in lines:
                if "|" in ln:
                    self.add_account()
                    self.frames[-1].import_line(ln)
        except Exception as e:
            messagebox.showerror("Import", str(e))

    def save_accounts(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            initialfile=ACCOUNT_FILE,
            title="Accounts speichern …",
            filetypes=[("Textdateien", "*.txt"), ("Alle Dateien", "*.*")],
        )
        if not path:
            return
        try:
            Path(path).write_text("\n".join(f.export_line() for f in self.frames), encoding="utf-8")
        except Exception as e:
            messagebox.showerror("Export", str(e))


# ════════════════════════════════════════════════════════════
if __name__ == "__main__":
    try:
        import websocket  # noqa: F401
    except ImportError:
        messagebox.showerror(
            "Abhängigkeit fehlt", "Bitte zuerst installieren:\n\npip install websocket-client"
        )
        raise SystemExit

    MainApp().mainloop()
