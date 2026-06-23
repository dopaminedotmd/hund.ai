"""Tests for delegate_task tool."""
import pytest
from hund.tools.delegate_task import run_delegation


def test_too_many_tasks_rejected():
    """Max 3 tasks per delegation."""
    result = run_delegation({"tasks": [{"goal": "x"}] * 5})
    assert "error" in result
    assert "max 3" in result.lower()


def test_empty_tasks_rejected():
    """Om tasks saknas eller är tom, returnera felmeddelande."""
    result1 = run_delegation({})
    assert "error" in result1
    
    result2 = run_delegation({"tasks": []})
    assert "error" in result2
    assert "tom" in result2.lower()
