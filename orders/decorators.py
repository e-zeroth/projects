# orders/decorators.py
from functools import wraps
from django.shortcuts import redirect
from django.urls import reverse
from django.contrib import messages
from .models import StaffMember  # optional – only needed if you want to attach the instance


def staff_required(view_func):
    """
    Guarantees that a staff member is logged‑in via the *code‑only* login.

    The login view stores ``request.session['staff_id']`` (and optionally
    ``request.session['staff_name']``).  If that key is missing we redirect
    the user to the staff‑login page and show a warning message.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if request.session.get("staff_id"):
            # OPTIONAL: make the StaffMember instance readily available as
            # ``request.staff`` for any view that needs more info.
            # Uncomment the line below if you want this convenience.
            # request.staff = StaffMember.objects.get(pk=request.session["staff_id"])
            return view_func(request, *args, **kwargs)

        # No staff session – send them to the login page.
        messages.warning(request, "Please enter your staff code.")
        return redirect(reverse("orders:staff_login"))

    return _wrapped_view