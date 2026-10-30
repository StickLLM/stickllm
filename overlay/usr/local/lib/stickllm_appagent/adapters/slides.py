"""Slides simulator adapter (in-memory, the reference app of the intent experiments)."""
from .slides_sim import SlideApp
from . import manual

class SimSlides(SlideApp):
    name = "slides"
    description = "simulated one-slide presentation editor (in memory)"
    verbs = ["add", "scale", "resize", "move", "nudge", "fill", "settext", "delete"]
    def __init__(self, start=None):
        super().__init__(start); self.manual = manual("MANUAL_slides.md")
    def undo(self): return self.do("undo")
    def reset(self, start): self.__init__(start)
    def export(self): return {"objs": self.objs}
