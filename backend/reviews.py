"""
Rider reviews of a completed pickup (S15 follow-up), kept in one JSON file
under `storage.directory` -- see backend/downtime.py, whose read-on-every-
call, atomic-rewrite, single-process-lock shape this follows exactly. Reviews
are never edited or deleted once submitted, so unlike downtime this only
ever reads the whole file and appends to it.

A JSON-lines file (one review per line, no read-modify-write needed to
append) would also have been a reasonable choice for something append-only
like this -- picked the shared-array shape instead so there is only one
pattern for the team to know, not two, while the number of reviews stays
small enough that reading the whole file back is not a cost worth avoiding.
Revisit if that stops being true.
"""

from __future__ import annotations
import json
import threading
from pathlib import Path

from backend.files import write_json_atomic
from backend.models import Review
from backend.repository.base import RepositoryError

FILE_VERSION = 1


class DuplicateReview(Exception):
    """
    The pickup request already has a review: one review per pickup.
    """


class ReviewStore:
    """
    Reviews in one JSON file: `{"version": 1, "reviews": [...]}`. A missing
    file means no reviews yet.
    """

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._lock = threading.Lock()

    def list(self) -> list[Review]:
        """
        Every review, ascending by `created_at`.
        """
        return sorted(self._read(), key=lambda r: r.created_at)

    def add(self, review: Review) -> Review:
        """
        Store a new review.

        Raises
        ------
        DuplicateReview
            If its pickup request already has one. Checked under the lock,
            so two submits of the same form in the same instant store one.
        """
        with self._lock:
            reviews = self._read()
            if any(r.pickup_request_id == review.pickup_request_id for r in reviews):
                raise DuplicateReview(review.pickup_request_id)
            reviews.append(review)
            self._write(reviews)
        return review

    def _read(self) -> list[Review]:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except OSError as exc:
            raise RepositoryError(f"Could not read {self.path}: {exc}") from exc

        try:
            raw = json.loads(text)
            if raw.get("version") != FILE_VERSION:
                raise ValueError(f"unsupported version {raw.get('version')!r}")
            return [Review.from_dict(entry) for entry in raw["reviews"]]
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise RepositoryError(f"{self.path} is not a valid reviews file: {exc}") from exc

    def _write(self, reviews: list[Review]) -> None:
        try:
            write_json_atomic(self.path, {"version": FILE_VERSION, "reviews": [r.to_dict() for r in reviews]})
        except OSError as exc:
            raise RepositoryError(f"Could not write {self.path}: {exc}") from exc
