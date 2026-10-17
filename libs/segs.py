from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Segment:
    source: float
    target: float

    @classmethod
    def parse(cls, raw: Any) -> "Segment":
        source_text, target_text = str(raw).split("@", 1)
        return cls(source=float(source_text), target=float(target_text))


@dataclass(frozen=True)
class SegmentMapping:
    segments: tuple[Segment, ...]

    @classmethod
    def parse(cls, raw: Any) -> "SegmentMapping":
        if raw is None:
            return cls(())
        if not isinstance(raw, list):
            raise TypeError(f"segs must be a list, got {type(raw).__name__}")

        segments = tuple(Segment.parse(item) for item in raw)
        if not segments:
            return cls(())

        sorted_segments = tuple(sorted(segments, key=lambda item: item.source))
        previous_source: float | None = None
        for segment in sorted_segments:
            if previous_source is not None and segment.source == previous_source:
                raise ValueError(f"duplicate seg source value: {segment.source}")
            previous_source = segment.source
        return cls(sorted_segments)

    def apply(self, value: float) -> float:
        if not self.segments:
            return value

        if len(self.segments) == 1:
            source = self.segments[0].source
            target = self.segments[0].target
            if source == 0:
                if target == 0:
                    return 0.0
                raise ValueError("single seg source cannot be zero unless target is also zero")
            return value * target / source

        if value <= self.segments[0].source:
            return self._interpolate(value, self.segments[0], self.segments[1])

        for left, right in zip(self.segments, self.segments[1:], strict=False):
            if value <= right.source:
                return self._interpolate(value, left, right)

        return self._interpolate(value, self.segments[-2], self.segments[-1])

    def apply_reverse(self, value: float) -> float:
        """反向映射：真实值(target) → PLC原始值(source)，apply 的反函数"""
        if not self.segments:
            return value

        if len(self.segments) == 1:
            source = self.segments[0].source
            target = self.segments[0].target
            if target == 0:
                if source == 0:
                    return 0.0
                raise ValueError("single seg target cannot be zero unless source is also zero")
            return value * source / target

        # 按 target 排序，用于按真实值查找所在区间
        by_target = sorted(self.segments, key=lambda s: s.target)

        result = None
        if value <= by_target[0].target:
            result = self._interpolate_reverse(value, by_target[0], by_target[1])
        else:
            for left, right in zip(by_target, by_target[1:], strict=False):
                if value <= right.target:
                    result = self._interpolate_reverse(value, left, right)
                    break
            if result is None:
                result = self._interpolate_reverse(value, by_target[-2], by_target[-1])

        return result

    @staticmethod
    def _interpolate(value: float, left: Segment, right: Segment) -> float:
        span = right.source - left.source
        if span == 0:
            raise ValueError(f"invalid seg span: {left.source} == {right.source}")
        ratio = (value - left.source) / span
        return left.target + ratio * (right.target - left.target)

    @staticmethod
    def _interpolate_reverse(value: float, left: Segment, right: Segment) -> float:
        span = right.target - left.target
        if span == 0:
            raise ValueError(f"invalid seg target span: {left.target} == {right.target}")
        ratio = (value - left.target) / span
        return left.source + ratio * (right.source - left.source)
