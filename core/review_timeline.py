"""Incremental interval lookup on the original audio timeline, including overlap."""

import math
from bisect import bisect_right


class ReviewTimeline:
    def __init__(self, rows=()):
        self.events = []
        for index, row in enumerate(rows):
            start, end = float(row.get("start", 0)), float(row.get("end", 0))
            if math.isfinite(start) and math.isfinite(end) and end > start:
                self.events.extend(((start, 1, index), (end, -1, index)))
        self.events.sort()
        self.times = [event[0] for event in self.events]
        self.cursor = 0
        self.active = set()

    def at(self, seconds):
        if not math.isfinite(seconds):
            return []
        end = bisect_right(self.times, seconds)
        if end < self.cursor:
            self.cursor = 0
            self.active.clear()
        while self.cursor < end:
            _, kind, index = self.events[self.cursor]
            if kind == 1:
                self.active.add(index)
            else:
                self.active.discard(index)
            self.cursor += 1
        return sorted(self.active)
