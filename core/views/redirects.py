from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


@login_required
def old_user_bookings_redirect(request, username):
    return redirect("user_bookings", username=username, permanent=True)


@login_required
def reservation_redirect(request, location_slug, rest_of_path):
    return redirect(
        f"/locations/{location_slug}/booking/{rest_of_path}/",
        permanent=True,
    )
