"""Job queue between the service and the ONLYOFFICE editor plugin. The plugin long-polls /oo/poll, runs the
JS body with Asc.plugin.callCommand inside the open editor (Presentation API), and posts the JSON result to /oo/result."""
import itertools, json, queue, threading, time

class Bridge:
    def __init__(self):
        self.jobs = queue.Queue(); self.res = {}; self.cv = threading.Condition(); self.ids = itertools.count(1)
        self.last_poll = 0.0; self.client = None
    def connected(self, within=30): return time.time() - self.last_poll < within
    def run(self, body, timeout=30):
        """body = JS statements; S = slide 0; must `return` a JSON-able value. Returns the value or raises."""
        jid = next(self.ids)
        code = ("try { var P = Api.GetPresentation(); var S = P.GetSlideByIndex(0);\n%s\n} catch (e) {"
                " return JSON.stringify({__error: String(e && e.message || e)}); }") % body
        wrapped = "var __r = (function(){ %s })(); return typeof __r === 'string' ? __r : JSON.stringify(__r);" % code
        self.jobs.put({"id": jid, "code": wrapped})
        end = time.time() + timeout
        with self.cv:
            while jid not in self.res:
                left = end - time.time()
                if left <= 0: raise TimeoutError("editor plugin did not answer in %ds (is the editor open?)" % timeout)
                self.cv.wait(left)
            r = self.res.pop(jid)
        if isinstance(r, str):
            try: r = json.loads(r)
            except Exception: pass
        if isinstance(r, dict) and "__error" in r: raise RuntimeError("editor: " + r["__error"])
        return r
    def poll(self, client, wait=20):
        self.last_poll = time.time(); self.client = client
        try: j = self.jobs.get(timeout=wait)
        except queue.Empty: return None
        finally: self.last_poll = time.time()
        return j
    def result(self, jid, value):
        with self.cv: self.res[int(jid)] = value; self.cv.notify_all()
