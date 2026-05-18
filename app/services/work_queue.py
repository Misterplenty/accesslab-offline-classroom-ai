from __future__ import annotations

from collections import Counter, deque
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Condition
from time import perf_counter
from typing import Iterator

from app.db import utc_now_iso


@dataclass(slots=True)
class QueueReceipt:
    ticket_id: int
    job_kind: str
    enqueued_at: str
    weight: int = 1
    started_at: str = ""
    finished_at: str = ""
    outcome: str = "queued"
    wait_seconds: float = 0.0
    run_seconds: float = 0.0


class LocalWorkQueue:
    DEFAULT_JOB_WEIGHTS = {
        "upload-material": 2,
        "grounded-qa": 1,
        "code-tutor": 1,
        "delete-material": 1,
        "semantic-index": 2,
        "ocr": 2,
        "request": 1,
    }

    def __init__(
        self,
        *,
        max_concurrent_jobs: int = 1,
        job_weights: dict[str, int] | None = None,
        recent_job_limit: int = 8,
    ) -> None:
        self.max_concurrent_jobs = max(1, int(max_concurrent_jobs))
        self._job_weights = {**self.DEFAULT_JOB_WEIGHTS, **(job_weights or {})}
        self._recent_job_limit = max(1, int(recent_job_limit))
        self._condition = Condition()
        self._waiting_receipts: deque[QueueReceipt] = deque()
        self._active_receipts: dict[int, QueueReceipt] = {}
        self._recent_receipts: deque[QueueReceipt] = deque(maxlen=self._recent_job_limit)
        self._active_budget = 0
        self._next_ticket_id = 1
        self._completed_jobs = 0
        self._failed_jobs = 0
        self._total_wait_seconds = 0.0
        self._last_started_at = ""
        self._last_completed_at = ""
        self._last_failed_at = ""
        self._last_job_kind = ""
        self._last_wait_seconds = 0.0

    @contextmanager
    def job(self, *, job_kind: str = "request") -> Iterator[QueueReceipt]:
        normalized_kind = job_kind.strip() or "request"
        receipt = QueueReceipt(
            ticket_id=0,
            job_kind=normalized_kind,
            enqueued_at=utc_now_iso(),
            weight=self._resolve_job_weight(normalized_kind),
        )
        enqueued_monotonic = perf_counter()

        with self._condition:
            receipt.ticket_id = self._next_ticket_id
            self._next_ticket_id += 1
            self._waiting_receipts.append(receipt)

            while (
                self._waiting_receipts[0].ticket_id != receipt.ticket_id
                or self._active_budget + receipt.weight > self.max_concurrent_jobs
            ):
                self._condition.wait()

            self._waiting_receipts.popleft()
            self._active_receipts[receipt.ticket_id] = receipt
            self._active_budget += receipt.weight
            receipt.started_at = utc_now_iso()
            receipt.wait_seconds = perf_counter() - enqueued_monotonic
            receipt.outcome = "running"
            self._last_started_at = receipt.started_at
            self._last_job_kind = receipt.job_kind
            self._last_wait_seconds = round(receipt.wait_seconds, 3)

        run_start = perf_counter()
        try:
            yield receipt
        except Exception:
            receipt.finished_at = utc_now_iso()
            receipt.run_seconds = perf_counter() - run_start
            receipt.outcome = "failed"
            with self._condition:
                self._finish_receipt(receipt)
                self._failed_jobs += 1
                self._total_wait_seconds += receipt.wait_seconds
                self._last_failed_at = receipt.finished_at
                self._condition.notify_all()
            raise
        else:
            receipt.finished_at = utc_now_iso()
            receipt.run_seconds = perf_counter() - run_start
            receipt.outcome = "complete"
            with self._condition:
                self._finish_receipt(receipt)
                self._completed_jobs += 1
                self._total_wait_seconds += receipt.wait_seconds
                self._last_completed_at = receipt.finished_at
                self._condition.notify_all()

    def snapshot(self) -> dict[str, object]:
        with self._condition:
            completed_total = self._completed_jobs + self._failed_jobs
            average_wait_seconds = (
                round(self._total_wait_seconds / completed_total, 3)
                if completed_total
                else 0.0
            )
            waiting_jobs = len(self._waiting_receipts)
            active_jobs = len(self._active_receipts)
            waiting_by_kind = Counter(receipt.job_kind for receipt in self._waiting_receipts)
            active_by_kind = Counter(receipt.job_kind for receipt in self._active_receipts.values())
            return {
                "max_concurrent_jobs": self.max_concurrent_jobs,
                "active_jobs": active_jobs,
                "waiting_jobs": waiting_jobs,
                "queue_depth": active_jobs + waiting_jobs,
                "active_budget": self._active_budget,
                "available_budget": max(0, self.max_concurrent_jobs - self._active_budget),
                "last_started_at": self._last_started_at,
                "last_completed_at": self._last_completed_at,
                "last_failed_at": self._last_failed_at,
                "last_job_kind": self._last_job_kind,
                "last_wait_seconds": self._last_wait_seconds,
                "average_wait_seconds": average_wait_seconds,
                "completed_jobs": self._completed_jobs,
                "failed_jobs": self._failed_jobs,
                "active_by_kind": dict(active_by_kind),
                "waiting_by_kind": dict(waiting_by_kind),
                "recent_jobs": [self._receipt_snapshot(receipt) for receipt in reversed(self._recent_receipts)],
                "active_job_receipts": [
                    self._receipt_snapshot(receipt)
                    for receipt in sorted(self._active_receipts.values(), key=lambda item: item.ticket_id)
                ],
            }

    def _resolve_job_weight(self, job_kind: str) -> int:
        raw_weight = self._job_weights.get(job_kind, 1)
        try:
            normalized = max(1, int(raw_weight))
        except (TypeError, ValueError):
            normalized = 1
        return min(normalized, self.max_concurrent_jobs)

    def _finish_receipt(self, receipt: QueueReceipt) -> None:
        self._active_receipts.pop(receipt.ticket_id, None)
        self._active_budget = max(0, self._active_budget - receipt.weight)
        self._recent_receipts.append(receipt)

    @staticmethod
    def _receipt_snapshot(receipt: QueueReceipt) -> dict[str, int | float | str]:
        return {
            "ticket_id": receipt.ticket_id,
            "job_kind": receipt.job_kind,
            "weight": receipt.weight,
            "enqueued_at": receipt.enqueued_at,
            "started_at": receipt.started_at,
            "finished_at": receipt.finished_at,
            "outcome": receipt.outcome,
            "wait_seconds": round(receipt.wait_seconds, 3),
            "run_seconds": round(receipt.run_seconds, 3),
        }
