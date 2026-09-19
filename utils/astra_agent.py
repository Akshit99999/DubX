"""Astra 6 (GPT-6 Astra) Autonomous Coding Agent Interface.

Connects to Abacus.AI RouteLLM to run code generation, audits, refactoring,
and optimizations directly from Python or the command line.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from config import PROJECT_ROOT

try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

ASTRA_API_URL = "https://routellm.abacus.ai/v1/chat/completions"
DEFAULT_MODEL = os.getenv("ASTRA_MODEL", "gpt-6-astra")


def get_api_key() -> str:
    key = os.getenv("ASTRA_API_KEY") or os.getenv("ABACUS_API_KEY") or ""
    if not key.strip():
        raise RuntimeError(
            "ASTRA_API_KEY is not set. Please add ASTRA_API_KEY=s2_... to your .env file."
        )
    return key.strip()


def run_astra_coding_task(
    task_prompt: str,
    context_files: list[str | Path] | None = None,
    system_role: str | None = None,
    temperature: float = 0.2,
    timeout: int = 60,
) -> str:
    """Execute a coding task using Astra 6 (GPT-6 Astra via Abacus.AI)."""
    import requests

    key = get_api_key()
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    file_contexts = ""
    if context_files:
        for file_path in context_files:
            p = Path(file_path)
            if not p.is_absolute():
                p = PROJECT_ROOT / p
            if p.is_file():
                try:
                    content = p.read_text(encoding="utf-8", errors="replace")
                    file_contexts += f"\n\n--- FILE: {p.relative_to(PROJECT_ROOT)} ---\n{content}\n"
                except Exception as exc:
                    file_contexts += f"\n\n--- FILE: {p.name} (Error reading: {exc}) ---\n"

    default_system = (
        "You are Astra 6 (GPT-6 Astra), an elite software engineer and AI architect. "
        "Your role is to write production-grade, highly efficient, well-tested code. "
        "Always provide clean, complete, bug-free solutions with clear rationale."
    )
    system_content = system_role or default_system

    user_content = task_prompt
    if file_contexts:
        user_content = f"{file_contexts}\n\n--- TASK ---\n{task_prompt}"

    payload = {
        "model": DEFAULT_MODEL,
        "messages": [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ],
        "temperature": temperature,
    }

    response = requests.post(ASTRA_API_URL, headers=headers, json=payload, timeout=timeout)
    if response.status_code != 200:
        raise RuntimeError(
            f"Astra 6 API request failed ({response.status_code}): {response.text}"
        )

    data = response.json()
    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError("Astra 6 returned no choices in response")

    return choices[0]["message"]["content"]


def main():
    parser = argparse.ArgumentParser(description="Astra 6 Coding Agent CLI")
    parser.add_argument("task", help="The coding instruction or question for Astra 6")
    parser.add_argument(
        "-f", "--files", nargs="*", help="File paths to supply as context to Astra 6"
    )
    parser.add_argument(
        "-t", "--temperature", type=float, default=0.2, help="Sampling temperature"
    )
    args = parser.parse_args()

    try:
        result = run_astra_coding_task(
            task_prompt=args.task,
            context_files=args.files,
            temperature=args.temperature,
        )
        print(result)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
