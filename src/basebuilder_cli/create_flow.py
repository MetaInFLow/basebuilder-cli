from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .intake import build_refine_instruction


@dataclass
class ThreeElements:
    manage_what: str
    workflow: str
    fields: str
    background_knowledge: str = ""

    def to_dict(self) -> dict[str, str]:
        data = {
            "manage_what": self.manage_what,
            "workflow": self.workflow,
            "fields": self.fields,
        }
        if self.background_knowledge:
            data["backgroundKnowledge"] = self.background_knowledge
            data["background_knowledge"] = self.background_knowledge
        return data

    def missing_required(self) -> list[str]:
        missing: list[str] = []
        for key, value in (
            ("manage_what", self.manage_what),
            ("workflow", self.workflow),
            ("fields", self.fields),
        ):
            if not str(value or "").strip():
                missing.append(key)
        return missing

    def is_complete(self) -> bool:
        return self.missing_required() == []


@dataclass
class CreateResult:
    status: str
    elements: ThreeElements
    run: dict[str, Any]
    message_id: int = 0
    task_id: str = ""


class CreateFlow:
    def __init__(self, api: Any):
        self.api = api

    def run(self, prompt: str, decisions: list[Any]) -> CreateResult:
        analyze_response = self.api.analyze(prompt)
        elements = normalize_elements(analyze_response)
        message_id = extract_message_id(analyze_response)
        task_id = extract_task_id(analyze_response)
        run: dict[str, Any] = {}
        if not elements.is_complete():
            return CreateResult(status="analyzing", elements=elements, run=run, message_id=message_id, task_id=task_id)

        for decision in decisions:
            if isinstance(decision, str):
                action = decision
                payload: dict[str, Any] = {}
            else:
                action = str(decision.get("action") or "")
                payload = dict(decision)

            if action in {"show", "review", ""}:
                continue
            if action == "optimize":
                instruction = str(payload.get("instruction") or "")
                files = [str(path) for path in payload.get("files") or []]
                refine_instruction = build_refine_instruction(instruction=instruction, files=files)
                optimize_response = self.api.optimize(elements, refine_instruction, message_id=message_id or None, task_id=task_id or None)
                elements = merge_elements(elements, normalize_elements(optimize_response))
                message_id = extract_message_id(optimize_response) or message_id
                task_id = extract_task_id(optimize_response) or task_id
                continue
            if action == "edit":
                elements = ThreeElements(
                    manage_what=str(payload.get("manage_what") or elements.manage_what),
                    workflow=str(payload.get("workflow") or elements.workflow),
                    fields=str(payload.get("fields") or elements.fields),
                    background_knowledge=str(
                        payload.get("backgroundKnowledge")
                        or payload.get("background_knowledge")
                        or elements.background_knowledge
                    ),
                )
                continue
            if action == "accept":
                if not elements.is_complete():
                    return CreateResult(status="analyzing", elements=elements, run=run, message_id=message_id, task_id=task_id)
                run = self.api.start_build(elements, message_id=message_id or None, task_id=task_id or None)
                task_id = extract_task_id(run) or task_id
                return CreateResult(status="building", elements=elements, run=run, message_id=message_id, task_id=task_id)

            raise ValueError(f"unknown create decision: {action}")

        status = "needs_confirmation" if elements.is_complete() else "analyzing"
        return CreateResult(status=status, elements=elements, run=run, message_id=message_id, task_id=task_id)


def normalize_elements(value: Any) -> ThreeElements:
    if isinstance(value, ThreeElements):
        return value
    if isinstance(value, dict):
        data = value.get("elements") if isinstance(value.get("elements"), dict) else value
        return ThreeElements(
            manage_what=str(data.get("manage_what") or ""),
            workflow=str(data.get("workflow") or ""),
            fields=str(data.get("fields") or ""),
            background_knowledge=str(
                data.get("backgroundKnowledge")
                or data.get("background_knowledge")
                or data.get("background")
                or ""
            ),
        )
    raise TypeError("three elements response must be a mapping")


def merge_elements(previous: ThreeElements, incoming: ThreeElements) -> ThreeElements:
    return ThreeElements(
        manage_what=incoming.manage_what or previous.manage_what,
        workflow=incoming.workflow or previous.workflow,
        fields=incoming.fields or previous.fields,
        background_knowledge=incoming.background_knowledge or previous.background_knowledge,
    )


def extract_message_id(value: Any) -> int:
    if not isinstance(value, dict):
        return 0
    for key in ("messageId", "message_id"):
        try:
            message_id = int(value.get(key) or 0)
        except (TypeError, ValueError):
            message_id = 0
        if message_id > 0:
            return message_id
    return 0


def extract_task_id(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    for key in ("taskId", "task_id"):
        text = str(value.get(key) or "").strip()
        if text:
            return text
    data = value.get("data")
    if isinstance(data, dict):
        return extract_task_id(data)
    return ""
