import datetime
import logging

from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.sites.models import Site
from django.db.models import Q
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from stripe.error import CardError

from bank.models import Currency, Entry, Transaction
from modernomad.core import payment_gateway
from modernomad.core.decorators import house_admin_required
from modernomad.core.emails.messages import (
    new_booking_notify,
    send_booking_receipt,
)
from modernomad.core.forms import (
    AdminBookingForm,
    BookingEmailTemplateForm,
)
from modernomad.core.models import *
from modernomad.core.tasks import guest_welcome

logger = logging.getLogger(__name__)


# ******************************************************
#           booking management views
# ******************************************************
@house_admin_required
def BookingManageList(request, location_slug):
    if request.method == "POST":
        booking_id = request.POST.get("booking_id")
        booking = get_object_or_404(Booking, id=booking_id)
        return HttpResponseRedirect(
            reverse("booking_manage", args=(booking.use.location.slug, booking.id))
        )

    location = get_object_or_404(Location, slug=location_slug)

    show_all = False
    if "show_all" in request.GET and request.GET.get("show_all") == "True":
        show_all = True

    bookings = (
        Booking.objects.filter(use__location=location)
        .order_by("-id")
        .select_related("use", "use__resource", "use__user", "bill")
        # this makes is is_paid() efficient
        .prefetch_related("bill__line_items", "bill__line_items__fee", "bill__payments")
    )

    pending = bookings.filter(use__status="pending")
    approved = bookings.filter(use__status="approved")
    confirmed = bookings.filter(use__status="confirmed")
    canceled = (
        bookings.exclude(use__status="confirmed")
        .exclude(use__status="approved")
        .exclude(use__status="pending")
    )

    if not show_all:
        today = timezone.localtime(timezone.now())
        confirmed = confirmed.filter(use__depart__gt=today)
        canceled = canceled.filter(use__depart__gt=today)
    owing = Use.objects.confirmed_but_unpaid(location=location)

    return render(
        request,
        "booking_list.html",
        {
            "pending": pending,
            "approved": approved,
            "confirmed": confirmed,
            "canceled": canceled,
            "owing": owing,
            "location": location,
        },
    )


@house_admin_required
def BookingToggleComp(request, location_slug, booking_id):
    if request.method != "POST":
        return HttpResponseRedirect("/404")
    location = get_object_or_404(Location, slug=location_slug)
    booking = Booking.objects.get(pk=booking_id)
    if not booking.is_comped():
        # Let these nice people stay here for free
        booking.comp()
    else:
        # Put the rate back to the default rate
        booking.reset_rate()
        # if confirmed set status back to APPROVED
        if booking.is_confirmed():
            booking.approve()
    return HttpResponseRedirect(
        reverse("booking_manage", args=(location.slug, booking_id))
    )


@house_admin_required
def BookingManageCreate(request, location_slug):
    username = ""
    if request.method == "POST":
        location = get_object_or_404(Location, slug=location_slug)

        notify = request.POST.get("email_announce")
        logger.debug("notify was set to:")
        logger.debug(notify)

        try:
            username = request.POST.get("username")
            the_user = User.objects.get(username=username)
        except:
            messages.add_message(
                request,
                messages.INFO,
                "There is no user with the username %s" % username,
            )
            return HttpResponseRedirect(
                reverse("booking_manage_create", args=(location.slug,))
            )

        form = AdminBookingForm(request.POST)
        if form.is_valid():
            use = form.save(commit=False)
            use.location = location
            use.user = the_user
            if use.suggest_drft():
                use.accounted_by = Use.DRFT
                use.save()
            use.status = request.POST.get("status")
            use.save()
            # Make sure the rate is set and then generate a bill
            booking = Booking(use=use)
            booking.reset_rate()
            if notify:
                new_booking_notify(booking)

            messages.add_message(
                request,
                messages.INFO,
                "The booking for %s %s was created."
                % (use.user.first_name, use.user.last_name),
            )
            return HttpResponseRedirect(
                reverse("booking_manage", args=(location.slug, booking.id))
            )
        else:
            logger.debug("the form had errors")
            logger.debug(form.errors)
    else:
        form = AdminBookingForm()
        username = request.GET.get("username", "")
    all_users = User.objects.all().order_by("username")
    return render(
        request,
        "booking_manage_create.html",
        {
            "all_users": all_users,
            "booking_statuses": Booking.BOOKING_STATUSES,
            "username": username,
        },
    )


@house_admin_required
def BookingManage(request, location_slug, booking_id):
    location = get_object_or_404(Location, slug=location_slug)
    booking = get_object_or_404(Booking, id=booking_id)
    user = User.objects.get(username=booking.use.user.username)
    other_bookings = (
        Booking.objects.filter(use__user=user)
        .exclude(use__status="canceled")
        .exclude(id=booking_id)
    )
    past_bookings = []
    upcoming_bookings = []
    for b in other_bookings:
        if b.use.arrive >= datetime.date.today():
            upcoming_bookings.append(b)
        else:
            past_bookings.append(b)
    domain = Site.objects.get_current().domain
    emails = EmailTemplate.objects.filter(context="booking").filter(
        Q(shared=True) | Q(creator=request.user)
    )
    email_forms = []
    email_templates_by_name = []
    for email_template in emails:
        form = BookingEmailTemplateForm(email_template, booking, location)
        email_forms.append(form)
        email_templates_by_name.append(email_template.name)

    capacity = location.capacity(booking.use.arrive, booking.use.depart)
    free = location.rooms_free(booking.use.arrive, booking.use.depart)
    date_list = date_range_to_list(booking.use.arrive, booking.use.depart)
    if booking.use.resource in free:
        room_has_capacity = True
    else:
        room_has_capacity = False

    # Pull all the booking notes for this person
    if "note" in request.POST:
        note = request.POST["note"]
        if note:
            UseNote.objects.create(use=booking.use, created_by=request.user, note=note)
            # The Right Thing is to do an HttpResponseRedirect after a form
            # submission, which clears the POST request data (even though we
            # are redirecting to the same view)
            return HttpResponseRedirect(
                reverse("booking_manage", args=(location_slug, booking_id))
            )
    use_notes = UseNote.objects.filter(use=booking.use)

    # Pull all the user notes for this person
    if "user_note" in request.POST:
        note = request.POST["user_note"]
        if note:
            UserNote.objects.create(user=user, created_by=request.user, note=note)
            # The Right Thing is to do an HttpResponseRedirect after a form submission
            return HttpResponseRedirect(
                reverse("booking_manage", args=(location_slug, booking_id))
            )
    user_notes = UserNote.objects.filter(user=user)

    user_drft_balance = user.profile.drft_spending_balance()

    return render(
        request,
        "booking_manage.html",
        {
            "r": booking,
            "past_bookings": past_bookings,
            "upcoming_bookings": upcoming_bookings,
            "user_notes": user_notes,
            "use_notes": use_notes,
            "email_forms": email_forms,
            "use_statuses": Use.USE_STATUSES,
            "email_templates_by_name": email_templates_by_name,
            "days_before_welcome_email": location.welcome_email_days_ahead,
            "room_has_capacity": room_has_capacity,
            "avail": capacity,
            "dates": date_list,
            "domain": domain,
            "location": location,
            "user_drft_balance": user_drft_balance,
        },
    )


@house_admin_required
def BookingManagePayWithDrft(request, location_slug, booking_id):
    # check that request.user is an admin at the house in question
    location = get_object_or_404(Location, slug=location_slug)
    booking = Booking.objects.get(id=booking_id)
    use = booking.use
    requested_nights = use.total_nights()

    if request.user not in location.house_admins.all():
        messages.add_message(request, messages.INFO, "Request not allowed")
        return HttpResponseRedirect("/404")

    drft = Currency.objects.get(name="DRFT")
    user_drft_account = use.user.profile.primary_drft_account()
    user_drft_balance = use.user.profile.drft_spending_balance()
    room_drft_account = booking.use.resource.backing.drft_account

    if not (user_drft_balance >= requested_nights):
        messages.add_message(request, messages.INFO, "Oops. Insufficient Balance")
    elif not (
        use.resource.backing and use.resource.drftable_between(use.arrive, use.depart)
    ):
        messages.add_message(request, messages.INFO, "Oops. Room does not accept DRFT")
    elif not (use.resource.available_between(use.arrive, use.depart)):
        messages.add_message(
            request, messages.INFO, "This room appears to be full or unavailable"
        )
    else:
        t = Transaction.objects.create(
            reason="use %d" % booking.use.id,
            approver=request.user,
        )
        Entry.objects.create(
            account=user_drft_account, amount=-requested_nights, transaction=t
        )
        Entry.objects.create(
            account=room_drft_account, amount=requested_nights, transaction=t
        )

        if t.valid:
            # this is a hack because ideally we don't even WANT a booking
            # object for DRFT uses. we'll get there...
            booking.comp()
            booking.confirm()
            booking.use.accounted_by = Use.DRFT
            booking.use.save()
            UseTransaction.objects.create(use=booking.use, transaction=t)
            days_until_arrival = (booking.use.arrive - datetime.date.today()).days
            if days_until_arrival <= location.welcome_email_days_ahead:
                try:
                    guest_welcome(booking.use)
                except:
                    messages.add_message(
                        request,
                        messages.INFO,
                        "Could not connect to MailGun to send welcome email. Please try again manually.",
                    )
        else:
            messages.add_message(
                request,
                messages.INFO,
                "Hmm, something went wrong. Please check with an admin",
            )

    return HttpResponseRedirect(
        reverse("booking_manage", args=(location_slug, booking_id))
    )


@house_admin_required
def BookingManageAction(request, location_slug, booking_id):
    if request.method != "POST":
        return HttpResponseRedirect("/404")

    location = get_object_or_404(Location, slug=location_slug)
    booking = Booking.objects.get(id=booking_id)
    booking_action = request.POST.get("booking-action")
    logger.debug("booking action")
    logger.debug(booking_action)

    if booking_action == "set-tentative":
        booking.approve()
    elif booking_action == "set-confirm":
        booking.confirm()
        days_until_arrival = (booking.use.arrive - datetime.date.today()).days
        if days_until_arrival <= location.welcome_email_days_ahead:
            guest_welcome(booking.use)
    elif booking_action == "set-comp":
        booking.comp()
    elif booking_action == "res-charge-card":
        try:
            payment_gateway.charge_booking(booking)
            booking.confirm()
            send_booking_receipt(booking)
            days_until_arrival = (booking.use.arrive - datetime.date.today()).days
            if days_until_arrival <= location.welcome_email_days_ahead:
                guest_welcome(booking.use)
        except CardError:
            # raise Booking.ResActionError(e)
            # messages.add_message(request, messages.INFO, "There was an error: %s" % e)
            # status_area_html = render(request, "snippets/res_status_area.html", {"r": booking, 'location': location, 'error': True})
            return HttpResponse(status=500)
    else:
        raise Booking.ResActionError("Unrecognized action.")

    messages.add_message(request, messages.INFO, "Your action has been registered!")
    status_area_html = render(
        request,
        "snippets/res_status_area.html",
        {"r": booking, "location": location, "error": False},
    )
    return status_area_html


@house_admin_required
def BookingManageEdit(request, location_slug, booking_id):
    logger.debug("BookingManageEdit")
    location = get_object_or_404(Location, slug=location_slug)
    booking = Booking.objects.get(id=booking_id)
    logger.debug(request.POST)
    if "username" in request.POST:
        try:
            new_user = User.objects.get(username=request.POST.get("username"))
            booking.use.user = new_user
            booking.use.save()
            messages.add_message(request, messages.INFO, "User changed.")
        except:
            messages.add_message(request, messages.INFO, "Invalid user given!")
    elif "arrive" in request.POST:
        try:
            arrive = datetime.datetime.strptime(request.POST.get("arrive"), "%Y-%m-%d")
            depart = datetime.datetime.strptime(request.POST.get("depart"), "%Y-%m-%d")
            if arrive >= depart:
                messages.add_message(
                    request,
                    messages.INFO,
                    "Arrival must be at least 1 day before Departure.",
                )
            else:
                booking.use.arrive = arrive
                booking.use.depart = depart
                booking.use.save()
                booking.generate_bill()
                messages.add_message(request, messages.INFO, "Dates changed.")
        except:
            messages.add_message(request, messages.INFO, "Invalid dates given!")

    elif "status" in request.POST:
        try:
            status = request.POST.get("status")
            booking.use.status = status
            booking.use.save()
            if status == "confirmed":
                messages.add_message(
                    request,
                    messages.INFO,
                    "Status changed. You must manually send a confirmation email if desired.",
                )
            else:
                messages.add_message(request, messages.INFO, "Status changed.")
        except:
            messages.add_message(request, messages.INFO, "Invalid room given!")
    elif "room_id" in request.POST:
        try:
            new_room = Resource.objects.get(pk=request.POST.get("room_id"))
            booking.use.resource = new_room
            booking.use.save()
            booking.reset_rate()
            messages.add_message(request, messages.INFO, "Room changed.")
        except:
            messages.add_message(request, messages.INFO, "Invalid room given!")
    elif "rate" in request.POST:
        rate = request.POST.get("rate")
        if Decimal(rate) >= Decimal(0.0) and rate != booking.get_rate():
            booking.set_rate(rate)
            messages.add_message(request, messages.INFO, "Rate changed.")
        else:
            messages.add_message(
                request, messages.ERROR, "Room rate must be a positive number"
            )

    return HttpResponseRedirect(
        reverse("booking_manage", args=(location_slug, booking_id))
    )


@house_admin_required
def BookingSendReceipt(request, location_slug, booking_id):
    if request.method != "POST":
        return HttpResponseRedirect("/404")
    location = get_object_or_404(Location, slug=location_slug)
    booking = Booking.objects.get(id=booking_id)
    if booking.is_paid():
        status = send_booking_receipt(booking)
        if status is not False:
            messages.add_message(request, messages.INFO, "The receipt was sent.")
        else:
            messages.add_message(
                request,
                messages.INFO,
                "Hmm, there was a problem and the receipt was not sent. Please contact an administrator.",
            )
    else:
        messages.add_message(
            request,
            messages.INFO,
            "This booking has not been paid, so the receipt was not sent.",
        )
    if "manage" in request.META.get("HTTP_REFERER"):
        return HttpResponseRedirect(
            reverse("booking_manage", args=(location.slug, booking_id))
        )
    else:
        return HttpResponseRedirect(
            reverse("booking_detail", args=(location.slug, booking_id))
        )


@house_admin_required
def BookingSendWelcomeEmail(request, location_slug, booking_id):
    if request.method != "POST":
        return HttpResponseRedirect("/404")
    location = get_object_or_404(Location, slug=location_slug)
    booking = Booking.objects.get(id=booking_id)
    if booking.is_confirmed():
        guest_welcome(booking.use)
        messages.add_message(request, messages.INFO, "The welcome email was sent.")
    else:
        messages.add_message(
            request,
            messages.INFO,
            "The booking is not comfirmed, so the welcome email was not sent.",
        )
    return HttpResponseRedirect(
        reverse("booking_manage", args=(location.slug, booking_id))
    )


@house_admin_required
def BookingSendMail(request, location_slug, booking_id):
    if request.method != "POST":
        return HttpResponseRedirect("/404")

    _assemble_and_send_email(location_slug, request.POST)
    booking = Booking.objects.get(id=booking_id)
    booking.mark_last_msg()
    messages.add_message(request, messages.INFO, "Your message was sent.")
    return HttpResponseRedirect(
        reverse("booking_manage", args=(location_slug, booking_id))
    )
