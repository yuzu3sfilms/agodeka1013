"""Local conservative request budgeting; process-wide rolling 60s admission.
Byte count is an upper-bound proxy for byte-level text tokenization, not a
provider tokenizer. Allow extra room for message framing and JSON mode.
"""
from __future__ import annotations
import os, threading, time
from dataclasses import dataclass

def env_int(name, default, low, high):
    try: v=int(os.environ.get(name,default))
    except (TypeError,ValueError): v=default
    return max(low,min(high,v))

def estimate(messages, completion):
    return 256 + sum(len(m['content'].encode('utf-8'))+16 for m in messages) + completion

@dataclass
class Reservation:
    at: float
    tokens: int

class RollingBudget:
    def __init__(self, limit=None, clock=time.monotonic):
        self.limit=limit if limit is not None else env_int('AGO_TPM_LIMIT',8000,1000,8000)-400
        self.clock=clock; self.lock=threading.RLock(); self.items=[]; self.blocked_until=0.0
    def _available(self):
        now=self.clock(); self.items[:]=[r for r in self.items if now-r.at<60]
        return 0 if now<self.blocked_until else max(0,self.limit-sum(r.tokens for r in self.items))
    def available(self):
        with self.lock: return self._available()
    def reserve(self,tokens):
        with self.lock:
            if tokens>self._available(): return None
            r=Reservation(self.clock(),tokens); self.items.append(r);return r
    def reconcile(self,r,usage,completion):
        # Retain output allowance and margin: provider admission can differ
        # from actual token usage. Never release an ambiguous failed request.
        if usage is None:return
        prompt=getattr(usage,'prompt_tokens',None); total=getattr(usage,'total_tokens',None)
        if not isinstance(prompt,int) or prompt<0:return
        used=max(prompt+completion, total if isinstance(total,int) else 0)+256
        with self.lock:
            if r in self.items:r.tokens=used
    def backoff(self,seconds):
        with self.lock:self.blocked_until=max(self.blocked_until,self.clock()+seconds)

PROCESS_BUDGET=RollingBudget()
