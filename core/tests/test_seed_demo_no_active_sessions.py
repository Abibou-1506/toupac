"""Le seed ne doit laisser aucune session ouverte — sinon l'app contrôleur est bloquée."""
from io import StringIO

import pytest
from django.core.management import call_command

from voyage.models import ControlSession


@pytest.mark.django_db
def test_the_seed_leaves_no_open_control_session():
    call_command("seed_demo", "--quiet", stdout=StringIO())
    open_sessions = ControlSession.objects.filter(closed_at__isnull=True)
    assert not open_sessions.exists(), (
        f"{open_sessions.count()} session(s) ouverte(s) laissée(s) par le seed — "
        f"un contrôleur réel ne pourra pas ouvrir la sienne."
    )
