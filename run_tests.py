#!/usr/bin/env python3
"""
Test runner for langfuse_mcp tests.
"""
import os
import asyncio
import pytest

if __name__ == "__main__":
    # Run all tests in the tests directory
    exit_code = pytest.main(["-xvs", "tests/"])
    exit(exit_code) 