from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable


@dataclass(frozen=True)
class EvidenceTestDependencies:
    """Explicit seams for workflow-facade tests.

    The production workflow remains free to choose its adapters. Tests pass deterministic
    clients, repositories, embedding services, model output, identity, and clock values into
    the facade factory so assertions observe behavior rather than patching module globals.
    """

    client: Any
    repository: Any
    embeddings: Any
    model_output: Any
    identity: Any
    clock: Callable[[], datetime]

    def build_workflow(self, workflow_factory: Callable[..., Any]) -> Any:
        return workflow_factory(
            client=self.client,
            repository=self.repository,
            embeddings=self.embeddings,
            model_output=self.model_output,
            identity=self.identity,
            clock=self.clock,
        )
