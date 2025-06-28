#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CoC Event Multi-Account – pro Account eigener Web-Socket-Server,
ohne Lambda-Indizes (kein „Unresolved reference 'idx'“ mehr)
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import websocket
import threading
import json
import random
import queue
import time
import browser_cookie3


MAX_LOG_LINES = 500


# ────────────────────────────────────────────────
#   Hintergrund-Thread für einen Account
# ────────────────────────────────────────────────
class AccountConnection(threading.Thread):
    def __init__(self, server_url_base: str, token: str,
                 log_queue: queue.Queue, gui_callback):
        super().__init__(daemon=True)
        self.server_url_base = server_url_base.rstrip('/')
        self.token           = token
        self.log_queue       = log_queue
        self.gui_callback    = gui_callback
        self.ws              = None

        self.answered_quizzes           = set()
        self.answered_polls             = set()
        self.answered_match_predictions = set()

    # -------------------------------------------
    def run(self):
        url = (f"{self.server_url_base}?token={self.token}"
               if not self.server_url_base.endswith("?token=")
               else f"{self.server_url_base}{self.token}")

        def send_vote(ws, payload):
            ws.send(json.dumps(payload))
            self.log_queue.put(("Gesendet", payload))
            self.gui_callback()

        # ---- Callbacks -----------------------------------
        def on_message(ws, message):
            try:
                data = json.loads(message)

                def relevant(item):
                    return item.get("messageType") in {
                        "poll", "quiz", "match_prediction"
                    }

                if isinstance(data, list):
                    for item in filter(relevant, data):
                        self.log_queue.put(("Empfangen", item))
                        self.handle_event(ws, item, send_vote)
                elif relevant(data):
                    self.log_queue.put(("Empfangen", data))
                    self.handle_event(ws, data, send_vote)
            except Exception as e:
                self.log_queue.put(("Error", f"Parsing: {e}"))
            finally:
                self.gui_callback()

        def on_error(ws, error):
            self.log_queue.put(("Error", str(error)))
            self.gui_callback()

        def on_close(ws, code, msg):
            self.log_queue.put(("Info", f"Verbindung geschlossen: {code} {msg}"))
            self.gui_callback()

        def on_open(ws):
            self.log_queue.put(("Info", "Socket verbunden!"))
            self.gui_callback()

        self.ws = websocket.WebSocketApp(
            url,
            on_open    = on_open,
            on_message = on_message,
            on_error   = on_error,
            on_close   = on_close,
            header=[
                "Origin: https://event.supercell.com",
                "User-Agent: Mozilla/5.0"
            ]
        )
        self.ws.run_forever()

    # -------------------------------------------
    def handle_event(self, ws, item, send_vote):
        mtype   = item.get("messageType")
        payload = item.get("payload", {})

        if mtype == "poll":
            type_id = payload.get("typeId")
            if type_id in self.answered_polls:
                return
            alt_count = (
                payload.get("alternatives")
                if isinstance(payload.get("alternatives"), int)
                else len(payload.get("alternatives") or payload.get("options") or []) or
                     payload.get("optionsCount") or 4
            )
            vote = {
                "messageType": "poll",
                "payload": {"typeId": type_id,
                            "alternative": random.randint(1, alt_count)},
                "timestamp": int(time.time() * 1000)
            }
            send_vote(ws, vote)
            self.answered_polls.add(type_id)

        elif mtype == "match_prediction":
            type_id = payload.get("typeId")
            if type_id in self.answered_match_predictions:
                return
            answers   = payload.get("answers", {})
            alt_index = max(answers, key=answers.get) if answers else None
            if alt_index:
                vote = {
                    "messageType": "match_prediction",
                    "payload": {"typeId": type_id,
                                "alternative": int(alt_index)},
                    "timestamp": int(time.time() * 1000)
                }
                send_vote(ws, vote)
                self.answered_match_predictions.add(type_id)

        elif mtype == "quiz":
            type_id = payload.get("typeId")
            if type_id in self.answered_quizzes:
                return
            correct = payload.get("correctAnswer", {}).get("alternative")
            if correct is not None:
                vote = {
                    "messageType": "quiz",
                    "payload": {"typeId": type_id,
                                "alternative": int(correct)},
                    "timestamp": int(time.time() * 1000)
                }
                send_vote(ws, vote)
                self.answered_quizzes.add(type_id)

    def stop(self):
        if self.ws:
            self.ws.close()


# ────────────────────────────────────────────────
#   GUI-Frame für einen Account
# ────────────────────────────────────────────────
class AccountFrame(ttk.Frame):
    DEFAULT_SERVER = (
        "wss://lb2.socketserver.clashersports.supercell.com:29049/?token="
    )

    def __init__(self, parent, remove_callback):
        super().__init__(parent)
        self.remove_callback = remove_callback
        self.conn_thread     = None
        self.log_queue       = queue.Queue()
        self.log_history     = []
        self.running         = False
        self.last_log_len    = 0

        # ---------------- Eingaben ----------------
        self.server_var = tk.StringVar(value=self.DEFAULT_SERVER)
        self.token_var  = tk.StringVar()
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self.show_log())

        ttk.Label(self, text="Server:").grid(row=0, column=0, sticky="w")
        ttk.Entry(self, textvariable=self.server_var, width=70).grid(
            row=0, column=1, columnspan=5, sticky="we", pady=1
        )

        ttk.Label(self, text="Token:").grid(row=1, column=0, sticky="w")
        ttk.Entry(self, textvariable=self.token_var, width=70).grid(
            row=1, column=1, padx=2, sticky="w"
        )
        ttk.Button(self, text="Token aus Browser",
                   command=self.get_token_from_browser).grid(row=1, column=2, padx=2)

        self.start_btn  = ttk.Button(self, text="Start", command=self.start_account)
        self.stop_btn   = ttk.Button(self, text="Stop",
                                     command=self.stop_account, state=tk.DISABLED)
        self.remove_btn = ttk.Button(self, text="Entfernen",
                                     command=lambda: self.remove_callback(self))

        self.start_btn.grid( row=1, column=3, padx=2)
        self.stop_btn.grid(  row=1, column=4, padx=2)
        self.remove_btn.grid(row=1, column=5, padx=2)

        ttk.Label(self, text="Filter:").grid(row=2, column=0, sticky="e")
        ttk.Entry(self, textvariable=self.filter_var, width=20).grid(
            row=2, column=1, sticky="w"
        )

        self.log_text = scrolledtext.ScrolledText(
            self, width=120, height=12, wrap="none", state=tk.DISABLED
        )
        self.log_text.grid(row=3, column=0, columnspan=6, pady=4, sticky="we")

        self.columnconfigure(1, weight=1)
        self.show_log()

    # -------------------------------------------
    def get_token_from_browser(self):
        token = None
        try:
            cj = browser_cookie3.chrome(domain_name="event.supercell.com")
            token = next((c.value for c in cj if c.name == "token"), None)
        except Exception:
            pass
        if not token:
            try:
                cj = browser_cookie3.firefox(domain_name="event.supercell.com")
                token = next((c.value for c in cj if c.name == "token"), None)
            except Exception:
                pass

        if token:
            self.token_var.set(token)
        else:
            messagebox.showerror(
                "Token nicht gefunden",
                ("Kein Token in Chrome/Firefox gefunden.\n"
                 "Auf https://event.supercell.com eingeloggt?")
            )

    # -------------------------------------------
    def start_account(self):
        server = self.server_var.get().strip()
        token  = self.token_var.get().strip()
        if not server or not token:
            messagebox.showwarning("Fehlende Daten",
                                   "Bitte Server-URL *und* Token eintragen.")
            return

        self.conn_thread = AccountConnection(server, token,
                                             self.log_queue, self.update_log)
        self.conn_thread.start()

        self.running = True
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)

    def stop_account(self):
        if self.conn_thread:
            self.conn_thread.stop()
        self.running = False
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)

    # -------------------------------------------
    #   Log
    # -------------------------------------------
    def update_log(self):
        while not self.log_queue.empty():
            self.log_history.append(self.log_queue.get())
            if len(self.log_history) > MAX_LOG_LINES:
                self.log_history = self.log_history[-MAX_LOG_LINES:]
        self.show_log(append_only=True)
        if self.running:
            self.after(500, self.update_log)

    def show_log(self, append_only=False):
        filter_text = self.filter_var.get().lower()
        if not append_only:
            self.log_text.config(state=tk.NORMAL)
            self.log_text.delete(1.0, tk.END)
            self.last_log_len = 0

        new_entries = self.log_history[self.last_log_len:]
        for typ, msg in new_entries:
            raw = json.dumps(msg, ensure_ascii=False) \
                  if not isinstance(msg, str) else msg
            if filter_text and filter_text not in raw.lower():
                continue
            prefix = f"[{typ}]".ljust(11)
            self.log_text.config(state=tk.NORMAL)
            self.log_text.insert(tk.END, f"{prefix} {raw}\n")
            self.log_text.config(state=tk.DISABLED)

        if new_entries:
            self.log_text.see(tk.END)
            self.last_log_len = len(self.log_history)

    # -------------------------------------------
    def destroy(self):
        self.stop_account()
        super().destroy()


# ────────────────────────────────────────────────
#   Haupt-GUI
# ────────────────────────────────────────────────
class MainApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CoC Event Multi-Account")
        self.geometry("1250x800")

        self.account_frames = []

        ctl = ttk.Frame(self)
        ctl.pack(fill=tk.X, padx=10, pady=5)
        ttk.Button(ctl, text="+ Account", command=self.add_account).pack(side=tk.LEFT)

        self.container = ttk.Frame(self)
        self.container.pack(fill=tk.BOTH, expand=True)

        self.add_account()

    def add_account(self):
        frame = AccountFrame(self.container, self.remove_account)
        frame.pack(fill=tk.X, padx=8, pady=8)
        self.account_frames.append(frame)

    def remove_account(self, frame: AccountFrame):
        frame.destroy()
        self.account_frames.remove(frame)


# ────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        import websocket  # noqa: F401
    except ImportError:
        print("Installiere 'websocket-client' mit:\n    pip install websocket-client")
        exit(1)

    MainApp().mainloop()
