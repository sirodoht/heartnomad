from django.contrib import messages
from django.contrib.auth.models import User
from django.http import HttpResponseRedirect

from core import models


def get_user_and_perms(request, username):
    try:
        user = User.objects.get(username=username)
    except Exception:
        messages.add_message(
            request, messages.INFO, "There is no user with that username."
        )
        return HttpResponseRedirect("/404")

    user_is_house_admin_somewhere = False
    for location in models.Location.objects.filter(visibility="public"):
        if request.user in location.house_admins.all():
            user_is_house_admin_somewhere = True
            break
    return user, user_is_house_admin_somewhere


def has_active_membership(user):
    """
    Check if user has an active membership.
    """
    membership_list = models.Membership.objects.filter(user=user)
    return any(membership.is_active() for membership in membership_list)
