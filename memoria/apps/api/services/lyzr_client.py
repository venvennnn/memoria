from __future__ import annotations

import json
import re
from typing import Any

import httpx
from openai import OpenAI

from apps.api.agents.prompts import AGENT_PROMPTS
from apps.api.settings import Settings

_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


class LyzrClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._openai: OpenAI | None = None
        if settings.openai_api_key:
            self._openai = OpenAI(api_key=settings.openai_api_key)

    @property
    def mode(self) -> str:
        return self.settings.lyzr_mode

    def _agent_id(self, role: str) -> str:
        mapping = {
            "gatekeeper": self.settings.lyzr_gatekeeper_id,
            "policy": self.settings.lyzr_policy_id,
            "librarian": self.settings.lyzr_librarian_id,
            "forgetter": self.settings.lyzr_forgetter_id,
            "registrar": self.settings.lyzr_registrar_id,
            "analyst": self.settings.lyzr_analyst_id,
            "manager": self.settings.lyzr_manager_id,
        }
        return mapping.get(role, "")

    async def infer_json(
        self,
        role: str,
        uid: str,
        session_id: str,
        user_message: str | dict[str, Any],
    ) -> dict[str, Any]:
        msg = user_message if isinstance(user_message, str) else json.dumps(user_message)
        agent_id = self._agent_id(role)
        if self.settings.lyzr_live and agent_id:
            try:
                return await self._lyzr_chat(agent_id, uid, session_id, msg)
            except Exception:
                pass
        return await self._openai_json(role, msg)

    async def _lyzr_chat(
        self, agent_id: str, uid: str, session_id: str, message: str
    ) -> dict[str, Any]:
        url = f"{self.settings.lyzr_base_url.rstrip('/')}/v3/inference/chat/"
        headers = {"x-api-key": self.settings.lyzr_api_key, "Content-Type": "application/json"}
        body = {
            "user_id": uid,
            "agent_id": agent_id,
            "session_id": session_id,
            "message": message,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
        text = self._extract_text(data)
        return self._parse_json(text)

    async def _openai_json(self, role: str, user_message: str) -> dict[str, Any]:
        system = AGENT_PROMPTS.get(role, "Return JSON only.")
        if not self._openai:
            return {}
        resp = self._openai.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.1,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_message},
            ],
        )
        text = resp.choices[0].message.content or "{}"
        return self._parse_json(text)

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        for key in ("response", "message", "output", "text", "content"):
            if key in data and isinstance(data[key], str):
                return data[key]
        if "data" in data and isinstance(data["data"], dict):
            for key in ("response", "message"):
                if key in data["data"]:
                    return str(data["data"][key])
        return json.dumps(data)

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        text = text.strip()
        m = _FENCE_RE.search(text)
        if m:
            text = m.group(1).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                return json.loads(text[start : end + 1])
            raise
