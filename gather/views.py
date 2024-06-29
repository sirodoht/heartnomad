import datetime
import json
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.contrib.sites.models import Site
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone

from gather.emails import (
    event_approved_notification,
    event_published_notification,
    mailgun_send,
    new_event_notification,
)
from gather.forms import EventEmailTemplateForm, EventForm
from gather.models import Event, EventAdminGroup
from modernomad.core.forms import UserProfileForm
from modernomad.core.models import Location

logger = logging.getLogger(__name__)


def create_event(request, location_slug=None):
    location = get_object_or_404(Location, slug=location_slug)
    current_user = request.user
    logger.debug(f"create_event: location:{location}, user:{current_user}")

    # if the user doesn't have a proper profile, then make sure they extend it first
    logger.debug(current_user.id)
    if current_user.id is None:
        messages.add_message(
            request,
            messages.INFO,
            "We want to know who you are! Please create a profile before submitting an event.",
        )
        next_url = f"/locations/{location.slug}/events/create/"
        return HttpResponseRedirect(f"/people/register/?next={next_url}")
    elif current_user.is_authenticated and (
        (not current_user.profile.bio) or (not current_user.profile.image)
    ):
        messages.add_message(
            request,
            messages.INFO,
            "We want to know a bit more about you! Please complete your profile before submitting an event.",
        )
        return HttpResponseRedirect(f"/people/{current_user.username}/edit/")

    other_users = User.objects.exclude(id=current_user.id)
    # get a list of users so that those creating an event can select from
    # existing users as event co-organizers
    user_list = [u.username for u in other_users]
    location_admin_group = EventAdminGroup.objects.get(location=location)
    is_event_admin = current_user in location_admin_group.users.all()

    if request.method == "POST":
        logger.debug(f"create_event: POST={request.POST}")
        form = EventForm(request.POST, request.FILES)
        if form.is_valid():
            event = form.save(commit=False)
            event.creator = current_user
            # associate this event with a specific location and admin group
            event.location = location
            event.admin = location_admin_group
            event.save()
            co_organizers = form.cleaned_data.get("co_organizers")
            # always make sure current user is an organizer
            event.organizers.add(current_user)
            event.organizers.add(*co_organizers)
            # organizers should be attendees by default, too.
            event.attendees.add(current_user)
            event.save()

            new_event_notification(event, location)

            messages.add_message(request, messages.INFO, "The event has been created.")
            return HttpResponseRedirect(
                reverse(
                    "gather_view_event",
                    args=(event.location.slug, event.id, event.slug),
                )
            )
        else:
            logger.debug("form error")
            logger.debug(form)
            logger.debug(form.errors)

    else:
        form = EventForm()
    return render(
        request,
        "gather_event_create.html",
        {
            "form": form,
            "current_user": current_user,
            "user_list": json.dumps(user_list),
            "is_event_admin": is_event_admin,
            "location": location,
        },
    )


@login_required
def edit_event(request, event_id, event_slug, location_slug=None):
    location = get_object_or_404(Location, slug=location_slug)
    current_user = request.user
    other_users = User.objects.exclude(id=current_user.id)
    user_list = [u.username for u in other_users]
    event = Event.objects.get(id=event_id)
    if not (
        request.user.is_authenticated
        and (
            request.user in event.organizers.all()
            or request.user in event.location.house_admins.all()
        )
    ):
        return HttpResponseRedirect("/")

    if request.method == "POST":
        form = EventForm(request.POST, request.FILES, instance=event)
        if form.is_valid():
            event = form.save(commit=False)
            co_organizers = form.cleaned_data.get("co_organizers")
            logger.debug(co_organizers)
            event.organizers.add(*co_organizers)
            event.save()
            messages.add_message(request, messages.INFO, "The event has been saved.")
            return HttpResponseRedirect(
                reverse(
                    "gather_view_event",
                    args=(event.location.slug, event.id, event.slug),
                )
            )
        else:
            logger.debug("form error")
            logger.debug(form.errors)

    else:
        # format the organizers as a string for use with the autocomplete field
        other_organizers = event.organizers.exclude(id=current_user.id)
        other_organizer_usernames = [u.username for u in other_organizers]
        other_organizer_usernames_string = ",".join(other_organizer_usernames)
        logger.debug(event.organizers.all())
        form = EventForm(
            instance=event, initial={"co_organizers": other_organizer_usernames_string}
        )
    return render(
        request,
        "gather_event_edit.html",
        {
            "form": form,
            "current_user": current_user,
            "event_id": event_id,
            "event_slug": event_slug,
            "user_list": json.dumps(user_list),
            "location": location,
        },
    )


def view_event(request, event_id, event_slug, location_slug=None):
    # XXX should we double check the associated location here? currently the
    # assumption is that if an event is being viewed under a specific location
    # that that will be reflected in the URL path.
    try:
        event = Event.objects.get(id=event_id)
    except Exception:
        logger.debug("event not found")
        return HttpResponseRedirect("/404")

    location = get_object_or_404(Location, slug=location_slug)
    # if the slug has changed, redirect the viewer to the correct url (one
    # where the url matches the current slug)
    if event.slug != event_slug:
        logger.debug("event slug has changed")
        # there's some tomfoolery here since we don't know for sure if the app
        # is being used in a project that specifies the location as part of the
        # url. probably a better way to do this...
        return HttpResponseRedirect(
            reverse(
                "gather_view_event", args=(event.location.slug, event.id, event.slug)
            )
        )

    # is the event in the past?
    today = timezone.now()
    logger.debug(event.end)
    past = event.end < today

    # set up for those without accounts to RSVP
    if request.user.is_authenticated:
        current_user = request.user
        new_user_form = None
        login_form = None
        location_event_admin = EventAdminGroup.objects.get(location=location)
        if (
            request.user in location_event_admin.users.all()
            or request.user in location.house_admins.all()
        ):
            user_is_event_admin = True
        else:
            user_is_event_admin = False
    else:
        current_user = None
        new_user_form = UserProfileForm()
        login_form = AuthenticationForm()
        user_is_event_admin = False

    # this is counter-intuitive - private events are viewable to those who have
    # the link. so private events are indeed shown to anyone (once they are
    # approved). and we dont have a way of knowing what the previous status of
    # canceled events was (!), so we also let this go through but then suppress
    # the event details and a cancelation notice on the event page.
    if (
        (event.status == "live" and event.visibility == Event.PRIVATE)
        or event.is_viewable(current_user)
        or event.status == "canceled"
    ):
        if current_user and current_user in event.organizers.get_queryset():
            user_is_organizer = True
        else:
            user_is_organizer = False
        num_attendees = len(event.attendees.all())
        # only meaningful if event.limit > 0
        spots_remaining = event.limit - num_attendees
        event_email = "event%d@%s.%s" % (
            event.id,
            event.location.slug,
            settings.LIST_DOMAIN,
        )
        domain = Site.objects.get_current().domain
        formatted_title = event.title.replace(" ", "+")
        formatted_dates = (
            event.start.strftime("%Y%m%dT%H%M00Z")
            + "/"
            + event.end.strftime("%Y%m%dT%H%M00Z")
        )  # "20140127T224000Z/20140320T221500Z"
        detail_url = (
            "https://"
            + domain
            + reverse(
                "gather_view_event", args=(event.location.slug, event.id, event.slug)
            )
        )
        formatted_location = event.where.replace(" ", "+")
        event_google_cal_link = (
            f"""https://www.google.com/calendar/render?action=TEMPLATE&text={formatted_title}&dates={formatted_dates}&details=For+details%3a+{detail_url}&location={formatted_location}&sf=true&output=xml"""
        )
        if user_is_event_admin or user_is_organizer:
            email_form = EventEmailTemplateForm(event, location)
        else:
            email_form = None
        return render(
            request,
            "gather_event_view.html",
            {
                "event": event,
                "current_user": current_user,
                "event_google_cal_link": event_google_cal_link,
                "user_is_organizer": user_is_organizer,
                "new_user_form": new_user_form,
                "event_email": event_email,
                "domain": domain,
                "login_form": login_form,
                "spots_remaining": spots_remaining,
                "user_is_event_admin": user_is_event_admin,
                "email_form": email_form,
                "num_attendees": num_attendees,
                "in_the_past": past,
                "endorsements": event.endorsements.all(),
                "location": location,
            },
        )

    elif not current_user:
        # if the user is not logged in and this is not a public event, have them login and try again
        messages.add_message(
            request, messages.INFO, "Please log in to view this event."
        )
        next_url = reverse(
            "gather_view_event", args=(event.location.slug, event.id, event.slug)
        )
        return HttpResponseRedirect(f"/people/login/?next={next_url}")
    else:
        # the user is logged in but the event is not viewable to them based on their status
        messages.add_message(
            request,
            messages.INFO,
            "Oops! You do not have permission to view this event.",
        )
        return HttpResponseRedirect(f"/locations/{location.slug}")


def upcoming_events_all_locations(request):
    """if a site supports multiple locations this page can be used to show
    events across all locations."""
    current_user = request.user if request.user.is_authenticated else None
    datetime.datetime.today()
    all_upcoming = Event.objects.upcoming(current_user=request.user)
    culled_upcoming = []
    for event in all_upcoming:
        if event.is_viewable(current_user):
            culled_upcoming.append(event)

    # show 10 events per page
    paged_upcoming = Paginator(culled_upcoming, 10)
    page = request.GET.get("page")
    try:
        events = paged_upcoming.page(page)
    except PageNotAnInteger:
        # If page is not an integer, deliver first page.
        events = paged_upcoming.page(1)
    except EmptyPage:
        # If page is out of range (e.g. 9999), deliver last page of results.
        events = paged_upcoming.page(paged_upcoming.num_pages)

    return render(
        request,
        "gather_events_list.html",
        {
            "events": events,
            "current_user": current_user,
            "page_title": "Upcoming Events",
        },
    )


def upcoming_events(request, location_slug=None):
    """upcoming events limited to a specific location (either the one
    specified or the default single location)."""
    current_user = request.user if request.user.is_authenticated else None
    datetime.datetime.today()
    location = get_object_or_404(Location, slug=location_slug)
    all_upcoming = Event.objects.upcoming(current_user=request.user, location=location)
    culled_upcoming = []
    for event in all_upcoming:
        if event.is_viewable(current_user):
            culled_upcoming.append(event)

    # show 10 events per page
    paged_upcoming = Paginator(culled_upcoming, 10)
    page = request.GET.get("page")
    try:
        events = paged_upcoming.page(page)
    except PageNotAnInteger:
        # If page is not an integer, deliver first page.
        events = paged_upcoming.page(1)
    except EmptyPage:
        # If page is out of range (e.g. 9999), deliver last page of results.
        events = paged_upcoming.page(paged_upcoming.num_pages)

    return render(
        request,
        "gather_events_list.html",
        {
            "events": events,
            "current_user": current_user,
            "page_title": "Upcoming Events",
            "location": location,
        },
    )


def user_events(request, username):
    user = User.objects.get(username=username)
    today = timezone.now()
    events_organized_upcoming = (
        user.events_organized.all().filter(end__gte=today).order_by("start")
    )
    events_attended_upcoming = (
        user.events_attending.all().filter(end__gte=today).order_by("start")
    )
    events_organized_past = (
        user.events_organized.all().filter(end__lt=today).order_by("-start")
    )
    events_attended_past = (
        user.events_attending.all().filter(end__lt=today).order_by("-start")
    )
    return render(
        request,
        "gather_user_events_list.html",
        {
            "events_organized_upcoming": events_organized_upcoming,
            "events_attended_upcoming": events_attended_upcoming,
            "events_organized_past": events_organized_past,
            "events_attended_past": events_attended_past,
            "current_user": user,
            "page_title": "Upcoming Events",
        },
    )


@login_required
def needs_review(request, location_slug=None):
    location = get_object_or_404(Location, slug=location_slug)
    # if user is not an event admin at this location, redirect
    location_admin_group = EventAdminGroup.objects.get(location=location)
    if not request.user.is_authenticated or (
        request.user not in location_admin_group.users.all()
    ):
        return HttpResponseRedirect("/")

    # upcoming events that are not yet live
    today = timezone.now()
    events_pending = (
        Event.objects.filter(status=Event.PENDING)
        .filter(end__gte=today)
        .filter(location=location)
    )
    events_under_discussion = (
        Event.objects.filter(status=Event.FEEDBACK)
        .filter(end__gte=today)
        .filter(location=location)
    )
    return render(
        request,
        "gather_events_admin_needing_review.html",
        {
            "events_pending": events_pending,
            "events_under_discussion": events_under_discussion,
            "location": location,
        },
    )


def past_events(request, location_slug=None):
    location = get_object_or_404(Location, slug=location_slug)
    current_user = request.user if request.user.is_authenticated else None
    today = datetime.datetime.today()
    # most recent first
    all_past = (
        Event.objects.filter(start__lt=today)
        .order_by("-start")
        .filter(location=location)
    )
    culled_past = []
    for event in all_past:
        if event.is_viewable(current_user):
            culled_past.append(event)
    # show 10 events per page
    paged_past = Paginator(culled_past, 10)
    page = request.GET.get("page")
    try:
        events = paged_past.page(page)
    except PageNotAnInteger:
        # If page is not an integer, deliver first page.
        events = paged_past.page(1)
    except EmptyPage:
        # If page is out of range (e.g. 9999), deliver last page of results.
        events = paged_past.page(paged_past.num_pages)

    return render(
        request,
        "gather_events_list.html",
        {
            "events": events,
            "user": current_user,
            "page_title": "Past Events",
            "location": location,
        },
    )


def email_preferences(request, username, location_slug=None):
    if request.method != "POST":
        return HttpResponseRedirect("/404")

    u = User.objects.get(username=username)
    notifications = u.event_notifications
    if request.POST.get("event_reminders") == "on":
        notifications.reminders = True
    else:
        notifications.reminders = False

    for location in Location.objects.all():
        # update preferences on new receiving weekly updates
        weekly_updates = request.POST.get("weekly_" + location.slug)
        if (
            weekly_updates == "on"
            and location not in notifications.location_weekly.all()
        ):
            notifications.location_weekly.add(location)
        if weekly_updates is None and location in notifications.location_weekly.all():
            notifications.location_weekly.remove(location)

        # update preferences on new event notifications
        publish_notify = request.POST.get("publish_" + location.slug)
        if (
            publish_notify == "on"
            and location not in notifications.location_publish.all()
        ):
            notifications.location_publish.add(location)
        if publish_notify is None and location in notifications.location_publish.all():
            notifications.location_publish.remove(location)

    notifications.save()
    logger.debug(notifications.location_weekly.all())
    messages.add_message(request, messages.INFO, "Your preferences have been updated.")
    return HttpResponseRedirect(f"/people/{u.username}/")


def event_approve(request, event_id, event_slug, location_slug=None):
    location = get_object_or_404(Location, slug=location_slug)
    location_event_admin = EventAdminGroup.objects.get(location=location)
    if request.user not in location_event_admin.users.all():
        return HttpResponseRedirect("/404")
    event = Event.objects.get(id=event_id)
    if not (
        request.user.is_authenticated
        and (
            request.user in event.organizers.all()
            or request.user in event.location.house_admins.all()
        )
    ):
        return HttpResponseRedirect("/")

    event.status = Event.READY
    event.save()
    if request.user in location_event_admin.users.all():
        pass
    else:
        pass
    request.user in event.organizers.all()

    msg_success = "Success! The event has been approved."
    messages.add_message(request, messages.INFO, msg_success)

    # notify the event organizers and admins
    event_approved_notification(event, location)

    return HttpResponseRedirect(
        reverse("gather_view_event", args=(location.slug, event.id, event.slug))
    )


@login_required
def event_publish(request, event_id, event_slug, location_slug=None):
    location = get_object_or_404(Location, slug=location_slug)
    location_event_admin = EventAdminGroup.objects.get(location=location)

    event = Event.objects.get(id=event_id)
    if (
        request.user not in location_event_admin.users.all()
        and request.user not in event.location.house_admins.all()
        and request.user not in event.organizers.all()
    ):
        logger.debug("user does not have correct permissions to publish event")
        return HttpResponseRedirect("/404")

    logger.debug(request.POST)
    event.status = Event.LIVE
    event.save()
    if request.user in location_event_admin.users.all():
        pass
    else:
        pass
    request.user in event.organizers.all()
    msg_success = "Success! The event has been published."
    messages.add_message(request, messages.INFO, msg_success)

    # notify the event organizers and admins
    event_published_notification(event, location)

    return HttpResponseRedirect(
        reverse("gather_view_event", args=(location.slug, event.id, event.slug))
    )


def event_cancel(request, event_id, event_slug, location_slug=None):
    location = get_object_or_404(Location, slug=location_slug)
    location_event_admin = EventAdminGroup.objects.get(location=location)
    if request.user not in location_event_admin.users.all():
        return HttpResponseRedirect("/404")
    event = Event.objects.get(id=event_id)
    if not (
        request.user.is_authenticated
        and (
            request.user in event.organizers.all()
            or request.user in event.location.house_admins.all()
        )
    ):
        return HttpResponseRedirect("/")

    event.status = Event.CANCELED
    event.save()
    if request.user in location_event_admin.users.all():
        pass
    else:
        pass
    request.user in event.organizers.all()
    msg = "The event has been canceled."
    messages.add_message(request, messages.INFO, msg)

    return HttpResponseRedirect(
        reverse("gather_view_event", args=(location.slug, event.id, event.slug))
    )


def event_send_mail(request, event_id, event_slug, location_slug=None):
    if request.method != "POST":
        return HttpResponseRedirect("/404")

    get_object_or_404(Location, slug=location_slug)
    subject = request.POST.get("subject")
    recipients = [
        request.POST.get("recipient"),
    ]
    body = request.POST.get("body") + "\n\n" + request.POST.get("footer")

    # the from address is set to the organizer's email so people can respond
    # directly with questions if needed.
    mailgun_data = {
        "from": request.user.email,
        "to": request.user.email,
        "bcc": recipients,
        "subject": subject,
        "text": body,
    }

    resp = mailgun_send(mailgun_data)

    logger.debug(resp)
    if resp.status_code == 200:
        messages.add_message(request, messages.INFO, "Your message was sent.")
    else:
        messages.add_message(
            request,
            messages.INFO,
            "There was a connection problem and your message was not sent.",
        )
    return HttpResponseRedirect(
        reverse("gather_view_event", args=(location_slug, event_id, event_slug))
    )


############################################
########### AJAX REQUESTS ##################


@login_required
def rsvp_event(request, event_id, event_slug, location_slug=None):
    location = get_object_or_404(Location, slug=location_slug)
    if request.method != "POST":
        return HttpResponseRedirect("/404")

    user_id_str = request.POST.get("user_id")
    event = Event.objects.get(id=event_id)
    user = User.objects.get(pk=int(user_id_str))
    user_is_organizer = user in event.organizers.all()
    if user not in event.attendees.all():
        event.attendees.add(user)
        event.save()
        num_attendees = event.attendees.count()
        spots_remaining = event.limit - num_attendees
        return render(
            request,
            "snippets/rsvp_info.html",
            {
                "num_attendees": num_attendees,
                "spots_remaining": spots_remaining,
                "event": event,
                "current_user": user,
                "user_is_organizer": user_is_organizer,
                "location": location,
            },
        )
    else:
        logger.debug("user was aready attending")
    return HttpResponse(status=500)


@login_required
def rsvp_cancel(request, event_id, event_slug, location_slug=None):
    location = get_object_or_404(Location, slug=location_slug)
    if request.method != "POST":
        return HttpResponseRedirect("/404")

    user_id_str = request.POST.get("user_id")

    logger.debug("event slug: %s", event_slug)
    event = Event.objects.get(id=event_id)
    user = User.objects.get(pk=int(user_id_str))
    user_is_organizer = user in event.organizers.all()

    if user in event.attendees.all():
        event.attendees.remove(user)
        event.save()
        num_attendees = event.attendees.count()
        spots_remaining = event.limit - num_attendees
        return render(
            request,
            "snippets/rsvp_info.html",
            {
                "num_attendees": num_attendees,
                "spots_remaining": spots_remaining,
                "event": event,
                "current_user": user,
                "user_is_organizer": user_is_organizer,
                "location": location,
            },
        )

    logger.debug("user was not attending")
    return HttpResponse(status=500)


def rsvp_new_user(request, event_id, event_slug, location_slug=None):
    location = get_object_or_404(Location, slug=location_slug)
    if request.method != "POST":
        return HttpResponseRedirect("/404")

    logger.debug("in rsvp_new_user")
    logger.debug(request.POST)
    # get email signup info and remove from form, since we tacked this field on
    # but it's not part of the user model.
    weekly_updates = request.POST.get("weekly-email-notifications")
    notify_new = request.POST.get("new-event-notifications")
    weekly_updates = weekly_updates == "on"
    logger.debug("weekly updates?")
    logger.debug(weekly_updates)
    notify_new = notify_new == "on"

    # Create new user but simplify the process
    form = UserProfileForm(request.POST)
    form.fields["city"].required = False
    form.fields["referral"].required = False
    form.fields["image"].required = False
    form.fields["discussion"].required = False
    form.fields["sharing"].required = False
    form.fields["projects"].required = False
    logger.debug(form)
    if form.is_valid():
        new_user = form.save()
        new_user.save()
        notifications = new_user.event_notifications
        if weekly_updates:
            # since the signup was related to a specific location we assume
            # they wanted weekly emails about the same location
            notifications.location_weekly.add(location)
        if notify_new:
            # since the signup was related to a specific location we assume
            # they wanted weekly emails about the same location
            notifications.location_publish.add(location)
        notifications.save()

        password = request.POST.get("password1")
        new_user = authenticate(username=new_user.username, password=password)
        login(request, new_user)
        # RSVP new user to the event
        event = Event.objects.get(id=event_id)
        event.attendees.add(new_user)
        logger.debug(event.attendees.all())
        event.save()
        messages.add_message(
            request,
            messages.INFO,
            "Thanks! Your account has been created. Check your email for login info and how to update your preferences.",
        )
        return HttpResponse(status=200)
    else:
        errors = json.dumps({"errors": form.errors})
        return HttpResponse(json.dumps(errors))

    return HttpResponse(status=500)


def endorse(request, event_id, event_slug, location_slug=None):
    location = get_object_or_404(Location, slug=location_slug)
    if request.method != "POST":
        return HttpResponseRedirect("/404")

    event = Event.objects.get(id=event_id)

    logger.debug(request.POST)
    endorser = request.user
    event.endorsements.add(endorser)
    event.save()
    endorsements = event.endorsements.all()
    return render(
        request,
        "snippets/endorsements.html",
        {
            "endorsements": endorsements,
            "current_user": request.user,
            "location": location,
            "event": event,
        },
    )
