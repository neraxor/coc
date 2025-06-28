#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CoC Event Multi-Account
– Scrollbare Accounts
– Punktestatistik
– Sound + Auto-Reconnect (4000 / 1006 usw.)
– Import / Export
"""

import json, queue, random, threading, time, tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import List, Tuple

import browser_cookie3, websocket

try:
    import winsound
    def beep(): winsound.MessageBeep(winsound.MB_ICONHAND)
except ImportError:
    def beep(): print("\a", end="", flush=True)

MAX_LOG = 300
SAVE_TXT = "accounts.txt"

# ───────────────── Netzwerk-Thread ──────────────────────────
class AccountConn(threading.Thread):
    def __init__(self, host:str, token:str, q:queue.Queue, cb):
        super().__init__(daemon=True)
        self.host, self.token = host, token
        self.q, self.cb = q, cb
        self.ws = None; self.points = 0; self.ids = set()

    def run(self):
        url = f"wss://{self.host}/?token={self.token}"
        self.q.put(("Info", f"Verbinde zu {url}")); self.cb()

        def snd(p):
            self.ws.send(json.dumps(p))
            self.q.put(("Gesendet", p)); self.cb()

        def on_msg(_, m):
            try:
                for it in (json.loads(m) if isinstance(json.loads(m), list) else [json.loads(m)]):
                    if it.get("messageType") in {"quiz","poll","match_prediction"}:
                        self.q.put(("Empfangen", it)); self.handle(it, snd)
            except Exception as e:
                self.q.put(("Error", f"Parse:{e}"))
            finally: self.cb()

        def on_err(_, e):  self.q.put(("Error", str(e))); self.cb()
        def on_cls(_, c, msg): self.q.put(("Closed", f"{c} {msg}")); self.cb()
        def on_opn(_): self.q.put(("Info", "Verbunden")); self.cb()

        self.ws = websocket.WebSocketApp(
            url, on_open=on_opn, on_message=on_msg,
            on_error=on_err, on_close=on_cls,
            header=["Origin: https://event.supercell.com",
                    "User-Agent: Mozilla/5.0"])
        self.ws.run_forever()

    def handle(self,it,snd):   # Punkte-/Vote-Logik (unverändert)
        t=it["messageType"]; pl=it.get("payload",{}); tid=pl.get("typeId")
        if tid in self.ids: return
        ip=int(pl.get("interactionPoints",0)); bonus=0
        if t=="quiz":
            a=pl.get("correctAnswer",{}).get("alternative")
            pts=pl.get("correctAnswer",{}).get("points",0)
            if a is not None:
                snd({"messageType":"quiz","payload":{"typeId":tid,"alternative":int(a)},
                     "timestamp":int(time.time()*1000)}); bonus=pts
        elif t=="poll":
            ac=pl.get("alternatives") if isinstance(pl.get("alternatives"),int) \
                else len(pl.get("alternatives") or pl.get("options") or []) \
                or pl.get("optionsCount") or 4
            snd({"messageType":"poll","payload":{"typeId":tid,
                 "alternative":random.randint(1,ac)},
                 "timestamp":int(time.time()*1000)})
        elif t=="match_prediction":
            ans=pl.get("answers",{}); best=max(ans,key=ans.get) if ans else None
            bonus=pl.get("correctMatchPredictionPoints",0)
            if ans:
                snd({"messageType":"match_prediction","payload":{"typeId":tid,"alternative":int(best)},
                     "timestamp":int(time.time()*1000)})
        self.points+=ip+bonus; self.ids.add(tid)

# ───────────────── Account-GUI ───────────────────────────────
class AccountFrame(ttk.Frame):
    def __init__(self,parent,remove_cb):
        super().__init__(parent,relief="groove",padding=4)
        self.remove_cb = remove_cb
        self.conn=None; self.running=False
        self.q=queue.Queue(); self.log=[]; self.last=0
        self.host=tk.StringVar(value="lb2.socketserver.clashersports.supercell.com:29049")
        self.token=tk.StringVar(); self.filt=tk.StringVar()
        self.filt.trace_add("write",lambda *_:self.render())
        self.points=tk.IntVar(value=0)

        ttk.Label(self,text="Server").grid(row=0,column=0,sticky="w")
        ttk.Entry(self,textvariable=self.host,width=55).grid(row=0,column=1,columnspan=3,sticky="we")
        ttk.Label(self,text="Token").grid(row=1,column=0,sticky="w")
        ttk.Entry(self,textvariable=self.token,width=55).grid(row=1,column=1,columnspan=3,sticky="we")

        self.st=ttk.Button(self,text="Start",command=self.start); self.st.grid(row=0,column=5)
        self.sp=ttk.Button(self,text="Stop",command=self.stop,state=tk.DISABLED); self.sp.grid(row=1,column=5)
        ttk.Button(self,text="Entfernen",command=lambda:remove_cb(self)).grid(row=2,column=5)

        ttk.Label(self,text="Punkte:").grid(row=2,column=0,sticky="e")
        ttk.Label(self,textvariable=self.points,width=10).grid(row=2,column=1,sticky="w")
        ttk.Label(self,text="Filter").grid(row=2,column=2,sticky="e")
        ttk.Entry(self,textvariable=self.filt,width=18).grid(row=2,column=3,sticky="w")

        self.logtxt=scrolledtext.ScrolledText(self,height=9,wrap="none",state=tk.DISABLED)
        self.logtxt.grid(row=3,column=0,columnspan=6,sticky="we",pady=4)
        self.columnconfigure(1,weight=1)

    def get_token(self):
        token=None
        for grab in (browser_cookie3.chrome,browser_cookie3.firefox):
            try:
                cj=grab(domain_name="event.supercell.com")
                token=next((c.value for c in cj if c.name=="token"),None)
                if token: break
            except Exception: pass
        if token: self.token.set(token)
        else: messagebox.showerror("Token","Kein Token-Cookie gefunden.")

    # Haupt-Loop
    def pump(self):
        while not self.q.empty():
            self.log.append(self.q.get()); self.log=self.log[-MAX_LOG:]
        if self.conn: self.points.set(self.conn.points)

        # ─ Auto-Reconnect ─
        if any(t=="Closed" for t,_ in self.log[self.last:]):
            beep()
            self.stop_buttons()
            if self.running:          # nur 1× pro Ereignis
                self.running=False
                self.after(1000,self.start)   # <-- 1 s warten

        self.render(True)
        if self.running: self.after(400,self.pump)

    def render(self,append=False):
        if not append:
            self.logtxt.config(state=tk.NORMAL); self.logtxt.delete(1.0,tk.END); self.last=0
        for typ,msg in self.log[self.last:]:
            raw=json.dumps(msg,ensure_ascii=False) if not isinstance(msg,str) else msg
            if self.filt.get().lower() and self.filt.get().lower() not in raw.lower(): continue
            self.logtxt.config(state=tk.NORMAL)
            self.logtxt.insert(tk.END,f"[{typ:<7}] {raw}\n"); self.logtxt.config(state=tk.DISABLED)
        if self.log[self.last:]: self.logtxt.see(tk.END); self.last=len(self.log)

    def start(self):
        if self.running: return
        if not self.host.get().strip() or not self.token.get().strip():
            messagebox.showwarning("Fehlt","Host oder Token leer"); return
        self.conn=AccountConn(self.host.get().strip(),self.token.get().strip(),self.q,self.pump)
        self.conn.start(); self.running=True
        self.st.config(state=tk.DISABLED); self.sp.config(state=tk.NORMAL)
        self.after(400,self.pump)

    def stop(self):
        if self.conn and self.conn.ws: self.conn.ws.close()
        self.running=False; self.stop_buttons()

    def stop_buttons(self):
        self.st.config(state=tk.NORMAL); self.sp.config(state=tk.DISABLED)

    def exp(self): return f"{self.host.get().strip()}|{self.token.get().strip()}"
    def imp(self,line):
        if "|" in line: h,t=line.split("|",1); self.host.set(h.strip()); self.token.set(t.strip())
    def destroy(self): self.stop(); super().destroy()

# ───────────── Hauptfenster ─────────────────────
class MainApp(tk.Tk):
    def __init__(self):
        super().__init__(); self.title("CoC Event Multi-Account"); self.minsize(900,600)
        m=tk.Menu(self); fm=tk.Menu(m,tearoff=False)
        fm.add_command(label="Laden…",command=self.load)
        fm.add_command(label="Speichern…",command=self.save)
        fm.add_separator(); fm.add_command(label="Ende",command=self.destroy)
        m.add_cascade(label="Datei",menu=fm); self.config(menu=m)

        wrap=ttk.Frame(self); wrap.pack(fill="both",expand=True)
        self.canvas=tk.Canvas(wrap,highlightthickness=0)
        vsb=ttk.Scrollbar(wrap,orient="vertical",command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right",fill="y"); self.canvas.pack(side="left",fill="both",expand=True)

        self.inner=ttk.Frame(self.canvas)
        self.canvas.create_window((0,0),window=self.inner,anchor="nw")
        self.inner.bind("<Configure>",lambda e:self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind_all("<MouseWheel>",lambda e:self.canvas.yview_scroll(-int(e.delta/120),"units"))

        ttk.Button(self,text="+ Account",command=self.add).pack(pady=4)
        self.frames:List[AccountFrame]=[]; self.add()

    def add(self):
        f=AccountFrame(self.inner,self.rem); f.pack(fill="x",pady=6,padx=6); self.frames.append(f)
    def rem(self,f): f.destroy(); self.frames.remove(f)

    def load(self):
        p=filedialog.askopenfilename(title="Laden",initialfile=SAVE_TXT,
            filetypes=[("Text","*.txt"),("Alle","*.*")]);
        if not p: return
        for fr in list(self.frames): self.rem(fr)
        for ln in Path(p).read_text(encoding="utf-8").splitlines():
            if "|" in ln: self.add(); self.frames[-1].imp(ln)

    def save(self):
        p=filedialog.asksaveasfilename(defaultextension=".txt",initialfile=SAVE_TXT,
            title="Speichern",filetypes=[("Text","*.txt"),("Alle","*.*")])
        if not p: return
        Path(p).write_text("\n".join(f.exp() for f in self.frames),encoding="utf-8")

# ────────── Start ───────────────────────────────
if __name__ == "__main__":
    MainApp().mainloop()
