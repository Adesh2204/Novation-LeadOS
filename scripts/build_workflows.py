"""Export disabled n8n v2 workflows. Every stage calls real shared backend logic."""

import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]
STAGES = [
    ("Mock Market Search", "discovery"),
    ("Normalise", "normalise"),
    ("Entity Resolve", "resolve"),
    ("Signal Detect", "detect"),
    ("Vertical Route", "route"),
    ("RAG Opportunity Analysis", "research"),
    ("Score", "score"),
    ("Evidence Audit", "audit"),
    ("Store Opportunity", "store"),
]


def node(name, kind, version, params, x):
    return {
        "id": str(uuid5(NAMESPACE_URL, name)),
        "name": name,
        "type": kind,
        "typeVersion": version,
        "position": [x, 0],
        "parameters": params,
    }


def build(scheduled=False):
    trigger = "Schedule Trigger" if scheduled else "Manual Trigger"
    nodes = [
        node(
            trigger,
            "n8n-nodes-base.scheduleTrigger"
            if scheduled
            else "n8n-nodes-base.manualTrigger",
            1.2 if scheduled else 1,
            {"rule": {"interval": [{"field": "hours", "hoursInterval": 24}]}}
            if scheduled
            else {},
            0,
        )
    ]
    nodes.append(
        node(
            "Start Mock Run",
            "n8n-nodes-base.httpRequest",
            4.2,
            {
                "method": "POST",
                "url": "http://backend:8000/pipeline/start",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "{}",
                "options": {"timeout": 60000},
            },
            220,
        )
    )
    for i, (name, stage) in enumerate(STAGES):
        nodes.append(
            node(
                name,
                "n8n-nodes-base.httpRequest",
                4.2,
                {
                    "method": "POST",
                    "url": "=http://backend:8000/pipeline/runs/{{$json.run_id}}/"
                    + stage,
                    "options": {"timeout": 60000},
                },
                440 + i * 220,
            )
        )
    nodes.append(
        node(
            "IF Score at Least 80 and Verified",
            "n8n-nodes-base.if",
            2.2,
            {
                "conditions": {
                    "options": {
                        "caseSensitive": True,
                        "leftValue": "",
                        "typeValidation": "strict",
                        "version": 2,
                    },
                    "conditions": [
                        {
                            "id": "eligible-reviews",
                            "leftValue": "={{ $json.human_review_ids.length }}",
                            "rightValue": 0,
                            "operator": {"type": "number", "operation": "gt"},
                        }
                    ],
                    "combinator": "and",
                },
                "options": {},
            },
            2420,
        )
    )
    nodes.append(
        node(
            "Create Human Review Task",
            "n8n-nodes-base.httpRequest",
            4.2,
            {
                "method": "POST",
                "url": "=http://backend:8000/pipeline/runs/{{$json.run_id}}/review-tasks/create",
                "options": {"timeout": 60000},
            },
            2640,
        )
    )
    connections = {
        nodes[i]["name"]: {
            "main": [[{"node": nodes[i + 1]["name"], "type": "main", "index": 0}]]
        }
        for i in range(len(nodes) - 1)
    }
    connections["IF Score at Least 80 and Verified"]["main"].append([])
    workflow = {
        "id": "LeadOSMockSchedule" if scheduled else "LeadOSMockManual",
        "name": f"LeadOS Mock {'Schedule (DISABLED)' if scheduled else 'Manual'}",
        "nodes": nodes,
        "connections": connections,
        "active": False,
        "settings": {"executionOrder": "v1", "timezone": "Asia/Kolkata"},
        "pinData": {},
        "tags": [],
    }
    path = ROOT / f"workflows/mock_{'schedule' if scheduled else 'manual'}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(workflow, indent=2) + "\n")


if __name__ == "__main__":
    build()
    build(scheduled=True)
