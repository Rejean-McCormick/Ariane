"""
Batch scan pipeline for Theseus.

This module builds on `simple_scan` to run multiple scans, typically
for different targets (apps, URLs, environments) in a single process.

It is intentionally:

- Dependency-free (standard library only).
- Sequential by default (one job after another).
- Safe: errors in one job do not crash the others (unless configured).

Typical use case:

    from theseus.pipelines.simple_scan import SimpleScanConfig
    from theseus.pipelines.batch_scan import BatchJob, run_batch_scan

    def make_driver_for_example():
        # return an ExplorationDriver instance
        ...

    jobs = [
        BatchJob(
            job_id="example",
            create_driver=make_driver_for_example,
            scan_config=SimpleScanConfig(app_id="example-app"),
        ),
    ]

    result = run_batch_scan(jobs)
    for job_id, job_result in result.results.items():
        if job_result.error is None:
            print(job_id, "OK", job_result.scan_result.context.context_id)
        else:
            print(job_id, "FAILED", job_result.error)

"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from ..core.exploration_engine import ExplorationDriver
from .simple_scan import (
    SimpleScanConfig,
    SimpleScanResult,
    run_simple_scan,
)

LOG = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Job / result types
# --------------------------------------------------------------------------- #


@dataclass
class BatchJob:
    """
    Description of a single scan job in a batch.

    Attributes:
        job_id:
            Logical identifier for the job (e.g. "firefox-homepage").
            Must be unique within a batch.
        create_driver:
            Callable that returns a fresh ExplorationDriver instance for
            this job. It is called once per job when the batch runner
            is ready to execute it.
        scan_config:
            SimpleScanConfig describing how to run the scan.
    """

    job_id: str
    create_driver: Callable[[], ExplorationDriver]
    scan_config: SimpleScanConfig


@dataclass
class BatchJobResult:
    """
    Result of a single job within a batch.

    Attributes:
        job:
            The job description that was executed.
        scan_result:
            The SimpleScanResult produced by the scan, or None if the job
            failed before or during scanning.
        error:
            Exception instance if the job failed, otherwise None.
    """

    job: BatchJob
    scan_result: Optional[SimpleScanResult]
    error: Optional[BaseException] = None

    @property
    def ok(self) -> bool:
        """Return True if the job finished without error."""
        return self.error is None and self.scan_result is not None


@dataclass
class BatchScanResult:
    """
    Aggregate result for a batch of jobs.

    Attributes:
        results:
            Mapping of job_id -> BatchJobResult.
    """

    results: Dict[str, BatchJobResult]

    def successful_jobs(self) -> List[BatchJobResult]:
        """Return all jobs that completed successfully."""
        return [r for r in self.results.values() if r.ok]

    def failed_jobs(self) -> List[BatchJobResult]:
        """Return all jobs that failed."""
        return [r for r in self.results.values() if not r.ok]


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #


def run_batch_scan(
    jobs: List[BatchJob],
    *,
    stop_on_error: bool = False,
) -> BatchScanResult:
    """
    Run multiple Theseus scans in sequence.

    Args:
        jobs:
            List of BatchJob objects. job_id must be unique per job.
        stop_on_error:
            If True, abort the batch when the first job fails.
            If False (default), continue with remaining jobs and record
            the error in each failing job's BatchJobResult.

    Returns:
        BatchScanResult with per-job results.
    """
    if not jobs:
        return BatchScanResult(results={})

    # Basic uniqueness check for job_ids
    seen_ids = set()
    for job in jobs:
        if job.job_id in seen_ids:
            raise ValueError(f"Duplicate job_id in batch: {job.job_id}")
        seen_ids.add(job.job_id)

    results: Dict[str, BatchJobResult] = {}

    LOG.info("Starting batch scan with %d job(s)", len(jobs))

    for job in jobs:
        LOG.info("Running job '%s' (app_id=%s)", job.job_id, job.scan_config.app_id)

        try:
            driver = job.create_driver()
        except Exception as exc:  # noqa: BLE001
            LOG.exception("Failed to create driver for job '%s'", job.job_id)
            result = BatchJobResult(job=job, scan_result=None, error=exc)
            results[job.job_id] = result
            if stop_on_error:
                LOG.info("Stopping batch due to error in job '%s'", job.job_id)
                break
            continue

        try:
            scan_result = run_simple_scan(
                driver=driver,
                config=job.scan_config,
                tracker_config=None,
            )
            result = BatchJobResult(job=job, scan_result=scan_result, error=None)
            LOG.info(
                "Job '%s' completed: context_id=%s",
                job.job_id,
                scan_result.context.context_id,
            )
        except Exception as exc:  # noqa: BLE001
            LOG.exception("Error during scan for job '%s'", job.job_id)
            result = BatchJobResult(job=job, scan_result=None, error=exc)
            if stop_on_error:
                results[job.job_id] = result
                LOG.info("Stopping batch due to error in job '%s'", job.job_id)
                break

        results[job.job_id] = result

    LOG.info(
        "Batch scan finished: %d total, %d success, %d failed",
        len(results),
        sum(1 for r in results.values() if r.ok),
        sum(1 for r in results.values() if not r.ok),
        )
    return BatchScanResult(results=results)
