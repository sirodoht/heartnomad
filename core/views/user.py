import datetime
import json
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from core import models
from core.data_fetchers import (
    SerializedResourceCapacity,
)
from core.emails.messages import (
    new_booking_notify,
)
from core.forms import (
    LocationRoomForm,
    UserProfileForm,
)

from .view_helpers import _get_user_and_perms

logger = logging.getLogger(__name__)


@login_required
def user_email_settings(request, username):
    """TODO: rethink permissions here"""
    user, user_is_house_admin_somewhere = _get_user_and_perms(request, username)

    return render(
        request,
        "user_email.html",
        {
            "u": user,
            "user_is_house_admin_somewhere": user_is_house_admin_somewhere,
            "stripe_publishable_key": settings.STRIPE_PUBLISHABLE_KEY,
        },
    )


@login_required
def user_subscriptions(request, username):
    """TODO: rethink permissions here"""
    user, user_is_house_admin_somewhere = _get_user_and_perms(request, username)
    subscriptions = models.Subscription.objects.filter(user=user).order_by("start_date")

    return render(
        request,
        "user_subscriptions.html",
        {
            "u": user,
            "user_is_house_admin_somewhere": user_is_house_admin_somewhere,
            "stripe_publishable_key": settings.STRIPE_PUBLISHABLE_KEY,
            "subscriptions": subscriptions,
        },
    )


@login_required
def user_events(request, username):
    """TODO: rethink permissions here"""
    user, user_is_house_admin_somewhere = _get_user_and_perms(request, username)
    events = list(user.events_attending.all())
    events.reverse()

    return render(
        request,
        "user_events.html",
        {
            "u": user,
            "user_is_house_admin_somewhere": user_is_house_admin_somewhere,
            "stripe_publishable_key": settings.STRIPE_PUBLISHABLE_KEY,
            "events": events,
        },
    )


@login_required
def user_edit_room(request, username, room_id):
    user, user_is_house_admin_somewhere = _get_user_and_perms(request, username)

    room = models.Resource.objects.get(id=room_id)

    # make sure this user has permissions on the room
    if room not in models.Resource.objects.backed_by(user):
        return HttpResponseRedirect("/404")

    has_image = bool(room.image)
    resource_capacity = SerializedResourceCapacity(
        room, timezone.localtime(timezone.now())
    )
    room_capacity = json.dumps(resource_capacity.as_dict())
    location = room.location
    form = LocationRoomForm(instance=room)

    return render(
        request,
        "user_room_area.html",
        {
            "u": user,
            "user_is_house_admin_somewhere": user_is_house_admin_somewhere,
            "form": form,
            "room_id": room.id,
            "room_name": room.name,
            "location": location,
            "has_image": has_image,
            "room_capacity": room_capacity,
            "stripe_publishable_key": settings.STRIPE_PUBLISHABLE_KEY,
        },
    )


@login_required
def ListUsers(request):
    users = User.objects.filter(is_active=True)
    return render(request, "user_list.html", {"users": users})


@login_required
def UserDetail(request, username):
    user, user_is_house_admin_somewhere = _get_user_and_perms(request, username)

    return render(
        request,
        "user_profile.html",
        {
            "u": user,
            "user_is_house_admin_somewhere": user_is_house_admin_somewhere,
            "stripe_publishable_key": settings.STRIPE_PUBLISHABLE_KEY,
        },
    )


# ******************************************************
#           registration and login callbacks and views
# ******************************************************


def process_unsaved_booking(request):
    logger.debug("in process_unsaved_booking")
    if request.session.get("booking"):
        logger.debug("found booking")
        logger.debug(request.session["booking"])
        details = request.session.pop("booking")
        use = models.Use(
            arrive=datetime.date(
                details["arrive"]["year"],
                details["arrive"]["month"],
                details["arrive"]["day"],
            ),
            depart=datetime.date(
                details["depart"]["year"],
                details["depart"]["month"],
                details["depart"]["day"],
            ),
            location=models.Location.objects.get(id=details["location"]["id"]),
            resource=models.Resource.objects.get(id=details["resource"]["id"]),
            purpose=details["purpose"],
            arrival_time=details["arrival_time"],
            user=request.user,
        )
        use.save()
        comment = details["comments"]
        booking = models.Booking(use=use, comments=comment)
        # reset rate calls set_rate which calls generate_bill
        booking.reset_rate()
        booking.save()

        logger.debug("new booking %d saved." % booking.id)
        new_booking_notify(booking)
        # we can't just redirect here because the user doesn't get logged
        # in. so save the reservaton ID and redirect below.
        request.session["new_booking_redirect"] = {
            "booking_id": booking.id,
            "location_slug": booking.use.location.slug,
        }
    else:
        logger.debug("no booking found")
    return


def user_login(request, username=None):
    logger.debug("in user_login")
    next_page = None
    if "next" in request.GET:
        next_page = request.GET["next"]

    password = ""
    if request.POST:
        # Username is pre-set if this is part of registration flow
        if not username:
            username = request.POST["username"]
        # JKS this is a bit janky. this is because we use this view both after
        # the user registration or after the login view, which themselves use
        # slightly different forms.
        if "password" in request.POST:
            password = request.POST["password"]
        elif "password2" in request.POST:
            password = request.POST["password2"]
        if "next" in request.POST:
            next_page = request.POST["next"]

        user = authenticate(username=username, password=password)
        if user is not None:
            if user.is_active:
                login(request, user)

            process_unsaved_booking(request)
            # if there was a pending booking redirect to the booking page
            if request.session.get("new_booking_redirect"):
                booking_id = request.session["new_booking_redirect"]["booking_id"]
                location_slug = request.session["new_booking_redirect"]["location_slug"]
                request.session.pop("new_booking_redirect")
                messages.add_message(
                    request,
                    messages.INFO,
                    "Thank you! Your booking has been submitted. Please allow us up to 24 hours to respond.",
                )
                return HttpResponseRedirect(
                    reverse("booking_detail", args=(location_slug, booking_id))
                )

            # this is where they go on successful login if there is not pending booking
            if not next_page or len(next_page) == 0 or "logout" in next_page:
                next_page = "/"
            return HttpResponseRedirect(next_page)

    # redirect to the login page if there was a problem
    return render(request, "registration/login.html")


def register(request):
    booking = request.session.get("booking")
    if request.method == "POST":
        profile_form = UserProfileForm(request.POST, request.FILES)
        if profile_form.is_valid():
            user = profile_form.save()
            return user_login(request, username=user.username)
        else:
            logger.debug("profile form contained errors:")
            logger.debug(profile_form.errors)
    else:
        if request.user.is_authenticated:
            messages.info(
                request,
                'You are already logged in. Please <a href="/people/logout">log out</a> to create a new account',
            )
            return HttpResponseRedirect(
                reverse("user_detail", args=(request.user.username,))
            )
        profile_form = UserProfileForm()
    all_users = User.objects.all()
    return render(
        request,
        "registration/registration_form.html",
        {"form": profile_form, "booking": booking, "all_users": all_users},
    )


@login_required
def UserEdit(request, username):
    profile = models.UserProfile.objects.get(user__username=username)
    user = User.objects.get(username=username)
    if not (request.user.is_authenticated and request.user.id == user.id):
        messages.info(request, "You cannot edit this profile")
        return HttpResponseRedirect("/404")

    if request.method == "POST":
        profile_form = UserProfileForm(request.POST, request.FILES, instance=profile)
        if profile_form.is_valid():
            user = profile_form.save()
            messages.info(request, "Your profile has been updated.")
            return HttpResponseRedirect(f"/people/{user.username}")
        else:
            logger.debug("profile form contained errors:")
            logger.debug(profile_form.errors)
    else:
        profile_form = UserProfileForm(instance=profile)
    has_image = bool(profile.image)
    return render(
        request,
        "registration/registration_form.html",
        {"form": profile_form, "has_image": has_image, "existing_user": True},
    )


@csrf_exempt
def username_available(request):
    """AJAX request to check for existing user with the submitted username"""
    logger.debug("in username_available")
    if request.headers.get("x-requested-with") != "XMLHttpRequest":
        return HttpResponseRedirect("/404")
    username = request.POST.get("username")
    users_with_username = len(User.objects.filter(username=username))
    if users_with_username:
        logger.debug(f"username {username} is already in use")
        is_available = "false"
    else:
        logger.debug(f"username {username} is available")
        is_available = "true"
    return HttpResponse(is_available)


@csrf_exempt
def email_available(request):
    """AJAX request to check for existing user with the submitted email"""
    logger.debug("in email_available")
    if request.headers.get("x-requested-with") != "XMLHttpRequest":
        return HttpResponseRedirect("/404")
    email = request.POST.get("email").lower()
    users_with_email = len(User.objects.filter(email=email))
    if users_with_email:
        logger.debug(f"email address {email} is already in use")
        is_available = "false"
    else:
        logger.debug(f"email address {email} is available")
        is_available = "true"
    return HttpResponse(is_available)


@login_required
def UserAvatar(request, username):
    if request.method != "POST":
        return HttpResponseRedirect("/404")
    user = get_object_or_404(User, username=username)
    try:
        url = user.profile.image.url
    except Exception:
        url = "/static/img/default.jpg"
    return HttpResponse(url)
