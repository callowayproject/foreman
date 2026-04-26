"""HTTP client for the Foreman agent harness."""

from __future__ import annotations

import httpx
import structlog

from foremanclient.models import DecisionMessage, TaskMessage

logger = structlog.get_logger(__name__)


class ForemanClientError(Exception):
    """Raised when the Foreman harness returns a non-2xx HTTP response.

    Args:
        status_code: The HTTP status code returned by the harness.
        message: A description of the error.
    """

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"HTTP {status_code}: {message}")


class ForemanClient:
    """Synchronous HTTP client for the Foreman agent harness.

    Wraps the three queue endpoints an agent needs: claim a task, complete a
    task, and send a heartbeat to extend the claim window.

    Args:
        harness_url: Base URL of the running Foreman harness
            (e.g. ``"http://localhost:8000"``).
        agent_url: This agent's own base URL, sent when claiming tasks so
            the harness knows which agent holds the claim.

    Example:
        >>> client = ForemanClient(
        ...     harness_url="http://localhost:8000",
        ...     agent_url="http://localhost:9001",
        ... )
        >>> task = client.next_task()
        >>> if task:
        ...     client.complete_task(task.task_id, decision)
    """

    def __init__(self, harness_url: str, agent_url: str) -> None:
        self._agent_url = agent_url
        self._http = httpx.Client(base_url=harness_url)

    def next_task(self) -> TaskMessage | None:
        """Claim and return the next pending task from the harness queue.

        Sends ``POST /queue/next`` with this agent's URL. The harness
        atomically marks the task as claimed and returns it.

        Returns:
            A :class:`~foremanclient.models.TaskMessage` when a task is
            available, or ``None`` when the queue is empty (HTTP 204).
        """
        response = self._http.post("/queue/next", json={"agent_url": self._agent_url})
        log = logger.bind(method="next_task", status_code=response.status_code)
        if response.status_code == 204:
            log.debug("Queue empty")
            return None
        if response.is_success:
            task = TaskMessage.model_validate(response.json())
            log.debug("Task claimed", task_id=task.task_id)
            return task
        log.warning("next_task failed", body=response.text)
        raise ForemanClientError(response.status_code, response.text)

    def complete_task(self, task_id: str, decision: DecisionMessage) -> None:
        """Store a completed decision and nudge the harness drain loop.

        Sends ``POST /queue/complete`` with the full decision, then
        ``POST /harness/result`` to wake the drain loop immediately.

        Args:
            task_id: The ``task_id`` from the original
                :class:`~foremanclient.models.TaskMessage`.
            decision: The agent's :class:`~foremanclient.models.DecisionMessage`
                to store.
        """
        log = logger.bind(method="complete_task", task_id=task_id)

        complete_resp = self._http.post("/queue/complete", json=decision.model_dump(mode="json"))
        if not complete_resp.is_success:
            log.warning("complete_task /queue/complete failed", status_code=complete_resp.status_code)
            raise ForemanClientError(complete_resp.status_code, complete_resp.text)
        log.debug("Decision stored", status_code=complete_resp.status_code)

        nudge_resp = self._http.post("/harness/result", json={"task_id": task_id})
        if not nudge_resp.is_success:
            log.warning("complete_task /harness/result failed", status_code=nudge_resp.status_code)
            raise ForemanClientError(nudge_resp.status_code, nudge_resp.text)
        log.debug("Drain nudge sent", status_code=nudge_resp.status_code)

    def heartbeat(self, task_id: str) -> None:
        """Extend the claim window for an in-progress task.

        Sends ``POST /queue/heartbeat`` to reset the harness timeout clock.
        Agents processing long LLM calls should call this at least once every
        30 seconds to prevent the task from being re-queued.

        Args:
            task_id: The ``task_id`` of the currently claimed task.
        """
        response = self._http.post("/queue/heartbeat", json={"task_id": task_id})
        log = logger.bind(method="heartbeat", task_id=task_id, status_code=response.status_code)
        if not response.is_success:
            log.warning("heartbeat failed")
            raise ForemanClientError(response.status_code, response.text)
        log.debug("Heartbeat sent")
