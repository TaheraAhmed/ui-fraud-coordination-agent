"""Pytest configuration and shared fixtures.

This file is automatically loaded by pytest. We use it to ensure the .env
file is loaded before any tests run.
"""

from dotenv import load_dotenv

load_dotenv()