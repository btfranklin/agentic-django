from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model


@pytest.fixture()
def user(db: Any) -> Any:
    User = get_user_model()
    return User.objects.create_user(username="tester", password="password")
