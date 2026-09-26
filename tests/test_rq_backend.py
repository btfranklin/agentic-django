from __future__ import annotations

import importlib.util
import subprocess
import sys
from textwrap import dedent

import pytest


@pytest.mark.skipif(
    importlib.util.find_spec('django_tasks_rq') is None,
    reason='Install the rq extra to test the RQ backend.',
)
def test_rq_configuration_loads_and_submits_the_package_task() -> None:
    script = dedent('''
        import os
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        os.environ['DJANGO_SETTINGS_MODULE'] = 'tests.settings'
        from django.conf import settings
        settings.INSTALLED_APPS += ['django_rq', 'django_tasks_rq']
        settings.RQ_QUEUES = {'default': {'URL': 'redis://localhost:6379/0'}}
        settings.TASKS = {'default': {
            'BACKEND': 'django_tasks_rq.RQBackend', 'QUEUES': ['default'],
        }}
        import django
        django.setup()
        from django.core.management import get_commands, load_command_class
        from django.utils import timezone
        from django_tasks_rq import Job, RQBackend
        from agentic_django.tasks import run_agent_task

        backend = run_agent_task.get_backend()
        assert isinstance(backend, RQBackend)
        assert list(backend.check()) == []
        job = SimpleNamespace(enqueued_at=timezone.now())
        queue = Mock()
        queue.create_job.return_value = job
        queue.enqueue_job.return_value = job
        with patch('django_rq.get_queue', return_value=queue) as get_queue:
            result = run_agent_task.enqueue('run-id')
        get_queue.assert_called_once_with('default', job_class=Job)
        args, kwargs = queue.create_job.call_args
        assert args == ('agentic_django.tasks.run_agent_task',)
        assert kwargs['args'] == ('run-id',)
        assert kwargs['job_id'] == result.id
        assert result.enqueued_at == job.enqueued_at

        command = load_command_class(get_commands()['rqworker'], 'rqworker')
        options = command.create_parser('manage.py', 'rqworker').parse_args(
            ['default', '--job-class', 'django_tasks_rq.Job']
        )
        assert options.job_class == 'django_tasks_rq.Job'
    ''')
    result = subprocess.run(
        [sys.executable, '-c', script], capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
